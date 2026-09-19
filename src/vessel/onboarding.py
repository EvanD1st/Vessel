"""Local owner setup wizard. No provider credentials or automatic native task binding."""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from vessel import adapters, registry
from vessel.dashboard import approved_origin
from vessel.service import Vessel, canonical
from vessel.storage import Store, safe_directory

PROFILE = "desktop_setup"


def local_path(value):
    value = str(value).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if not value or any(ord(ch) < 32 for ch in value):
        raise ValueError("Enter a full path without control characters")
    return Path(os.path.abspath(os.path.expandvars(os.path.expanduser(value))))


def state_for(workspace, state=None):
    registered = registry.lookup(canonical(workspace))
    if state is not None:
        chosen = local_path(state)
        if registered and os.path.normcase(str(chosen)) != os.path.normcase(str(registered)):
            raise ValueError(f"This project is already enrolled. Use its existing state: {registered}")
    elif registered:
        chosen = registered
    else:
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
        tag = hashlib.sha256(canonical(workspace).encode()).hexdigest()[:16]
        chosen = base / "VESSEL" / "projects" / tag
    if chosen.is_relative_to(workspace) or workspace.is_relative_to(chosen):
        raise ValueError("Keep private VESSEL state separate from the project folder")
    existing_parent = chosen
    while not existing_parent.exists():
        existing_parent = existing_parent.parent
    safe_directory(existing_parent)
    if registered and not (chosen / "vessel.sqlite3").is_file():
        raise ValueError("The registered authority is missing. Restore or inspect it before setting up again")
    return chosen


def existing_setup(state):
    if not (state / "vessel.sqlite3").exists():
        return None, None, None
    store = Store(state)
    try:
        if store.get("control", "restored"):
            raise ValueError("Restored state is inspection-only; it cannot be used for guided setup")
        return (
            store.get("control", "enrollment"),
            store.get("control", "policy"),
            store.get("control", PROFILE),
        )
    finally:
        store.close()


def validate_profile(profile, state):
    if not isinstance(profile, dict) or profile.get("schema") != 1:
        raise ValueError("Run vessel setup to save a companion launch profile")
    workspace = safe_directory(local_path(profile["workspace"]))
    if state.is_relative_to(workspace) or workspace.is_relative_to(state):
        raise ValueError("Private state must be separate from the project")
    approved_origin(profile["origin"])
    if type(profile.get("port")) is not int or not 1024 <= profile["port"] <= 65535:
        raise ValueError("Companion port must be between 1024 and 65535")
    if type(profile.get("ttl")) is not int or not 60 <= profile["ttl"] <= 28800:
        raise ValueError("Access session lifetime must be between 60 and 28800 seconds")
    interpreter = local_path(profile["python"])
    if not interpreter.is_file():
        raise ValueError("The saved Python interpreter moved. Rerun setup with a working VESSEL installation")
    return profile


def load_profile(state):
    state = safe_directory(local_path(state))
    enrollment, _, profile = existing_setup(state)
    validate_profile(profile, state)
    if not enrollment or enrollment["canonical_workspace"] != canonical(profile["workspace"]):
        raise ValueError("Saved launch profile does not match this enrollment")
    return profile


def prepare(workspace, *, state=None, mission=None, mcp_config=None, origin=None, port=None, ttl=None):
    workspace = safe_directory(local_path(workspace))
    state = state_for(workspace, state)
    enrollment, policy, previous = existing_setup(state)
    previous = previous or {}
    if enrollment and enrollment["canonical_workspace"] != canonical(workspace):
        raise ValueError("This state already belongs to another project")
    if policy:
        if mission is not None and mission != policy["mission"]:
            raise ValueError("Setup preserves the existing mission; use owner policy commands to change it")
        mission = policy["mission"]
    if not isinstance(mission, str) or not mission.strip() or len(mission.encode()) > 65536:
        raise ValueError("Provide a mission describing the work you want Cline to complete")
    manifest = adapters._manifest(workspace, state) if state.exists() else None
    config = local_path(mcp_config or (manifest or {}).get("mcp_path") or previous.get("mcp_config", ""))
    safe_directory(config.parent)
    if config.is_relative_to(workspace):
        raise ValueError("Use the active settings file opened by Cline MCP Configure, outside this project")
    data = adapters._json(config)
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("Cline mcpServers must be an object; settings were preserved")
    if manifest:
        if config != Path(manifest["mcp_path"]):
            raise ValueError("Uninstall the owned adapter before changing its MCP settings file")
        if not adapters.inspect("cline", workspace, state)["installed"]:
            raise ValueError("Existing adapter files changed; inspect them before rerunning setup")
    else:
        name = "vessel-" + hashlib.sha256(str(workspace).casefold().encode()).hexdigest()[:12]
        if name in servers:
            raise ValueError("Cline MCP server name conflict; existing entry was preserved")
        for directory in (workspace / ".clinerules" / "hooks", workspace / ".cline" / "hooks"):
            parent = directory if directory.exists() else directory.parent
            if parent.exists():
                safe_directory(parent)
            if directory.exists() and any(
                p.stem.casefold() in {h.casefold() for h in adapters.HOOKS} for p in directory.iterdir()
            ):
                raise ValueError("Existing Cline hooks conflict; review them before setup")
    profile = {
        "schema": 1,
        "workspace": str(workspace),
        "mcp_config": str(config),
        "origin": approved_origin(origin or previous.get("origin", "http://localhost:3000")),
        "port": port if port is not None else previous.get("port", 8765),
        "ttl": ttl if ttl is not None else previous.get("ttl", 3600),
        "python": str(Path(sys.executable).resolve(strict=True)),
    }
    validate_profile(profile, state)
    return {
        "state": str(state),
        "mission": mission,
        "existing_enrollment": bool(enrollment),
        "profile": profile,
        "other_enabled_servers": [
            name
            for name, entry in servers.items()
            if isinstance(entry, dict)
            and not entry.get("disabled", False)
            and name != (manifest or {}).get("server_name")
        ],
    }


