"""Cline command hooks: native identity, bounded input and conservative receipts.

SDK payloads are normalized into the existing client-independent event ledger.
Legacy payloads lacking native tool IDs remain explicitly incomplete.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path

from vessel.sanitization import EventRejected, sanitize

MAX_INPUT_BYTES = 1024 * 1024
EVENTS = {
    "agent_start": "sessionStart",
    "TaskStart": "sessionStart",
    "agent_resume": "sessionStart",
    "TaskResume": "sessionStart",
    "prompt_submit": "beforeSubmitPrompt",
    "UserPromptSubmit": "beforeSubmitPrompt",
    "tool_call": "preToolUse",
    "PreToolUse": "preToolUse",
    "tool_result": "postToolUse",
    "PostToolUse": "postToolUse",
    "agent_end": "stop",
    "TaskComplete": "stop",
    "agent_abort": "stop",
    "TaskCancel": "stop",
    "agent_error": "stop",
    "TaskError": "stop",
    "session_shutdown": "sessionEnd",
    "SessionShutdown": "sessionEnd",
    "PreCompact": "preCompact",
}


def parse(raw):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise EventRejected("duplicate_event_field")
            out[key] = value
        return out

    def constant(_):
        raise EventRejected("invalid_event_number")

    if len(raw) > MAX_INPUT_BYTES:
        raise EventRejected("event_input_too_large")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise EventRejected("invalid_event_json") from None


def _identifier(value):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(ord(ch) < 32 for ch in value)
    ):
        raise EventRejected("invalid_native_identifier")
    return value


def _path(value):
    if os.name == "nt" and re.match(r"^/[A-Za-z]:/", value):
        value = value[1:]
    return Path(value).expanduser()


def _scope(value, workspace, depth=0):
    if depth > 20:
        raise EventRejected("event_nesting_limit")
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "file_path", "filePath", "cwd", "working_directory"} and isinstance(item, str):
                path = _path(item)
                path = path if path.is_absolute() else workspace / path
                if not path.resolve().is_relative_to(workspace):
                    raise EventRejected("tool_path_outside_workspace")
            else:
                _scope(item, workspace, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _scope(item, workspace, depth + 1)


def _bridge_payload(payload):
    """Read native values retained by the versioned VS Code compatibility bridge."""
    native = payload.get("vesselCapture")
    if native is None:
        return payload
    if not isinstance(native, dict) or type(native.get("schema")) is not int or native["schema"] != 2:
        raise EventRejected("invalid_cline_bridge_payload")
    root = _identifier(native.get("rootSessionId"))
    conversation = _identifier(native.get("conversationId"))
    agent = _identifier(native.get("agentId"))
    native_run = _identifier(native.get("runId"))
    if conversation != payload.get("taskId"):
        raise EventRejected("cline_bridge_conversation_mismatch")
    name = EVENTS.get(payload.get("hookName"))
    iteration = native.get("iteration")
    if (iteration is not None or name in {"preToolUse", "postToolUse"}) and (
        type(iteration) is not int or iteration < 0
    ):
        raise EventRejected("invalid_cline_iteration")
    result = {
        **payload,
        "taskId": conversation,
        "sessionContext": {"rootSessionId": root},
        "agent_id": agent,
        "native_run_id": native_run,
        "iteration": iteration,
    }
    if name in {"preToolUse", "postToolUse"}:
        key = "toolCall" if name == "preToolUse" else "toolResult"
        record = native.get(key)
        if not isinstance(record, dict):
            raise EventRejected("missing_cline_bridge_tool")
        result["tool_call" if name == "preToolUse" else "tool_result"] = record
        if name == "postToolUse":
            legacy = payload.get("postToolUse", {})
            if not isinstance(legacy, dict):
                raise EventRejected("invalid_tool_payload")
            result["postToolUse"] = {**legacy, "success": record.get("success")}
    return result


def _outcome(tool_name, output, success, gaps):
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except ValueError:
            pass
    if tool_name == "run_commands":
        # A successful batch wrapper can contain failed, detached, or unobserved
        # commands. Only the native terminal completion data can certify a batch.
        if not isinstance(output, list) or not output or any(not isinstance(x, dict) for x in output):
            gaps.add("native_tool_exit_status_unavailable")
            return output, False
        failed = any(x.get("success") is False or x.get("error") for x in output)
        codes = [x.get("exitCode") for x in output]
        observed = all(type(code) is int for code in codes) and all(
            x.get("completed") is True for x in output
        )
        if not observed:
            gaps.add("native_tool_exit_status_unavailable")
        success = (
            success is True and not failed and observed
            and all(x.get("success") is True for x in output) and all(code == 0 for code in codes)
        )
        aggregate = {"commands": output}
        if observed:
            aggregate["exitCode"] = next((code for code in codes if code != 0), 0)
        return aggregate, success
    # The SDK's batched file tools also report per-item failures inside a
    # successfully returned tool envelope. Preserve those as failed operations.
    items = output if isinstance(output, list) else [output]
    if any(isinstance(x, dict) and (x.get("success") is False or x.get("error")) for x in items):
        success = False
    if isinstance(output, dict) and "exit_code" in output and "exitCode" not in output:
        output = {**output, "exitCode": output["exit_code"]}
    return output, success


def normalize_event(payload, workspace):
    workspace = Path(workspace).resolve(strict=True)
    if not isinstance(payload, dict):
        raise EventRejected("event_must_be_object")
    hook_name = payload.get("hookName")
    name = EVENTS.get(hook_name) if isinstance(hook_name, str) else None
    if name is None:
        raise EventRejected("unsupported_cline_hook")
    payload = _bridge_payload(payload)
    sid = _identifier(payload.get("taskId"))
    session_context = payload.get("sessionContext", {})
    if not isinstance(session_context, dict):
        raise EventRejected("invalid_cline_session_context")
    root = session_context.get("rootSessionId")
    if root is not None:
        root = _identifier(root)
    roots = payload.get("workspaceRoots")
    if (
        not isinstance(roots, list)
        or len(roots) != 1
        or not isinstance(roots[0], str)
        or _path(roots[0]).resolve() != workspace
    ):
        raise EventRejected("workspace_mismatch")
    gaps = set()
    clean = sanitize(payload, gaps)
    event = {
        "hook_event_name": name,
        "conversation_id": root or sid,
        "native_conversation_id": sid,
        "workspace_roots": [str(workspace)],
        "client": "cline",
        "client_version": clean.get("clineVersion", ""),
        "native_hook_name": payload["hookName"],
        "native_payload": clean,
    }
    if payload.get("native_run_id") is not None:
        event["native_run_id"] = _identifier(payload["native_run_id"])
    if name in {"preToolUse", "postToolUse"}:
        record = payload.get("tool_call" if name == "preToolUse" else "tool_result")
        legacy = payload.get("preToolUse" if name == "preToolUse" else "postToolUse", {})
        if not isinstance(legacy, dict):
            raise EventRejected("invalid_tool_payload")
        if isinstance(record, dict):
            tool_id = _identifier(record.get("id"))
            agent = _identifier(payload.get("agent_id"))
            identity = [agent, tool_id]
            if root is not None:
                iteration = payload.get("iteration")
                if type(iteration) is not int or iteration < 0:
                    raise EventRejected("invalid_cline_iteration")
                # A new SDK execution can reuse conversation/agent/call_0 and
                # reset iteration. Only its native runId distinguishes that turn.
                native_run = _identifier(payload.get("native_run_id"))
                identity = [sid, agent, native_run, iteration, tool_id]
            event["tool_use_id"] = json.dumps(identity, separators=(",", ":"))
            tool_name = _identifier(record.get("name"))
            tool_input = record.get("input", {})
        else:
            # Do not match repeated calls using names, timing or input similarity.
            gaps.add("native_tool_id_unavailable")
            tool_name = _identifier(legacy.get("toolName"))
            tool_input = legacy.get("parameters", {})
        _scope(tool_input, workspace)
        event["native_tool_name"] = tool_name
        event["tool_name"] = "Shell" if tool_name in {"bash", "execute_command", "run_commands"} else tool_name
        event["tool_input"] = sanitize(tool_input, gaps)
        if name == "postToolUse":
            success = legacy.get("success")
            if type(success) is not bool:
                gaps.add("native_tool_outcome_unavailable")
            output = record.get("output") if isinstance(record, dict) else legacy.get("result")
            output, success = _outcome(tool_name, output, success, gaps)
            event["native_tool_success"] = success is True
            event["tool_output"] = sanitize(output, gaps)
            if success is not True or (isinstance(record, dict) and record.get("error")):
                event["hook_event_name"] = "postToolUseFailure"
                event["error"] = "Native tool reported failure or an unverified outcome"
    event["_vessel_capture_gaps"] = sorted(gaps)
    return event, sorted(gaps)


def main(argv=None):
    parser = argparse.ArgumentParser(description="VESSEL Cline observation hook")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)
    from vessel.service import Vessel

    service = None
    try:
        service = Vessel(args.state)
        service.status(args.workspace)
        event, gaps = normalize_event(parse(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)), args.workspace)
        with service.store.transaction() as conn:
            for gap in gaps:
                service._gap(gap, conn)
        service.observe(args.workspace, event, "cline_" + uuid.uuid4().hex)
        print("{}")  # Observations never instruct Cline to run, approve tools or transfer ownership.
        return 0
    except (ValueError, OSError, RecursionError, sqlite3.Error) as error:
        reason = str(error) if isinstance(error, EventRejected) else "cline_hook_unavailable"
        if service:
            try:
                service.observe(
                    args.workspace,
                    {"hook_event_name": "vesselCaptureGap", "reason": reason},
                    "cline_gap_" + uuid.uuid4().hex,
                )
            except (ValueError, OSError, sqlite3.Error):
                pass
        print("{}")
        print("VESSEL capture degraded: " + reason, file=sys.stderr)
        return 1
    finally:
        if service:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
