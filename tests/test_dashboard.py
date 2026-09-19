import threading

import pytest
from fastapi.testclient import TestClient
from test_service import project as project

from vessel.dashboard import approved_origin, create_app
from vessel.service import Vessel

ORIGIN = "https://vessel.example"
TOKEN = "test-only-session-token-" * 3


@pytest.fixture
def bridge(project):
    service, _, _, clock = project
    app = create_app(service.store.dir, origin=ORIGIN, token=TOKEN, clock=lambda: clock[0])
    with TestClient(
        app, base_url="http://127.0.0.1:8765", headers={"Origin": ORIGIN, "Authorization": "Bearer " + TOKEN}
    ) as client:
        yield client


def envelope(project, action="task", **payload):
    service, _, run, _ = project
    return {
        "request_id": "request-1",
        "action": action,
        "policy_revision": service.policy()["revision"],
        "execution_epoch": run["execution_epoch"],
        "payload": payload or {"run_id": run["id"], "task_id": "reset", "description": "Implement reset"},
    }


def test_local_snapshot_never_contains_bridge_or_encryption_keys(bridge, project):
    service, _, run, _ = project
    response = bridge.get("/v1/snapshot")
    assert response.status_code == 200
    assert response.json()["lease"]["holder_run_id"] == run["id"]
    assert TOKEN not in response.text and service.store._fernet._signing_key.hex() not in response.text
    assert "checkpoint_details" not in response.json()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "headers,code",
    [
        ({"Origin": "https://unapproved.example"}, 403),
        ({"Origin": "null"}, 403),
        ({"Host": "attacker.example:8765"}, 403),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Authorization": ""}, 401),
    ],
)
def test_requests_require_exact_origin_host_and_session(bridge, headers, code):
    assert bridge.get("/v1/snapshot", headers=headers).status_code == code


def test_preflight_is_scoped_and_session_expires(bridge, project):
    response = bridge.options("/v1/actions", headers={"Authorization": ""})
    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == ORIGIN
    project[3][0] += 3600
    assert bridge.get("/v1/snapshot").status_code == 401


def test_repeated_owner_request_is_idempotent(bridge, project):
    body = envelope(project)
    first = bridge.post("/v1/actions", json=body)
    assert first.status_code == 200, first.text
    assert bridge.post("/v1/actions", json=body).json() == first.json()
    assert bridge.get("/v1/requests/request-1").json() == first.json()
    body["payload"]["description"] = "Different inputs"
    assert bridge.post("/v1/actions", json=body).status_code == 409
    assert len(project[0].store.list("tasks")) == 1


def test_capture_block_reports_native_gap_and_both_conversations(bridge, project):
    from test_service import observe

    service, workspace, _, _ = project
    observe(service, workspace, "unbound-implementation-task", "sessionStart")
    with service.store.transaction() as conn:
        service._gap("native_tool_id_unavailable", conn)
    response = bridge.post("/v1/actions", json=envelope(project))
    assert response.status_code == 409
    error = response.json()["error"]
    assert "omitted native tool IDs" in error
    assert "Bound conversation: source-conversation" in error
    assert "unbound-implementation-task" in error
    assert len(error) <= 2000
    assert not service.store.list("tasks")
    assert service.status()["capture"]["state"] == "degraded"


def test_stale_review_and_malformed_requests_do_not_mutate(bridge, project):
    body = envelope(project)
    body["policy_revision"] = 99
    assert bridge.post("/v1/actions", json=body).status_code == 409
    body["policy_revision"] = 1
    body["execution_epoch"] = 2
    assert bridge.post("/v1/actions", json=body).status_code == 409
    body["execution_epoch"] = 1
    body["payload"] = {}
    result = bridge.post("/v1/actions", json=body)
    assert result.status_code == 409 and "Missing action field" in result.text
    assert not project[0].store.list("tasks")
    assert bridge.post("/v1/actions", content="bad").status_code == 415
    assert bridge.post("/v1/actions", json={"action": "shell"}).status_code == 400
    assert (
        bridge.post(
            "/v1/actions", content=b"x" * 131073, headers={"Content-Type": "application/json"}
        ).status_code
        == 413
    )