def apply(plan):
    # Revalidate after the interactive review; do not trust stale settings.
    p = plan["profile"]
    plan = prepare(
        p["workspace"],
        state=plan["state"],
        mission=plan["mission"],
        mcp_config=p["mcp_config"],
        origin=p["origin"],
        port=p["port"],
        ttl=p["ttl"],
    )
    p = plan["profile"]
    service = Vessel(plan["state"])
    try:
        enrollment = service.enroll(p["workspace"], plan["mission"])
        configured = adapters.install(
            "cline",
            Path(p["workspace"]),
            service.store.dir,
            python_executable=p["python"],
            mcp_config=p["mcp_config"],
        )
        if not service.store.get("control", "cline_adapter"):
            service.store.put("control", "cline_adapter", {"installed": True, "native_verified": False})
        service.store.put("control", PROFILE, p)
        return {
            **plan,
            "enrollment_id": enrollment["id"],
            "configuration": configured,
            "next_steps": [
                "Open this project in VS Code. Enable Cline hooks and reload the window while Cline is idle.",
                "Check the listed VESSEL MCP server. Keep only the intended project's VESSEL server enabled.",
                "Configure your inference provider and key in Cline; VESSEL setup does not read that key.",
                "Cline 4.1.17 or later is required; the compatibility patch is applied automatically on setup.",
                "Send a fresh READY-only probe, inspect sessions, then bind the exact observed native task ID.",
                "Use vessel launch with this state to connect the dashboard, then start capture for the bound run.",
            ],
        }
    finally:
        service.close()


def wizard(args, *, input_fn=input, emit=print, interactive=None):
    interactive = sys.stdin.isatty() if interactive is None else interactive
    if not args.yes and not interactive:
        raise ValueError(
            "Use an interactive terminal, or pass --yes with --workspace, --mission and --mcp-config"
        )

    def ask(label, default=None):
        value = input_fn(label + (f" [{default}]" if default is not None else "") + ": ").strip()
        return value or default

    workspace = args.workspace
    if not workspace and not args.yes:
        workspace = ask("Project folder (open this same folder in VS Code)")
    if not workspace:
        raise ValueError("--workspace is required for unattended setup")
    workspace = safe_directory(local_path(workspace))
    state = state_for(workspace, args.state)
    enrollment, policy, old = existing_setup(state)
    mission = args.mission or (policy or {}).get("mission")
    if not mission and not args.yes:
        mission = ask("What should Cline accomplish in this project?")
    manifest = adapters._manifest(workspace, state) if state.exists() else None
    config = args.mcp_config or (manifest or {}).get("mcp_path")
    if not config and not args.yes:
        emit("In Cline, open MCP Servers > Configure MCP Servers and copy that file's full path.")
        config = ask("Active Cline MCP settings file")
    old = old or {}
    origin, port = args.origin, args.port
    if not args.yes:
        origin = origin or ask("Dashboard address", old.get("origin", "http://localhost:3000"))
        port = port if port is not None else int(ask("Companion port", old.get("port", 8765)))
    plan = prepare(
        workspace, state=state, mission=mission, mcp_config=config, origin=origin, port=port, ttl=args.ttl
    )
    startup, launch = args.startup, args.launch
    if not args.yes:
        if os.name == "nt" and not startup:
            startup = ask("Start the companion when you sign in to Windows? y/n", "n").lower() == "y"
        if not launch:
            launch = ask("Start the companion now? y/n", "y").lower() == "y"
        emit(
            f"Project: {workspace}\nPrivate state: {state}\nMission: {plan['mission']}\n"
            f"Cline settings: {plan['profile']['mcp_config']}\n"
            f"Dashboard: {plan['profile']['origin']} | Companion port: {plan['profile']['port']}\n"
            f"Windows startup: {'enable' if startup else 'unchanged'}"
        )
        if ask("Apply this setup? y/n", "y").lower() != "y":
            return {"status": "cancelled", "changes_applied": False}
    if startup:
        from vessel.startup import command_for

        command_for(state, plan["profile"])  # Check platform/path constraints before enrollment.
    result = apply(plan)
    if startup:
        from vessel.startup import configure

        result["startup"] = configure(state, "enable")
    if launch:
        from vessel.desktop import launch as start_companion

        result["companion"] = start_companion(state)
    return result
