"""Disposable extension integration tests; no installed Cline or provider credentials."""
import asyncio
import json
import socket
import uuid

import httpx
import pytest

from vessel import adapters
from vessel import extension_api as api
from vessel.service import Vessel


@pytest.fixture
def setup(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "app.py").write_text("# preserved")
    config = tmp_path / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "preserve"}}}))
    storage = tmp_path / "storage"
    storage.mkdir()
    return {"workspace": str(workspace), "state": str(tmp_path / "state"), "mcp_config": str(config), "storage": str(storage), "mission": "Test feature",
            "models": list(api.gateway.MODELS), "port": 19871, "gateway_port": 19872}


def call(setup, action, **kwargs):
    return api.dispatch({**setup, "schema": 1, "action": action, **kwargs})


def configure(setup):
    plan = call(setup, "plan")
    result = call(setup, "apply", transaction=plan["id"], review=plan["review"], credential_version=uuid.uuid4().hex, verified_at=1)
    return plan, result


def test_plan_apply_retry_preserves_mcp_and_reports_native_pending(setup):
    plan, result = configure(setup)
    assert result["status"] == "configured"
    assert call(setup, "apply", transaction=plan["id"], review=plan["review"])["status"] == "configured"
    status = call(setup, "status")
    assert status["configuration"]["installed"]
    assert status["capture"]["state"] == "unknown"
    assert status["checkpoints"] == [] and status["runs"] == []
    assert status["gateway_config"]["paused"]
    assert json.loads(api.Path(setup["mcp_config"]).read_text())["mcpServers"]["other"] == {"command": "preserve"}


def test_stale_review_and_unrelated_hook_refused(setup):
    plan = call(setup, "plan")
    api.Path(setup["mcp_config"]).write_text('{"mcpServers":{},"changed":true}')
    with pytest.raises(api.RequestError, match="review_changed"):
        call(setup, "apply", transaction=plan["id"], review=plan["review"], credential_version=uuid.uuid4().hex)
    hooks = api.Path(setup["workspace"]) / ".clinerules/hooks"
    hooks.mkdir(parents=True)
    (hooks / "PreToolUse.ps1").write_text("# owner hook")
    with pytest.raises(api.RequestError, match="configuration_conflict"):
        call(setup, "plan")


def test_existing_enrollment_mission_preserved(setup):
    plan, _ = configure(setup)
    found = call(setup, "discover")
    assert found["existing"] and api.Path(found["state"]).resolve() == api.Path(plan["plan"]["state"]).resolve()
    with pytest.raises(api.RequestError, match="configuration_conflict"):
        call(setup, "plan", mission="Silently change mission")


def test_rollback_removes_only_owned_configuration_and_preserves_state(setup):
    plan, _ = configure(setup)
    result = call(setup, "rollback", transaction=plan["id"], review=plan["review"])
    assert result["recovery_data_preserved"]
    assert (api.Path(plan["plan"]["state"]) / "vessel.sqlite3").exists()
    assert json.loads(api.Path(setup["mcp_config"]).read_text())["mcpServers"] == {"other": {"command": "preserve"}}


def test_rollback_refuses_owner_edited_hook(setup):
    plan, _ = configure(setup)
    manifest = adapters._manifest(api.Path(setup["workspace"]), api.Path(plan["plan"]["state"]))
    hook = api.Path(setup["workspace"]) / next(iter(manifest["hooks"]))
    hook.write_text("# owner changed this")
    with pytest.raises(ValueError):
        call(setup, "rollback", transaction=plan["id"], review=plan["review"])
    assert hook.read_text() == "# owner changed this"


def test_owner_cannot_bind_unobserved_session_or_checkpoint_without_run(setup):
    plan, _ = configure(setup)
    with pytest.raises(api.RequestError, match="owner_action_blocked"):
        call(setup, "owner-action", name="start", payload={"session_id": "invented"}, request_id=uuid.uuid4().hex, revision=2)
    service = Vessel(plan["plan"]["state"])
    try:
        with pytest.raises(ValueError):
            service.checkpoint("default")
        assert not service.store.events() and not service.store.list("checkpoints")
    finally:
        service.close()


