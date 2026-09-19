import base64
import json

import pytest

from vessel.cli import main
from vessel.identity import (
    export_identity_pass,
    import_identity_pass,
    inspect_identity_pass,
    parse_pass_input,
)
from vessel.storage import Store


@pytest.fixture
def temp_store(tmp_path):
    store = Store(tmp_path / "test_store")
    yield store
    store.close()


def test_parse_pass_input_json_and_token(tmp_path):
    card = {
        "format": "vessel-operator-identity",
        "version": 1,
        "operator": {"id": "usr_test123", "name": "Test Op", "email": "test@vessel.local"},
        "origin": "https://vessel-dashboard.cloud-ip.cc",
        "enrollmentId": "enr_abc123",
        "deviceId": "dev_test",
        "port": 8765,
        "pairingCredential": "cred_secret_token",
        "issuedAt": 1726000000000,
        "fingerprint": "vsl-id-12345678-usr_te",
    }
    # Test pass_file
    pass_file = tmp_path / "vessel-identity.json"
    pass_file.write_text(json.dumps(card), encoding="utf-8")
    parsed_from_file = parse_pass_input(pass_file=pass_file)
    assert parsed_from_file["operator"]["id"] == "usr_test123"

    # Test token
    encoded = base64.urlsafe_b64encode(json.dumps(card).encode("utf-8")).decode("ascii").rstrip("=")
    token = f"vessel-pass:{encoded}"
    parsed_from_token = parse_pass_input(token=token)
    assert parsed_from_token["operator"]["id"] == "usr_test123"
    assert parsed_from_token["enrollmentId"] == "enr_abc123"


def test_parse_pass_invalid():
    with pytest.raises(ValueError, match="Either --pass-file or --token must be supplied"):
        parse_pass_input()

    with pytest.raises(ValueError, match="Unsupported Identity Card format or version"):
        parse_pass_input(token="vessel-pass:" + base64.urlsafe_b64encode(b'{"format":"unknown"}').decode("ascii"))

    with pytest.raises(ValueError, match="missing required operator credentials"):
        parse_pass_input(token="vessel-pass:" + base64.urlsafe_b64encode(b'{"format":"vessel-operator-identity","version":1}').decode("ascii"))


def test_inspect_identity_pass():
    card = {
        "format": "vessel-operator-identity",
        "version": 1,
        "operator": {"id": "usr_alice", "name": "Alice", "email": "alice@local"},
        "origin": "https://vessel-dashboard.cloud-ip.cc",
        "enrollmentId": "enr_999",
        "deviceId": "dev_win",
        "port": 8765,
        "pairingCredential": "token_abc",
        "issuedAt": 1700000000000,
        "fingerprint": "vsl-id-test",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(card).encode("utf-8")).decode("ascii")
    inspection = inspect_identity_pass(token=f"vessel-pass:{encoded}")
    assert inspection["valid"] is True
    assert inspection["operator"]["id"] == "usr_alice"
    assert inspection["has_pairing_credential"] is True
    assert inspection["enrollment_id"] == "enr_999"


def test_import_and_export_identity(temp_store, tmp_path):
    card = {
        "format": "vessel-operator-identity",
        "version": 1,
        "operator": {"id": "usr_bob", "name": "Bob", "email": "bob@local"},
        "origin": "https://vessel-dashboard.cloud-ip.cc",
        "enrollmentId": "enr_bob_1",
        "deviceId": "dev_laptop",
        "port": 8765,
        "pairingCredential": "pair_bob_123",
        "issuedAt": 1700000000000,
        "fingerprint": "vsl-id-bob",
    }
    encoded = base64.urlsafe_b64encode(json.dumps(card).encode("utf-8")).decode("ascii")
    import_res = import_identity_pass(temp_store, token=f"vessel-pass:{encoded}")
    assert import_res["status"] == "imported"
    assert import_res["operator"]["id"] == "usr_bob"

    # Verify store content
    op_record = temp_store.get("operator", "identity")
    assert op_record["operator"]["name"] == "Bob"
    pairing_record = temp_store.get("operator", "pairing")
    assert pairing_record["enrollment_id"] == "enr_bob_1"
    assert pairing_record["credential"] == "pair_bob_123"

    # Export
    out_file = tmp_path / "exported.json"
    export_res = export_identity_pass(temp_store, pass_file=out_file)
    assert export_res["status"] == "exported"
    assert out_file.exists()

    exported_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert exported_data["operator"]["id"] == "usr_bob"
    assert exported_data["enrollmentId"] == "enr_bob_1"
    assert exported_data["pairingCredential"] == "pair_bob_123"


def test_cli_identity_inspect_and_import(tmp_path, capsys):
    state_dir = tmp_path / "cli_state"
    card = {
        "format": "vessel-operator-identity",
        "version": 1,
        "operator": {"id": "usr_cli", "name": "CLI User", "email": "cli@local"},
        "origin": "https://vessel-dashboard.cloud-ip.cc",
        "enrollmentId": "enr_cli",
        "deviceId": "dev_cli",
        "port": 8765,
        "pairingCredential": "cred_cli",
        "issuedAt": 1700000000000,
        "fingerprint": "vsl-id-cli",
    }
    pass_file = tmp_path / "pass.json"
    pass_file.write_text(json.dumps(card), encoding="utf-8")

    # CLI inspect
    ret = main(["--state", str(state_dir), "identity", "inspect", "--pass-file", str(pass_file)])
    assert ret == 0
    captured = capsys.readouterr()
    assert '"valid": true' in captured.out
    assert '"usr_cli"' in captured.out

    # CLI import
    ret = main(["--state", str(state_dir), "identity", "import", "--pass-file", str(pass_file)])
    assert ret == 0
    captured = capsys.readouterr()
    assert '"status": "imported"' in captured.out

    # CLI export
    ret = main(["--state", str(state_dir), "identity", "export"])
    assert ret == 0
    captured = capsys.readouterr()
    assert '"format": "vessel-operator-identity"' in captured.out
    assert '"usr_cli"' in captured.out
