import asyncio
import dataclasses
import json

import httpx
import pytest

from vessel.gateway import (
    AuthorizationDenied,
    CaptureUnhealthy,
    GatewayAdmission,
    UpstreamRoute,
    create_app,
)
from vessel.orbio import UnsupportedCapability, UnsupportedOrbioAdapter

TOKEN = "vessel-test-credential-0123456789"
SECRET = "upstream-secret-must-never-leak"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
PAYLOAD = {"model": "verified-model", "messages": [{"role": "user", "content": "Continue"}]}


def admission(**updates):
    current = GatewayAdmission(
        enrollment_id="enrollment-1",
        credential_id="credential-1",
        owner_id="owner-1",
        agent_id="agent-1",
        workspace_id="workspace-1",
        route_id="route-1",
        execution_epoch=1,
        policy_revision=1,
        credential_execution_epoch=1,
        credential_policy_revision=1,
        allowed_models=frozenset({"verified-model"}),
    )
    return dataclasses.replace(current, **updates)


class Chunks(httpx.AsyncByteStream):
    def __init__(self, *chunks, fail=False):
        self.chunks = chunks
        self.fail = fail
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk
        if self.fail:
            raise httpx.ReadError(f"provider exception containing {SECRET}")

    async def aclose(self):
        self.closed = True


def app_for(handler, **kwargs):
    return create_app(
        routes={
            "route-1": UpstreamRoute(
                endpoint="https://verified.example/v1/chat/completions",
                api_key=SECRET,
                allowed_models=frozenset({"verified-model"}),
            )
        },
        authorize=kwargs.pop("authorize", lambda token: admission() if token == TOKEN else None),
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def request(app, *, payload=None, headers=None):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            return await client.post(
                "/v1/chat/completions",
                json=payload or PAYLOAD,
                headers=HEADERS if headers is None else headers,
            )


def test_successful_sse_preserves_split_tool_calls_and_attributes_to_enrollment():
    chunks = (
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"lookup","arguments":"{\\"q\\":"}}]}}]}\n\n',
        b'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"x\\"}"}}]}}]}\n\n',
        b"data: [DO",
        b"NE]\n\n",
    )
    source = Chunks(*chunks)
    requests = []

    def upstream(req):
        requests.append(req)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=source)

    app = app_for(upstream)
    result = asyncio.run(
        request(
            app,
            payload={**PAYLOAD, "stream": True},
            headers={**HEADERS, "X-Run-Id": "unverified-client-value"},
        )
    )
    assert result.content == b"".join(chunks)
    assert source.closed
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == f"Bearer {SECRET}"
    assert "X-Run-Id" not in requests[0].headers
    event = app.state.events[-1]
    assert event.phase == "completed"
    assert event.enrollment_id == "enrollment-1"
    assert event.attribution_level == "enrollment" and event.run_id is None
    assert event.cost is None
    assert SECRET not in repr(event)
    assert app.state.in_flight == 0


def test_interrupted_stream_never_retries_or_switches(caplog):
    first = (
        b'data: {"choices":[{"delta":{"content":"This response has begun and must never be replaced."}}]}\n\n'
    )
    source = Chunks(first, fail=True)
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=source)

    app = app_for(upstream)
    response = asyncio.run(request(app, payload={**PAYLOAD, "stream": True}))
    assert first.startswith(response.content) and response.content
    assert len(calls) == 1 and source.closed
    assert app.state.events[-1].phase == "uncertain"
    assert app.state.events[-1].error_code == "upstream_stream_interrupted"
    assert b"[DONE]" not in response.content
    assert SECRET not in response.text + caplog.text + repr(app.state.events)
    assert app.state.in_flight == 0


def test_clean_eof_without_done_is_uncertain():
    source = Chunks(b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
    app = app_for(
        lambda req: httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=source)
    )
    asyncio.run(request(app, payload={**PAYLOAD, "stream": True}))
    assert app.state.events[-1].error_code == "upstream_stream_incomplete"


def test_configured_secret_is_removed_across_stream_chunks():
    source = Chunks(b'data: {"message":"upstream-secret-', b'must-never-leak"}\n\n', b"data: [DONE]\n\n")
    app = app_for(
        lambda req: httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=source)
    )
    result = asyncio.run(request(app, payload={**PAYLOAD, "stream": True}))
    assert result.content == b'data: {"message":"[REDACTED]"}\n\ndata: [DONE]\n\n'


def test_provider_error_sse_frame_is_not_forwarded_or_mistaken_for_completion():
    source = Chunks(
        b'data: {"error":{"message":"' + SECRET.encode() + b' sensitive provider details"}}\n\n',
        b"data: [DONE]\n\n",
    )
    app = app_for(
        lambda req: httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=source)
    )
    result = asyncio.run(request(app, payload={**PAYLOAD, "stream": True}))
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "upstream_stream_error"
    assert app.state.events[-1].phase == "uncertain"
    assert app.state.events[-1].error_code == "upstream_stream_error"


