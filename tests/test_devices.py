import json
import threading

import pytest
from fastapi.testclient import TestClient
from test_service import project as project

from vessel import cli, devices
from vessel.dashboard import create_app
from vessel.service import Vessel

ORIGIN = "https://vessel.example"
BOOTSTRAP = "bootstrap-test-only-" * 3


@pytest.fixture
def paired(project):
    service, _, _, clock = project
    app = create_app(service.store.dir, origin=ORIGIN, token=BOOTSTRAP, clock=lambda: clock[0])
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Origin": ORIGIN}) as client:
        response = client.post("/v1/pair", json={"label": "Test browser"}, headers=bearer(BOOTSTRAP))
        assert response.status_code == 200, response.text
        yield client, response.json()


def bearer(token):
    return {"Authorization": "Bearer " + token}


def test_pairing_is_separate_from_access_and_device_list_is_useful(paired, project):
    client, grant = paired
    assert grant["credential"] != grant["token"]
    assert client.get("/v1/snapshot", headers=bearer(grant["credential"])).status_code == 401
    result = client.get("/v1/devices", headers=bearer(grant["token"]))
    row = result.json()["devices"][0]
    assert row["id"] == grant["device_id"] and row["label"] == "Test browser"
    assert grant["credential"] not in result.text and "credential_digest" not in result.text
    second = client.post("/v1/pair", json={"label": "Other browser"}, headers=bearer(BOOTSTRAP)).json()
    assert second["device_id"] != grant["device_id"]
    assert (
        client.post(
            "/v1/pair", json={"label": "Unauthorized pair"}, headers=bearer(grant["token"])
        ).status_code
        == 403
    )


def test_offline_pair_survives_restart_and_renews_with_its_own_expiry(paired, project):
    client, grant = paired
    service, _, _, clock = project
    clock[0] += 7 * 86400
    app = create_app(
        service.store.dir, origin=ORIGIN, token="new-test-bootstrap-" * 3, ttl=600, clock=lambda: clock[0]
    )
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Origin": ORIGIN}) as restarted:
        assert restarted.get("/v1/snapshot", headers=bearer(grant["token"])).status_code == 401
        clock[0] += 100
        response = restarted.post("/v1/renew", json={}, headers=bearer(grant["credential"]))
        assert response.status_code == 200, response.text
        renewed = response.json()
        snapshot = restarted.get("/v1/snapshot", headers=bearer(renewed["token"])).json()
        assert snapshot["bridge"]["expires_at"] == renewed["expires_at"] == clock[0] + 600
        assert snapshot["bridge"]["renew_after"] == clock[0] + 300
        assert snapshot["bridge"]["device_id"] == grant["device_id"]


def test_pairing_cannot_move_to_another_origin(paired, project):
    _, grant = paired
    service, _, _, clock = project
    app = create_app(
        service.store.dir,
        origin="https://other.example",
        token="other-test-bootstrap-" * 3,
        clock=lambda: clock[0],
    )
    with TestClient(
        app, base_url="http://127.0.0.1:8765", headers={"Origin": "https://other.example"}
    ) as client:
        assert client.post("/v1/renew", json={}, headers=bearer(grant["credential"])).status_code == 401
        assert client.get("/v1/snapshot", headers=bearer(grant["token"])).status_code == 401


def test_delete_revokes_sessions_and_renewal_but_not_other_devices(paired):
    client, grant = paired
    other = client.post("/v1/pair", json={"label": "Other"}, headers=bearer(BOOTSTRAP)).json()
    for _ in range(2):
        response = client.delete("/v1/devices/current", headers=bearer(grant["credential"]))
        assert response.status_code == 200 and response.json()["status"] == "revoked"
    assert client.get("/v1/snapshot", headers=bearer(grant["token"])).status_code == 401
    assert client.post("/v1/renew", json={}, headers=bearer(grant["credential"])).status_code == 401
    assert client.get("/v1/snapshot", headers=bearer(other["token"])).status_code == 200


def test_renewal_does_not_overwrite_concurrent_owner_revocation(paired, project, monkeypatch):
    client, grant = paired
    owner = Vessel(project[0].store.dir, clock=lambda: project[3][0])
    entered, release, revoke_started, revoked = (threading.Event() for _ in range(4))
    original = devices._issue_session
    responses, errors = [], []

    def slow_issue(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    def revoke():
        try:
            revoke_started.set()
            devices.revoke(owner, grant["device_id"])
            revoked.set()
        except Exception as error:
            errors.append(error)

    monkeypatch.setattr(devices, "_issue_session", slow_issue)
    renewal = threading.Thread(
        target=lambda: responses.append(
            client.post("/v1/renew", json={}, headers=bearer(grant["credential"]))
        )
    )
    revocation = threading.Thread(target=revoke)
    try:
        renewal.start()
        assert entered.wait(3)
        revocation.start()
        assert revoke_started.wait(3)
        assert not revoked.wait(0.1), "Revocation must serialize with session issuance"
    finally:
        release.set()
        renewal.join(5)
        if revocation.ident is not None:
            revocation.join(5)
        owner.close()
    assert not errors and revoked.is_set() and responses[0].status_code == 200
    assert client.get("/v1/snapshot", headers=bearer(responses[0].json()["token"])).status_code == 401
    assert client.post("/v1/renew", json={}, headers=bearer(grant["credential"])).status_code == 401


def test_device_revoked_after_middleware_cannot_commit_owner_action(paired, project, monkeypatch):
    from test_dashboard import envelope

    from vessel import dashboard

    client, grant = paired
    original = dashboard.dispatch

    def revoke_then_dispatch(service, *args):
        with_owner = Vessel(service.store.dir, clock=service.clock)
        try:
            devices.revoke(with_owner, grant["device_id"])
        finally:
            with_owner.close()
        return original(service, *args)

    monkeypatch.setattr(dashboard, "dispatch", revoke_then_dispatch)
    response = client.post("/v1/actions", json=envelope(project), headers=bearer(grant["token"]))
    assert response.status_code == 409 and "revoked" in response.text
    assert not project[0].store.list("tasks")


def test_cli_lists_ids_including_legacy_rows_and_revokes(paired, project, capsys):
    _, grant = paired
    service = project[0]
    legacy_id = "a" * 24
    service.store.put("devices", legacy_id, {"created_at": 1000, "expires_at": 4600})
    args = ["--state", str(service.store.dir)]
    assert cli.main([*args, "devices"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["id"] for r in rows} == {grant["device_id"], legacy_id}
    assert cli.main([*args, "revoke-device", grant["device_id"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "revoked"
    assert cli.main([*args, "revoke-device", "b" * 24]) == 1
    assert "not found" in capsys.readouterr().err


def test_receipt_identity_survives_access_session_rotation(paired, project):
    from test_dashboard import envelope

    client, grant = paired
    first = client.post("/v1/actions", json=envelope(project), headers=bearer(grant["token"]))
    assert first.status_code == 200
    renewed = client.post("/v1/renew", json={}, headers=bearer(grant["credential"])).json()
    receipt = client.get("/v1/requests/request-1", headers=bearer(renewed["token"]))
    assert receipt.json() == first.json()
    replay = client.post("/v1/actions", json=envelope(project), headers=bearer(renewed["token"]))
    assert replay.json() == first.json() and len(project[0].store.list("tasks")) == 1


@pytest.mark.parametrize("body", [{}, {"label": ""}, {"label": "a" * 81}, {"label": "x", "extra": 1}])
def test_invalid_pairing_body_is_rejected(paired, body):
    client, _ = paired
    assert client.post("/v1/pair", json=body, headers=bearer(BOOTSTRAP)).status_code == 400
