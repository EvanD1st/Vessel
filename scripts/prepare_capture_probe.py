"""Prepare a separate native hook probe; no MCP or inference configuration changes."""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from vessel.adapters import HOOKS, _wrapper
from vessel.service import Vessel
from vessel.storage import _atomic_write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1] / ".cline-capture-check")
    root = parser.parse_args().root.resolve()
    workspace = root / "project"
    state = root / "private-state"
    if workspace.exists():
        raise ValueError("Probe already exists; inspect its evidence rather than resetting it")
    workspace.mkdir(parents=True)
    (workspace / "probe.py").write_text("print('VESSEL_TOOL_PROBE')\n", encoding="utf-8")
    (workspace / "README.md").write_text(
        "# VESSEL native capture probe\n\n"
        "This folder tests Cline hook capture only. No MCP server is needed.\n"
        "Follow the owner's probe prompt; do not edit files or install dependencies.\n"
        f"Python: `{sys.executable}`. Run `probe.py` with this interpreter when asked.\n",
        encoding="utf-8",
    )
    with_service = Vessel(state)
    try:
        enrollment = with_service.enroll(
            workspace, "Verify native Cline task identity and command capture",
            restrictions=["Read-only probe; no code edits, external services or dependency installation"],
            required_paths=["probe.py"],
        )
    finally:
        with_service.close()
    directory = workspace / ".clinerules" / "hooks"
    directory.mkdir(parents=True)
    wrapper = _wrapper(sys.executable, state, workspace)
    for name in HOOKS:
        path = directory / (name + (".ps1" if os.name == "nt" else ""))
        _atomic_write(path, wrapper, exclusive=True)
        path.chmod(0o700)
    report = {
        "workspace": str(workspace), "state": str(state), "enrollment_id": enrollment["id"],
        "purpose": "native_hooks_only", "mcp_installed": False, "events_injected": 0,
        "hook_sha256": hashlib.sha256(wrapper).hexdigest(),
    }
    (root / "setup.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