def test_gateway_mode_requires_current_owner_revision(setup):
    configure(setup)
    with pytest.raises(ValueError):
        call(setup, "gateway-mode", revision=999, epoch=None, paused=False)
    status = call(setup, "status")
    assert status["gateway_config"]["paused"]
    assert call(setup, "gateway-mode", revision=status["policy_revision"], epoch=None, paused=False) == {"paused": False}


@pytest.mark.parametrize("models", [[api.gateway.MODELS[0]] * 2, ["invented", "model"], [], "bad"])
def test_models_fail_closed(models):
    with pytest.raises(api.RequestError):
        api.model_pair(models)


def test_validation_uses_gateway_with_canned_prompts_and_no_workspace_data():
    requests = []
    def upstream(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.url == api.gateway.ENDPOINT
        assert request.headers["authorization"] == "Bearer dummy-test-key"
        return httpx.Response(200, json={"id": "test", "object": "chat.completion", "created": 1,
                              "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "READY"}}]})
    result = asyncio.run(api.validate_provider("dummy-test-key", list(api.gateway.MODELS), transport=httpx.MockTransport(upstream)))
    assert result["text"] == "verified" and result["native_cline"] == "pending"
    assert len(requests) == 2
    assert all(body["messages"] == [{"role": "user", "content": "Reply with exactly READY."}] for body in requests)


def test_provider_rejection_is_not_green_or_body_disclosure():
    transport = httpx.MockTransport(lambda _: httpx.Response(401, json={"error": "dummy-private-key"}))
    with pytest.raises(api.RequestError, match="provider_rejected") as error:
        asyncio.run(api.validate_provider("dummy-test-key", list(api.gateway.MODELS), transport=transport))
    assert "dummy-private-key" not in str(error.value)


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_real_companion_actions_receipts_and_capture_remain_truthful(setup):
    setup["port"] = free_port()
    plan, _ = configure(setup)
    try:
        call(setup, "launch", transaction=plan["id"])
        status = call(setup, "status")
        assert status["companion"]["running"] and not status["bridge"]["capture_worker_running"]
        request_id = uuid.uuid4().hex
        assert call(setup, "action-result", request_id=request_id)["status"] == "not_recorded"
        receipt = call(setup, "owner-action", request_id=request_id, name="review-environment",
                       payload={"note": "Disposable test environment", "model": api.gateway.MODELS[0], "context_bytes": 12000},
                       revision=status["policy_revision"], epoch=None)
        assert receipt["status"] == "succeeded"
        # A renewed access token still reads the same durable device's receipt.
        assert call(setup, "action-result", request_id=request_id) == receipt
        status = call(setup, "status")
        assert not status["runs"] and not status["checkpoints"] and status["capture"]["state"] == "unknown"
    finally:
        call(setup, "stop-companion")


def test_gateway_lifecycle_and_pause_do_not_leak_provider_key(setup):
    setup["gateway_port"] = free_port()
    configure(setup)
    status = call(setup, "status")
    call(setup, "gateway-mode", revision=status["policy_revision"], epoch=None, paused=False)
    try:
        started = call(setup, "gateway-launch", key="dummy-only-never-upstream")
        assert started["running"] and started["status"] == "ready"
        assert call(setup, "gateway-launch", key="dummy-only-never-upstream")["instance"] == started["instance"]
        with httpx.Client(trust_env=False) as client:
            response = client.post(f"http://127.0.0.1:{setup['gateway_port']}/v1/chat/completions",
                                   headers={"Authorization": "Bearer invalid-test-credential"}, json={"model": "vessel-auto", "messages": []})
        assert response.status_code in {401, 403}
        call(setup, "gateway-mode", revision=status["policy_revision"], epoch=None, paused=True)
        with pytest.raises(ValueError, match="paused"):
            call(setup, "gateway-launch", key="dummy-only-never-upstream")
        for name in ["extension-gateway.json", "extension-gateway-stop.json"]:
            file = api.Path(setup["state"]) / name
            if file.exists():
                assert "dummy-only-never-upstream" not in file.read_text()
    finally:
        call(setup, "gateway-stop")
    assert not call(setup, "status")["gateway"]["running"]


def test_interrupted_configuration_is_retryable_and_rollback_idempotent(setup, monkeypatch):
    plan = call(setup, "plan")
    original = api.onboarding.apply
    monkeypatch.setattr(api.onboarding, "apply", lambda _: (_ for _ in ()).throw(OSError("test interruption")))
    with pytest.raises(OSError):
        call(setup, "apply", transaction=plan["id"], review=plan["review"], credential_version=uuid.uuid4().hex)
    assert call(setup, "transaction", transaction=plan["id"])["status"] == "failed"
    monkeypatch.setattr(api.onboarding, "apply", original)
    call(setup, "apply", transaction=plan["id"], review=plan["review"], credential_version=uuid.uuid4().hex)
    first = call(setup, "rollback", transaction=plan["id"], review=plan["review"])
    assert call(setup, "rollback", transaction=plan["id"], review=plan["review"]) == first


def test_occupied_gateway_port_never_stops_other_listener(setup):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        setup["gateway_port"] = listener.getsockname()[1]
        with pytest.raises(api.RequestError, match="companion_failed"):
            call(setup, "plan")
        assert listener.getsockname()[1] == setup["gateway_port"]


def test_remove_preserves_enrollment_and_unrelated_mcp(setup):
    configure(setup)
    status = call(setup, "status")
    call(setup, "remove", revision=status["policy_revision"], epoch=None)
    assert call(setup, "discover")["existing"]
    assert not call(setup, "status")["configuration"]["installed"]
    assert json.loads(api.Path(setup["mcp_config"]).read_text())["mcpServers"] == {"other": {"command": "preserve"}}


def test_retry_after_installer_committed_before_journal_update(setup, monkeypatch):
    plan = call(setup, "plan")
    original = api.onboarding.apply

    def interrupted(plan):
        original(plan)
        raise OSError("power loss after domain commit")

    monkeypatch.setattr(api.onboarding, "apply", interrupted)
    version = uuid.uuid4().hex
    with pytest.raises(OSError):
        call(setup, "apply", transaction=plan["id"], review=plan["review"], credential_version=version)
    monkeypatch.setattr(api.onboarding, "apply", original)
    assert call(setup, "apply", transaction=plan["id"], review=plan["review"], credential_version=version)["status"] == "configured"
    assert call(setup, "status")["runs"] == []


def test_extension_api_orbio_credential_lifecycle(setup):
    plan, _ = configure(setup)

    # Initially no key
    status = call(setup, "orbio-status")
    assert status["has_key"] is False
    assert status["masked_key"] is None

    # Migrate key from extension SecretStorage
    migrated = call(setup, "orbio-migrate-key", key="sk-orbio-extension-key-1234")
    assert migrated["migrated"] is True
    assert migrated["masked_key"] == "sk-orbio-••••1234"

    # Check status
    status2 = call(setup, "orbio-status")
    assert status2["has_key"] is True
    assert status2["masked_key"] == "sk-orbio-••••1234"

    # Get key
    key_doc = call(setup, "orbio-get-key")
    assert key_doc["has_key"] is True
    assert key_doc["key"] == "sk-orbio-extension-key-1234"

    # Forget key
    forgotten = call(setup, "orbio-forget-key")
    assert forgotten["status"] == "forgotten"
    assert forgotten["paused"] is True

    status3 = call(setup, "orbio-status")
    assert status3["has_key"] is False
