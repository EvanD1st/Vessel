import pytest
from test_service import checkpoint, observe, operation, transfer
from test_service import project as project

from vessel.service import Blocked, Vessel


def test_accept_mission_records_review_without_expanding_capabilities(project):
    service, workspace, run, _ = project
    old = service.policy()
    proposal = service.propose(
        workspace, "mission", {"mission": "Finish password reset", "constraints": ["No deployment"]}
    )
    result = service.review_proposal(
        proposal["id"], "accept", "Reviewed the revised scope", policy_revision=1
    )
    policy = service.policy()
    assert policy["revision"] == 2 and policy["mission"] == "Finish password reset"
    assert set(old["restrictions"]).issubset(policy["restrictions"])
    assert policy["allowed_models"] == old["allowed_models"]
    assert policy["recovery_allowed"] == old["recovery_allowed"]
    assert result["provenance"] == "agent_claim" and result["reviewed_by"] == old["authorized_by"]
    with pytest.raises(Blocked, match="Policy changed"):
        service.heartbeat(run["id"], 1)
    assert (
        service.review_proposal(proposal["id"], "accept", "Reviewed the revised scope", policy_revision=1)
        == result
    )
    assert service.policy()["revision"] == 2


def test_proposal_review_rechecks_policy_and_cannot_be_changed(project):
    service, workspace, _, _ = project
    proposal = service.propose(workspace, "mission", {"mission": "Proposal", "constraints": []})
    service.policy(recovery_allowed=False)
    with pytest.raises(Blocked, match="policy changed"):
        service.review_proposal(proposal["id"], "accept", "Review", policy_revision=1)
    rejected = service.review_proposal(proposal["id"], "reject", "Outside scope", policy_revision=2)
    assert not rejected["accepted"]
    with pytest.raises(Blocked, match="already reviewed"):
        service.review_proposal(proposal["id"], "accept", "Review", policy_revision=2)


def test_task_proposal_cannot_certify_its_own_completion(project):
    service, workspace, run, _ = project
    proposal = service.propose(
        workspace,
        "task",
        {"description": "Reset", "claimed_status": "completed", "evidence": ["model-said-done"]},
    )
    service.review_proposal(
        proposal["id"],
        "accept",
        "Assign and verify later",
        policy_revision=1,
        run_id=run["id"],
        task_id="reset",
    )
    task = service.store.get("tasks", f"{run['id']}:reset")
    assert task["status"] == "pending" and not task["evidence"]
    assert service.store.get("proposals", proposal["id"])["assignment"] == run["id"]


def test_owner_can_accept_task_with_independent_success_evidence(project):
    service, workspace, run, _ = project
    op = operation(service, workspace, "source-conversation")
    proposal = service.propose(
        workspace, "task", {"description": "Verified endpoint", "claimed_status": "completed"}
    )
    service.review_proposal(
        proposal["id"],
        "accept",
        "Reviewed the actual test receipt",
        policy_revision=1,
        run_id=run["id"],
        task_id="endpoint",
        evidence=op["id"],
    )
    assert service.store.get("tasks", f"{run['id']}:endpoint")["status"] == "done"


def test_task_dependencies_block_premature_work_and_invalid_reopening(project):
    service, workspace, run, _ = project
    service.task(run["id"], "login", "Build login")
    service.task(run["id"], "reset", "Build reset", dependencies=["login"])
    with pytest.raises(Blocked, match="unfinished dependency"):
        service.task(run["id"], "reset", "Build reset", status="active")
    op = operation(service, workspace, "source-conversation")
    service.task(run["id"], "login", "Build login", status="done", evidence=op["id"])
    service.task(run["id"], "reset", "Build reset", status="active")
    with pytest.raises(Blocked, match="unfinished dependency"):
        service.task(run["id"], "login", "Reopen login")
    assert service.store.get("tasks", f"{run['id']}:login")["status"] == "done"


