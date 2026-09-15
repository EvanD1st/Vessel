"""Cline contract fixtures and real local process checks; no model inference."""

import asyncio
import json
import os
import subprocess
import sys

import pytest

from vessel import adapters
from vessel.cline import EventRejected, normalize_event, parse
from vessel.sanitization import sanitize
from vessel.service import Blocked, Vessel


@pytest.fixture
def project(tmp_path):
    workspace = tmp_path / "project café's files"
    workspace.mkdir()
    (workspace / "app.py").write_text("pass\n")
    state = tmp_path / "private state"
    service = Vessel(state)
    service.enroll(workspace, "Verify Cline continuity", required_paths=["app.py"])
    config = tmp_path / "cline_mcp_settings.json"
    config.write_text(json.dumps({"mcpServers": {"existing": {"command": "preserve"}}}))
    yield workspace, state, config, service
    service.close()


def payload(workspace, hook="agent_start", **extra):
    return {
        "clineVersion": "4.1.17-fixture",
        "taskId": "native-task-1",
        "agent_id": "agent-1",
        "workspaceRoots": [str(workspace)],
        "hookName": hook,
        **extra,
    }


def test_install_inspect_remove_preserves_other_servers(project):
    workspace, state, config, _ = project
    installed = adapters.install("cline", workspace, state, mcp_config=config)
    assert installed["installed"] and installed["native_capture"] == "unverified"
    assert adapters.install("cline", workspace, state, mcp_config=config) == installed
    content = json.loads(config.read_text())
    content["mcpServers"]["added-later"] = {"command": "keep-too"}
    config.write_text(json.dumps(content))
    assert adapters.uninstall("cline", workspace, state)["uninstalled"]
    assert json.loads(config.read_text())["mcpServers"] == {
        "existing": {"command": "preserve"},
        "added-later": {"command": "keep-too"},
    }


@pytest.mark.parametrize("text", ["{broken", "[]", '{"mcpServers":1}', '{"mcpServers":{},"mcpServers":{}}'])
def test_invalid_config_never_overwritten(project, text):
    workspace, state, config, _ = project
    config.write_text(text)
    with pytest.raises(ValueError):
        adapters.install("cline", workspace, state, mcp_config=config)
    assert config.read_text() == text


def test_changed_owned_config_is_preserved(project):
    workspace, state, config, _ = project
    installed = adapters.install("cline", workspace, state, mcp_config=config)
    value = json.loads(config.read_text())
    value["mcpServers"][installed["server_name"]]["command"] = "changed-by-owner"
    config.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        adapters.uninstall("cline", workspace, state)
    assert "changed-by-owner" in config.read_text()


def test_existing_hooks_preserved(project):
    workspace, state, config, _ = project
    hook = workspace / ".cline/hooks/PreToolUse.py"
    hook.parent.mkdir(parents=True)
    hook.write_text("# owner hook")
    before = config.read_bytes()
    with pytest.raises(ValueError, match="conflicts"):
        adapters.install("cline", workspace, state, mcp_config=config)
    assert hook.read_text() == "# owner hook" and config.read_bytes() == before


@pytest.mark.parametrize(
    "raw", [b"{}{}", b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"\xef\xbb\xbf\xef\xbb\xbf{}"]
)
def test_strict_input_rejection(raw):
    with pytest.raises(EventRejected):
        parse(raw)


def test_bom_unicode_and_secret_redaction(project):
    workspace, _, _, _ = project
    original = payload(
        workspace, "prompt_submit", userPromptSubmit={"prompt": "café\ufeff visible"}, api_key="hidden"
    )
    raw = b"\xef\xbb\xbf" + json.dumps(original, ensure_ascii=False).encode()
    event, gaps = normalize_event(parse(raw), workspace)
    assert not gaps
    assert event["native_payload"]["userPromptSubmit"]["prompt"] == "café\ufeff visible"
    assert "hidden" not in json.dumps(event)
    assert sanitize({"text": "Bearer never-log-this", "secret": "private"}) == {
        "text": "[REDACTED]",
        "secret": "[REDACTED]",
    }


def test_foreign_root_and_tool_paths_rejected(project, tmp_path):
    workspace, _, _, _ = project
    with pytest.raises(EventRejected, match="workspace_mismatch"):
        normalize_event(payload(tmp_path), workspace)
    with pytest.raises(EventRejected, match="outside_workspace"):
        normalize_event(
            payload(
                workspace,
                "tool_call",
                tool_call={"id": "call-1", "name": "readFile", "input": {"path": "../outside"}},
            ),
            workspace,
        )


def test_legacy_receipts_do_not_invent_tool_identity(project):
    workspace, _, _, _ = project
    event, gaps = normalize_event(
        payload(
            workspace,
            "PreToolUse",
            preToolUse={"toolName": "execute_command", "parameters": {"command": "echo test"}},
        ),
        workspace,
    )
    assert "native_tool_id_unavailable" in gaps and "tool_use_id" not in event


def test_binding_preserves_observed_native_session_metadata(project):
    workspace, _, _, service = project
    event, _ = normalize_event(payload(workspace), workspace)
    service.observe(workspace, event, "native-probe")
    before = service.store.get("sessions", "native-task-1")
    run = service.start(workspace, "native-task-1")
    after = service.store.get("sessions", "native-task-1")
    assert after == {**before, "run_id": run["id"], "active": True}
    assert service.store.events()[0]["run_id"] == "unbound"
    assert service.status()["capture"]["state"] == "unknown"


