"""Safety and wire parsing for the opt-in runner; no provider requests here."""

import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

spec = importlib.util.spec_from_file_location(
    "gateway_live_probe", Path(__file__).parents[1] / "scripts/verify_gateway_live.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def tool_call(**updates):
    return {
        "id": "call_123",
        "type": "function",
        "function": {"name": "vessel_add_probe", "arguments": '{"a":17,"b":25}'},
        **updates,
    }


def test_tool_execution_uses_returned_id_and_refuses_replay():
    executed = set()
    result = probe.execute_tool(tool_call(), executed)
    assert result["tool_call_id"] == "call_123"
    assert json.loads(result["content"]) == {"sum": 42}
    with pytest.raises(ValueError, match="duplicate"):
        probe.execute_tool(tool_call(), executed)


@pytest.mark.parametrize(
    "arguments", ['{"a":true,"b":25}', '{"a":17,"b":25,"command":"whoami"}', '{"a":18,"b":25}']
)
def test_tool_executor_cannot_expand_scope(arguments):
    call = tool_call(function={"name": "vessel_add_probe", "arguments": arguments})
    with pytest.raises(ValueError):
        probe.execute_tool(call, set())
    with pytest.raises(ValueError):
        probe.execute_tool(tool_call(function={"name": "run_command", "arguments": "{}"}), set())


def test_stream_parser_preserves_tool_identity_and_arguments_across_byte_splits():
    pieces = [
        {
            "model": "verified-model",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_123",
                                "type": "function",
                                "function": {"name": "vessel_add_probe", "arguments": '{"a":'},
                            }
                        ]
                    }
                }
            ],
        },
        {
            "model": "verified-model",
            "choices": [
                {
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '17,"b":25}'}}]},
                    "finish_reason": "tool_calls",
                }
            ],
        },
    ]
    raw = (
        b": heartbeat\r\n\r\n"
        + b"".join(b"data: " + json.dumps(x).encode() + b"\r\n\r\n" for x in pieces)
        + b"data: [DONE]\r\n\r\n"
    )
    parsed = probe.SSE()
    for byte in raw:
        parsed.feed(bytes([byte]))
    assert parsed.done and parsed.frames == 2
    assert parsed.calls[0] == tool_call()
    assert parsed.models == {"verified-model"}


def test_chaos_interrupt_uses_real_first_data_frame_after_a_buffered_comment():
    raw = b': comment\n\ndata: {"choices":[{"delta":{"content":"real"}}]}\n\ndata: [DONE]\n\n'

    async def collect():
        stream = probe.InterruptAfterFrame(probe.Bytes(raw))
        observed = []
        with pytest.raises(httpx.ReadError):
            async for chunk in stream:
                observed.append(chunk)
        return b"".join(observed)

    received = asyncio.run(collect())
    assert b"real" in received and b"[DONE]" not in received


def test_cline_credential_cannot_be_sent_to_a_different_upstream(tmp_path):
    path = tmp_path / "providers.json"
    path.write_text(
        json.dumps(
            {
                "providers": {
                    "openai-compatible": {
                        "settings": {
                            "baseUrl": "https://configured.example/v1",
                            "apiKey": "private-probe-key",
                        }
                    }
                }
            }
        )
    )
    args = SimpleNamespace(cline_provider_file=path, upstream="https://elsewhere.example/v1/chat/completions")
    with pytest.raises(ValueError, match="does not match"):
        probe.credentials(args)