@pytest.mark.parametrize("payload", [{"error": {"message": SECRET}}, {"unexpected": SECRET}])
def test_success_status_with_invalid_upstream_json_is_normalized(payload):
    app = app_for(lambda req: httpx.Response(200, json=payload))
    result = asyncio.run(request(app))
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "upstream_invalid_response"
    assert SECRET not in result.text


@pytest.mark.parametrize(
    "current,code",
    [
        (None, "admission_denied"),
        (admission(active=False), "admission_denied"),
        (admission(execution_epoch=2), "stale_gateway_credential"),
        (admission(policy_revision=2), "stale_gateway_credential"),
        (admission(authority="unknown"), "unknown_authority"),
    ],
)
def test_invalid_current_authority_never_reaches_upstream(current, code):
    def never(req):
        pytest.fail("Denied request reached upstream")

    app = app_for(never, authorize=lambda token: current)
    result = asyncio.run(request(app))
    assert result.json()["error"]["code"] == code
    assert not app.state.events


def test_missing_credential_and_authority_exception_are_redacted():
    def broken(token):
        raise RuntimeError(SECRET)

    app = app_for(lambda req: pytest.fail("must not send"), authorize=broken)
    result = asyncio.run(request(app, headers={}))
    assert result.status_code == 401
    app = app_for(lambda req: pytest.fail("must not send"), authorize=broken)
    result = asyncio.run(request(app))
    assert result.status_code == 503
    assert SECRET not in result.text


def test_explicit_authority_denial_is_not_server_error():
    def denied(token):
        raise AuthorizationDenied(SECRET)

    app = app_for(lambda req: pytest.fail("must not send"), authorize=denied)
    assert asyncio.run(request(app)).status_code == 403


def test_capture_block_is_actionable_without_claiming_credentials_are_invalid():
    def capture_blocked(token):
        raise CaptureUnhealthy(SECRET)

    app = app_for(lambda req: pytest.fail("must not send"), authorize=capture_blocked)
    result = asyncio.run(request(app))
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "capture_unhealthy"
    assert "companion's capture health" in result.json()["error"]["message"]
    assert result.headers["Cache-Control"] == "no-store"
    assert SECRET not in result.text
    assert not app.state.events


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "upstream_credential_rejected"),
        (403, "upstream_credential_rejected"),
        (402, "upstream_funding_required"),
        (429, "upstream_rate_limited"),
        (500, "upstream_unavailable"),
        (307, "upstream_redirect_rejected"),
    ],
)
def test_nonstream_upstream_errors_are_normalized_without_body_or_headers(status, code, caplog):
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(
            status,
            json={"error": {"message": SECRET}},
            headers={"Location": f"https://evil.example/{SECRET}", "X-Debug": SECRET},
        )

    app = app_for(upstream)
    result = asyncio.run(request(app))
    assert result.json()["error"]["code"] == code
    assert len(calls) == 1
    assert SECRET not in result.text + repr(result.headers) + caplog.text + repr(app.state.events)
    assert app.state.events[-1].phase == "uncertain"


def test_successful_nonstream_response_preserves_tool_structure():
    response = {
        "id": "completion-1",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "inspect", "arguments": '{"file":"app.py"}'},
                        }
                    ],
                }
            }
        ],
    }
    app = app_for(lambda req: httpx.Response(200, json=response))
    result = asyncio.run(request(app))
    assert result.json() == response
    assert app.state.events[-1].phase == "completed"


@pytest.mark.parametrize(
    "extra,expected",
    [
        ({"model": "not-approved"}, 403),
        ({"base_url": "https://evil.example"}, 400),
        ({"api_key": "arbitrary-key"}, 400),
        ({"run_id": "guessed"}, 400),
        ({"stream": "yes"}, 400),
    ],
)
def test_client_cannot_choose_unapproved_route_model_or_run(extra, expected):
    app = app_for(lambda req: pytest.fail("must not send"))
    assert asyncio.run(request(app, payload={**PAYLOAD, **extra})).status_code == expected


def test_body_bounds_apply_to_declared_and_chunked_uploads():
    async def check():
        app = app_for(lambda req: pytest.fail("must not send"), max_request_bytes=80)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                result = await client.post(
                    "/v1/chat/completions",
                    content=b"x" * 81,
                    headers={**HEADERS, "Content-Type": "application/json"},
                )
                assert result.status_code == 413

                async def body():
                    yield b"x" * 60
                    yield b"x" * 21

                result = await client.post(
                    "/v1/chat/completions",
                    content=body(),
                    headers={**HEADERS, "Content-Type": "application/json"},
                )
                assert result.status_code == 413
        assert app.state.in_flight == 0

    asyncio.run(check())


