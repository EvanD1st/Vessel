"""Measure the installed command hook with synthetic 32 KiB input and real storage."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import time
import uuid
from pathlib import Path

from vessel.adapters import install
from vessel.cline import normalize_event
from vessel.maintenance import Maintenance
from vessel.service import Vessel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    args = parser.parse_args()
    if not 5 <= args.samples <= 100:
        parser.error("Use 5 to 100 samples")
    root = (
        Path(".demo-runs") / ("capture-" + time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
    ).resolve()
    workspace = root / "project with spaces"
    workspace.mkdir(parents=True)
    (workspace / "app.py").write_text("fixture = True\n")
    os.environ["VESSEL_REGISTRY_DIR"] = str(root / "registry")
    service = Vessel(root / "private state")
    try:
        service.enroll(workspace, "Measure fixture capture performance", required_paths=["app.py"])
        config = root / "cline_mcp_settings.json"
        config.write_text('{"mcpServers": {}}', encoding="utf-8")
        install("cline", workspace, service.store.dir, mcp_config=config)
        run = service.start(workspace, "synthetic-benchmark-session")
        hook = (
            workspace
            / ".clinerules/hooks"
            / ("TaskComplete.ps1" if os.name == "nt" else "TaskComplete")
        )
        command = ["powershell.exe", "-NoProfile", "-File", str(hook)] if os.name == "nt" else [str(hook)]
        latency = []
        for index in range(args.samples):
            service.heartbeat(run["id"], 1)
            event = {
                "taskId": run["native_session_id"],
                "hookName": "agent_end",
                "clineVersion": "synthetic-benchmark",
                "workspaceRoots": [str(workspace)],
                "text": "x" * 16384,
                "fixture_detail": "",
            }
            event["fixture_detail"] = "x" * (32768 - len(json.dumps(event).encode()))
            payload = json.dumps(event)
            assert len(payload.encode()) == 32768
            assert normalize_event(event, workspace)[1] == []
            started = time.perf_counter()
            completed = subprocess.run(
                command, input=payload.encode(), capture_output=True, cwd=workspace, timeout=20
            )
            latency.append((time.perf_counter() - started) * 1000)
            if completed.returncode or completed.stdout.strip() != b"{}":
                raise RuntimeError("Installed hook failed its fixture acknowledgment")
        pending = service.store.get("capture_requests", run["id"])
        assert pending["count"] == args.samples
        assert len(service.store.events(run_id=run["id"])) == args.samples
        service.stop(run["id"], attested=True, note="All fixture hook subprocesses joined; no native agent")
        time.sleep(max(0, pending["due_at"] - service.clock()))
        result = Maintenance(service).work_once()
        assert result["status"] == "captured" and result["eligible"]
        checkpoint = service.store.get("checkpoints", result["checkpoint_id"])
        p95 = sorted(latency)[math.ceil(0.95 * len(latency)) - 1]
        report = {
            "kind": "synthetic hook payload through installed command and OS shell",
            "native_cline_tested": False,
            "inference_requests": 0,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "storage_medium": "not independently identified",
            "samples": args.samples,
            "payload_bytes": 32768,
            "payload_shape": "two synthetic text fields below the per-field truncation bound",
            "durable_ack_p50_ms": statistics.median(latency),
            "durable_ack_p95_ms": p95,
            "target_p95_ms": 250,
            "target_met": p95 <= 250,
            "latency_scope": "shell and Python startup, validation, encryption, durable commit and process exit",
            "coalesced_requests": pending["count"],
            "automatic_checkpoints": len(service.store.list("checkpoints")),
            "checkpoint_seconds": checkpoint["capture_seconds"],
            "state_bytes": service.store.storage_bytes(),
            "individual_ack_ms": latency,
            "output_directory": str(root),
        }
        (root / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        service.close()


if __name__ == "__main__":
    main()
