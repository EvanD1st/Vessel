import copy
import hashlib
import importlib.metadata
import json
import subprocess
import sys
import uuid

import pytest
from test_service import checkpoint
from test_service import project as project

from vessel.artifacts import Artifacts
from vessel.environment import compare, findings, normalize
from vessel.service import Blocked
from vessel.storage import Store


def requirements():
    return {
        "schema_version": 1,
        "client": {"name": "cline", "version": "4.1.17", "capabilities": ["mcp", "command-hooks"]},
        "python_packages": {"fastapi": importlib.metadata.version("fastapi")},
        "migration_files": ["migrations/001.sql"],
        "services": [{"id": "demo-api", "required": True, "available": True}],
        "databases": [
            {
                "id": "demo-db",
                "required": True,
                "available": True,
                "expected_schema": "001",
                "observed_schema": "001",
            }
        ],
        "secret_references": [{"id": str(uuid.uuid4()), "required": True, "available": True}],
    }


def declared(project):
    service, workspace, *_ = project
    (workspace / "migrations").mkdir()
    (workspace / "migrations/001.sql").write_text("CREATE TABLE demo (id INTEGER PRIMARY KEY);\n")
    payload = requirements()
    service.declare_environment(payload, "Owner checked the disposable fixture resources")
    return payload


def manifest(project):
    return Artifacts(project[1], project[0].store).environment()


def test_observed_versions_and_migration_digests_are_separate_from_owner_claims(project):
    declared(project)
    env = manifest(project)
    assert env["schema_version"] == 2
    assert env["python_packages"]["fastapi"]["observed"] == importlib.metadata.version("fastapi")
    assert (
        env["migration_digests"]["migrations/001.sql"]
        == hashlib.sha256((project[1] / "migrations/001.sql").read_bytes()).hexdigest()
    )
    assert env["client_version"] == "4.1.17" and env["client_provenance"] == "owner_declared"
    assert env["availability_provenance"].startswith("owner_attested")
    assert env["git"]["status"] == "not inspected"
    assert not findings(env)
    project[0].review_environment("Checked fixture dependencies and resources", "fixture-model", 24000)
    plan = project[0].prepare_recovery(checkpoint(project)["id"], "new-environment-session", "declared")
    assert plan["preflight"]["blockers"] == []
    assert plan["preflight"]["context"]["environment_requirements"]["client"]["name"] == "cline"


@pytest.mark.parametrize("kind", ["services", "secret_references", "databases"])
def test_required_unavailable_and_unverified_resources_cannot_be_attested_away(project, kind):
    value = declared(project)
    for available in (None, False):
        value[kind][0]["available"] = available
        project[0].declare_environment(value, "Resource is currently unavailable or unknown")
        assert any(item["severity"] == "blocking" for item in findings(manifest(project)))
        with pytest.raises(Blocked, match="requirements need repair"):
            project[0].review_environment("Everything is fine", "fixture-model", 24000)


def test_database_schema_mismatch_is_a_specific_blocker(project):
    value = declared(project)
    value["databases"][0]["observed_schema"] = "000"
    project[0].declare_environment(value, "Old database schema is still present")
    assert any(item["code"] == "database_schema_mismatch" for item in findings(manifest(project)))


def test_missing_python_distribution_requires_repair_without_importing_workspace_code(project):
    value = declared(project)
    value["python_packages"] = {"vessel-intentionally-absent-distribution": "1.0"}
    (project[1] / "vessel_intentionally_absent_distribution.py").write_text(
        "raise AssertionError('do not import')"
    )
    project[0].declare_environment(value, "Verify an unavailable package")
    env = manifest(project)
    assert env["python_packages"]["vessel-intentionally-absent-distribution"]["observed"] is None
    assert findings(env)[0]["code"] == "python_dependency_mismatch"


def test_missing_migration_or_recognizable_secret_has_no_bytes_in_manifest(project):
    declared(project)
    migration = project[1] / "migrations/001.sql"
    migration.write_text("-----BEGIN PRIVATE KEY-----\nfixture-secret-content")
    env = manifest(project)
    assert env["migration_digests"] == {}
    assert "fixture-secret-content" not in json.dumps(env)
    assert findings(env)[0]["code"] == "environment_inspection_failed"
    migration.unlink()
    assert findings(manifest(project))[0]["code"] == "environment_inspection_failed"


def test_optional_resource_gap_is_informational_and_visible_in_context(project):
    value = declared(project)
    value["services"][0].update(required=False, available=None)
    project[0].declare_environment(value, "Optional service is not configured")
    project[0].review_environment("Optional service is unnecessary for this fixture", "fixture-model", 24000)
    plan = project[0].prepare_recovery(checkpoint(project)["id"], "optional-session", "optional")
    assert plan["preflight"]["blockers"] == []
    assert plan["preflight"]["context"]["environment_findings"][0]["severity"] == "informational"


