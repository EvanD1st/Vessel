"""Recovery acceptance tests with synthetic Cline observations, no paid inference."""

import json
import uuid

import pytest

from vessel.gateway import CaptureUnhealthy
from vessel.service import Blocked, Vessel
from vessel.storage import Store


@pytest.fixture
def project(tmp_path):
    workspace = tmp_path / "project with spaces"
    workspace.mkdir()
    (workspace / "app.py").write_text("mission = 'finish password reset'\n")
    clock = [1000.0]
    service = Vessel(tmp_path / "private state", clock=lambda: clock[0])
    service.enroll(workspace, "Implement registration, login and password reset", required_paths=["app.py"])
    service.review_environment("Fixture environment; no external services or secrets", "fixture-model", 24000)
    run = service.start(workspace, "source-conversation")
    observe(service, workspace, "source-conversation", "beforeSubmitPrompt", prompt="Continue the task")
    yield service, workspace, run, clock
    service.close()


def observe(service, workspace, session, event, **fields):
    payload = {
        "conversation_id": session,
        "hook_event_name": event,
        "workspace_roots": [str(workspace)],
        **fields,
    }
    return service.observe(workspace, payload, "fixture_" + uuid.uuid4().hex)


def operation(service, workspace, session, native_id="tool-1", *, result="postToolUse", exit_code=0):
    for name in ("preToolUse", result):
        observe(
            service,
            workspace,
            session,
            name,
            tool_use_id=native_id,
            tool_name="Shell",
            tool_input={"command": "python -m pytest"},
            **(
                {"tool_output": json.dumps({"exitCode": exit_code, "stdout": "test result"})}
                if name != "preToolUse"
                else {}
            ),
        )
    bound = service.store.get("sessions", session)["run_id"]
    return next(op for op in service.operations(bound) if op["native_id"] == native_id)


def checkpoint(project):
    service, workspace, run, clock = project
    service.task(run["id"], "reset", "Implement password reset")
    service.stop(run["id"], attested=True, note="Fixture writer stopped; no background process")
    return service.checkpoint(run["id"])


def transfer(project):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    recovery = service.prepare_recovery(cp["id"], "destination-conversation", "recover-once")
    assert recovery["preflight"]["blockers"] == []
    return cp, service.handover(recovery["id"], recovery["review_token"])


def test_full_continuation_and_restart_durability(project):
    service, workspace, run, clock = project
    cp, recovery = transfer(project)
    assert recovery["destination_epoch"] == 2
    context = service.recovery_context(recovery["id"])
    assert context["mission"].startswith("Implement registration")
    assert context["tasks"][0]["status"] == "pending"
    assert service.store.get("recoveries", recovery["id"])["status"] == "context_served"
    assert (workspace / "app.py").read_text().startswith("mission =")
    with pytest.raises(Blocked, match="Missing operations"):
        service.confirm_continuation(recovery["id"], "invented-success", "model said done")
    op = operation(service, workspace, "destination-conversation")
    confirmed = service.confirm_continuation(
        recovery["id"], op["id"], "Owner reviewed the intended test step"
    )
    assert confirmed["status"] == "succeeded"
    restarted = Vessel(service.store.dir, clock=lambda: clock[0])
    try:
        assert restarted.store.get("recoveries", recovery["id"])["status"] == "succeeded"
        assert restarted.validate_checkpoint(cp["id"])["eligible"]
    finally:
        restarted.close()


def test_second_authority_for_same_workspace_is_rejected(project, tmp_path):
    service, workspace, run, clock = project
    other = Vessel(tmp_path / "second authority")
    try:
        with pytest.raises(ValueError, match="already enrolled"):
            other.enroll(workspace, "Competing writer")
    finally:
        other.close()


