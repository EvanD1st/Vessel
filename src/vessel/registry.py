"""One canonical enrollment authority per workspace for the current OS user."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from vessel.storage import _atomic_write, _regular_file, safe_directory


def registry_dir():
    return Path(
        os.environ.get(
            "VESSEL_REGISTRY_DIR",
            str(
                Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
                / "VESSEL"
                / "registry"
            ),
        )
    )


def lookup(workspace: str):
    """Find the original authority without creating a new registry or enrollment."""
    base = registry_dir()
    if not base.exists():
        return None
    safe_directory(base)
    entry = base / (hashlib.sha256(workspace.encode()).hexdigest() + ".json")
    if not entry.exists():
        return None
    existing = json.loads(_regular_file(entry, 16384))
    if not isinstance(existing, dict) or existing.get("workspace") != workspace:
        raise ValueError("Workspace registry entry changed; inspect its original authority")
    state = existing.get("state")
    if not isinstance(state, str) or not Path(state).is_absolute():
        raise ValueError("Workspace registry has an invalid state path")
    return Path(state)


def register(workspace: str, state_dir: Path):
    base = safe_directory(registry_dir(), create=True)
    entry = base / (hashlib.sha256(workspace.encode()).hexdigest() + ".json")
    expected = {"workspace": workspace, "state": os.path.normcase(str(state_dir.resolve()))}
    _atomic_write(entry, json.dumps(expected, sort_keys=True).encode(), exclusive=True)
    existing = json.loads(_regular_file(entry, 16384))
    if existing != expected:
        raise ValueError(
            "This canonical workspace is already enrolled under another state directory. "
            "Use its original authority; a second independent lease is forbidden."
        )