def test_missing_tool_ids_explain_block_without_waiving_evidence(project):
    workspace, _, _, service = project
    run = service.start(workspace, "native-task-1")
    event, gaps = normalize_event(
        payload(
            workspace,
            "PreToolUse",
            taskId="other-native-task",
            preToolUse={"toolName": "execute_command", "parameters": {"command": "echo test"}},
        ),
        workspace,
    )
    with service.store.transaction() as conn:
        for gap in gaps:
            service._gap(gap, conn)
    service.observe(workspace, event, "native-tool")
    health = service.status()["capture"]
    with pytest.raises(Blocked) as blocked:
        service.task(run["id"], "reset", "Password reset")
    message = str(blocked.value)
    assert "omitted native tool IDs" in message
    assert "Bound conversation: native-task-1" in message
    assert "other-native-task" in message
    assert not service.store.list("tasks")
    assert not service.operations(run["id"])
    assert service.status()["capture"] == health


def test_unknown_capture_explains_probe_in_bound_conversation(project):
    workspace, _, _, service = project
    run = service.start(workspace, "native-task-1")
    with pytest.raises(Blocked, match="No healthy native observation"):
        service.task(run["id"], "reset", "Password reset")
    assert service.status()["capture"]["state"] == "unknown"


def test_unbound_native_tools_degrade_capture_but_ready_probe_does_not(project):
    workspace, _, _, service = project
    run = service.start(workspace, "native-task-1")
    for sid in ["native-task-1", "other-native-task"]:
        event, _ = normalize_event(payload(workspace, taskId=sid), workspace)
        service.observe(workspace, event, sid + "-probe")
    assert service.status()["capture"]["state"] == "healthy"
    event, _ = normalize_event(
        payload(
            workspace,
            "tool_call",
            taskId="other-native-task",
            tool_call={"id": "call-1", "name": "bash", "input": {"command": "echo test"}},
        ),
        workspace,
    )
    service.observe(workspace, event, "other-native-tool")
    assert service.status()["capture"]["gaps"] == ["unbound_native_tool_activity"]
    assert service.store.events()[-1]["run_id"] == "unbound"
    assert service.operations(run["id"]) == []
    event, _ = normalize_event(payload(workspace), workspace)
    service.observe(workspace, event, "bound-probe-again")
    assert service.status()["capture"]["state"] == "degraded"


@pytest.mark.parametrize("name", [None, {}, [], 123])
def test_malformed_hook_name_is_bounded_rejection(project, name):
    workspace, _, _, _ = project
    with pytest.raises(EventRejected, match="unsupported_cline_hook"):
        normalize_event(payload(workspace, name), workspace)


def test_configuration_inspection_flags_owner_schema_change(project):
    workspace, state, config, _ = project
    adapters.install("cline", workspace, state, mcp_config=config)
    config.write_text('{"mcpServers": []}')
    with pytest.raises(ValueError, match="mcpServers"):
        adapters.inspect("cline", workspace, state)


def test_active_adapter_health_is_not_native_verification(project):
    workspace, state, config, service = project
    adapters.install("cline", workspace, state, mcp_config=config)
    service.store.put("control", "cline_adapter", {"installed": True})
    restarted = Vessel(state)
    try:
        assert "cline_configuration_missing_or_changed" not in json.dumps(restarted.status()["capture"])
        assert restarted.status()["capabilities"]["native_correlation"] == "unverified"
    finally:
        restarted.close()


def test_sdk_receipts_match_actual_ids_and_require_exit_status(project):
    workspace, _, _, service = project
    run = service.start(workspace, "native-task-1")
    call = {"id": "call-1", "name": "bash", "input": {"command": "python -m pytest"}}
    intent, _ = normalize_event(payload(workspace, "tool_call", tool_call=call), workspace)
    result, _ = normalize_event(
        payload(
            workspace,
            "tool_result",
            tool_result={**call, "output": {"exit_code": 0, "stdout": "1 passed"}},
            postToolUse={"success": True},
        ),
        workspace,
    )
    service.observe(workspace, intent, "delivery-1")
    service.observe(workspace, result, "delivery-2")
    op = service.operations(run["id"])[0]
    assert service._successful_operation(op)
    result["tool_output"] = {"stdout": "claimed success"}
    service.observe(workspace, result, "delivery-3")
    assert not service._successful_operation(service.operations(run["id"])[0])


def test_real_installed_hook_process_preserves_encoding(project):
    workspace, state, config, service = project
    adapters.install("cline", workspace, state, mcp_config=config)
    hook = workspace / ".clinerules/hooks" / ("TaskStart.ps1" if os.name == "nt" else "TaskStart")
    command = ["powershell.exe", "-NoProfile", "-File", str(hook)] if os.name == "nt" else [str(hook)]
    result = subprocess.run(
        command,
        input=json.dumps(payload(workspace), ensure_ascii=False).encode(),
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert json.loads(result.stdout.decode("utf-8-sig")) == {}
    assert service.status()["sessions"][0]["id"] == "native-task-1"


def test_real_mcp_stdio_discovery_and_workspace_status(project):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    workspace, state, _, service = project

    async def check():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "vessel.mcp_server", "--state", str(state), "--workspace", str(workspace)],
            env={**os.environ},
        )
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            names = {tool.name for tool in (await session.list_tools()).tools}
            assert len(names) == 5 and "vessel_get_recovery_context" in names
            result = await session.call_tool("vessel_status", {})
            assert not result.isError
            status = json.loads(result.content[0].text)
            assert status["enrollment"]["id"] == service.status()["enrollment"]["id"]

    asyncio.run(check())