def test_owner_authority_cannot_live_inside_project(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    service = Vessel(workspace / "model-editable-state")
    try:
        with pytest.raises(Blocked, match="outside"):
            service.enroll(workspace, "mission")
    finally:
        service.close()


def test_expired_lease_never_allows_automatic_takeover(project):
    service, workspace, run, clock = project
    clock[0] += 31
    with pytest.raises(Blocked, match="expired"):
        service.task(run["id"], "new", "Another task")
    with pytest.raises(Blocked, match="lease exists"):
        service.start(workspace, "new conversation")
    assert service.status()["lease_stale"]
    service.heartbeat(run["id"], 1)
    assert not service.status()["lease_stale"]


def test_uncertain_external_effect_blocks_checkpoint_continuation(project):
    service, workspace, run, clock = project
    observe(
        service,
        workspace,
        "source-conversation",
        "preToolUse",
        tool_use_id="unresolved",
        tool_name="Shell",
        tool_input={"command": "external write"},
    )
    cp = checkpoint(project)
    assert not service.validate_checkpoint(cp["id"])["eligible"]
    recovery = service.prepare_recovery(cp["id"], "new", "blocked")
    assert "unresolved_operations" in recovery["preflight"]["blockers"]
    pending = service.operations(run["id"])[0]
    service.resolve_operation(pending["id"], "Owner checked external receipt; operation never executed")
    # Prior immutable capture remains incomplete: repair must create a fresh checkpoint.
    assert not service.validate_checkpoint(cp["id"])["eligible"]
    repaired = service.checkpoint(run["id"])
    assert service.validate_checkpoint(repaired["id"])["eligible"]


def test_out_of_order_receipts_are_reconciled_by_native_id(project):
    service, workspace, run, clock = project
    observe(
        service,
        workspace,
        "source-conversation",
        "postToolUse",
        tool_use_id="late-intent",
        tool_name="Shell",
        tool_output='{"exitCode":0}',
    )
    assert service.operations(run["id"])[0]["uncertain"]
    observe(
        service, workspace, "source-conversation", "preToolUse", tool_use_id="late-intent", tool_name="Shell"
    )
    assert not service.operations(run["id"])[0]["uncertain"]


def test_conflicting_receipt_degrades_capture(project):
    service, workspace, run, clock = project
    operation(service, workspace, "source-conversation")
    observe(
        service,
        workspace,
        "source-conversation",
        "postToolUse",
        tool_use_id="tool-1",
        tool_name="Shell",
        tool_output='{"exitCode":1}',
    )
    assert service.operations(run["id"])[0]["uncertain"]
    assert service.status()["capture"]["state"] == "degraded"


def test_duplicate_delivery_is_idempotent_conflict_is_visible(project):
    service, workspace, run, clock = project
    event = {
        "conversation_id": "source-conversation",
        "hook_event_name": "afterAgentResponse",
        "text": "claimed done",
    }
    first = service.observe(workspace, event, "repeated-delivery")
    second = service.observe(workspace, event, "repeated-delivery")
    assert first["sequence"] == second["sequence"] and second["duplicate"]
    with pytest.raises(ValueError, match="Conflicting"):
        service.observe(workspace, dict(event, text="different"), "repeated-delivery")
    assert service.status()["capture"]["state"] == "degraded"


def test_model_proposal_cannot_change_policy(project):
    service, workspace, run, clock = project
    before = service.policy()
    proposal = service.propose(
        workspace, "mission", {"mission": "deploy now", "provenance": "owner_instruction"}
    )
    assert proposal["provenance"] == "agent_claim" and not proposal["accepted"]
    assert service.policy() == before


def test_failed_shell_exit_cannot_verify_a_task(project):
    service, workspace, run, clock = project
    failed = operation(service, workspace, "source-conversation", exit_code=1)
    with pytest.raises(Blocked, match="observed success"):
        service.task(run["id"], "fake-success", "Claimed done", status="done", evidence=failed["id"])


def test_environment_review_is_required_for_continuation(project):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    service.store.connection.execute("DELETE FROM documents WHERE kind='control' AND id='environment_review'")
    plan = service.prepare_recovery(cp["id"], "new", "missing-environment")
    assert "owner_environment_and_model_review_required" in plan["preflight"]["blockers"]


def test_changed_policy_invalidates_recovery_review(project):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    recovery = service.prepare_recovery(cp["id"], "destination", "idempotent")
    service.policy(restrictions=["Deployment prohibited"])
    with pytest.raises(Blocked, match="changed"):
        service.handover(recovery["id"], recovery["review_token"])
    refreshed = service.prepare_recovery(cp["id"], "destination", "idempotent")
    service.handover(refreshed["id"], refreshed["review_token"])
    context = service.recovery_context(refreshed["id"])
    assert context["current_owner_policy"]["restrictions"] == ["Deployment prohibited"]
    assert context["historical_policy_revision"] == 1


def test_revoked_policy_blocks_recovery(project):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    service.policy(recovery_allowed=False)
    recovery = service.prepare_recovery(cp["id"], "destination", "revoked")
    assert "current_policy_disallows_recovery" in recovery["preflight"]["blockers"]


def test_recovery_idempotency_and_stale_epoch_rejection(project):
    service, workspace, run, clock = project
    cp, recovery = transfer(project)
    again = service.handover(recovery["id"], recovery["review_token"])
    assert again["destination_run_id"] == recovery["destination_run_id"]
    assert len(service.store.list("runs")) == 2
    with pytest.raises(Blocked, match="different recovery inputs"):
        service.prepare_recovery(cp["id"], "other", "recover-once")
    with pytest.raises(Blocked, match="Stale execution"):
        service.task(run["id"], "stale", "Old agent update")
    observe(service, workspace, "source-conversation", "preToolUse", tool_use_id="late", tool_name="Shell")
    assert service.status()["lease"]["execution_epoch"] == 2
    assert "old_run_native_activity_after_handover" in service.status()["capture"]["gaps"]


def test_second_conversation_blocks_assisted_recovery(project):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    observe(service, workspace, "competing-task", "beforeSubmitPrompt", prompt="parallel writer")
    plan = service.prepare_recovery(cp["id"], "destination", "request")
    assert "another_native_session_is_active" in plan["preflight"]["blockers"]
    service.dismiss_session("competing-task", "Owner stopped the other task")
    assert service.prepare_recovery(cp["id"], "destination", "request")["status"] == "awaiting_owner"


@pytest.mark.parametrize("mutation", ["missing", "changed", "context", "lock"], ids=str)
def test_preflight_blocks_incompatible_recovery(project, mutation):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    if mutation == "missing":
        (workspace / "app.py").unlink()
    if mutation == "changed":
        (workspace / "app.py").write_text("unrelated current work")
    if mutation == "lock":
        (workspace / "requirements.txt").write_text("unknown-package==999")
    plan = service.prepare_recovery(
        cp["id"], "destination", "request", context_budget=1 if mutation == "context" else 24000
    )
    assert plan["status"] == "blocked"


@pytest.mark.parametrize(
    "stage", ["after_blob_flush", "after_blob_rename", "before_checkpoint_commit", "after_checkpoint_commit"]
)
def test_checkpoint_crash_windows(project, stage):
    service, workspace, run, clock = project
    original = checkpoint(project)
    (workspace / "app.py").write_text("modified = True")

    def fault(point):
        if point == stage:
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError, match="simulated"):
        service.checkpoint(run["id"], fault=fault)
    checkpoints = service.store.list("checkpoints")
    assert len(checkpoints) == (2 if stage == "after_checkpoint_commit" else 1)
    assert service.validate_checkpoint(original["id"])["eligible"]
    for cp in checkpoints:
        assert service.validate_checkpoint(cp["id"])["eligible"]


