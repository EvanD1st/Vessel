"""Loopback-only owner bridge. No filesystem browsing or arbitrary command endpoint."""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from vessel import __version__, devices
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
    state_dir: Path, *, origin: str, token: str, port=8765, ttl=3600, clock=time.time, start_workers=False
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
