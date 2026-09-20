"""Versioned owner-only stdin RPC for the VS Code extension, never registered in MCP.

The existing service, adapter, dashboard and gateway remain the authorities. Requests
and errors are bounded; provider keys are never persisted or returned in diagnostics.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import socket
import sys
import time
import uuid
from pathlib import Path

import httpx

from vessel import __version__, adapters, cline_compat, desktop, devices, onboarding, registry
from vessel import extension_gateway as gateway
from vessel.dashboard import ACTIONS, reviewed_authority
from vessel.gateway import GatewayAdmission, UpstreamRoute, create_app
from vessel.locking import ArtifactLock
from vessel.service import Blocked, Vessel, canonical, digest
from vessel.storage import _atomic_write, _regular_file, safe_directory


class RequestError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def write_json(path, value):
    _atomic_write(path, json.dumps(value, sort_keys=True).encode())


def identifier(value):
    if not isinstance(value, str) or len(value) != 32 or any(ch not in "0123456789abcdef" for ch in value):
        raise RequestError("invalid_request")
    return value


def state_for(workspace):
    workspace = safe_directory(onboarding.local_path(workspace))
    state = registry.lookup(canonical(workspace))
    if not state:
        raise RequestError("not_enrolled")
    return workspace, safe_directory(state)


def port_available(port):
    if type(port) is not int or not 1024 <= port <= 65535:
        raise RequestError("invalid_request")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def model_pair(models):
    if not isinstance(models, list) or len(models) != 2 or len(set(models)) != 2 or set(models) != set(gateway.MODELS):
        raise RequestError("invalid_request")
    return models


def transaction_path(storage, transaction):
    return storage / "transactions" / (identifier(transaction) + ".json")


def prepare(request, storage):
    workspace = safe_directory(onboarding.local_path(request["workspace"]))
    if storage.is_relative_to(workspace) or workspace.is_relative_to(storage):
        raise RequestError("invalid_request")
    models = model_pair(request.get("models") or list(gateway.MODELS))
    try:
        plan = onboarding.prepare(workspace, state=request.get("state"), mission=request.get("mission"), mcp_config=request.get("mcp_config"),
                                  origin=request.get("origin", "http://localhost:3000"), port=request.get("port", 8765))
    except ValueError:
        raise RequestError("configuration_conflict") from None
    state = Path(plan["state"])
    config = Path(plan["profile"]["mcp_config"])
    current_gateway = None
    prior_manifest = None
    prior_profile = None
    prior_policy = None
    prior_epoch = None
    if plan["existing_enrollment"]:
        service = Vessel(state)
        try:
            current_gateway = service.store.get("control", gateway.CONTROL)
            prior_manifest = adapters._manifest(workspace, state)
            prior_profile = service.store.get("control", onboarding.PROFILE)
            prior_policy = service.policy()
            lease = service.store.get("control", "lease")
            prior_epoch = lease["execution_epoch"] if lease else None
        finally:
            service.close()
    bridge_port = plan["profile"]["port"]
    gateway_port = request.get("gateway_port", (current_gateway or {}).get("port", 8091))
    if gateway_port == bridge_port:
        raise RequestError("invalid_request")
    if not port_available(bridge_port) and not (state.exists() and desktop.status(state)["running"]):
        raise RequestError("companion_failed")
    if not port_available(gateway_port) and not (state.exists() and gateway.status(state)["running"]):
        raise RequestError("companion_failed")
    transaction = uuid.uuid4().hex
    changes = [str(workspace / ".clinerules/hooks" / (hook + ".ps1")) for hook in adapters.HOOKS] if not prior_manifest else []
    record = {"schema": 1, "id": transaction, "status": "review", "plan": plan, "models": models,
              "gateway_port": gateway_port, "mcp_sha256": hashlib.sha256(_regular_file(config, 1048576)).hexdigest(),
              "mcp_content_digest": digest(json.loads(_regular_file(config, 1048576))),
              "previous_profile": prior_profile, "previous_gateway": current_gateway, "previous_policy": prior_policy,
              "previous_epoch": prior_epoch,
              "existing_adapter": bool(prior_manifest), "changes": changes + [str(config), str(state)],
              "processes": ["loopback owner companion", "loopback inference gateway; key in memory only"],
              "completed": [], "created_at": time.time()}
    record["review"] = digest(record)
    safe_directory(storage / "transactions", create=True)
    write_json(transaction_path(storage, transaction), record)
    return record


def apply(request, storage):
    path = transaction_path(storage, request["transaction"])
    with ArtifactLock(path.parent).hold():
        record = json.loads(_regular_file(path, 131072))
        if record["review"] != request["review"] or record["status"] not in {"review", "failed", "applying", "configured"}:
            raise RequestError("review_changed")
        if record["status"] == "configured":
            return record
        plan, completed = record["plan"], record["completed"]
        state = Path(plan["state"])
        if not completed and hashlib.sha256(_regular_file(Path(plan["profile"]["mcp_config"]), 1048576)).hexdigest() != record["mcp_sha256"]:
            # Recover a crash after the domain installer committed, before our journal did.
            manifest = adapters._manifest(Path(plan["profile"]["workspace"]), state) if state.exists() else None
            if not record.get("configuration_started") or record["existing_adapter"] or not manifest:
                raise RequestError("review_changed")
            current = json.loads(_regular_file(Path(plan["profile"]["mcp_config"]), 1048576))
            if current.get("mcpServers", {}).pop(manifest["server_name"], None) != manifest["entry"]:
                raise RequestError("review_changed")
            if digest(current) != record["mcp_content_digest"]:
                raise RequestError("review_changed")
        record["status"] = "applying"
        write_json(path, record)
        try:
            if "configuration" not in completed:
                # Domain implementation rechecks enrollment, mission, conflicts and scope.
                record["configuration_started"] = True
                write_json(path, record)
                result = onboarding.apply(plan)
                completed.append("configuration")
                record["enrollment_id"] = result["enrollment_id"]
                write_json(path, record)
            with_service = Vessel(state)
            try:
                if "routing" not in completed:
                    policy = with_service.policy()
                    before = record["previous_policy"]
                    intent = record.get("routing_intent")
                    resumed_policy = bool(intent and policy["revision"] == intent["revision"] and
                                          policy["allowed_models"] == intent["allowed_models"])
                    if before and policy != before and not resumed_policy:
                        raise RequestError("review_changed")
                    with reviewed_authority(with_service, policy["revision"], record["previous_epoch"]):
                        allowed = list(dict.fromkeys(policy["allowed_models"] + record["models"]))
                        version = identifier(request.get("credential_version") or uuid.uuid4().hex)
                        if intent and intent["credential_version"] != version:
                            raise RequestError("review_changed")
                        record["routing_intent"] = {"revision": policy["revision"] + int(allowed != policy["allowed_models"]),
                                                    "allowed_models": allowed, "credential_version": version}
                        write_json(path, record)
                        if allowed != policy["allowed_models"]:
                            policy = with_service.policy(allowed_models=allowed)
                        record["written_policy_revision"] = policy["revision"]
                        record["written_credential_version"] = version
                        write_json(path, record)
                        config = {"schema": 1, "port": record["gateway_port"], "models": record["models"],
                                  "credential_version": version, "paused": True, "verified_at": request.get("verified_at"),
                                  "validation": "canned_text_probe", "native_cline": "pending"}
                        with with_service.store.transaction() as conn:
                            with_service.store.put("control", gateway.CONTROL, config, conn=conn)
                        record["written_credential_version"] = version
                    completed.append("routing")
                    write_json(path, record)
            finally:
                with_service.close()
            record["status"] = "configured"
            write_json(path, record)
            return record
        except Exception:
            record.update(status="failed", error_code="setup_step_failed")
            write_json(path, record)
            raise


def rollback(request, storage):
    path = transaction_path(storage, request["transaction"])
    with ArtifactLock(path.parent).hold():
        record = json.loads(_regular_file(path, 131072))
        if record["review"] != request["review"]:
            raise RequestError("review_changed")
        if record["status"] == "rolled_back":
            return {"status": "rolled_back", "recovery_data_preserved": True}
        state = Path(record["plan"]["state"])
        if state.exists() and (state / "vessel.sqlite3").exists():
            service = Vessel(state)
            try:
                current = service.store.get("control", gateway.CONTROL)
                if current and record.get("written_credential_version") and current["credential_version"] != record["written_credential_version"]:
                    raise RequestError("review_changed")
                if current:
                    current["paused"] = True
                    service.store.put("control", gateway.CONTROL, current)
                # Never restore old authority or delete enrollment/checkpoints on rollback.
                if record.get("routing_intent") and record.get("previous_policy"):
                    policy = service.policy()
                    intended = record["routing_intent"]
                    if policy != record["previous_policy"] and (policy["revision"] != intended["revision"] or policy["allowed_models"] != intended["allowed_models"]):
                        raise RequestError("review_changed")
                    if policy != record["previous_policy"]:
                        service.policy(allowed_models=record["previous_policy"]["allowed_models"])
                        record["previous_policy"] = service.policy()
                        write_json(path, record)
                if record.get("configuration_started") and not record["existing_adapter"]:
                    adapters.uninstall("cline", Path(record["plan"]["profile"]["workspace"]), state)
                    service.store.delete("control", "cline_adapter")
                if record.get("previous_profile"):
                    service.store.put("control", onboarding.PROFILE, record["previous_profile"])
                if record.get("previous_gateway"):
                    service.store.put("control", gateway.CONTROL, {**record["previous_gateway"], "paused": True})
            finally:
                service.close()
            # Only extension-owned instances are stopped here.
            if record.get("gateway_instance") == gateway.status(state).get("instance"):
                gateway.stop(state)
            if record.get("companion_instance") == desktop.status(state).get("instance"):
                desktop.stop(state)
        record["status"] = "rolled_back"
        write_json(path, record)
        return {"status": "rolled_back", "recovery_data_preserved": True}


def bridge_request(state, method, route, payload=None):
    profile = onboarding.load_profile(state)
    service = Vessel(state)
    try:
        saved = service.store.get("control", "extension_device")
        enrollment = service._enrollment()["id"]
        if not saved:
            paired = devices.pair(service, profile["origin"], enrollment, "VS Code VESSEL", profile["ttl"])
            saved = {"credential": paired["credential"]}
            service.store.put("control", "extension_device", saved)
        session = devices.renew(service, saved["credential"], profile["origin"], enrollment, profile["ttl"])
    finally:
        service.close()
    with httpx.Client(trust_env=False, timeout=25, follow_redirects=False) as client:
        response = client.request(method, f"http://127.0.0.1:{profile['port']}{route}", json=payload,
                                  headers={"Origin": profile["origin"], "Authorization": "Bearer " + session["token"]})
    if method == "GET" and route.startswith("/v1/requests/") and response.status_code == 404:
        return {"status": "not_recorded"}
    if response.status_code != 200:
        raise RequestError("owner_action_blocked")
    result = response.json()
    if method != "GET" and isinstance(result, dict) and result.get("status") in {"failed", "uncertain"}:
        raise RequestError("owner_action_blocked")
    return result


def snapshot(workspace, state):
    service = Vessel(state)
    try:
        result = service.status(workspace)
        result["policy"] = service.policy()
        result["tasks"] = service.store.list("tasks")[-200:]
        result["operations"] = []
        lease = result["lease"]
        if lease:
            result["operations"] = [
                {"id": item["id"], "uncertain": item["uncertain"], "successful": service._successful_operation(item)}
                for item in service.operations(lease["holder_run_id"])[-200:]
            ]
        result["gateway_config"] = service.store.get("control", gateway.CONTROL)
        result["companion"] = desktop.status(state)
        result["bridge"] = {"capture_worker_running": False, "worker_error": None}
        if result["companion"]["running"]:
            try:
                bridge = bridge_request(state, "GET", "/v1/snapshot")["bridge"]
                result["bridge"] = {"capture_worker_running": bridge["capture_worker_running"],
                                    "worker_error": "capture_worker_failed" if bridge["worker_error"] else None}
            except (ValueError, OSError, httpx.HTTPError):
                result["bridge"]["worker_error"] = "companion_unreachable"
        result["gateway"] = gateway.status(state)
        result["configuration"] = adapters.inspect("cline", workspace, state)
        result["checkpoints"] = [{**cp, "validation": service.validate_checkpoint(cp["id"])} for cp in result["checkpoints"][-100:]]
        result["runs"] = result["runs"][-100:]
        result["sessions"] = result["sessions"][-100:]
        result["recoveries"] = result["recoveries"][-50:]
        return result
    finally:
        service.close()


async def validate_provider(key, models, *, transport=None):
    model_pair(models)
    if not isinstance(key, str) or not 1 <= len(key) <= 8192 or any(c.isspace() for c in key):
        raise RequestError("provider_rejected")
    # The fixed probe goes through the same bounded inference boundary as production.
    token = uuid.uuid4().hex
    admission = GatewayAdmission("probe", "probe", "owner", "probe", "probe", "default", 1, 1, 1, 1, frozenset(models))
    endpoint = gateway.resolve_endpoint(key)
    app = create_app(routes={"default": UpstreamRoute(endpoint, key, frozenset(models))},
                     authorize=lambda supplied: admission if supplied == token else None,
                     transport=transport, upstream_timeout_seconds=15)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
            for model in models:
                response = await client.post("/v1/chat/completions", headers={"Authorization": "Bearer " + token}, json={
                    "model": model, "messages": [{"role": "user", "content": "Reply with exactly READY."}], "max_tokens": 16,
                    "stream": False})
                if response.status_code != 200:
                    raise RequestError("provider_rejected")
                body = response.json()
                if body.get("model") != model or body["choices"][0].get("finish_reason") != "stop" or body["choices"][0]["message"].get("content", "").strip() != "READY":
                    raise RequestError("provider_rejected")
    finally:
        await app.state.client.aclose()
    return {"verified_at": time.time(), "models": models, "text": "verified", "tools": "historical_2026_09_14", "native_cline": "pending"}


def dispatch(request):
    if not isinstance(request, dict) or request.get("schema") != 1:
        raise RequestError("invalid_request")
    action = request.get("action")
    storage = safe_directory(onboarding.local_path(request["storage"]), create=True)
    if action == "hello":
        return {"version": __version__, "schema": 1}
    if action == "models":
        return {"models": list(gateway.MODELS), "endpoint": gateway.ENDPOINT,
                "evidence": "docs/gateway-live-20260914.md", "text": "previously_verified", "tools": "previously_verified", "native_cline": "pending"}
    if action == "validate-provider":
        return asyncio.run(validate_provider(request["key"], request.get("models") or list(gateway.MODELS)))
    if action == "compatibility":
        return cline_compat.inspect(Path(request["extension"]), Path(request["backup"]))
    if action in {"patch", "restore-patch"}:
        extension, backup = Path(request["extension"]), Path(request["backup"])
        plan = cline_compat.plan(extension, backup)
        if plan["bundle_sha256"] != request["bundle_sha256"]:
            raise RequestError("review_changed")
        if action == "patch":
            cline_compat.install(extension, backup)
            return cline_compat.verify(extension, backup)
        return cline_compat.restore(extension, backup)
    if action == "discover":
        workspace = safe_directory(onboarding.local_path(request["workspace"]))
        state = onboarding.state_for(workspace)
        enrollment, policy, profile = onboarding.existing_setup(state)
        return {"state": str(state), "existing": bool(enrollment), "mission": (policy or {}).get("mission"), "profile": profile}
    if action == "plan":
        return prepare(request, storage)
    if action == "apply":
        return apply(request, storage)
    if action == "rollback":
        return rollback(request, storage)
    if action == "transaction":
        return json.loads(_regular_file(transaction_path(storage, request["transaction"]), 131072))
    if action == "orbio-status":
        workspace = safe_directory(onboarding.local_path(request["workspace"]))
        reg_state = registry.lookup(canonical(workspace))
        if not reg_state or not (safe_directory(reg_state) / "vessel.sqlite3").exists():
            return {
                "has_key": False,
                "masked_key": None,
                "credential_version": None,
                "verified_at": None,
            }
        state = safe_directory(reg_state)
        service = Vessel(state)
        try:
            secret = service.store.get("secrets", "orbio_credential")
            return {
                "has_key": bool(secret and secret.get("key")),
                "masked_key": secret.get("masked") if secret else None,
                "credential_version": secret.get("credential_version") if secret else None,
                "verified_at": secret.get("verified_at") if secret else None,
            }
        finally:
            service.close()
    if action == "orbio-migrate-key":
        key = request["key"]
        if not isinstance(key, str) or not key or len(key) > 8192 or any(ch.isspace() for ch in key):
            raise RequestError("invalid_request")
        workspace = safe_directory(onboarding.local_path(request["workspace"]))
        reg_state = registry.lookup(canonical(workspace))
        if not reg_state or not (safe_directory(reg_state) / "vessel.sqlite3").exists():
            return {"migrated": False, "credential_version": request.get("credential_version")}
        state = safe_directory(reg_state)
        service = Vessel(state)
        try:
            with service.store.transaction() as conn:
                service._writable(conn)
                existing = service.store.get("secrets", "orbio_credential", conn=conn)
                if not existing or not existing.get("key"):
                    from vessel.orbio import mask_key
                    version = request.get("credential_version") or uuid.uuid4().hex
                    secret_record = {
                        "provider": "orbio",
                        "credential_version": version,
                        "key": key,
                        "masked": mask_key(key),
                        "verified_at": request.get("verified_at") or time.time(),
                        "created_at": time.time(),
                    }
                    service.store.put("secrets", "orbio_credential", secret_record, conn=conn)
            verified = service.store.get("secrets", "orbio_credential")
            if not verified or verified.get("key") != key:
                raise RequestError("migration_failed")
            return {"migrated": True, "credential_version": verified["credential_version"], "masked_key": verified["masked"]}
        finally:
            service.close()
    workspace, state = state_for(request["workspace"])
    if request.get("transaction"):
        record = json.loads(_regular_file(transaction_path(storage, request["transaction"]), 131072))
        if canonical(record["plan"]["state"]) != canonical(state) or record["status"] != "configured":
            raise RequestError("review_changed")
    if action == "status":
        return snapshot(workspace, state)
    if action == "launch":
        before = desktop.status(state)
        result = desktop.launch(state)
        if request.get("transaction") and not before["running"]:
            path = transaction_path(storage, request["transaction"])
            record = json.loads(_regular_file(path, 131072))
            record["companion_instance"] = result["instance"]
            write_json(path, record)
        return {"running": True, "status": result["status"], "port": result["port"]}
    if action == "stop-companion":
        return desktop.stop(state)
    if action == "gateway-launch":
        before = gateway.status(state)
        result = gateway.launch(state, request.get("key"))
        if request.get("transaction") and not before["running"]:
            path = transaction_path(storage, request["transaction"])
            record = json.loads(_regular_file(path, 131072))
            record["gateway_instance"] = result["instance"]
            write_json(path, record)
        return result
    if action == "gateway-stop":
        return gateway.stop(state)
    if action == "orbio-get-key":
        service = Vessel(state)
        try:
            secret = service.store.get("secrets", "orbio_credential")
            if not secret or not secret.get("key"):
                return {"has_key": False, "key": None}
            return {"has_key": True, "key": secret["key"], "credential_version": secret.get("credential_version")}
        finally:
            service.close()
    if action == "orbio-forget-key":
        service = Vessel(state)
        try:
            with service.store.transaction() as conn:
                service._writable(conn)
                service.store.delete("secrets", "orbio_credential", conn=conn)
                current_cfg = service.store.get("control", gateway.CONTROL, conn=conn)
                if current_cfg:
                    current_cfg["paused"] = True
                    current_cfg["credential_version"] = uuid.uuid4().hex
                    service.store.put("control", gateway.CONTROL, current_cfg, conn=conn)
            if gateway.status(state)["running"]:
                gateway.stop(state)
            return {"status": "forgotten", "paused": True}
        finally:
            service.close()
    if action == "action-result":
        return bridge_request(state, "GET", "/v1/requests/" + identifier(request["request_id"]))
    if action == "owner-action":
        name, payload = request["name"], request["payload"]
        if name not in ACTIONS:
            raise RequestError("invalid_request")
        service = Vessel(state)
        try:
            if name in {"start", "prepare-recovery"}:
                observed = service.store.get("sessions", payload.get("session_id"))
                if not observed or observed.get("last_observation") is None:
                    raise RequestError("owner_action_blocked")
        finally:
            service.close()
        return bridge_request(state, "POST", "/v1/actions", {"request_id": identifier(request["request_id"]),
                              "action": name, "payload": payload, "policy_revision": request["revision"],
                              "execution_epoch": request.get("epoch")})
    service = Vessel(state)
    try:
        if action in {"gateway-mode", "gateway-key", "remove"}:
            lease = service.store.get("control", "lease")
            with reviewed_authority(service, request["revision"], request.get("epoch")):
                if action == "gateway-mode":
                    with service.store.transaction() as conn:
                        config = service._get("control", gateway.CONTROL, conn)
                        config["paused"] = request["paused"] is True
                        if request.get("credential_version"):
                            config["credential_version"] = identifier(request["credential_version"])
                            config["verified_at"] = request.get("verified_at")
                        service.store.put("control", gateway.CONTROL, config, conn=conn)
                    return {"paused": config["paused"]}
                if action == "gateway-key":
                    config = service._get("control", gateway.CONTROL)
                    if config["paused"]:
                        raise RequestError("owner_action_blocked")
                    return service.issue_gateway_credential("default", config["models"])
                with service.store.transaction():
                    if lease and lease["status"] not in {"closed", "paused"}:
                        raise RequestError("owner_action_blocked")
                    result = adapters.uninstall("cline", workspace, state)
                return result
        raise RequestError("invalid_request")
    finally:
        service.close()


def main():
    try:
        raw = sys.stdin.buffer.read(262145)
        if len(raw) > 262144:
            raise RequestError("invalid_request")
        result = dispatch(json.loads(raw))
        encoded = json.dumps({"schema": 1, "ok": True, "result": result})
        if len(encoded.encode()) > 2 * 1024 * 1024:
            raise RequestError("response_too_large")
    except RequestError as error:
        encoded = json.dumps({"schema": 1, "ok": False, "code": error.code})
    except Blocked:
        encoded = json.dumps({"schema": 1, "ok": False, "code": "owner_action_blocked"})
    except Exception as error:
        encoded = json.dumps({"schema": 1, "ok": False, "code": "local_operation_failed", "error": f"{type(error).__name__}: {error}"})
    print(encoded)


if __name__ == "__main__":
    main()