def test_competing_policy_change_between_review_and_write_is_rejected(bridge, project, monkeypatch):
    from vessel import dashboard

    original = dashboard.dispatch

    def competing(service, name, payload, revision):
        other = Vessel(service.store.dir, clock=service.clock)
        try:
            other.policy(recovery_allowed=False)
            other.heartbeat(project[2]["id"], 1, revalidate=True)
        finally:
            other.close()
        return original(service, name, payload, revision)

    monkeypatch.setattr(dashboard, "dispatch", competing)
    result = bridge.post("/v1/actions", json=envelope(project))
    assert result.status_code == 409 and "Reviewed authority changed" in result.text
    assert not project[0].store.list("tasks")


def test_slow_owner_action_does_not_block_snapshot_or_admit_second_action(bridge, project, monkeypatch):
    from vessel import dashboard

    original = dashboard.dispatch
    entered, release = threading.Event(), threading.Event()

    def slow(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(dashboard, "dispatch", slow)
    responses = []
    thread = threading.Thread(
        target=lambda: responses.append(bridge.post("/v1/actions", json=envelope(project)))
    )
    thread.start()
    try:
        assert entered.wait(3)
        assert bridge.get("/v1/snapshot").status_code == 200
        assert bridge.post("/v1/actions", json=envelope(project)).status_code == 409
    finally:
        release.set()
        thread.join(5)
    assert responses[0].status_code == 200


def test_unfinished_receipt_is_never_replayed(bridge, project, monkeypatch):
    from vessel import dashboard

    def crash(*args):
        raise RuntimeError("simulate interrupted owner action")

    monkeypatch.setattr(dashboard, "dispatch", crash)
    assert bridge.post("/v1/actions", json=envelope(project)).status_code == 500
    receipt = bridge.post("/v1/actions", json=envelope(project))
    assert receipt.status_code == 409 and receipt.json()["status"] == "started"
    assert not project[0].store.list("tasks")


def test_dashboard_review_to_handover_preserves_guard_through_own_epoch_change(bridge, project):
    from test_service import operation

    service, workspace, run, _ = project
    count = 0

    def call(action, **payload):
        nonlocal count
        count += 1
        body = envelope(project, action, **payload)
        body.update(
            request_id=f"review-{count}", execution_epoch=service.status()["lease"]["execution_epoch"]
        )
        response = bridge.post("/v1/actions", json=body)
        assert response.status_code == 200, response.text
        return response.json()["result"]

    call("task", run_id=run["id"], task_id="reset", description="Implement reset")
    call("stop", run_id=run["id"], attested=True, note="Stopped the fixture writer")
    cp = call("checkpoint", run_id=run["id"])
    recovery = call(
        "prepare-recovery",
        checkpoint_id=cp["id"],
        session_id="destination",
        idempotency_key="selected-checkpoint",
        context_bytes=24000,
    )
    assert recovery["status"] == "awaiting_owner"
    transferred = call("handover", recovery_id=recovery["id"], review_token=recovery["review_token"])
    assert transferred["destination_epoch"] == 2
    service.recovery_context(recovery["id"])
    op = operation(service, workspace, "destination")
    call("confirm", recovery_id=recovery["id"], operation_id=op["id"], note="Reviewed real fixture receipt")
    assert bridge.get("/v1/snapshot").json()["lease"]["execution_epoch"] == 2


def test_dashboard_mission_review_commits_its_own_policy_change(bridge, project):
    service, workspace, _, _ = project
    proposal = service.propose(workspace, "mission", {"mission": "Reviewed scope", "constraints": []})
    response = bridge.post(
        "/v1/actions",
        json=envelope(
            project,
            "review-proposal",
            proposal_id=proposal["id"],
            decision="accept",
            note="Reviewed the scope",
        ),
    )
    assert response.status_code == 200, response.text
    assert service.policy()["revision"] == 2


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.com",
        "https://example.com/path",
        "https://user:pass@example.com",
        "https://example.com?x=1",
    ],
)
def test_bridge_origin_cannot_include_credentials_or_paths(origin):
    with pytest.raises(ValueError):
        approved_origin(origin)


def test_orbio_status_initial_not_configured(bridge, project):
    response = bridge.get("/v1/orbio/status")
    assert response.status_code == 200
    data = response.json()
    assert data["connected"] is False
    assert data["status"] == "not_configured"
    assert data["masked_key"] is None
    assert data["balance"]["available"] is False
    assert data["balance"]["currency"] == "CREDIT"


