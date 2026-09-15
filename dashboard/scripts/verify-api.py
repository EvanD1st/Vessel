"""Compatibility entry point: verify real invite-only accounts on localhost.

Disposable account fixtures also exercise connection isolation and label limits.
No fixed credentials or provider requests are used.
"""
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
node = shutil.which("node")
if not node:
    raise SystemExit("Install Node.js 22.13+ first.")
raise SystemExit(subprocess.call([node, "scripts/verify-accounts.mjs"], cwd=root))