def test_events_arriving_during_capture_never_qualify(project):
    service, workspace, run, clock = project
    checkpoint(project)
    delivered = False

    def fault(point):
        nonlocal delivered
        if point == "after_read" and not delivered:
            delivered = True
            observe(service, workspace, "source-conversation", "afterAgentResponse", text="late")

    cp = service.checkpoint(run["id"], fault=fault)
    assert "events_arrived_during_capture" in service.validate_checkpoint(cp["id"])["blockers"]


def test_backup_restore_never_reactivates_execution(project, tmp_path):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    service.store.backup(tmp_path / "backup")
    restored = Store.restore_local(tmp_path / "backup", tmp_path / "restored")
    restored.close()
    restored_service = Vessel(tmp_path / "restored", clock=lambda: clock[0])
    try:
        assert restored_service.validate_checkpoint(cp["id"])["eligible"]
        assert restored_service.status()["restored_inspection_only"]
        with pytest.raises(Blocked, match="inspection-only"):
            restored_service.prepare_recovery(cp["id"], "destination", "restore")
    finally:
        restored_service.close()


def test_gateway_key_revocation_uses_current_epoch(project):
    service, workspace, run, clock = project
    service.policy(allowed_models=["fixture-model"])
    service.heartbeat(run["id"], 1, revalidate=True)
    credential = service.issue_gateway_credential("default", ["fixture-model"])
    assert service.authorize_gateway(credential["token"]).execution_epoch == 1
    transfer(project)
    assert service.authorize_gateway(credential["token"]) is None


def test_gateway_reports_capture_block_and_retains_guard_until_reviewed_repair(project):
    service, workspace, run, clock = project
    service.policy(allowed_models=["fixture-model"])
    service.heartbeat(run["id"], 1, revalidate=True)
    credential = service.issue_gateway_credential("default", ["fixture-model"])
    observe(
        service, workspace, "source-conversation", "vesselCaptureGap",
        reason="native_tool_exit_status_unavailable",
    )
    with pytest.raises(CaptureUnhealthy):
        service.authorize_gateway(credential["token"])
    # Another prompt cannot erase the unresolved gap or reopen inference.
    observe(service, workspace, "source-conversation", "beforeSubmitPrompt", prompt="Retry")
    with pytest.raises(CaptureUnhealthy):
        service.authorize_gateway(credential["token"])
    service.repair_capture("Fixture: owner reviewed terminal repair; old outcome remains unknown")
    assert service.authorize_gateway(credential["token"]).execution_epoch == 1
    assert service.store.list("capture_repairs")[0]["previous"]["gaps"] == [
        "native_tool_exit_status_unavailable"
    ]


