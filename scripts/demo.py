"""Local fixture drill: real FastAPI tests, synthetic ledger events, no LLM request."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import uuid
from pathlib import Path

from vessel.adapters import install, uninstall
from vessel.service import Vessel
from vessel.storage import Store

INITIAL_APP = """from fastapi import FastAPI
app = FastAPI(title="VESSEL continuity fixture")

@app.get("/health")
def health():
    return {"status": "ok"}
"""
INITIAL_TEST = """import asyncio
import httpx
from app import app

def get(path):
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://fixture") as client:
            return await client.get(path)
    return asyncio.run(request())

def test_health():
    assert get("/health").json() == {"status": "ok"}
"""
CONTINUATION = """
@app.get("/greeting/{name}")
def greeting(name: str):
    return {"message": f"Hello, {name}"}
"""
CONTINUATION_TEST = """
def test_greeting():
    assert get("/greeting/Ada").json() == {"message": "Hello, Ada"}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".demo-runs"))
    args = parser.parse_args()
    root = (args.output / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])).resolve()
    workspace = root / "FastAPI project"
    workspace.mkdir(parents=True)
    os.environ["VESSEL_REGISTRY_DIR"] = str(root / "enrollment-registry")
    (workspace / "app.py").write_text(INITIAL_APP)
    (workspace / "test_app.py").write_text(INITIAL_TEST)
    service = Vessel(root / "private-state")
    latencies = []

    def event(session, name, **payload):
        start = time.perf_counter()
        result = service.observe(
            workspace,
            {
                "conversation_id": session,
                "generation_id": "fixture-generation",
                "hook_event_name": name,
                "client_version": "fixture-not-native",
                "workspace_roots": [str(workspace)],
                **payload,
            },
            "fixture_" + uuid.uuid4().hex,
        )
        latencies.append((time.perf_counter() - start) * 1000)
        return result

    def run_tests(session, native_id):
        fields = {
            "tool_use_id": native_id,
            "tool_name": "Shell",
            "tool_input": {"command": "python -m pytest -q", "working_directory": str(workspace)},
        }
        event(session, "preToolUse", **fields)
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        event(
            session,
            "postToolUse",
            **fields,
            tool_output=json.dumps(
                {"exitCode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr}
            ),
        )
        if completed.returncode:
            raise RuntimeError("Fixture FastAPI tests failed: " + completed.stdout + completed.stderr)
        run_id = service.store.get("sessions", session)["run_id"]
        op = next(op for op in service.operations(run_id) if op["native_id"] == native_id)
        return op, completed.stdout.strip()

    try:
        enrollment = service.enroll(
            workspace,
            "Keep the health endpoint working and implement a greeting endpoint",
            required_paths=["app.py", "test_app.py"],
        )
        config = root / "cline_mcp_settings.json"
        config.write_text('{"mcpServers": {}}', encoding="utf-8")
        installation = install("cline", workspace, service.store.dir, mcp_config=config)
        first = service.start(workspace, "fixture-source")
        event("fixture-source", "beforeSubmitPrompt", prompt="Implement health, then greeting")
        first_op, initial_tests = run_tests("fixture-source", "initial-tests")
        service.task(first["id"], "health", "Health endpoint", status="done", evidence=first_op["id"])
        service.task(first["id"], "greeting", "Add /greeting/{name} and verify its response")
        for index in range(30):
            event("fixture-source", "afterAgentResponse", text=f"Fixture observation {index}")
        service.stop(first["id"], attested=True, note="Demo subprocess joined; synthetic writer paused")
        cp = service.checkpoint(first["id"])
        if not service.validate_checkpoint(cp["id"])["eligible"]:
            raise RuntimeError("Fixture checkpoint did not pass integrity/capture checks")
        service.backup(root / "backup")
        restart_at = time.perf_counter()
        service.close()
        service = Vessel(root / "private-state")
        restart_seconds = time.perf_counter() - restart_at
        service.review_environment(
            "FastAPI fixture tests pass; no external services, secrets or database", "fixture-model", 24000
        )
        recovery_at = time.perf_counter()
        review = service.prepare_recovery(
            cp["id"], "fixture-destination", "demo-handover", context_budget=24000
        )
        if review["status"] != "awaiting_owner":
            raise RuntimeError("Fixture preflight blocked: " + json.dumps(review["preflight"]["blockers"]))
        handover = service.handover(review["id"], review["review_token"])
        context = service.recovery_context(handover["id"])
        assert context["tasks"][0] or context["tasks"][1]
        with (workspace / "app.py").open("a") as target:
            target.write(CONTINUATION)
        with (workspace / "test_app.py").open("a") as target:
            target.write(CONTINUATION_TEST)
        event("fixture-destination", "afterFileEdit", file_path=str(workspace / "app.py"))
        continued_op, continued_tests = run_tests("fixture-destination", "continued-tests")
        result = service.confirm_continuation(
            handover["id"],
            continued_op["id"],
            "Fixture driver inspected the pending task and added greeting; both endpoint tests now pass",
        )
        recovery_seconds = time.perf_counter() - recovery_at
        restored = Store.restore_local(root / "backup", root / "restored-history")
        restored.close()
        restored_service = Vessel(root / "restored-history")
        try:
            restored_valid = restored_service.validate_checkpoint(cp["id"])["eligible"]
            restored_read_only = restored_service.status()["restored_inspection_only"]
        finally:
            restored_service.close()
        sorted_latency = sorted(latencies)
        report = {
            "kind": "automated local fixture drill",
            "native_cline_tested": False,
            "inference_requests": 0,
            "wallet_verified": False,
            "enrollment_id": enrollment["id"],
            "checkpoint_id": cp["id"],
            "source_epoch": 1,
            "destination_epoch": handover["destination_epoch"],
            "recovery_id": result["id"],
            "recovery_status": result["status"],
            "checkpoint_seconds": cp["capture_seconds"],
            "restart_seconds": restart_seconds,
            "continuation_seconds": recovery_seconds,
            "event_samples": len(latencies),
            "in_process_ack_p50_ms": statistics.median(latencies),
            "in_process_ack_p95_ms": sorted_latency[int(0.95 * (len(sorted_latency) - 1))],
            "latency_scope": "in-process durable event acknowledgments; excludes native hook process startup",
            "state_bytes": service.store.storage_bytes(),
            "initial_tests": initial_tests,
            "continuation_tests": continued_tests,
            "backup_restore_verified": restored_valid,
            "restored_history_inspection_only": restored_read_only,
            "configuration_installed": installation["installed"],
            "output_directory": str(root),
        }
        uninstall("cline", workspace, service.store.dir)
        (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        service.close()


if __name__ == "__main__":
    main()
