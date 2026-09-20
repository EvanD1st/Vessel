"""Loopback-only owner bridge. No filesystem browsing or arbitrary command endpoint."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from vessel import __version__, devices
from vessel.orbio import InvalidOrbioCredential, OrbioNetworkError, RealOrbioAdapter, mask_key
from vessel.service import Blocked, Vessel, digest

MAX_BODY = 128 * 1024
ACTIONS = {
    "start",
    "keep-capturing",
    "stop",
    "task",
    "review-proposal",
    "checkpoint",
    "prepare-recovery",
    "handover",
    "confirm",
    "cancel-recovery",
    "finish-run",
    "review-environment",
    "repair-capture",
    "resolve-operation",
    "revalidate-policy",
}


def approved_origin(value):
    parsed = urlsplit(value)
    local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    if (parsed.scheme != "https" and not local) or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Dashboard origin must be HTTPS or an explicit local development origin")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Use only the dashboard origin, without a path, query or fragment")
    return f"{parsed.scheme}://{parsed.netloc}"


def create_app(
    state_dir: Path,
    *,
    origin: str,
    token: str,
    port=8765,
    ttl=3600,
    clock=time.time,
    start_workers=False,
    orbio_adapter=None,
):
    origin = approved_origin(origin)
    if not isinstance(port, int) or not 1024 <= port <= 65535 or not 60 <= ttl <= 28800:
        raise ValueError("Invalid bridge port or session lifetime")
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError("Use a strong random bridge session token")
    created = clock()
    session = hashlib.sha256(token.encode()).hexdigest()[:24]
    with VesselSession(state_dir, clock=clock) as service:
        enrollment_id = service._enrollment()["id"]
        service._writable()
    app = FastAPI(title="VESSEL owner bridge", docs_url=None, redoc_url=None, openapi_url=None)
    adapter = orbio_adapter or RealOrbioAdapter(clock=clock)
    from vessel import extension_gateway
    mutation_lock = threading.Lock()
    worker = {"thread": None, "run": None, "epoch": None, "error": None}

    def keep_capturing(run_id, epoch):
        from vessel.companion import run

        active = worker["thread"]
        if active and active.is_alive():
            if worker["run"] != run_id or worker["epoch"] != epoch:
                raise Blocked("Previous companion is stopping; retry after it exits")
            return
        if not start_workers:
            return

        def work():
            try:
                run(state_dir, run_id, epoch, emit=lambda _: None)
            except Exception as error:
                worker["error"] = type(error).__name__

        worker.update(
            run=run_id,
            epoch=epoch,
            error=None,
            thread=threading.Thread(target=work, name="vessel-dashboard-companion", daemon=True),
        )
        worker["thread"].start()

    @app.middleware("http")
    async def local_owner_only(request: Request, call_next):
        headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
        if request.headers.get("host") != f"127.0.0.1:{port}":
            return JSONResponse({"error": "Unexpected bridge host"}, status_code=403, headers=headers)
        if request.headers.get("origin") != origin:
            return JSONResponse(
                {"error": "This dashboard origin is not approved"}, status_code=403, headers=headers
            )
        headers.update(
            {
                "Access-Control-Allow-Origin": origin,
                "Vary": "Origin",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS, DELETE",
                "Access-Control-Allow-Headers": "Authorization, Content-Type",
                "Access-Control-Allow-Private-Network": "true",
            }
        )
        if request.method == "OPTIONS":
            return Response(status_code=204, headers=headers)
        authorization = request.headers.get("authorization", "")
        provided_token = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not provided_token:
            return JSONResponse({"error": "Missing authorization token"}, status_code=401, headers=headers)
        try:
            with VesselSession(state_dir, clock=clock) as service:
                admission = admit(service, provided_token, request.method, request.url.path)
            request.state.token = provided_token
            request.state.session_id = admission["session_id"]
            request.state.admission = admission
            response = await call_next(request)
        except devices.DeviceUnauthorized as error:
            response = JSONResponse({"error": str(error)}, status_code=401)
        except Exception:
            response = JSONResponse(
                {"error": "The local companion could not complete this request"}, status_code=500
            )
        response.headers.update(headers)
        return response

    def check_enrollment(service):
        if service._enrollment()["id"] != enrollment_id:
            raise Blocked("Enrollment changed; restart the bridge")

    def admit(service, provided_token, method, path, conn=None):
        check_enrollment(service)
        if secrets.compare_digest(provided_token.encode(), token.encode()):
            if clock() >= created + ttl:
                raise devices.DeviceUnauthorized(
                    "Private connection link expired. Start a fresh bridge link."
                )
            return {"kind": "bootstrap", "session_id": session, "expires_at": created + ttl}
        credential = (method, path) in {("POST", "/v1/renew"), ("DELETE", "/v1/devices/current")}
        return devices.authorize(
            service,
            provided_token,
            origin,
            enrollment_id,
            credential=credential,
            deleting=method == "DELETE",
            conn=conn,
        )

    @app.get("/v1/snapshot")
    def snapshot(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            result = service.status()
            result.update(
                policy=service.policy(),
                tasks=service.store.list("tasks"),
                proposals=service.store.list("proposals"),
                operations=service.store.list("operations"),
                version=__version__,
            )
            for operation in result["operations"]:
                operation["uncertain"] = not operation.get("resolution") and (
                    not operation["intent"]
                    or not operation["result"]
                    or operation.get("conflict", False)
                    or operation["result"]["kind"] == "postToolUseFailure"
                )
            result["bridge"] = {
                "expires_at": request.state.admission["expires_at"],
                "device_id": request.state.admission.get("device_id"),
                "renew_after": request.state.admission.get("renew_after", created + ttl),
                "origin": origin,
                "capture_worker_running": bool(worker["thread"] and worker["thread"].is_alive()),
                "worker_error": worker["error"],
                "data_location": "local_machine",
            }
            return result

    @app.post("/v1/pair")
    async def pair_device(request: Request):
        if request.state.admission["kind"] != "bootstrap":
            return JSONResponse(
                {"error": "Use a fresh private connection link to pair a browser"}, status_code=403
            )
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > 2048:
                return JSONResponse({"error": "Pairing request is too large"}, status_code=413)
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or set(body) != {"label"}:
                raise ValueError("Pairing requires a device label")
            with VesselSession(state_dir, clock=clock) as service:
                admit(service, request.state.token, "POST", "/v1/pair")
                return devices.pair(service, origin, enrollment_id, body["label"], ttl)
        except (ValueError, TypeError) as error:
            return JSONResponse({"error": str(error)}, status_code=400)

    @app.get("/v1/devices")
    def paired_devices():
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            return {"devices": devices.list_devices(service)}

    @app.post("/v1/renew")
    def renew_device(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            try:
                return devices.renew(service, request.state.token, origin, enrollment_id, ttl)
            except devices.DeviceUnauthorized as error:
                return JSONResponse({"error": str(error)}, status_code=401)

    @app.delete("/v1/devices/current")
    def disconnect_device(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            if request.state.admission["kind"] != "credential":
                return JSONResponse(
                    {"error": "Use the paired device credential to revoke it"}, status_code=403
                )
            return devices.revoke(service, request.state.session_id)

    @app.get("/v1/requests/{request_id}")
    def request_status(request: Request, request_id: str):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            result = service.store.get("dashboard_requests", f"{request.state.session_id}:{request_id}")
            if not result:
                return JSONResponse({"error": "Request was not recorded"}, status_code=404)
            return result

    @app.get("/v1/orbio/status")
    async def get_orbio_status(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            secret = service.store.get("secrets", "orbio_credential")
            gateway_cfg = service.store.get("control", extension_gateway.CONTROL) or {}

        current_gateway = extension_gateway.status(state_dir)
        has_key = bool(secret and secret.get("key"))
        masked = secret.get("masked") if has_key else None
        version = secret.get("credential_version") if has_key else None
        verified_at = secret.get("verified_at") if has_key else None

        raw_key = secret.get("key") if has_key else None
        conn_status = await adapter.connection_status(raw_key)
        usage_data = await adapter.fetch_usage_analytics(raw_key) if has_key else {}

        gateway_state = "offline"
        if current_gateway.get("running"):
            gateway_state = "healthy" if current_gateway.get("status") == "ready" else current_gateway.get("status", "running")
        elif gateway_cfg.get("paused"):
            gateway_state = "paused"

        balance_obj = conn_status.get("balance")
        if not balance_obj or not balance_obj.get("available"):
            if usage_data.get("available"):
                balance_obj = {
                    "available": True,
                    "amount": usage_data.get("remaining_credits"),
                    "currency": "USD",
                    "reason": None,
                }
            else:
                balance_obj = {
                    "available": False,
                    "amount": None,
                    "currency": "CREDIT",
                    "reason": "Not available without Orbio Remote MCP authorization",
                }

        usage_obj = {
            "available": bool(usage_data.get("available")),
            "amount": usage_data.get("usage") if usage_data.get("available") else None,
            "currency": "USD" if has_key else "CREDIT",
            "reason": None if usage_data.get("available") else "Usage reporting not available in this release",
        }

        return {
            "connected": has_key,
            "masked_key": masked,
            "credential_version": version,
            "status": "active" if (has_key and not gateway_cfg.get("paused")) else ("paused" if has_key else "not_configured"),
            "probe_status": "ok" if has_key else "unconfigured",
            "verified_at": verified_at,
            "gateway": {
                "status": gateway_state,
                "port": gateway_cfg.get("port", 8091),
                "base_url": f"http://127.0.0.1:{gateway_cfg.get('port', 8091)}/v1/chat/completions",
                "models": gateway_cfg.get("models", list(extension_gateway.MODELS)),
                "active_model": (gateway_cfg.get("models") or [extension_gateway.MODELS[0]])[0],
                "smart_routing": bool(gateway_cfg.get("smart_routing") or "openrouter/auto" in gateway_cfg.get("models", [])),
                "running": current_gateway.get("running", False),
            },
            "balance": balance_obj,
            "usage": usage_obj,
            "mcp": conn_status.get("mcp", {"configured": False, "capabilities": []}),
            "last_error": None,
        }

    @app.post("/v1/orbio/credentials")
    async def set_orbio_credentials(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "JSON request required"}, status_code=415)
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > 8192:
                return JSONResponse({"error": "Payload exceeds 8 KiB"}, status_code=413)
        try:
            body = json.loads(raw)
            if not isinstance(body, dict) or "key" not in body:
                return JSONResponse({"error": "Orbio API key is required"}, status_code=400)
            key = body["key"]
            if not isinstance(key, str) or not 1 <= len(key) <= 8192 or any(ch.isspace() for ch in key):
                return JSONResponse({"error": "Invalid Orbio API key format"}, status_code=400)
        except Exception:
            return JSONResponse({"error": "Invalid JSON request"}, status_code=400)

        try:
            probe_result = await adapter.validate_credential(key)
        except InvalidOrbioCredential:
            return JSONResponse({"error": "Provider rejected credential. Check your Orbio API key."}, status_code=400)
        except OrbioNetworkError:
            return JSONResponse({"error": "Could not connect to Orbio gateway. Check network connectivity."}, status_code=502)
        except Exception:
            return JSONResponse({"error": "Credential verification failed."}, status_code=500)

        version = uuid.uuid4().hex
        masked = mask_key(key)
        verified_at = probe_result.get("verified_at", clock())

        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            with service.store.transaction() as conn:
                service._writable(conn)
                secret_record = {
                    "provider": "orbio",
                    "credential_version": version,
                    "key": key,
                    "masked": masked,
                    "verified_at": verified_at,
                    "created_at": clock(),
                }
                service.store.put("secrets", "orbio_credential", secret_record, conn=conn)

                current_cfg = service.store.get("control", extension_gateway.CONTROL, conn=conn) or {
                    "schema": 1,
                    "port": 8091,
                    "models": list(extension_gateway.MODELS),
                    "validation": "canned_text_probe",
                    "native_cline": "pending",
                }
                current_cfg.update({
                    "credential_version": version,
                    "verified_at": verified_at,
                    "paused": False,
                })
                service.store.put("control", extension_gateway.CONTROL, current_cfg, conn=conn)

        try:
            if extension_gateway.status(state_dir)["running"]:
                extension_gateway.stop(state_dir)
            extension_gateway.launch(state_dir, key)
        except Exception:
            pass

        adapter.clear_cache()
        return {
            "status": "connected",
            "credential_version": version,
            "masked_key": masked,
            "verified_at": verified_at,
        }

    @app.post("/v1/orbio/replace")
    async def replace_orbio_credentials(request: Request):
        return await set_orbio_credentials(request)

    @app.delete("/v1/orbio/credentials")
    async def delete_orbio_credentials(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            with service.store.transaction() as conn:
                service._writable(conn)
                service.store.delete("secrets", "orbio_credential", conn=conn)
                current_cfg = service.store.get("control", extension_gateway.CONTROL, conn=conn)
                if current_cfg:
                    current_cfg["paused"] = True
                    current_cfg["credential_version"] = uuid.uuid4().hex
                    service.store.put("control", extension_gateway.CONTROL, current_cfg, conn=conn)

        try:
            if extension_gateway.status(state_dir)["running"]:
                extension_gateway.stop(state_dir)
        except Exception:
            pass

        adapter.clear_cache()
        return {
            "status": "forgotten",
            "paused": True,
            "recovery_history_preserved": True,
        }

    @app.post("/v1/orbio/refresh")
    async def refresh_orbio_credentials(request: Request):
        adapter.clear_cache()
        return await get_orbio_status(request)

    @app.post("/v1/orbio/claim")
    async def claim_orbio_key(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)

        name = "vessel-operator-key"
        if request.headers.get("content-type", "").split(";")[0] == "application/json":
            try:
                body = await request.json()
                if isinstance(body, dict) and body.get("name"):
                    name = str(body["name"])[:64]
            except Exception:
                pass

        claim_res = await adapter.claim_key(name=name)
        if not claim_res.get("success"):
            return JSONResponse(
                {
                    "status": claim_res.get("status", "mcp_not_configured"),
                    "message": claim_res.get("message", "Orbio Remote MCP is not configured."),
                    "url": claim_res.get("url", "https://orbio.so"),
                },
                status_code=200,
            )

        key = claim_res["key"]
        try:
            probe_result = await adapter.validate_credential(key)
        except Exception as exc:
            return JSONResponse({"error": f"Claimed key failed validation: {exc}"}, status_code=500)

        version = uuid.uuid4().hex
        masked = mask_key(key)
        verified_at = probe_result.get("verified_at", clock())

        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            with service.store.transaction() as conn:
                service._writable(conn)
                secret_record = {
                    "provider": "orbio",
                    "credential_version": version,
                    "key": key,
                    "masked": masked,
                    "verified_at": verified_at,
                    "created_at": clock(),
                }
                service.store.put("secrets", "orbio_credential", secret_record, conn=conn)

                current_cfg = service.store.get("control", extension_gateway.CONTROL, conn=conn) or {
                    "schema": 1,
                    "port": 8091,
                    "models": list(extension_gateway.MODELS),
                    "validation": "canned_text_probe",
                    "native_cline": "pending",
                }
                current_cfg.update({
                    "credential_version": version,
                    "verified_at": verified_at,
                    "paused": False,
                })
                service.store.put("control", extension_gateway.CONTROL, current_cfg, conn=conn)

        try:
            if extension_gateway.status(state_dir)["running"]:
                extension_gateway.stop(state_dir)
            extension_gateway.launch(state_dir, key)
        except Exception:
            pass

        adapter.clear_cache()
        return {
            "status": "claimed",
            "credential_version": version,
            "masked_key": masked,
            "verified_at": verified_at,
            "message": "Orbio API key successfully claimed and saved to encrypted store.",
        }

    @app.get("/v1/orbio/models")
    async def get_orbio_models(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            secret = service.store.get("secrets", "orbio_credential")
            gateway_cfg = service.store.get("control", extension_gateway.CONTROL) or {}

        key = secret.get("key") if secret else None
        catalog = await adapter.fetch_model_catalog(key)
        models_cfg = gateway_cfg.get("models") or list(extension_gateway.MODELS)
        active = models_cfg[0] if models_cfg else "openrouter/auto"
        smart_routing = bool(gateway_cfg.get("smart_routing") or "openrouter/auto" in models_cfg)

        return {
            "models": catalog,
            "active_model": active,
            "gateway_models": models_cfg,
            "smart_routing": smart_routing,
        }

    @app.post("/v1/orbio/routing")
    async def set_orbio_routing(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "JSON request required"}, status_code=415)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "Invalid request format"}, status_code=400)
            active_model = str(body.get("active_model", "")).strip()
            smart_routing = bool(body.get("smart_routing", False))
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        if smart_routing:
            new_models = ["openrouter/auto"]
            if active_model and active_model != "openrouter/auto":
                new_models.append(active_model)
        else:
            if not active_model:
                return JSONResponse({"error": "active_model is required when smart_routing is disabled"}, status_code=400)
            fallbacks = [str(m).strip() for m in body.get("fallback_models", []) if isinstance(m, str) and m.strip()]
            new_models = list(dict.fromkeys([active_model] + fallbacks))

        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            with service.store.transaction() as conn:
                service._writable(conn)
                secret = service.store.get("secrets", "orbio_credential", conn=conn)
                current_cfg = service.store.get("control", extension_gateway.CONTROL, conn=conn) or {
                    "schema": 1,
                    "port": 8091,
                    "validation": "canned_text_probe",
                    "native_cline": "pending",
                }
                current_cfg["models"] = new_models
                current_cfg["smart_routing"] = smart_routing
                service.store.put("control", extension_gateway.CONTROL, current_cfg, conn=conn)

        raw_key = secret.get("key") if secret else None
        try:
            if extension_gateway.status(state_dir)["running"]:
                extension_gateway.stop(state_dir)
            if raw_key and not current_cfg.get("paused"):
                extension_gateway.launch(state_dir, raw_key)
        except Exception:
            pass

        adapter.clear_cache()
        return {
            "status": "updated",
            "active_model": new_models[0],
            "gateway_models": new_models,
            "smart_routing": smart_routing,
        }

    @app.get("/v1/orbio/usage")
    async def get_orbio_usage(request: Request):
        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            secret = service.store.get("secrets", "orbio_credential")
            wallet_rec = service.store.get("secrets", "orbio_wallet")

        key = secret.get("key") if secret else None
        usage_data = await adapter.fetch_usage_analytics(key)

        wallet_data = None
        if wallet_rec and wallet_rec.get("address"):
            wallet_data = await adapter.fetch_wallet_holdings(wallet_rec["address"])

        return {
            "usage": usage_data,
            "wallet": wallet_data,
            "has_key": bool(key),
            "checked_at": clock(),
        }

    @app.post("/v1/orbio/wallet")
    async def set_orbio_wallet(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "JSON request required"}, status_code=415)
        try:
            body = await request.json()
            if not isinstance(body, dict):
                return JSONResponse({"error": "Invalid request format"}, status_code=400)
            action = body.get("action")
            address = str(body.get("address") or body.get("wallet_address") or "").strip()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        with VesselSession(state_dir, clock=clock) as service:
            check_enrollment(service)
            with service.store.transaction() as conn:
                service._writable(conn)
                if action == "disconnect" or not address:
                    service.store.delete("secrets", "orbio_wallet", conn=conn)
                    adapter.clear_cache()
                    return {
                        "status": "disconnected",
                        "message": "Wallet unlinked successfully.",
                    }

                import re
                is_evm = bool(re.match(r"^0x[a-fA-F0-9]{40}$", address))
                if not is_evm:
                    return JSONResponse(
                        {"error": "Invalid Robinhood Chain address. Must be a 42-character 0x hex address."},
                        status_code=400,
                    )

                service.store.put(
                    "secrets",
                    "orbio_wallet",
                    {
                        "address": address,
                        "linked_at": clock(),
                    },
                    conn=conn,
                )

        adapter.clear_cache()
        wallet_info = await adapter.fetch_wallet_holdings(address)
        return {
            "status": "linked",
            "wallet": wallet_info,
            "message": f"Robinhood wallet linked. Tier: {wallet_info.get('tier_name')}",
        }

    @app.post("/v1/actions")
    async def action(request: Request):
        if request.headers.get("content-type", "").split(";")[0] != "application/json":
            return JSONResponse({"error": "JSON request required"}, status_code=415)
        raw = bytearray()
        async for part in request.stream():
            raw.extend(part)
            if len(raw) > MAX_BODY:
                return JSONResponse({"error": "Request exceeds 128 KiB"}, status_code=413)
        try:
            body = json.loads(raw)
            request_id, name, payload = body["request_id"], body["action"], body.get("payload", {})
            if (
                not isinstance(request_id, str)
                or not 1 <= len(request_id) <= 100
                or name not in ACTIONS
                or not isinstance(payload, dict)
            ):
                raise ValueError("Invalid owner action")
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "Invalid action request"}, status_code=400)
        return await run_in_threadpool(execute_action, request.state.token, body, request_id, name, payload)

    def execute_action(access_token, body, request_id, name, payload):
        if not mutation_lock.acquire(blocking=False):
            return JSONResponse({"error": "Another owner action is in progress"}, status_code=409)
        try:
            with VesselSession(state_dir, clock=clock) as service:
                check_enrollment(service)
                with service.store.transaction() as conn:
                    service._writable(conn)
                    admitted = admit(service, access_token, "POST", "/v1/actions", conn)
                    key, fingerprint = f"{admitted['session_id']}:{request_id}", digest(body)
                    previous = service.store.get("dashboard_requests", key, conn=conn)
                    if previous:
                        if previous["fingerprint"] != fingerprint:
                            return JSONResponse(
                                {"error": "Request ID was reused with different inputs"}, status_code=409
                            )
                        return JSONResponse(
                            previous, status_code=200 if previous["status"] == "succeeded" else 409
                        )
                    policy = service._get("control", "policy", conn)
                    lease = service.store.get("control", "lease", conn=conn)
                    if policy["revision"] != body.get("policy_revision") or policy["authority"] != "local":
                        raise Blocked("Policy changed; refresh and review the action again")
                    if (lease["execution_epoch"] if lease else None) != body.get("execution_epoch"):
                        raise Blocked("Execution changed; refresh and select the current run")
                    receipt = {
                        "id": request_id,
                        "action": name,
                        "fingerprint": fingerprint,
                        "status": "started",
                        "at": clock(),
                        "policy_revision": policy["revision"],
                    }
                    service.store.put("dashboard_requests", key, receipt, conn=conn)
                try:
                    with reviewed_authority(
                        service,
                        policy["revision"],
                        body.get("execution_epoch"),
                        admission=lambda conn: admit(service, access_token, "POST", "/v1/actions", conn),
                    ):
                        result = dispatch(service, name, payload, policy["revision"])
                    receipt.update(status="succeeded", result=result)
                    if name in {"start", "keep-capturing"}:
                        try:
                            keep_capturing(result["id"], result["execution_epoch"])
                        except (ValueError, OSError) as error:
                            receipt["warning"] = (
                                "Run updated, but capture worker did not start: " + str(error)[:300]
                            )
                except (ValueError, OSError, KeyError, TypeError) as error:
                    receipt.update(status="blocked", error=str(error)[:2000])
                service.store.put("dashboard_requests", key, receipt)
                return JSONResponse(receipt, status_code=200 if receipt["status"] == "succeeded" else 409)
        except (ValueError, OSError) as error:
            return JSONResponse({"error": str(error)[:2000]}, status_code=409)
        finally:
            mutation_lock.release()

    return app


@contextmanager
def reviewed_authority(service, revision, epoch, admission=None):
    """Check reviewed authority inside every write transaction of one owner action.

    The action may itself advance policy or epoch. Follow only changes committed
    by this connection; a competing change between transactions fails closed.
    Always restore the ordinary store before recording the action receipt.
    """
    original = service.store.transaction
    expected = [revision, epoch]

    def authority(conn):
        policy = service._get("control", "policy", conn)
        lease = service.store.get("control", "lease", conn=conn)
        if policy["authority"] != "local":
            raise Blocked("Current policy authority is unavailable")
        return [policy["revision"], lease["execution_epoch"] if lease else None]

    @contextmanager
    def checked_transaction():
        with original() as conn:
            if admission:
                admission(conn)
            if authority(conn) != expected:
                raise Blocked("Reviewed authority changed; refresh and review the action again")
            yield conn
            committed = authority(conn)
        expected[:] = committed

    service.store.transaction = checked_transaction
    try:
        yield
    finally:
        service.store.transaction = original


def dispatch(service, name, payload, revision):
    # Explicit field selection prevents payloads from reaching arbitrary methods,
    # paths, commands, credentials or caller-supplied SQL.
    def required(key):
        if key not in payload:
            raise ValueError("Missing action field: " + key)
        value = payload[key]
        if key == "context_bytes":
            if type(value) is not int or not 1024 <= value <= 1048576:
                raise ValueError("Context budget must be an integer between 1024 and 1048576 bytes")
        elif not isinstance(value, str) or not value.strip() or len(value.encode()) > 16384:
            raise ValueError("Invalid bounded text field: " + key)
        return value

    if name == "start":
        return service.start(service._enrollment()["workspace"], required("session_id"))
    if name == "keep-capturing":
        run = service._get("runs", required("run_id"))
        service.heartbeat(run["id"], run["execution_epoch"])
        return run
    if name == "revalidate-policy":
        run = service._get("runs", required("run_id"))
        return service.heartbeat(run["id"], run["execution_epoch"], revalidate=True)
    if name == "stop":
        return service.stop(
            required("run_id"), attested=payload.get("attested") is True, note=required("note")
        )
    if name == "task":
        return service.task(
            required("run_id"),
            required("task_id"),
            required("description"),
            status=payload.get("status", "pending"),
            evidence=payload.get("evidence"),
            dependencies=payload.get("dependencies"),
        )
    if name == "review-proposal":
        return service.review_proposal(
            required("proposal_id"),
            required("decision"),
            required("note"),
            policy_revision=revision,
            run_id=payload.get("run_id"),
            task_id=payload.get("task_id"),
            evidence=payload.get("evidence"),
            dependencies=payload.get("dependencies"),
        )
    if name == "checkpoint":
        return service.checkpoint(required("run_id"))
    if name == "prepare-recovery":
        return service.prepare_recovery(
            required("checkpoint_id"),
            required("session_id"),
            required("idempotency_key"),
            context_budget=required("context_bytes"),
        )
    if name == "handover":
        return service.handover(required("recovery_id"), required("review_token"))
    if name == "confirm":
        return service.confirm_continuation(
            required("recovery_id"), required("operation_id"), required("note")
        )
    if name == "cancel-recovery":
        return service.cancel_recovery(required("recovery_id"), required("note"))
    if name == "finish-run":
        return service.finish_run(
            required("run_id"), required("outcome"), required("note"), evidence=payload.get("evidence")
        )
    if name == "review-environment":
        return service.review_environment(required("note"), required("model"), required("context_bytes"))
    if name == "repair-capture":
        return service.repair_capture(required("note"))
    if name == "resolve-operation":
        return service.resolve_operation(required("operation_id"), required("note"))
    raise ValueError("Unsupported owner action")


class VesselSession:
    def __init__(self, state, *, clock=time.time):
        self.state = state
        self.clock = clock

    def __enter__(self):
        self.service = Vessel(self.state, clock=self.clock)
        return self.service

    def __exit__(self, *args):
        self.service.close()
