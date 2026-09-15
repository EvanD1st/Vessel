"""Prepare an isolated synthetic enrollment for real browser/bridge verification.

Does not install editor hooks, simulate native evidence, or alter existing enrollments.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from vessel.service import Vessel


def main():
    root = Path(__file__).resolve().parents[1] / ".demo-runs" / ("browser-" + uuid.uuid4().hex[:12])
    workspace = root / "project"
    workspace.mkdir(parents=True)
    (workspace / "app.py").write_text('mission = "Verify browser owner actions"\n')
    service = Vessel(root / "private-state")
    try:
        enrollment = service.enroll(
            workspace,
            "Synthetic browser canary: verify local owner actions",
            restrictions=["Disposable local fixture; no inference, deployment or real user data"],
            required_paths=["app.py"],
        )
        report = {
            "workspace": str(workspace),
            "state": str(service.store.dir),
            "enrollment_id": enrollment["id"],
            "native_events": False,
            "status": "awaiting_browser_verification",
        }
        (root / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
    finally:
        service.close()


if __name__ == "__main__":
    main()