def test_changed_declaration_invalidates_prepared_handover_even_after_new_review(project):
    value = declared(project)
    service = project[0]
    service.review_environment("All fixture requirements passed", "fixture-model", 24000)
    cp = checkpoint(project)
    plan = service.prepare_recovery(cp["id"], "changed-env-session", "changed-env")
    value["client"]["version"] = "3.20.0"
    service.declare_environment(value, "Owner changed the declared client version")
    service.review_environment("New client manually checked", "fixture-model", 24000)
    with pytest.raises(Blocked, match="preflight blocked"):
        service.handover(plan["id"], plan["review_token"])
    refreshed = service.prepare_recovery(cp["id"], "changed-env-session", "changed-env")
    assert "environment_changed_since_checkpoint" in refreshed["preflight"]["blockers"]
    assert any(
        item["field"] == "client_version" for item in refreshed["preflight"]["environment_differences"]
    )


def test_migration_change_and_old_manifest_schema_have_actionable_differences(project):
    declared(project)
    source = manifest(project)
    (project[1] / "migrations/001.sql").write_text("ALTER TABLE demo ADD COLUMN name TEXT;\n")
    current = manifest(project)
    assert any(item["field"] == "migration_digests" for item in compare(source, current))
    source["schema_version"] = 1
    assert any(
        item["field"] == "schema_version" and item["severity"] == "blocking"
        for item in compare(source, current)
    )


def test_declared_migrations_are_required_artifacts_under_capture_limits(project, monkeypatch):
    declared(project)
    monkeypatch.setattr("vessel.artifacts.MAX_TOTAL_BYTES", 50)
    cp = checkpoint(project)
    assert "migrations/001.sql" in cp["manifest"]["missing"]
    assert not project[0].validate_checkpoint(cp["id"])["eligible"]


def test_declaration_change_during_capture_prevents_checkpoint_commit(project):
    value = declared(project)
    service, _, run, _ = project
    service.stop(run["id"], attested=True, note="Disposable writer stopped")
    changed = False

    def change(stage):
        nonlocal changed
        if stage == "after_read" and not changed:
            changed = True
            value["services"][0]["available"] = False
            service.declare_environment(value, "Service changed during capture")

    with pytest.raises(Blocked, match="declaration changed during capture"):
        service.checkpoint(run["id"], fault=change)
    assert not service.store.list("checkpoints")


@pytest.mark.parametrize(
    "bad",
    [
        {"schema_version": True},
        {"schema_version": 2},
        {"schema_version": 1, "api_key": "do-not-store"},
        {"schema_version": 1, "migration_files": ["../escape.sql"]},
        {"schema_version": 1, "migration_files": [".env"]},
        {"schema_version": 1, "services": [{"id": "api", "required": 1, "available": True}]},
        {
            "schema_version": 1,
            "secret_references": [
                {"id": "sk-secret-is-not-a-reference", "required": True, "available": True}
            ],
        },
        {"schema_version": 1, "python_packages": {"my.package": "1", "my-package": "1"}},
        {
            "schema_version": 1,
            "client": {"name": "cline", "version": "3", "capabilities": [], "command": "install-something"},
        },
    ],
)
def test_unsafe_or_ambiguous_declarations_fail_without_mutation(project, bad):
    service = project[0]
    with pytest.raises(ValueError):
        service.declare_environment(bad, "Invalid fixture")
    assert service.store.get("control", "environment_requirements") is None


def test_mutating_caller_input_does_not_change_saved_requirements(project):
    value = declared(project)
    saved = copy.deepcopy(project[0].store.get("control", "environment_requirements"))
    value["services"][0]["available"] = False
    assert project[0].store.get("control", "environment_requirements") == saved
    assert normalize({"schema_version": 1})["services"] == []


def test_real_cli_declaration_roundtrip_and_restored_authority_denial(project, tmp_path):
    service = project[0]
    source = tmp_path / "owner requirements.json"
    source.write_text(json.dumps({"schema_version": 1, "services": []}))
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "vessel",
            "--state",
            str(service.store.dir),
            "declare-environment",
            str(source),
            "--note",
            "CLI fixture review",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout)["requirements"]["services"] == []
    inspected = subprocess.run(
        [sys.executable, "-m", "vessel", "--state", str(service.store.dir), "environment"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["findings"] == []
    backup = tmp_path / "backup"
    service.store.backup(backup)
    restored = Store.restore_local(backup, tmp_path / "restored")
    restored.close()
    from vessel.service import Vessel

    history = Vessel(tmp_path / "restored")
    try:
        with pytest.raises(Blocked, match="inspection-only"):
            history.declare_environment({"schema_version": 1}, "Cannot activate restored authority")
    finally:
        history.close()