@pytest.mark.parametrize(
    "invalidity", ["unknown", "revoked", "epoch", "expired", "paused", "policy", "revalidated_policy"]
)
def test_gateway_rejects_invalid_authority_before_disclosing_capture_health(project, invalidity):
    service, workspace, run, clock = project
    service.policy(allowed_models=["fixture-model"])
    service.heartbeat(run["id"], 1, revalidate=True)
    issued = service.issue_gateway_credential("default", ["fixture-model"])
    token = issued["token"]
    observe(service, workspace, "source-conversation", "vesselCaptureGap", reason="fixture_gap")
    if invalidity == "unknown":
        token = "unknown-gateway-credential"
    elif invalidity in {"revoked", "epoch"}:
        credential = service.store.list("gateway_credentials")[0]
        if invalidity == "revoked":
            credential["revoked"] = True
        else:
            credential["execution_epoch"] += 1
        service.store.put("gateway_credentials", credential["id"], credential)
    elif invalidity == "expired":
        clock[0] += 31
    elif invalidity == "paused":
        service.stop(run["id"], attested=True, note="Fixture writer stopped")
    else:
        service.policy(restrictions="Revised owner policy")
        if invalidity == "revalidated_policy":
            service.heartbeat(run["id"], 1, revalidate=True)
    assert service.authorize_gateway(token) is None


def test_native_wakeup_invalidates_earlier_shutdown_attestation(project):
    service, workspace, run, clock = project
    service.stop(run["id"], attested=True, note="Native task was stopped")
    observe(service, workspace, "source-conversation", "preToolUse", tool_use_id="woke", tool_name="Shell")
    with pytest.raises(Blocked, match="shutdown evidence"):
        service.checkpoint(run["id"])
    assert "native_activity_after_attested_stop" in service.status()["capture"]["gaps"]


def test_missing_referenced_blob_cannot_be_a_verified_backup(project, tmp_path):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    blob = cp["manifest"]["files"][0]["blob"]
    (service.store.blob_dir / (blob + ".blob")).unlink()
    with pytest.raises(OSError):
        service.store.backup(tmp_path / "broken-backup")
    assert not (tmp_path / "broken-backup").exists()


def test_policy_change_during_crash_requires_reviewed_repair(project, monkeypatch):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    plan = service.prepare_recovery(cp["id"], "destination", "policy-race")
    real_finish = service.finish_handover

    def crash(_):
        raise RuntimeError("before revocation")

    monkeypatch.setattr(service, "finish_handover", crash)
    with pytest.raises(RuntimeError):
        service.handover(plan["id"], plan["review_token"])
    service.policy(restrictions=["No deployment or messages"])
    monkeypatch.setattr(service, "finish_handover", real_finish)
    restarted = Vessel(service.store.dir, clock=lambda: clock[0])
    try:
        assert restarted.status()["lease"]["status"] == "handover"
        with pytest.raises(Blocked, match="Policy changed"):
            restarted.finish_handover(plan["id"])
        repaired = restarted.repair_handover(plan["id"], 2, "Owner reviewed the current tighter restrictions")
        assert repaired["status"] == "awaiting_continuation"
        assert restarted.recovery_context(plan["id"])["current_owner_policy"]["revision"] == 2
    finally:
        restarted.close()


def test_restart_retries_durable_handover_outbox(project, monkeypatch):
    service, workspace, run, clock = project
    cp = checkpoint(project)
    plan = service.prepare_recovery(cp["id"], "destination", "restart")

    def crash(_):
        raise RuntimeError("process killed before revocation")

    monkeypatch.setattr(service, "finish_handover", crash)
    with pytest.raises(RuntimeError):
        service.handover(plan["id"], plan["review_token"])
    assert service.status()["lease"]["status"] == "handover"
    restarted = Vessel(service.store.dir, clock=lambda: clock[0])
    try:
        assert restarted.status()["lease"]["status"] == "active"
        assert restarted.store.get("outbox", plan["id"])["done"]
        assert restarted.status()["lease"]["execution_epoch"] == 2
    finally:
        restarted.close()