def test_missing_and_cyclic_dependencies_are_rejected_atomically(project):
    service, _, run, _ = project
    with pytest.raises(Blocked, match="existing tasks"):
        service.task(run["id"], "reset", "Reset", dependencies=["unknown"])
    service.task(run["id"], "first", "First")
    service.task(run["id"], "second", "Second", dependencies=["first"])
    with pytest.raises(Blocked, match="cycle"):
        service.task(run["id"], "first", "First", dependencies=["second"])
    assert service.store.get("tasks", f"{run['id']}:first")["dependencies"] == []


def test_completion_requires_stopped_writer_all_tasks_and_acceptance_evidence(project):
    service, workspace, run, _ = project
    service.task(run["id"], "reset", "Reset")
    with pytest.raises(Blocked, match="shutdown"):
        service.finish_run(run["id"], "completed", "Tests pass")
    service.stop(run["id"], attested=True, note="Writer stopped")
    with pytest.raises(Blocked, match="every recorded task"):
        service.finish_run(run["id"], "completed", "Tests pass")


def test_completed_run_revokes_credentials_survives_restart_and_new_run_advances_epoch(project):
    service, workspace, run, clock = project
    service.policy(allowed_models=["fixture-model"])
    service.heartbeat(run["id"], 1, revalidate=True)
    credential = service.issue_gateway_credential("default", ["fixture-model"])
    assert service.authorize_gateway(credential["token"]) is not None
    op = operation(service, workspace, "source-conversation")
    service.task(run["id"], "reset", "Reset", status="done", evidence=op["id"])
    service.stop(run["id"], attested=True, note="Writer stopped")
    service.finish_run(run["id"], "completed", "Acceptance tests reviewed", evidence=op["id"])
    assert service.authorize_gateway(credential["token"]) is None
    assert all(key["revoked"] for key in service.store.list("gateway_credentials"))
    restarted = Vessel(service.store.dir, clock=lambda: clock[0])
    try:
        assert restarted.store.get("runs", run["id"])["status"] == "completed"
        with pytest.raises(Blocked, match="finished run"):
            restarted.stop(run["id"], attested=True, note="Reopen")
        with pytest.raises(Blocked, match="fresh native"):
            restarted.start(workspace, "source-conversation")
        new = restarted.start(workspace, "new-work")
        assert new["execution_epoch"] == 2
        assert restarted.status()["capture"]["state"] == "unknown"
        with pytest.raises(Blocked, match="health"):
            restarted.task(new["id"], "new-task", "Wait for new observed activity")
    finally:
        restarted.close()


def test_cancelled_run_retains_tasks_and_rejects_late_native_admission(project):
    service, workspace, run, _ = project
    service.task(run["id"], "reset", "Still pending")
    service.stop(run["id"], attested=True, note="Stopped all work")
    service.finish_run(run["id"], "cancelled", "Owner changed priorities")
    observe(service, workspace, "source-conversation", "preToolUse", tool_use_id="late", tool_name="Shell")
    assert service.store.get("control", "lease")["status"] == "closed"
    assert "native_activity_after_run_finished" in service.status()["capture"]["gaps"]
    assert service.store.get("tasks", f"{run['id']}:reset")["status"] == "pending"


def test_cancelled_recovery_cannot_be_handed_over(project):
    service, _, _, _ = project
    cp = checkpoint(project)
    recovery = service.prepare_recovery(cp["id"], "destination", "cancel-this")
    service.cancel_recovery(recovery["id"], "Different checkpoint preferred")
    with pytest.raises(Blocked, match="Cancelled recovery"):
        service.handover(recovery["id"], recovery["review_token"])
    assert service.store.get("control", "lease")["execution_epoch"] == 1


def test_transferred_recovery_cannot_be_cancelled(project):
    service, _, _, _ = project
    _, recovery = transfer(project)
    with pytest.raises(Blocked, match="Transferred"):
        service.cancel_recovery(recovery["id"], "Undo")
