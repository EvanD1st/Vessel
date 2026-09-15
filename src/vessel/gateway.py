"""Bounded inference proxy, independent of the local companion's HTTP surface.

This factory is a prepared integration surface. Deployers must supply an
authoritative admission callback and durable accounting before exposing it.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit
from uuid import uuid4

import anyio
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


class AuthorizationDenied(Exception):
    """An admission authority could not authorize the supplied credential."""


class CaptureUnhealthy(AuthorizationDenied):
    """Current credentials are valid, but capture prevents further inference."""


@dataclass(frozen=True)
class UpstreamRoute:
    """One administrator-configured route, never selected by a client URL."""

    endpoint: str
    api_key: str = field(repr=False)
    allowed_models: frozenset[str] = field(default_factory=frozenset)
    profiles: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    credential_version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.profiles, Mapping) or len(self.profiles) > 32:
            raise ValueError("At most 32 explicit routing profiles are supported")
        for alias, candidates in self.profiles.items():
            if (
                not isinstance(alias, str)
                or not alias.strip()
                or len(alias) > 256
                or any(ord(ch) < 32 for ch in alias)
                or alias in self.allowed_models
                or not isinstance(candidates, tuple)
                or not 1 <= len(candidates) <= 3
                or any(not isinstance(c, str) or not c for c in candidates)
                or len(set(candidates)) != len(candidates)
                or not set(candidates) <= self.allowed_models
            ):
                raise ValueError("Profiles require 1–3 distinct allowlisted models")
        parsed = urlsplit(self.endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.port not in (None, 443)
            or not parsed.path.endswith("/chat/completions")
        ):
            raise ValueError("Upstream route requires a configured HTTPS chat/completions endpoint")
        if not self.api_key or any(c in self.api_key for c in "\r\n"):
            raise ValueError("Upstream credential is missing or invalid")
        if not self.allowed_models or any(not isinstance(m, str) or not m for m in self.allowed_models):
            raise ValueError("A route requires an explicit model allowlist")


@dataclass(frozen=True)
class GatewayAdmission:
    """Current trusted facts returned for one dedicated VESSEL credential.

    The callback must re-read current epoch, policy, status, and credential
    revocation on EVERY call. It must not use exported checkpoint authority.
    """

    enrollment_id: str
    credential_id: str
    owner_id: str
    agent_id: str
    workspace_id: str
    route_id: str
    execution_epoch: int
    policy_revision: int
    credential_execution_epoch: int
    credential_policy_revision: int
    allowed_models: frozenset[str]
    authority: Literal["local", "cloud"] = "local"
    active: bool = True


@dataclass(frozen=True)
class GatewayEvent:
    request_id: str
    enrollment_id: str
    credential_id: str
    owner_id: str
    agent_id: str
    workspace_id: str
    execution_epoch: int
    policy_revision: int
    route_id: str
    model: str
    credential_version: str
    phase: Literal["admitted", "completed", "rejected", "uncertain"]
    requested_model: str | None = None
    attempt_index: int = 1
    error_code: str | None = None
    upstream_status: int | None = None
    emitted_bytes: int = 0
    attribution_level: str = "enrollment"
    run_id: None = None
    cost: None = None
    observed_at: float = field(default_factory=time.time)


Authorizer = Callable[[str], GatewayAdmission | None | Awaitable[GatewayAdmission | None]]
Auditor = Callable[[GatewayEvent], None | Awaitable[None]]

# This intentionally advertises a bounded Chat Completions subset. URL, key and
# arbitrary upstream-selection fields are never accepted from clients.
_REQUEST_FIELDS = frozenset(
    {
        "model",
        "messages",
        "stream",
        "tools",
        "tool_choice",
        "parallel_tool_calls",
        "temperature",
        "top_p",
        "n",
        "stop",
        "presence_penalty",
        "frequency_penalty",
        "max_tokens",
        "max_completion_tokens",
        "response_format",
        "seed",
        "stream_options",
        "logprobs",
        "top_logprobs",
        "logit_bias",
        "user",
        "reasoning_effort",
    }
)


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _invalid_constant(_value):
    raise ValueError("non-JSON numeric constant")


def _error(status: int, code: str) -> JSONResponse:
    message = (
        "Capture needs attention. Review the companion's capture health before retrying."
        if code == "capture_unhealthy"
        else code.replace("_", " ")
    )
    return JSONResponse(
        {"error": {"type": "vessel_gateway_error", "code": code, "message": message}},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


async def _deadline_chunks(iterator, deadline):
    while True:
        async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
            try:
                chunk = await iterator.__anext__()
            except StopAsyncIteration:
                return
        yield chunk


def _retryable_stream_error(frame):
    try:
        data = b"\n".join(line[5:].strip() for line in frame.splitlines() if line.startswith(b"data:"))
        error = json.loads(data).get("error", {})
        code = error.get("code", error.get("status"))
        return type(code) is int and code in {500, 502, 503, 504}
    except (ValueError, TypeError, AttributeError):
        return False


def _upstream_error(status: int) -> tuple[int, str]:
    if status in (401, 403):
        return 502, "upstream_credential_rejected"
    if status == 402:
        return 503, "upstream_funding_required"
    if status == 429:
        return 503, "upstream_rate_limited"
    if status in (400, 404, 422):
        return 502, "upstream_request_rejected"
    if 300 <= status < 400:
        return 502, "upstream_redirect_rejected"
    return 502, "upstream_unavailable"


async def _resolve(value):
    return await value if inspect.isawaitable(value) else value


async def _close_response(response: httpx.Response) -> bool:
    try:
        await response.aclose()
        return True
    except Exception:
        # Transport cleanup errors must not reveal raw provider details either.
        return False


class _SecretFilter:
    """Remove the configured credential even when it spans transport chunks."""

    def __init__(self, secret: str):
        self.secret = secret.encode("utf-8")
        self.pending = b""

    def feed(self, chunk: bytes, *, final: bool = False) -> bytes:
        data = self.pending + chunk
        output = bytearray()
        cutoff = len(data) if final else max(0, len(data) - len(self.secret) + 1)
        cursor = 0
        while cursor < cutoff:
            match = data.find(self.secret, cursor)
            if match < 0 or match >= cutoff:
                output.extend(data[cursor:cutoff])
                cursor = cutoff
            else:
                output.extend(data[cursor:match])
                output.extend(b"[REDACTED]")
                cursor = match + len(self.secret)
        self.pending = data[cursor:]
        return bytes(output)


class _DoneMarker:
    """Track the protocol terminator with constant memory, without reserializing."""

    def __init__(self):
        self.line = bytearray()
        self.oversized = False
        self.seen = False

    def feed(self, chunk: bytes) -> None:
        for byte in chunk:
            if byte == 10:
                if not self.oversized and bytes(self.line).strip() == b"data: [DONE]":
                    self.seen = True
                self.line.clear()
                self.oversized = False
            elif len(self.line) < 128 and not self.oversized:
                self.line.append(byte)
            else:
                self.oversized = True


class _SSEGuard:
    """Keep normal frames verbatim while withholding provider error frames."""

    def __init__(self):
        self.pending = b""

    def feed(self, chunk: bytes):
        self.pending += chunk
        while True:
            boundary = re.search(rb"\r\n\r\n|\n\n|\r\r", self.pending)
            if boundary is None:
                if len(self.pending) > 1_048_576:
                    raise ValueError("oversized SSE frame")
                return
            frame, self.pending = self.pending[: boundary.end()], self.pending[boundary.end() :]
            if len(frame) > 1_048_576:
                raise ValueError("oversized SSE frame")
            lines = frame.splitlines()
            data = b"\n".join(line[5:].lstrip(b" ") for line in lines if line.startswith(b"data:"))
            provider_error = any(line.strip() == b"event: error" for line in lines)
            if data and data.strip() != b"[DONE]":
                try:
                    parsed = json.loads(data)
                    provider_error = provider_error or (isinstance(parsed, dict) and "error" in parsed)
                except (ValueError, UnicodeDecodeError):
                    provider_error = True
            yield frame, provider_error


class _ManagedStream(StreamingResponse):
    """Close the upstream even if downstream disconnects before iteration starts."""

    def __init__(self, content, *, finish, **kwargs):
        super().__init__(content, **kwargs)
        self._finish = finish

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        except BaseException:
            await self._finish("client_disconnected")
            raise
        finally:
            await self._finish("client_disconnected")
            closer = getattr(self.body_iterator, "aclose", None)
            if closer is not None:
                with anyio.CancelScope(shield=True):
                    try:
                        await closer()
                    except Exception:
                        pass


def create_app(
    *,
    routes: Mapping[str, UpstreamRoute],
    authorize: Authorizer,
    audit: Auditor | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    max_request_bytes: int = 1_048_576,
    max_response_bytes: int = 8_388_608,
    max_concurrency: int = 4,
    upstream_timeout_seconds: float = 60.0,
) -> FastAPI:
    """Create the separate gateway service with no implicit credential authority.

    ``transport`` supports deterministic MockTransport tests; it is never client
    input. Only explicit bounded profiles can fall back before response commitment.
    No hidden transport retries, redirects or environment proxies are enabled.
    Event callbacks receive no prompt, token, upstream response body or secrets.
    Without a durable auditor, diagnostics live only in a bounded memory deque;
    this preview does not claim spending reservation or reconciliation.
    """

    if not routes or any(not isinstance(route, UpstreamRoute) for route in routes.values()):
        raise ValueError("At least one trusted upstream route is required")
    if min(max_request_bytes, max_response_bytes, max_concurrency, upstream_timeout_seconds) <= 0:
        raise ValueError("Gateway bounds must be positive")
    configured_routes = dict(routes)
    client = httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(upstream_timeout_seconds),
        limits=httpx.Limits(max_connections=max_concurrency, max_keepalive_connections=max_concurrency),
    )

    @asynccontextmanager
    async def lifespan(_app):
        yield
        await client.aclose()

    app = FastAPI(title="VESSEL inference gateway preview", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.events = deque(maxlen=1000)
    app.state.audit_healthy = True
    app.state.in_flight = 0
    app.state.client = client

    async def authorized(request: Request):
        header = request.headers.get("authorization", "")
        match = re.fullmatch(r"Bearer ([^\s]{16,4096})", header)
        if not match:
            return None, _error(401, "invalid_gateway_credential")
        if not app.state.audit_healthy:
            return None, _error(503, "accounting_unavailable")
        try:
            admission = await _resolve(authorize(match.group(1)))
        except CaptureUnhealthy:
            return None, _error(409, "capture_unhealthy")
        except AuthorizationDenied:
            return None, _error(403, "admission_denied")
        except Exception:
            return None, _error(503, "authority_unavailable")
        if not isinstance(admission, GatewayAdmission) or not admission.active:
            return None, _error(403, "admission_denied")
        if admission.authority not in {"local", "cloud"}:
            return None, _error(503, "unknown_authority")
        if (
            admission.execution_epoch < 1
            or admission.policy_revision < 1
            or admission.credential_execution_epoch != admission.execution_epoch
            or admission.credential_policy_revision != admission.policy_revision
        ):
            return None, _error(403, "stale_gateway_credential")
        if admission.route_id not in configured_routes:
            return None, _error(503, "route_unavailable")
        return admission, None

    @app.get("/health")
    async def health():
        return {
            "service": "vessel-gateway",
            "mode": "developer-preview",
            "accounting_healthy": app.state.audit_healthy,
        }

    @app.get("/v1/models")
    async def models(request: Request):
        admission, failure = await authorized(request)
        if failure is not None:
            return failure
        route = configured_routes[admission.route_id]
        visible = route.allowed_models & admission.allowed_models
        aliases = {
            alias for alias, chain in route.profiles.items() if any(model in visible for model in chain)
        }
        return {
            "object": "list",
            "data": [
                {"id": name, "object": "model", "owned_by": "configured-upstream"}
                for name in sorted(visible | aliases)
            ],
        }

    @app.post("/v1/chat/completions")
    async def completions(request: Request):
        admission, failure = await authorized(request)
        if failure is not None:
            return failure
        if app.state.in_flight >= max_concurrency:
            return _error(429, "gateway_busy")
        # Claim capacity before consuming bodies, including chunked uploads.
        app.state.in_flight += 1
        transferred = False
        upstream = None
        event_base = None
        dispatched = False

        async def record(phase, **extra) -> bool:
            event = GatewayEvent(**event_base, phase=phase, **extra)
            app.state.events.append(event)
            if audit is not None:
                try:
                    await _resolve(audit(event))
                except Exception:
                    app.state.audit_healthy = False
                    return False
            return True

        try:
            if request.url.query:
                return _error(400, "query_parameters_unsupported")
            if request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
                return _error(415, "json_required")
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    if int(length) < 0 or int(length) > max_request_bytes:
                        return _error(413, "request_too_large")
                except ValueError:
                    return _error(400, "invalid_content_length")
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > max_request_bytes:
                    return _error(413, "request_too_large")
                body.extend(chunk)
            try:
                payload = json.loads(body, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
            except (ValueError, UnicodeDecodeError):
                return _error(400, "invalid_json")
            if not isinstance(payload, dict) or payload.keys() - _REQUEST_FIELDS:
                return _error(400, "unsupported_request_fields")

            requested_model = payload.get("model")
            route = configured_routes[admission.route_id]
            if not isinstance(requested_model, str):
                return _error(400, "model_required")

            candidates = route.profiles.get(requested_model, (requested_model,))
            eligible_candidates = [
                c for c in candidates if c in route.allowed_models and c in admission.allowed_models
            ]

            if not eligible_candidates:
                return _error(403, "model_not_allowed")

            if not isinstance(payload.get("messages"), list) or not payload["messages"]:
                return _error(400, "messages_required")
            streaming = payload.get("stream", False)
            if not isinstance(streaming, bool):
                return _error(400, "invalid_stream_flag")

            request_id = str(uuid4())
            last_error = None

            deadline = time.monotonic() + upstream_timeout_seconds
            for attempt_index, candidate in enumerate(eligible_candidates, 1):
                last_error = None
                if time.monotonic() >= deadline:
                    return _error(504, "gateway_deadline_exceeded")
                payload["model"] = candidate
                body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

                # Revalidate after body upload: an epoch may have changed while a
                # slow client was uploading. Reject changed identity or permissions.
                refreshed, failure = await authorized(request)
                if failure is not None:
                    return failure
                if refreshed != admission:
                    return _error(403, "authority_changed")

                event_base = dict(
                    request_id=request_id,
                    requested_model=requested_model,
                    attempt_index=attempt_index,
                    enrollment_id=admission.enrollment_id,
                    credential_id=admission.credential_id,
                    owner_id=admission.owner_id,
                    agent_id=admission.agent_id,
                    workspace_id=admission.workspace_id,
                    execution_epoch=admission.execution_epoch,
                    policy_revision=admission.policy_revision,
                    route_id=admission.route_id,
                    model=candidate,
                    credential_version=route.credential_version,
                )

                if not await record("admitted"):
                    return _error(503, "accounting_unavailable")

                refreshed, failure = await authorized(request)
                if failure is not None or refreshed != admission:
                    await record("rejected", error_code="authority_changed")
                    return failure if failure is not None else _error(403, "authority_changed")

                req = client.build_request(
                    "POST",
                    route.endpoint,
                    content=body_bytes,
                    headers={
                        "Authorization": f"Bearer {route.api_key}",
                        "Content-Type": "application/json",
                        "Accept": "text/event-stream" if streaming else "application/json",
                        "Accept-Encoding": "identity",
                    },
                )
                dispatched = True
                async with asyncio.timeout(max(0.001, deadline - time.monotonic())):
                    upstream = await client.send(req, stream=True)

                if upstream.status_code != 200:
                    original_status = upstream.status_code
                    status, code = _upstream_error(original_status)
                    # Discard the upstream error body; it may contain credentials.
                    await record("uncertain", error_code=code, upstream_status=upstream.status_code)
                    last_error = _error(status, code)
                    await _close_response(upstream)
                    upstream = None
                    # Never infer model scope from normalized credential/funding/429 errors.
                    if original_status in (500, 502, 503, 504):
                        continue
                    else:
                        return last_error

                content_type = upstream.headers.get("content-type", "").split(";", 1)[0].lower()
                expected = "text/event-stream" if streaming else "application/json"
                if content_type != expected:
                    await record("uncertain", error_code="upstream_protocol_mismatch", upstream_status=200)
                    last_error = _error(502, "upstream_protocol_mismatch")
                    await _close_response(upstream)
                    upstream = None
                    return last_error

                if not streaming:
                    response_body = bytearray()
                    response_iterator = upstream.aiter_bytes()
                    async for chunk in _deadline_chunks(response_iterator, deadline):
                        if len(response_body) + len(chunk) > max_response_bytes:
                            await record(
                                "uncertain", error_code="upstream_response_too_large", upstream_status=200
                            )
                            last_error = _error(502, "upstream_response_too_large")
                            break
                        response_body.extend(chunk)

                    if last_error:
                        await _close_response(upstream)
                        upstream = None
                        return last_error

                    try:
                        decoded = json.loads(response_body)
                        if (
                            not isinstance(decoded, dict)
                            or "error" in decoded
                            or not isinstance(decoded.get("choices"), list)
                        ):
                            raise ValueError("invalid upstream response")
                    except (ValueError, UnicodeDecodeError):
                        await record("uncertain", error_code="upstream_invalid_response", upstream_status=200)
                        last_error = _error(502, "upstream_invalid_response")
                        await _close_response(upstream)
                        upstream = None
                        return last_error

                    safe_body = bytes(response_body).replace(route.api_key.encode(), b"[REDACTED]")
                    if not await record("completed", upstream_status=200, emitted_bytes=len(safe_body)):
                        return _error(503, "accounting_unavailable")
                    return Response(
                        safe_body, media_type="application/json", headers={"Cache-Control": "no-store"}
                    )

                # Buffer complete frames before committing headers, independent of TCP chunks.
                iterator = upstream.aiter_bytes()
                frames = _SSEGuard()
                prefetched = bytearray()
                failure_code = None
                retryable = False
                meaningful = False
                try:
                    async with asyncio.timeout(max(0.001, min(10.0, deadline - time.monotonic()))):
                        while not meaningful and failure_code is None:
                            try:
                                chunk = await iterator.__anext__()
                            except StopAsyncIteration:
                                failure_code = "upstream_stream_incomplete"
                                break
                            if len(prefetched) + len(chunk) > min(max_response_bytes, 1048576):
                                failure_code = "upstream_response_too_large"
                                break
                            prefetched.extend(chunk)
                            for frame, provider_error in frames.feed(chunk):
                                if provider_error:
                                    failure_code = "upstream_stream_error"
                                    retryable = _retryable_stream_error(frame)
                                    break
                                data_lines = [
                                    line for line in frame.splitlines() if line.startswith(b"data:")
                                ]
                                if data_lines:
                                    meaningful = True
                                    break
                except (httpx.HTTPError, TimeoutError):
                    # Dispatch occurred; an uncertain transport outcome is not safe to replay.
                    failure_code = "upstream_transport_failure"
                except ValueError:
                    failure_code = "upstream_invalid_response"
                if failure_code:
                    await record("uncertain", error_code=failure_code, upstream_status=200)
                    last_error = _error(502, failure_code)
                    await _close_response(upstream)
                    upstream = None
                    if retryable:
                        continue
                    return last_error
                first_chunk = bytes(prefetched)

                emitted = 0
                stream_finished = False

                async def finish_stream(failure_code):
                    nonlocal stream_finished
                    if stream_finished:
                        return
                    stream_finished = True
                    with anyio.CancelScope(shield=True):
                        try:
                            if not await _close_response(upstream):
                                failure_code = failure_code or "upstream_cleanup_failed"
                        finally:
                            app.state.in_flight -= 1
                            await record(
                                "uncertain" if failure_code else "completed",
                                error_code=failure_code,
                                upstream_status=200,
                                emitted_bytes=emitted,
                            )

                async def forward():
                    nonlocal emitted
                    marker = _DoneMarker()
                    scrubber = _SecretFilter(route.api_key)
                    frames_stream = _SSEGuard()
                    stream_failure_code = None
                    received = len(first_chunk)

                    try:
                        # Yield the first chunk we already read
                        for frame, provider_error in frames_stream.feed(first_chunk):
                            if provider_error:
                                stream_failure_code = "upstream_stream_error"
                                break
                            marker.feed(frame)
                            clean = scrubber.feed(frame)
                            if clean:
                                emitted += len(clean)
                                yield clean

                        if not stream_failure_code:
                            async for chunk in _deadline_chunks(iterator, deadline):
                                received += len(chunk)
                                if received > max_response_bytes:
                                    stream_failure_code = "upstream_response_too_large"
                                    break
                                for frame, provider_error in frames_stream.feed(chunk):
                                    if provider_error:
                                        stream_failure_code = "upstream_stream_error"
                                        break
                                    marker.feed(frame)
                                    clean = scrubber.feed(frame)
                                    if clean:
                                        emitted += len(clean)
                                        yield clean
                                if stream_failure_code:
                                    break

                        if stream_failure_code is None and not marker.seen:
                            stream_failure_code = "upstream_stream_incomplete"
                        tail = scrubber.feed(b"", final=True)
                        if tail:
                            emitted += len(tail)
                            yield tail
                    except asyncio.CancelledError:
                        stream_failure_code = "client_disconnected"
                        raise
                    except GeneratorExit:
                        stream_failure_code = "client_disconnected"
                        raise
                    except Exception:
                        # Never include str(exc), raw error bodies, or a fallback.
                        stream_failure_code = "upstream_stream_interrupted"
                    finally:
                        await finish_stream(stream_failure_code)

                transferred = True
                return _ManagedStream(
                    forward(),
                    finish=finish_stream,
                    media_type="text/event-stream",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                )

            return last_error or _error(503, "upstream_unavailable")
        except asyncio.CancelledError:
            if dispatched and event_base:
                with anyio.CancelScope(shield=True):
                    await record("uncertain", error_code="client_disconnected")
            raise
        except Exception:
            if dispatched and event_base:
                await record("uncertain", error_code="upstream_transport_failure")
                return _error(502, "upstream_transport_failure")
            return _error(400, "invalid_request")
        finally:
            if not transferred:
                try:
                    if upstream is not None:
                        with anyio.CancelScope(shield=True):
                            await _close_response(upstream)
                finally:
                    app.state.in_flight -= 1

    return app
