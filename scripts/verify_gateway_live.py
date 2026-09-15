"""Opt-in real inference through a loopback VESSEL gateway, never a native capture test.

Only tiny canned prompts and a validated addition tool are sent. Fault injection
is owned by this runner, never exposed as a gateway request parameter. Provider
credentials stay in memory; reports contain protocol metadata and canned output.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import secrets
import socket
import time
from pathlib import Path
from uuid import uuid4

import httpx
import uvicorn

from vessel.gateway import GatewayAdmission, UpstreamRoute, create_app

TOOL = {
    "type": "function",
    "function": {
        "name": "vessel_add_probe",
        "description": "Add the two supplied integers locally and return their sum.",
        "parameters": {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    },
}


def execute_tool(call, executed):
    """This is the entire tool executor: no eval, shell, files or network."""
    if call.get("type") != "function" or call.get("function", {}).get("name") != "vessel_add_probe":
        raise ValueError("Unexpected tool; execution refused")
    call_id = call.get("id")
    if not isinstance(call_id, str) or not call_id or call_id in executed:
        raise ValueError("Missing or duplicate tool call ID; execution refused")
    args = json.loads(call["function"]["arguments"])
    if not isinstance(args, dict) or set(args) != {"a", "b"}:
        raise ValueError("Unexpected tool arguments")
    if any(type(args[k]) is not int for k in args) or args != {"a": 17, "b": 25}:
        raise ValueError("Only the explicit 17 + 25 probe is authorized")
    result = {"sum": args["a"] + args["b"]}
    executed.add(call_id)
    return {"role": "tool", "tool_call_id": call_id, "content": json.dumps(result)}


class SSE:
    """Incremental client parser, including split JSON and tool argument deltas."""

    def __init__(self):
        self.pending = b""
        self.done = False
        self.frames = 0
        self.models = set()
        self.content = ""
        self.calls = {}
        self.finish = None
        self.usage = None

    def feed(self, chunk):
        self.pending += chunk
        self.pending = self.pending.replace(b"\r\n", b"\n")
        while b"\n\n" in self.pending:
            frame, self.pending = self.pending.split(b"\n\n", 1)
            data = b"\n".join(x[5:].lstrip() for x in frame.splitlines() if x.startswith(b"data:"))
            if not data:
                continue
            if data == b"[DONE]":
                self.done = True
                continue
            if self.done:
                raise ValueError("Data after stream completion")
            part = json.loads(data)
            if "error" in part:
                raise ValueError("Provider emitted an error frame")
            self.frames += 1
            if part.get("model"):
                self.models.add(part["model"])
            if part.get("usage"):
                self.usage = part["usage"]
            for choice in part.get("choices", []):
                if choice.get("finish_reason"):
                    self.finish = choice["finish_reason"]
                delta = choice.get("delta", {})
                self.content += delta.get("content") or ""
                for fragment in delta.get("tool_calls", []):
                    call = self.calls.setdefault(
                        fragment["index"],
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if fragment.get("id"):
                        if call["id"] and call["id"] != fragment["id"]:
                            raise ValueError("Tool call identity changed during streaming")
                        call["id"] = fragment["id"]
                    for field in ("name", "arguments"):
                        call["function"][field] += fragment.get("function", {}).get(field) or ""


class Bytes(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data

    async def __aiter__(self):
        # Explicitly exercise transport chunk splitting before gateway commitment.
        yield self.data[:13]
        yield self.data[13:]


class InterruptAfterFrame(httpx.AsyncByteStream):
    def __init__(self, source):
        self.source = source

    async def __aiter__(self):
        pending = b""
        async for chunk in self.source:
            pending += chunk
            while b"\n\n" in pending:
                first = pending.split(b"\n\n", 1)[0] + b"\n\n"
                if first.startswith(b":"):
                    yield first
                    pending = pending[len(first) :]
                    continue
                yield first
                raise httpx.ReadError("Injected disconnect after a real upstream frame")
        raise httpx.ReadError("Upstream ended before the interruption probe")

    async def aclose(self):
        await self.source.aclose()


class FaultTransport(httpx.AsyncBaseTransport):
    def __init__(self, primary, cap):
        self.real = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        self.primary = primary
        self.mode = None
        self.injected = False
        self.attempts = []
        self.live_count = 0
        self.cap = cap

    def arm(self, mode):
        self.mode, self.injected = mode, False
        self.attempts = []

    async def handle_async_request(self, request):
        model = json.loads(request.content)["model"]
        inject = bool(self.mode and not self.injected and model == self.primary)
        self.attempts.append({"model": model, "fault": self.mode if inject else None})
        if inject:
            self.injected = True
            if self.mode == "http_503":
                return httpx.Response(503)
            if self.mode == "initial_sse_503":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/event-stream"},
                    stream=Bytes(b'data: {"error":{"code":503}}\n\n'),
                )
        if self.live_count >= self.cap:
            raise httpx.RequestError("Live request cap reached")
        self.live_count += 1
        response = await self.real.handle_async_request(request)
        if inject and self.mode == "midstream_disconnect" and response.status_code == 200:
            response.stream = InterruptAfterFrame(response.stream)
        return response

    async def aclose(self):
        await self.real.aclose()


def credentials(args):
    if args.cline_provider_file:
        data = json.loads(args.cline_provider_file.read_text(encoding="utf-8"))
        cfg = data["providers"]["openai-compatible"]["settings"]
        # A Cline key may only be sent to the exact origin/base already configured.
        if cfg["baseUrl"].rstrip("/") + "/chat/completions" != args.upstream:
            raise ValueError("Cline provider URL does not match the explicit upstream")
        key = cfg["apiKey"]
    else:
        key = os.environ.get(args.key_env)
    if not isinstance(key, str) or not key:
        raise ValueError("Set the upstream key privately before running the live test")
    return key


async def run(args):
    key = credentials(args)
    models = frozenset((args.primary, args.secondary))
    if len(models) != 2:
        raise ValueError("Model switching requires two distinct models")
    route = UpstreamRoute(args.upstream, key, models, {"vessel-live-auto": (args.primary, args.secondary)})
    args.output.mkdir(parents=True, exist_ok=False)
    token = secrets.token_urlsafe(36)
    probe_id = "gateway_protocol_probe_" + uuid4().hex
    # Explicit test authority, not fabricated Cline capture or a resumed run.
    admission = GatewayAdmission(
        probe_id, probe_id, probe_id, probe_id, probe_id, "probe", 1, 1, 1, 1, models
    )
    events = []
    transport = FaultTransport(args.primary, args.max_calls)
    report = {
        "scope": "live_gateway_protocol_with_isolated_test_authority",
        "native_cline": "not_tested",
        "upstream": args.upstream,
        "models": sorted(models),
        "checks": [],
        "passed": False,
    }
    active = True

    def audit(event):
        record = dataclasses.asdict(event)
        assert key not in json.dumps(record) and token not in json.dumps(record)
        events.append(record)
        with (args.output / "gateway-receipts.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record) + "\n")

    app = create_app(
        routes={"probe": route},
        authorize=lambda supplied: admission if active and secrets.compare_digest(supplied, token) else None,
        audit=audit,
        transport=transport,
        max_concurrency=1,
        upstream_timeout_seconds=60,
    )
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
    )
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    for _ in range(200):
        if server.started:
            break
        if serving.done():
            await serving
            raise RuntimeError("Gateway did not start")
        await asyncio.sleep(0.01)
    if not server.started:
        raise RuntimeError("Gateway startup timed out")

    async with httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}",
        headers={"Authorization": "Bearer " + token},
        timeout=70,
        trust_env=False,
    ) as client:

        async def probe(name, model, messages, *, stream=False, extra=None, expect_complete=True):
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 256,
                "stream": stream,
                **(extra or {}),
            }
            start = time.perf_counter()
            offset = len(events)
            evidence = {"name": name, "requested_model": model, "stream": stream}
            try:
                if stream:
                    parsed = SSE()
                    chunks, first = 0, None
                    async with client.stream("POST", "/v1/chat/completions", json=payload) as response:
                        evidence["http_status"] = response.status_code
                        if response.status_code != 200:
                            raise ValueError("Gateway rejected streaming probe")
                        async for chunk in response.aiter_bytes():
                            assert key.encode() not in chunk and token.encode() not in chunk
                            first = first if first is not None else time.perf_counter() - start
                            chunks += 1
                            parsed.feed(chunk)
                    evidence.update(
                        done=parsed.done,
                        frames=parsed.frames,
                        network_chunks=chunks,
                        first_chunk_ms=round((first or 0) * 1000),
                        response_models=sorted(parsed.models),
                        finish_reason=parsed.finish,
                        usage=parsed.usage,
                    )
                    message = {"role": "assistant", "content": parsed.content or None}
                    if parsed.calls:
                        message["tool_calls"] = [parsed.calls[k] for k in sorted(parsed.calls)]
                    if expect_complete and (not parsed.done or parsed.frames < 2 or not parsed.models):
                        raise ValueError("Stream lacks completion, deltas or model identity")
                else:
                    response = await client.post("/v1/chat/completions", json=payload)
                    evidence["http_status"] = response.status_code
                    if response.status_code != 200:
                        raise ValueError("Gateway rejected completion probe")
                    data = response.json()
                    assert key not in response.text and token not in response.text
                    message = data["choices"][0]["message"]
                    evidence.update(
                        response_models=[data["model"]],
                        finish_reason=data["choices"][0]["finish_reason"],
                        usage=data.get("usage"),
                    )
                evidence["elapsed_ms"] = round((time.perf_counter() - start) * 1000)
                if expect_complete and evidence["finish_reason"] not in {"stop", "tool_calls"}:
                    raise ValueError("Model output did not finish normally within the test token bound")
                # Allow the streaming response finalizer to commit its terminal receipt.
                for _ in range(100):
                    if len(events) > offset and events[-1]["phase"] != "admitted":
                        break
                    await asyncio.sleep(0.01)
                receipt_slice = events[offset:]
                evidence["receipts"] = receipt_slice
                if expect_complete and (not receipt_slice or receipt_slice[-1]["phase"] != "completed"):
                    raise ValueError("No completed gateway receipt")
                evidence["passed"] = True
                print("PASS:", name, flush=True)
                return message, evidence
            except Exception:
                evidence.update(passed=False, receipts=events[offset:])
                raise
            finally:
                report["checks"].append(evidence)

        try:
            visible = (await client.get("/v1/models")).json()["data"]
            assert {m["id"] for m in visible} == models | {"vessel-live-auto"}
            ready = [{"role": "user", "content": "VESSEL gateway test. Reply with exactly READY."}]
            returned = []
            for model in (args.primary, args.secondary):
                transport.arm(None)
                message, evidence = await probe("direct-model:" + model, model, ready)
                assert "READY" in (message.get("content") or "")
                assert evidence["receipts"][-1]["model"] == model
                returned.append(evidence["response_models"][0])
            assert returned[0] != returned[1], "Provider reported the same model for both selections"
            for model in (args.primary, args.secondary):
                text_message, evidence = await probe(
                    "stream-text:" + model,
                    model,
                    [
                        {
                            "role": "user",
                            "content": "Count from 1 to 12, separated by commas, with no explanation.",
                        }
                    ],
                    stream=True,
                )
                assert [
                    int(x.strip()) for x in text_message["content"].strip().strip(".").split(",")
                ] == list(range(1, 13))
                assert evidence["network_chunks"] > 1, "Streaming was buffered into one network chunk"
                messages = [
                    {
                        "role": "user",
                        "content": "Call vessel_add_probe once with a=17 and b=25. Do not calculate the answer yourself. After receiving its result, report the sum.",
                    }
                ]
                message, evidence = await probe(
                    "stream-tool:" + model,
                    model,
                    messages,
                    stream=True,
                    extra={
                        "tools": [TOOL],
                        "tool_choice": {"type": "function", "function": {"name": "vessel_add_probe"}},
                    },
                )
                assert len(message.get("tool_calls", [])) == 1, "Expected exactly one provider tool call"
                executed = set()
                tool_result = execute_tool(message["tool_calls"][0], executed)
                evidence["tool_execution"] = {
                    "call_id": tool_result["tool_call_id"],
                    "result": {"sum": 42},
                    "executor": "local_python_allowlisted_addition",
                }
                with (args.output / "tool-receipts.jsonl").open("a", encoding="utf-8") as file:
                    file.write(json.dumps(evidence["tool_execution"]) + "\n")
                final, _ = await probe(
                    "tool-result-roundtrip:" + model,
                    model,
                    messages + [message, tool_result],
                    extra={"tools": [TOOL], "tool_choice": "none"},
                )
                assert "42" in (final.get("content") or ""), "Model did not use the executed tool result"
            for mode in ("http_503", "initial_sse_503"):
                transport.arm(mode)
                _, evidence = await probe(
                    "controlled-fallback:" + mode, "vessel-live-auto", ready, stream=mode == "initial_sse_503"
                )
                evidence["injected_failure"] = mode
                assert [a["model"] for a in transport.attempts] == [args.primary, args.secondary]
                assert evidence["receipts"][-1]["model"] == args.secondary
                assert evidence["receipts"][-1]["attempt_index"] == 2
            transport.arm("midstream_disconnect")
            _, evidence = await probe(
                "committed-stream-no-replay", "vessel-live-auto", ready, stream=True, expect_complete=False
            )
            evidence["injected_failure"] = "disconnect_after_real_upstream_frame"
            assert len(transport.attempts) == 1 and not evidence["done"]
            assert evidence["receipts"][-1]["phase"] == "uncertain"
            active = False
            rejected = await client.post(
                "/v1/chat/completions", json={"model": args.primary, "messages": ready}
            )
            assert rejected.status_code == 403
            report.update(passed=True, models_discovery=True, admission_revocation=True)
        except Exception as exc:
            # Never persist provider exceptions, request objects, response bodies or secrets.
            report["failure_type"] = type(exc).__name__
            if report["checks"]:
                report["checks"][-1]["passed"] = False
            print("STOP: live check failed; inspect the sanitized report.", flush=True)
        finally:
            active = False
            server.should_exit = True
            await serving
            sock.close()
            report["live_provider_requests"] = transport.live_count
            report["request_cap"] = args.max_calls
            report["max_output_tokens_per_request"] = 256
            report["funding_features"] = "not_used_or_tested"
            serialized = json.dumps(report, indent=2)
            assert key not in serialized and token not in serialized
            (args.output / "report.json").write_text(serialized + "\n", encoding="utf-8")
            print("Report:", args.output / "report.json", flush=True)
    return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--primary", required=True)
    parser.add_argument("--secondary", required=True)
    parser.add_argument("--key-env", default="VESSEL_UPSTREAM_KEY")
    parser.add_argument("--cline-provider-file", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New directory for sanitized evidence")
    parser.add_argument("--max-calls", type=int, default=12)
    parser.add_argument("--run", action="store_true", help="Authorize bounded real provider requests")
    args = parser.parse_args()
    if not 1 <= args.max_calls <= 16:
        parser.error("Choose at most 16 upstream requests")
    if not args.run:
        print("Ready. Add --run to make real inference requests (provider usage charges may apply).")
        return 0
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
