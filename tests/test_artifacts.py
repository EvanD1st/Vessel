import hashlib

import pytest

from vessel.artifacts import Artifacts
from vessel.storage import Store


@pytest.fixture
def artifacts(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = Store(tmp_path / "state")
    yield Artifacts(workspace, store)
    store.close()


def test_capture_untracked_files_excludes_secrets_and_restores_separately(artifacts, tmp_path):
    root = artifacts.workspace
    (root / "app.py").write_text("print('durable source')", encoding="utf-8")
    (root / ".env").write_text("SECRET=must-not-be-saved", encoding="utf-8")
    (root / ".env.example").write_text("SECRET=template", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "dependency.js").write_text("generated", encoding="utf-8")
    (root / "credential.txt").write_text("-----BEGIN PRIVATE KEY-----\nsensitive", encoding="utf-8")
    manifest = artifacts.capture(["app.py"])
    assert manifest["stable"] is True
    assert [record["path"] for record in manifest["files"]] == ["app.py"]
    assert {record["path"] for record in manifest["excluded"]} == {
        ".env",
        ".env.example",
        "node_modules",
        "credential.txt",
    }
    assert artifacts.verify(manifest) == []
    for blob in artifacts.store.blob_dir.glob("*.blob"):
        assert b"durable source" not in blob.read_bytes()
        assert b"must-not-be-saved" not in blob.read_bytes()
    destination = tmp_path / "restored files"
    assert artifacts.restore(manifest, destination)["restored"] is True
    assert (destination / "app.py").read_text() == "print('durable source')"
    assert not (destination / ".env").exists()
    assert (root / ".env").read_text() == "SECRET=must-not-be-saved"


def test_required_exclusion_blocks_eligibility(artifacts):
    (artifacts.workspace / ".env").write_text("SENSITIVE=value")
    result = artifacts.capture([".env", "missing.py"])
    assert result["missing"] == [".env", "missing.py"]
    assert any("Required artifacts missing" in blocker for blocker in artifacts.verify(result))


def test_changing_files_are_retried_and_remain_best_effort(artifacts):
    path = artifacts.workspace / "changing.txt"
    path.write_text("before")
    count = 0

    def mutate(stage):
        nonlocal count
        if stage == "after_read":
            count += 1
            path.write_text(f"changed {count}")

    manifest = artifacts.capture(["changing.txt"], fault=mutate)
    assert manifest["attempts"] == 2
    assert manifest["stable"] is False
    assert any("changed" in issue.lower() for issue in manifest["issues"])
    assert any("unstable" in blocker for blocker in artifacts.verify(manifest))


def test_one_time_change_can_recover_on_bounded_retry(artifacts):
    path = artifacts.workspace / "changing.txt"
    path.write_text("before")
    count = 0

    def mutate(stage):
        nonlocal count
        if stage == "after_read" and count == 0:
            path.write_text("stable after retry")
            count += 1

    manifest = artifacts.capture(["changing.txt"], fault=mutate)
    assert manifest["attempts"] == 2
    assert manifest["stable"] is True
    assert artifacts.store.read_blob(manifest["files"][0]["blob"]) == b"stable after retry"


def test_crash_after_blob_publication_never_creates_checkpoint(artifacts):
    (artifacts.workspace / "main.py").write_text("result = 42")

    def fail(stage):
        if stage == "after_blob_rename":
            raise RuntimeError("process terminated after durable file")

    with pytest.raises(RuntimeError):
        artifacts.capture(["main.py"], fault=fail)
    assert artifacts.store.list("checkpoint") == []
    assert len(list(artifacts.store.blob_dir.glob("*.blob"))) == 1
    assert artifacts.verify(artifacts.capture(["main.py"])) == []


@pytest.mark.parametrize(
    "relative",
    ["../secret", "/absolute", "C:/secret", "file:stream", "a\\b", "a/../b", "con.txt", "trailing."],
)
def test_manifest_path_escape_and_windows_unsafe_paths_rejected(artifacts, tmp_path, relative):
    blob = artifacts.store.write_blob(b"content")
    manifest = {
        "schema_version": 1,
        "stable": True,
        "missing": [],
        "files": [{"path": relative, "blob": blob, "digest": blob, "size": 7}],
    }
    assert artifacts.verify(manifest)
    with pytest.raises(ValueError):
        artifacts.restore(manifest, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_diff_and_existing_work_never_overwritten(artifacts, tmp_path):
    root = artifacts.workspace
    (root / "changed.py").write_text("before")
    (root / "missing.py").write_text("present at checkpoint")
    snapshot = artifacts.capture()
    (root / "changed.py").write_text("after")
    (root / "missing.py").unlink()
    (root / "extra.py").write_text("new work")
    differences = artifacts.diff(snapshot)
    assert differences["changed"] == ["changed.py"]
    assert differences["missing"] == ["missing.py"]
    assert differences["extra"] == ["extra.py"]
    with pytest.raises(ValueError, match="separate"):
        artifacts.restore(snapshot, root)
    destination = tmp_path / "nonempty"
    destination.mkdir()
    (destination / "important.txt").write_text("preserve")
    with pytest.raises(ValueError, match="never overwritten"):
        artifacts.restore(snapshot, destination)
    assert (destination / "important.txt").read_text() == "preserve"


def test_missing_and_modified_blobs_block_restore(artifacts, tmp_path):
    (artifacts.workspace / "source.py").write_text("saved source")
    snapshot = artifacts.capture(["source.py"])
    blob = artifacts.store.blob_dir / f"{snapshot['files'][0]['blob']}.blob"
    blob.unlink()
    assert any("missing artifact" in issue for issue in artifacts.verify(snapshot))
    with pytest.raises(ValueError):
        artifacts.restore(snapshot, tmp_path / "restored")


def test_limits_and_environment_do_not_execute_workspace_content(artifacts, monkeypatch):
    (artifacts.workspace / "large.txt").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    (artifacts.workspace / "requirements.txt").write_text("fastapi==0.100.0")
    (artifacts.workspace / "install.sh").write_text("exit 99")
    snapshot = artifacts.capture(["large.txt"])
    assert snapshot["missing"] == ["large.txt"]
    assert any("2 MiB" in item["reason"] for item in snapshot["excluded"])
    environment = artifacts.environment()
    assert environment["lock_digests"]["requirements.txt"] == hashlib.sha256(b"fastapi==0.100.0").hexdigest()
    assert environment["services"] == []
    assert environment["client_version"] == "unverified"


def test_symlink_escape_is_visible_and_required_path_missing(artifacts, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private outside content")
    target = artifacts.workspace / "escape.txt"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("OS user cannot create symlinks")
    snapshot = artifacts.capture(["escape.txt"])
    assert snapshot["files"] == []
    assert snapshot["missing"] == ["escape.txt"]
    assert any("symlink" in item["reason"] for item in snapshot["excluded"])


def test_state_inside_workspace_is_never_captured(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "app.py").write_text("application")
    with Store(root / "private-state") as state:
        state.put("mission", "secret", {"text": "private instruction"})
        manifest = Artifacts(root, state).capture()
        assert [record["path"] for record in manifest["files"]] == ["app.py"]
        assert any(item["reason"] == "VESSEL state storage" for item in manifest["excluded"])
