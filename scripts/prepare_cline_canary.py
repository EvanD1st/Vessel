"""Prepare an isolated VS Code + Cline recovery test without simulating native events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from vessel.adapters import inspect, install
from vessel.service import Vessel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / ".cline-canary")
    parser.add_argument("--mcp-config", type=Path, help="Existing file opened by Cline MCP Configure")
    args = parser.parse_args()
    root = args.root.resolve()
    workspace = root / "authentication-task"
    existing = workspace.exists()
    workspace.mkdir(parents=True, exist_ok=True)
    if not existing:
        (workspace / "app.py").write_text(
            'from fastapi import FastAPI\n\napp = FastAPI(title="VESSEL native canary")\n'
        )
        (workspace / "README.md").write_text(
            "# VESSEL native recovery canary\n\n"
            "This is disposable local test data. No real users, messages, deployments or external services.\n"
            "Mission: implement registration, login and password reset in the existing FastAPI app.\n"
            "First conversation: implement registration/login and tests. Leave password reset pending.\n"
            "Use an in-memory demo user store and standard password hashing. Keep all changes here.\n"
            "Fresh conversation: deliberately retrieve the selected VESSEL handover, inspect existing files, "
            "then implement password reset and run all tests.\n\n"
            f"The available Python interpreter is `{sys.executable}`. FastAPI, pytest and httpx are installed.\n"
            "Do not install dependencies or run a server in the background.\n",
            encoding="utf-8",
        )
    service = Vessel(root / "private-state")
    try:
        if existing:
            enrollment = service.status(workspace)["enrollment"]
        else:
            enrollment = service.enroll(
                workspace,
                "Implement registration, login and password reset in the local FastAPI canary",
                restrictions=["No deployment, messages, external services or real user data"],
                required_paths=["app.py"],
            )
        result = inspect("cline", workspace, service.store.dir)
        if not result["installed"]:
            result["next_step"] = "Open Cline MCP Configure, then rerun with --mcp-config"
        if args.mcp_config:
            service._writable()
            result = install("cline", workspace, service.store.dir, mcp_config=args.mcp_config)
            service.store.put("control", "cline_adapter", {"installed": True, "native_verified": False})
        report = {
            "workspace": str(workspace),
            "state": str(service.store.dir),
            "enrollment_id": enrollment["id"],
            "configuration": result,
            "native_status": "awaiting_native_canary",
        }
        (root / "setup.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        service.close()


if __name__ == "__main__":
    main()