def test_duplicate_model_and_nonjson_numeric_constants_cannot_bypass_validation():
    async def check():
        app = app_for(lambda req: pytest.fail("must not send"))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                for body in [
                    b'{"model":"unapproved","model":"verified-model","messages":[{"role":"user","content":"hi"}]}',
                    b'{"model":"verified-model","temperature":NaN,"messages":[{"role":"user","content":"hi"}]}',
                ]:
                    result = await client.post(
                        "/v1/chat/completions",
                        content=body,
                        headers={**HEADERS, "Content-Type": "application/json"},
                    )
                    assert result.status_code == 400

    asyncio.run(check())


def test_epoch_rechecked_after_slow_body_upload():
    async def check():
        facts = {"current": admission()}
        app = app_for(
            lambda req: pytest.fail("revoked upload reached upstream"),
            authorize=lambda token: facts["current"],
        )
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:

                async def body():
                    yield json.dumps(PAYLOAD).encode()
                    facts["current"] = admission(execution_epoch=2)

                result = await client.post(
                    "/v1/chat/completions",
                    content=body(),
                    headers={**HEADERS, "Content-Type": "application/json"},
                )
                assert result.status_code == 403
        assert app.state.in_flight == 0

    asyncio.run(check())


def test_epoch_rechecked_after_audit_before_network_dispatch():
    facts = {"current": admission()}

    def audit(event):
        if event.phase == "admitted":
            facts["current"] = admission(execution_epoch=2)

    app = app_for(
        lambda req: pytest.fail("must not send"), authorize=lambda token: facts["current"], audit=audit
    )
    assert asyncio.run(request(app)).status_code == 403
    assert app.state.events[-1].phase == "rejected"


def test_audit_failure_closes_future_admissions():
    async def check():
        def broken(event):
            raise RuntimeError(SECRET)

        app = app_for(lambda req: pytest.fail("must not send"), audit=broken)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                for _ in range(2):
                    result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                    assert result.status_code == 503 and SECRET not in result.text
        assert not app.state.audit_healthy

    asyncio.run(check())


def test_concurrency_limit_releases_slot_after_completion():
    async def check():
        entered = asyncio.Event()
        release = asyncio.Event()

        async def upstream(req):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={"choices": []})

        app = app_for(upstream, max_concurrency=1)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                first = asyncio.create_task(
                    client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                )
                await asyncio.wait_for(entered.wait(), timeout=2)
                second = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                assert second.status_code == 429
                release.set()
                assert (await first).status_code == 200
                assert app.state.in_flight == 0

    asyncio.run(check())


def test_disconnect_before_stream_iteration_closes_upstream_and_records_uncertainty():
    async def check():
        source = Chunks(b"data: [DONE]\n\n")
        app = app_for(
            lambda req: httpx.Response(200, headers={"Content-Type": "text/event-stream"}, stream=source)
        )
        body = json.dumps({**PAYLOAD, "stream": True}).encode()
        received = False

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            raise OSError("client gone")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/v1/chat/completions",
            "raw_path": b"/v1/chat/completions",
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"authorization", f"Bearer {TOKEN}".encode()),
                (b"content-type", b"application/json"),
            ],
            "server": ("gateway", 80),
            "client": ("client", 1234),
        }
        async with app.router.lifespan_context(app):
            with pytest.raises(Exception):
                await app(scope, receive, send)
        assert source.closed and app.state.in_flight == 0
        assert app.state.events[-1].phase == "uncertain"
        assert app.state.events[-1].error_code == "client_disconnected"

    asyncio.run(check())


def test_disconnect_during_upstream_send_is_uncertain():
    async def check():
        entered = asyncio.Event()

        async def upstream(req):
            entered.set()
            await asyncio.Event().wait()

        app = app_for(upstream)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                task = asyncio.create_task(client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS))
                await asyncio.wait_for(entered.wait(), timeout=2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        assert app.state.in_flight == 0
        assert app.state.events[-1].phase == "uncertain"
        assert app.state.events[-1].error_code == "client_disconnected"

    asyncio.run(check())


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://verified.example/v1/chat/completions",
        "https://user:pass@verified.example/v1/chat/completions",
        "https://verified.example/v1/chat/completions?key=secret",
        "https://verified.example:8443/v1/chat/completions",
        "https://verified.example/arbitrary",
    ],
)
def test_routes_require_explicit_https_endpoint(endpoint):
    with pytest.raises(ValueError):
        UpstreamRoute(endpoint, SECRET, frozenset({"verified-model"}))