def test_orbio_credentials_lifecycle(project):
    import httpx

    from vessel.orbio import OrbioGatewayClient, RealOrbioAdapter

    service, _, _, clock = project

    def handler(request: httpx.Request):
        if "sk-orbio-valid" in request.headers.get("authorization", ""):
            return httpx.Response(
                200,
                json={
                    "model": "openai/gpt-4.1-mini",
                    "choices": [{"finish_reason": "stop", "message": {"content": "READY"}}],
                },
            )
        return httpx.Response(401, json={"error": "unauthorized"})

    mock_adapter = RealOrbioAdapter(
        gateway_client=OrbioGatewayClient(transport=httpx.MockTransport(handler)),
        clock=lambda: clock[0],
    )

    app = create_app(
        service.store.dir,
        origin=ORIGIN,
        token=TOKEN,
        clock=lambda: clock[0],
        orbio_adapter=mock_adapter,
    )

    with TestClient(
        app,
        base_url="http://127.0.0.1:8765",
        headers={"Origin": ORIGIN, "Authorization": "Bearer " + TOKEN},
    ) as client:
        # Invalid key rejected without persistence
        rejected = client.post("/v1/orbio/credentials", json={"key": "sk-orbio-invalid-key"})
        assert rejected.status_code == 400
        assert "rejected" in rejected.json()["error"]
        assert service.store.get("secrets", "orbio_credential") is None

        # Valid key connects and returns masked representation
        connected = client.post("/v1/orbio/credentials", json={"key": "sk-orbio-valid-key-9999"})
        assert connected.status_code == 200
        result = connected.json()
        assert result["status"] == "connected"
        assert result["masked_key"] == "sk-orbio-••••9999"
        assert "sk-orbio-valid-key-9999" not in connected.text

        # Stored securely in encrypted Store
        secret = service.store.get("secrets", "orbio_credential")
        assert secret is not None
        assert secret["key"] == "sk-orbio-valid-key-9999"
        assert secret["masked"] == "sk-orbio-••••9999"

        # Status endpoint reflects active state
        status = client.get("/v1/orbio/status").json()
        assert status["connected"] is True
        assert status["masked_key"] == "sk-orbio-••••9999"

        # Replace key
        replaced = client.post("/v1/orbio/replace", json={"key": "sk-orbio-valid-key-8888"})
        assert replaced.status_code == 200
        assert replaced.json()["masked_key"] == "sk-orbio-••••8888"
        assert service.store.get("secrets", "orbio_credential")["key"] == "sk-orbio-valid-key-8888"

        # Forget key
        forgotten = client.delete("/v1/orbio/credentials")
        assert forgotten.status_code == 200
        assert forgotten.json()["status"] == "forgotten"
        assert service.store.get("secrets", "orbio_credential") is None

        # Status is back to unconfigured
        status_after = client.get("/v1/orbio/status").json()
        assert status_after["connected"] is False
        assert status_after["masked_key"] is None


def test_orbio_claim_and_models_and_routing(bridge):
    # Claim without MCP returns mcp_not_configured
    claim_res = bridge.post("/v1/orbio/claim", json={"name": "test-claim"})
    assert claim_res.status_code == 200
    assert claim_res.json()["status"] == "mcp_not_configured"

    # Get models returns catalog
    models_res = bridge.get("/v1/orbio/models")
    assert models_res.status_code == 200
    data = models_res.json()
    assert len(data["models"]) >= 8
    assert "openrouter/auto" in [m["id"] for m in data["models"]]
    assert "active_model" in data

    # Update routing to smart routing
    route_res = bridge.post("/v1/orbio/routing", json={"active_model": "openrouter/auto", "smart_routing": True})
    assert route_res.status_code == 200
    r_data = route_res.json()
    assert r_data["status"] == "updated"
    assert r_data["smart_routing"] is True
    assert "openrouter/auto" in r_data["gateway_models"]

    # Update routing to specific model
    route_res2 = bridge.post("/v1/orbio/routing", json={"active_model": "anthropic/claude-sonnet-4.5", "smart_routing": False})
    assert route_res2.status_code == 200
    assert route_res2.json()["active_model"] == "anthropic/claude-sonnet-4.5"
    assert route_res2.json()["smart_routing"] is False

