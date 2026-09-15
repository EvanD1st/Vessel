"""Durable browser pairing, short-lived access sessions and owner revocation."""

from __future__ import annotations

import hashlib
import re
import secrets


class DeviceUnauthorized(ValueError):
    pass


def fingerprint(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _device(service, device_id, origin, enrollment_id, conn=None, *, allow_revoked=False):
    device = service.store.get("devices", device_id, conn=conn)
    if (
        not device
        or device.get("kind") != "paired"
        or device.get("origin") != origin
        or device.get("enrollment_id") != enrollment_id
        or (device.get("revoked_at") is not None and not allow_revoked)
    ):
        raise DeviceUnauthorized("Device pairing is missing or revoked. Pair this browser again.")
    return device


def authorize(service, token, origin, enrollment_id, *, credential=False, deleting=False, conn=None):
    key = fingerprint(token)
    if credential:
        device = _device(service, key[:24], origin, enrollment_id, conn, allow_revoked=deleting)
        if not secrets.compare_digest(device["credential_digest"], key):
            raise DeviceUnauthorized("Invalid device credential")
        return {"device_id": device["id"], "session_id": device["id"], "kind": "credential"}
    session = service.store.get("dashboard_sessions", key, conn=conn)
    if not session or service.clock() >= session["expires_at"]:
        raise DeviceUnauthorized("Companion access session expired. Renew the paired device session.")
    device = _device(service, session["device_id"], origin, enrollment_id, conn)
    return {**session, "session_id": device["id"], "kind": "access"}


def _issue_session(service, device, ttl, conn):
    now = service.clock()
    # Expired access sessions are dispensable; durable owner receipts are separate.
    for old in service.store.list("dashboard_sessions", conn=conn):
        if now >= old["expires_at"]:
            service.store.delete("dashboard_sessions", old["id"], conn=conn)
    token = secrets.token_urlsafe(36)
    key = fingerprint(token)
    expires_at = now + ttl
    service.store.put(
        "dashboard_sessions",
        key,
        {
            "id": key,
            "device_id": device["id"],
            "expires_at": expires_at,
            "renew_after": expires_at - min(ttl / 2, 1800),
        },
        conn=conn,
    )
    device["last_used_at"] = now
    service.store.put("devices", device["id"], device, conn=conn)
    return {
        "token": token,
        "expires_at": expires_at,
        "device_id": device["id"],
        "enrollment_id": device["enrollment_id"],
    }


def pair(service, origin, enrollment_id, label, ttl):
    if not isinstance(label, str) or not label.strip() or len(label) > 80:
        raise ValueError("Use a device label of 1 to 80 characters")
    credential = secrets.token_urlsafe(36)
    key = fingerprint(credential)
    with service.store.transaction() as conn:
        service._writable(conn)
        device = {
            "id": key[:24],
            "kind": "paired",
            "credential_digest": key,
            "origin": origin,
            "enrollment_id": enrollment_id,
            "label": label.strip(),
            "created_at": service.clock(),
            "revoked_at": None,
        }
        if service.store.get("devices", device["id"], conn=conn):
            raise ValueError("Device identifier collision; retry pairing")
        return {**_issue_session(service, device, ttl, conn), "credential": credential}


def renew(service, credential, origin, enrollment_id, ttl):
    # BEGIN IMMEDIATE serializes the check and issuance with owner revocation.
    with service.store.transaction() as conn:
        service._writable(conn)
        admitted = authorize(service, credential, origin, enrollment_id, credential=True, conn=conn)
        device = _device(service, admitted["device_id"], origin, enrollment_id, conn)
        return _issue_session(service, device, ttl, conn)


def revoke(service, device_id):
    if not isinstance(device_id, str) or not re.fullmatch(r"[a-f0-9]{24}", device_id):
        raise ValueError("Choose the 24-character device ID printed by devices")
    with service.store.transaction() as conn:
        service._writable(conn)
        device = service.store.get("devices", device_id, conn=conn)
        if device is None:
            raise ValueError("Device was not found")
        if device.get("revoked_at") is None:
            device["revoked_at"] = service.clock()
        device["expires_at"] = 0  # Also denies legacy temporary credentials during migration.
        service.store.put("devices", device_id, device, conn=conn)
        return {"status": "revoked", "device_id": device_id}


def list_devices(service):
    result = []
    with service.store.transaction() as conn:
        # Older rows did not include their ID in the encrypted payload.
        ids = conn.execute("SELECT id FROM documents WHERE kind='devices' ORDER BY id").fetchall()
        for row in ids:
            device = service.store.get("devices", row[0], conn=conn)
            result.append(
                {
                    "id": row[0],
                    "label": device.get("label", "Legacy temporary connection"),
                    "kind": device.get("kind", "legacy"),
                    "origin": device.get("origin"),
                    "created_at": device.get("created_at"),
                    "last_used_at": device.get("last_used_at"),
                    "revoked_at": device.get("revoked_at"),
                }
            )
    return result
