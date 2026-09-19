"""Operator Identity Card and cross-system portability support."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from vessel.storage import Store


def parse_pass_input(pass_file: Path | None = None, token: str | None = None) -> dict[str, Any]:
    if pass_file:
        raw = Path(pass_file).read_text(encoding="utf-8").strip()
    elif token:
        raw = token.strip()
    else:
        raise ValueError("Either --pass-file or --token must be supplied")

    if raw.startswith("vessel-pass:"):
        encoded = raw[len("vessel-pass:") :].strip()
        padding = "=" * (-len(encoded) % 4)
        raw_json = base64.urlsafe_b64decode((encoded + padding).encode("ascii")).decode("utf-8")
    else:
        raw_json = raw

    data = json.loads(raw_json)
    if not isinstance(data, dict):
        raise ValueError("Invalid Identity Card format: expected JSON object")
    if data.get("format") != "vessel-operator-identity" or data.get("version") != 1:
        raise ValueError("Unsupported Identity Card format or version")
    if not data.get("operator") or not isinstance(data["operator"], dict) or not data["operator"].get("id"):
        raise ValueError("Identity Card missing required operator credentials")
    if not data.get("origin"):
        raise ValueError("Identity Card missing origin configuration")

    return data


def inspect_identity_pass(pass_file: Path | None = None, token: str | None = None) -> dict[str, Any]:
    data = parse_pass_input(pass_file, token)
    return {
        "valid": True,
        "format": data["format"],
        "version": data["version"],
        "operator": data["operator"],
        "origin": data["origin"],
        "fingerprint": data.get("fingerprint"),
        "enrollment_id": data.get("enrollmentId"),
        "device_id": data.get("deviceId"),
        "port": data.get("port"),
        "has_pairing_credential": bool(data.get("pairingCredential")),
        "issued_at": data.get("issuedAt"),
    }


def import_identity_pass(store: Store, pass_file: Path | None = None, token: str | None = None) -> dict[str, Any]:
    data = parse_pass_input(pass_file, token)
    store.put(
        "operator",
        "identity",
        {
            "operator": data["operator"],
            "origin": data["origin"],
            "fingerprint": data.get("fingerprint"),
            "imported_at": time.time(),
        },
    )
    if data.get("enrollmentId") and data.get("pairingCredential"):
        store.put(
            "operator",
            "pairing",
            {
                "enrollment_id": data["enrollmentId"],
                "device_id": data.get("deviceId"),
                "port": data.get("port"),
                "credential": data["pairingCredential"],
                "imported_at": time.time(),
            },
        )
    return {
        "status": "imported",
        "operator": data["operator"],
        "origin": data["origin"],
        "fingerprint": data.get("fingerprint"),
        "enrollment_id": data.get("enrollmentId"),
        "notice": "Identity pass successfully registered. Run the companion with 'python -m vessel companion' or VS Code to resume continuity.",
    }


def export_identity_pass(store: Store, pass_file: Path | None = None) -> dict[str, Any]:
    saved = store.get("operator", "identity") or {}
    operator = saved.get("operator", {"id": "usr_local", "name": "Local Operator", "email": "operator@local"})
    origin = saved.get("origin", "https://vessel-dashboard.cloud-ip.cc")
    pairing = store.get("operator", "pairing") or {}

    issued_at = int(time.time() * 1000)
    raw = f"{operator.get('id')}:{operator.get('email')}:{origin}:{pairing.get('enrollment_id', '')}:{issued_at}"
    fingerprint = f"vsl-id-{hashlib.sha256(raw.encode()).hexdigest()[:8]}-{operator.get('id', 'usr')[:6]}"

    card = {
        "format": "vessel-operator-identity",
        "version": 1,
        "operator": operator,
        "origin": origin,
        "enrollmentId": pairing.get("enrollment_id"),
        "deviceId": pairing.get("device_id"),
        "port": pairing.get("port"),
        "pairingCredential": pairing.get("credential"),
        "issuedAt": issued_at,
        "fingerprint": fingerprint,
    }

    if pass_file:
        Path(pass_file).write_text(json.dumps(card, indent=2), encoding="utf-8")
        return {"status": "exported", "path": str(pass_file), "fingerprint": fingerprint}

    return card
