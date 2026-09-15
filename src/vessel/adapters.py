"""Owner-controlled VS Code + Cline configuration; unrelated entries are preserved."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
from pathlib import Path

from vessel.locking import ArtifactLock
from vessel.storage import _atomic_write, _regular_file, safe_directory

HOOKS = (
    "TaskStart",
    "TaskResume",
    "TaskCancel",
    "TaskComplete",
    "TaskError",
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "SessionShutdown",
)
MANIFEST = "cline-install.json"


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate configuration key")
            result[key] = value
        return result

    try:
        value = json.loads(_regular_file(path, 1048576).decode("utf-8-sig"), object_pairs_hook=unique)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Invalid configuration JSON; original file preserved") from None
    if not isinstance(value, dict):
        raise ValueError("Configuration must be an object")
    return value


def _paths(client, workspace, state_dir):
    if client != "cline":
        raise ValueError("This release supports VS Code + Cline only")
    workspace = safe_directory(Path(workspace).expanduser())
    state_dir = safe_directory(Path(state_dir).expanduser())
    if state_dir.is_relative_to(workspace):
        raise ValueError("Keep adapter state outside the project")
    return workspace, state_dir


def _manifest(workspace, state_dir):
    path = state_dir / MANIFEST
    if not path.exists():
        return None
    result = _json(path)
    if result.get("workspace") != str(workspace) or result.get("schema") != 1:
        raise ValueError("Adapter manifest belongs to another project or version")
    return result


def _wrapper(python, state_dir, workspace):
    args = [python, "-m", "vessel.cline", "--state", str(state_dir), "--workspace", str(workspace)]
    if any(any(ord(ch) < 32 for ch in arg) for arg in args):
        raise ValueError("Hook paths contain control characters")
    if os.name == "nt":
        quoted = " ".join("'" + arg.replace("'", "''") + "'" for arg in args)
        return (
            "$ErrorActionPreference = 'Stop'\n"
            "$OutputEncoding = [Console]::OutputEncoding = [Console]::InputEncoding = "
            "[System.Text.UTF8Encoding]::new($false)\n"
            "[Console]::In.ReadToEnd() | & " + quoted + "\nexit $LASTEXITCODE\n"
        ).encode("utf-8-sig")  # Windows PowerShell 5 reads non-BOM scripts as ANSI.
    return ("#!/bin/sh\nexec " + shlex.join(args) + "\n").encode("utf-8")


def _lock(config):
    safe_directory(config.parent)
    lock = ArtifactLock(config.parent)
    lock.path = config.parent / ".vessel-mcp.lock"
    return lock


def install(client, workspace, state_dir, python_executable=sys.executable, *, mcp_config=None):
    workspace, state_dir = _paths(client, workspace, state_dir)
    existing = _manifest(workspace, state_dir)
    if existing:
        if mcp_config and Path(mcp_config).absolute() != Path(existing["mcp_path"]):
            raise ValueError("Uninstall the adapter before changing MCP configuration scope")
        result = inspect(client, workspace, state_dir)
        if not result["installed"]:
            raise ValueError("Installed files changed; review them before reinstalling")
        return result
    if mcp_config is None:
        raise ValueError("Pass --mcp-config with the file opened by Cline > MCP Servers > Configure")
    config = Path(os.path.abspath(mcp_config))
    safe_directory(config.parent)
    data = _json(config)  # Explicit existing file; never create a guessed VS Code profile.
    if not isinstance(data.get("mcpServers", {}), dict):
        raise ValueError("mcpServers must be an object; original file preserved")
    python = str(Path(python_executable).resolve(strict=True))
    name = "vessel-" + hashlib.sha256(str(workspace).casefold().encode()).hexdigest()[:12]
    if name in data.get("mcpServers", {}):
        raise ValueError("MCP server name conflict; existing server preserved")
    entry = {
        "command": python,
        "args": ["-m", "vessel.mcp_server", "--state", str(state_dir), "--workspace", str(workspace)],
        "disabled": False,
        "autoApprove": [],
    }
    hooks_dir = safe_directory(workspace / ".clinerules" / "hooks", create=True)
    extension = ".ps1" if os.name == "nt" else ""
    wrapper = _wrapper(python, state_dir, workspace)
    paths = [hooks_dir / (hook + extension) for hook in HOOKS]
    names = {hook.casefold() for hook in HOOKS}
    for directory in (hooks_dir, workspace / ".cline" / "hooks"):
        if directory.exists():
            safe_directory(directory)
            if any(p.stem.casefold() in names for p in directory.iterdir()):
                raise ValueError("Existing Cline hook conflicts; review a combined hook before installation")
    with _lock(config).hold():
        if _json(config) != data:
            raise ValueError("MCP configuration changed during installation; retry")
        created = []
        original = _regular_file(config, 1048576)
        changed = False
        try:
            for path in paths:
                _atomic_write(path, wrapper, exclusive=True)
                path.chmod(0o700)
                created.append(path)
            data.setdefault("mcpServers", {})[name] = entry
            _atomic_write(config, json.dumps(data, indent=2).encode("utf-8"))
            changed = True
            manifest = {
                "schema": 1,
                "workspace": str(workspace),
                "mcp_path": str(config),
                "server_name": name,
                "entry": entry,
                "native_verified": False,
                "hooks": {str(p.relative_to(workspace)): hashlib.sha256(wrapper).hexdigest() for p in paths},
            }
            _atomic_write(state_dir / MANIFEST, json.dumps(manifest, indent=2).encode(), exclusive=True)
        except Exception:
            if changed and _json(config) == data:
                _atomic_write(config, original)
            for path in created:
                if path.is_file() and path.read_bytes() == wrapper:
                    path.unlink()
            raise
    return inspect(client, workspace, state_dir)


def inspect(client, workspace, state_dir):
    workspace, state_dir = _paths(client, workspace, state_dir)
    manifest = _manifest(workspace, state_dir)
    if not manifest:
        return {
            "client": "cline",
            "installed": False,
            "mcp_configured": False,
            "configuration_health": "missing",
            "native_capture": "unverified",
        }
    config = Path(manifest["mcp_path"])
    safe_directory(config.parent)
    data = _json(config)
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers must be an object; original file preserved")
    mcp_ok = servers.get(manifest["server_name"]) == manifest["entry"]
    missing = []
    for relative, expected in manifest["hooks"].items():
        path = workspace / relative
        if not path.resolve().is_relative_to(workspace):
            raise ValueError("Hook scope changed")
        try:
            safe_directory(path.parent)
            valid = hashlib.sha256(_regular_file(path, 16384)).hexdigest() == expected
        except (OSError, ValueError):
            valid = False
        if not valid:
            missing.append(relative)
    good = mcp_ok and not missing
    return {
        "client": "cline",
        "installed": good,
        "mcp_configured": mcp_ok,
        "configuration_health": "configured" if good else "degraded",
        "missing_hooks": missing,
        "native_capture": "unverified",
        "server_name": manifest["server_name"],
        "mcp_path": str(config),
        "hook_failure_behavior": "observation_only",
    }


def uninstall(client, workspace, state_dir):
    workspace, state_dir = _paths(client, workspace, state_dir)
    manifest = _manifest(workspace, state_dir)
    if not manifest:
        return {"uninstalled": False, "reason": "No owned installation"}
    if not inspect(client, workspace, state_dir)["installed"]:
        raise ValueError("Installed configuration changed; refusing to remove edited files")
    config = Path(manifest["mcp_path"])
    with _lock(config).hold():
        data = _json(config)
        if data.get("mcpServers", {}).get(manifest["server_name"]) != manifest["entry"]:
            raise ValueError("MCP server changed; original preserved")
        del data["mcpServers"][manifest["server_name"]]
        _atomic_write(config, json.dumps(data, indent=2).encode())
        for relative, expected in manifest["hooks"].items():
            path = workspace / relative
            if not path.resolve().is_relative_to(workspace):
                raise ValueError("Hook scope changed")
            if hashlib.sha256(_regular_file(path, 16384)).hexdigest() != expected:
                raise ValueError("Hook changed during removal")
            path.unlink()
        (state_dir / MANIFEST).unlink()
    return {"client": "cline", "uninstalled": True}