def test_orbio_management_is_explicitly_unsupported():
    async def check():
        adapter = UnsupportedOrbioAdapter()
        assert not any(dataclasses.asdict(adapter.capabilities).values())
        for operation, args in [
            (adapter.validate_credential, ("ref",)),
            (adapter.get_balance, ("account",)),
            (adapter.rotate_credential, ("ref", "authorization")),
            (adapter.top_up, ("account", "authorization")),
        ]:
            with pytest.raises(UnsupportedCapability):
                await operation(*args)

    asyncio.run(check())


def fallback_app(handler, **options):
    return create_app(
        routes={
            "route-1": UpstreamRoute(
                "https://verified.example/v1/chat/completions",
                SECRET,
                frozenset({"primary", "secondary"}),
                profiles={"vessel-auto": ("primary", "secondary")},
            )
        },
        authorize=lambda _: admission(allowed_models=frozenset({"primary", "secondary"})),
        transport=httpx.MockTransport(handler),
        **options,
    )


def test_nonstream_fallback_returns_success_with_terminal_receipt():
    calls = []

    def upstream(req):
        calls.append(json.loads(req.content)["model"])
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, json={"choices": []})

    app = fallback_app(upstream)
    response = asyncio.run(request(app, payload={**PAYLOAD, "model": "vessel-auto"}))
    assert response.status_code == 200 and calls == ["primary", "secondary"]
    assert app.state.events[-1].phase == "completed"
    assert app.state.events[-1].requested_model == "vessel-auto"
    assert app.state.events[-1].attempt_index == 2


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422, 429])
def test_account_request_and_unscoped_rate_errors_never_switch_models(status):
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(status)

    app = fallback_app(upstream)
    response = asyncio.run(request(app, payload={**PAYLOAD, "model": "vessel-auto"}))
    assert response.status_code >= 400 and len(calls) == 1


@pytest.mark.parametrize("split", [1, 10, 35, None])
def test_initial_stream_error_fallback_independent_of_chunk_boundaries(split):
    calls = []
    error = b'data: {"error":{"code":503,"message":"unavailable"}}\n\n'
    success = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'

    def upstream(req):
        calls.append(json.loads(req.content)["model"])
        chunks = (error,) if split is None else (error[:split], error[split:])
        source = Chunks(*chunks) if len(calls) == 1 else Chunks(success)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=source)

    app = fallback_app(upstream)
    response = asyncio.run(request(app, payload={**PAYLOAD, "model": "vessel-auto", "stream": True}))
    assert response.content == success and calls == ["primary", "secondary"]


def test_prefetched_stream_bytes_respect_response_limit():
    large = b'data: {"choices":[{"delta":{"content":"' + b"x" * 400 + b'"}}]}\n\ndata: [DONE]\n\n'
    app = fallback_app(
        lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Chunks(large)),
        max_response_bytes=128,
    )
    response = asyncio.run(request(app, payload={**PAYLOAD, "model": "vessel-auto", "stream": True}))
    assert response.status_code == 502 and large not in response.content
    assert app.state.events[-1].error_code == "upstream_response_too_large"


@pytest.mark.parametrize("chain", [(), ("a", "a"), ("a", "b", "c", "d"), ("unapproved",)])
def test_profiles_bound_and_validate_candidate_chain(chain):
    with pytest.raises(ValueError):
        UpstreamRoute(
            "https://verified.example/v1/chat/completions",
            SECRET,
            frozenset({"a", "b", "c", "d"}),
            profiles={"alias": chain},
        )


@pytest.mark.parametrize("body", [b"invalid-json", b'{"error":"unknown"}', b"x" * 1024])
def test_unknown_nonstream_outcomes_do_not_replay(body):
    calls = []

    def upstream(req):
        calls.append(req)
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})

    app = fallback_app(upstream, max_response_bytes=128)
    response = asyncio.run(request(app, payload={**PAYLOAD, "model": "vessel-auto"}))
    assert response.status_code == 502 and len(calls) == 1


def test_model_discovery_exposes_eligible_alias():
    app = fallback_app(lambda _: pytest.fail("Discovery dispatched inference"))

    async def check():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://gateway"
            ) as client:
                response = await client.get("/v1/models", headers=HEADERS)
                assert {item["id"] for item in response.json()["data"]} == {
                    "primary",
                    "secondary",
                    "vessel-auto",
                }

    asyncio.run(check())


def test_alias_cannot_shadow_a_real_model():
    with pytest.raises(ValueError):
        UpstreamRoute(
            "https://verified.example/v1/chat/completions",
            SECRET,
            frozenset({"primary"}),
            profiles={"primary": ("primary",)},
        )
