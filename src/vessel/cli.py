"""Owner-operated commands. Never expose this interface as an MCP tool."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from vessel import __version__
from vessel.devices import list_devices
from vessel.devices import revoke as revoke_device
from vessel.service import Vessel


def default_state() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "VESSEL" / "default"


def build_parser():
    parser = argparse.ArgumentParser(description="VESSEL local continuity and reviewed recovery")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--state", type=Path, help="Private state outside the project; guided setup reuses its original state"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup", help="Guide project enrollment, Cline configuration and companion setup")
    p.add_argument("--workspace", type=Path)
    p.add_argument("--mission")
    p.add_argument("--mcp-config", type=Path, help="Existing file opened by Cline MCP Configure")
    p.add_argument("--origin", help="Dashboard origin; defaults to http://localhost:3000")
    p.add_argument("--port", type=int)
    p.add_argument("--ttl", type=int)
    p.add_argument("--startup", action="store_true", help="Opt in to current-user Windows sign-in startup")
    p.add_argument("--launch", action="store_true", help="Start the companion in the background after setup")
    p.add_argument("--yes", action="store_true", help="Use supplied values without interactive prompts")
    for name, help_text in {
        "launch": "Start the saved companion in the background, without another setup",
        "companion-status": "Inspect the managed companion process and its log location",
        "stop-companion": "Request shutdown of this state's managed companion",
        "connection": "Show the running managed companion's private pairing link",
        "doctor": "Check saved setup, Cline configuration and observed capture health",
    }.items():
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--workspace", type=Path, help="Use this project's registered private state")
    p = sub.add_parser("startup", help="Manage optional current-user Windows sign-in startup")
    p.add_argument("action", choices=["enable", "disable", "status"])
    p.add_argument("--workspace", type=Path, help="Use this project's registered private state")
    p = sub.add_parser(
        "dashboard", help="Serve an enrolled project to an explicitly approved dashboard origin"
    )
    p.add_argument(
        "--origin", required=True, help="Exact HTTPS dashboard origin, or localhost development origin"
    )
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--ttl", type=int, default=3600, help="Connection lifetime in seconds (60â€“28800)")
    p = sub.add_parser("enroll", help="Enroll one project and approve its mission")
    p.add_argument("workspace", type=Path)
    p.add_argument("--mission", required=True)
    p.add_argument("--restriction", action="append")
    p.add_argument("--required", action="append", default=[])
    p = sub.add_parser("status", help="Show capture, checkpoint, session and recovery evidence")
    p.add_argument("--workspace", type=Path)
    sub.add_parser("sessions", help="List observed native conversation IDs for explicit owner binding")
    p = sub.add_parser("start", help="Bind the first protected task to an explicit native conversation")
    p.add_argument("workspace", type=Path)
    p.add_argument("--session", required=True)
    p = sub.add_parser("heartbeat", help="Keep current execution lease alive (5-second interval)")
    p.add_argument("--run", required=True)
    p.add_argument("--epoch", required=True, type=int)
    p.add_argument("--once", action="store_true")
    p.add_argument("--revalidate-policy", action="store_true")
    p = sub.add_parser("companion", help="Run fixed-epoch heartbeat, background captures and retention")
    p.add_argument("--run", required=True)
    p.add_argument("--epoch", required=True, type=int)
    sub.add_parser("work-once", help="Process one due durable automatic capture request")
    p = sub.add_parser("retry-capture", help="Retry a blocked capture after owner repair")
    p.add_argument("--run", required=True)
    p = sub.add_parser(
        "cleanup", help="Preview retention; add --apply to prune unpinned checkpoints and orphan blobs"
    )
    p.add_argument("--apply", action="store_true")
    p.add_argument("--quota-pressure", action="store_true")
    p = sub.add_parser("pin", help="Pin a checkpoint against ordinary or quota retention")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("unpin", help="Remove only an owner-created checkpoint pin")
    p.add_argument("--checkpoint", required=True)
    p = sub.add_parser("stop", help="Record native shutdown evidence and pause managed admission")
    p.add_argument("--run", required=True)
    p.add_argument("--attest-stopped", action="store_true", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("dismiss-session", help="Attest that an unrelated native task was stopped")
    p.add_argument("--session", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("task", help="Owner-assigned task ledger update")
    p.add_argument("--run", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--status", default="pending", choices=["pending", "active", "blocked", "done"])
    p.add_argument("--evidence", help="Observed successful operation ID for completed tasks")
    p.add_argument(
        "--depends-on", action="append", help="Existing task ID required before this task can start"
    )
    sub.add_parser("proposals", help="List unattributed agent proposals for owner review")
    p = sub.add_parser(
        "review-proposal", help="Accept or reject an exact proposal under current owner policy"
    )
    p.add_argument("--proposal", required=True)
    p.add_argument("--decision", required=True, choices=["accept", "reject"])
    p.add_argument("--note", required=True)
    p.add_argument("--policy-revision", required=True, type=int)
    p.add_argument("--run")
    p.add_argument("--task-id")
    p.add_argument("--evidence")
    p.add_argument("--depends-on", action="append")
    p = sub.add_parser("finish-run", help="Close a stopped run with reviewed completion or cancellation")
    p.add_argument("--run", required=True)
    p.add_argument("--outcome", required=True, choices=["completed", "cancelled"])
    p.add_argument("--note", required=True)
    p.add_argument("--evidence")
    p = sub.add_parser("cancel-recovery", help="Cancel a recovery before ownership transfers")
    p.add_argument("--recovery", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("operations", help="Inspect tool receipts and uncertain outcomes")
    p.add_argument("--run", required=True)
    p = sub.add_parser("resolve", help="Record owner reconciliation of an uncertain operation")
    p.add_argument("--operation", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("repair-capture", help="Record owner review of a repaired capture gap")
    p.add_argument("--note", required=True)
    p = sub.add_parser("checkpoint", help="Capture paused writer state and encrypted artifacts")
    p.add_argument("--run", required=True)
    p = sub.add_parser("verify", help="Check checkpoint integrity and continuation eligibility")
    p.add_argument("--checkpoint", required=True)
    p = sub.add_parser("context", help="Read an explicitly selected run")
    p.add_argument("--run", required=True)
    p = sub.add_parser("recover", help="Prepare a concrete recovery plan for owner review")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--request", required=True, help="Stable owner-chosen idempotency key")
    p.add_argument(
        "--context-bytes",
        type=int,
        required=True,
        help="Owner-verified essential input budget after model/client/tool/output reserve",
    )
    p = sub.add_parser("handover", help="Apply a reviewed plan, rechecking policy and ownership")
    p.add_argument("--recovery", required=True)
    p.add_argument("--review-token", required=True)
    p = sub.add_parser("finish-handover", help="Retry a durable pending local credential revocation")
    p.add_argument("--recovery", required=True)
    p = sub.add_parser("repair-handover", help="Review current policy after an interrupted handover")
    p.add_argument("--recovery", required=True)
    p.add_argument("--policy-revision", required=True, type=int)
    p.add_argument("--note", required=True)
    p = sub.add_parser("recovery-context", help="Serve the selected handover; does not prove continuation")
    p.add_argument("--recovery", required=True)
    p = sub.add_parser("confirm", help="Owner reviews observed evidence of actual continuation")
    p.add_argument("--recovery", required=True)
    p.add_argument("--operation", required=True)
    p.add_argument("--note", required=True)
    p = sub.add_parser("policy", help="Read or change current owner policy")
    p.add_argument("--restriction", action="append")
    p.add_argument("--allow-model", action="append")
    p.add_argument("--recovery", choices=["allow", "deny"])
    sub.add_parser("environment", help="Inspect observed environment requirements before owner review")
    p = sub.add_parser(
        "declare-environment", help="Record bounded owner resource requirements; no secrets or probes"
    )
    p.add_argument("requirements", type=Path, help="JSON requirements file, at most 64 KiB")
    p.add_argument("--note", required=True)
    p = sub.add_parser(
        "verify-environment", help="Owner confirms services, dependencies, secret references and model budget"
    )
    p.add_argument("--note", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--context-bytes", type=int, required=True)
    p = sub.add_parser("devices", help="List all paired devices for dashboard access")
    p = sub.add_parser("revoke-device", help="Revoke access for a specific device session ID")
    p.add_argument("device_id", help="The 24-character device session ID to revoke")
    p = sub.add_parser("install-client", help="Install MCP configuration for a specific client")
    p.add_argument("workspace", type=Path)
    p.add_argument("--client", choices=["cline"], default="cline")
    p.add_argument(
        "--mcp-config", type=Path, required=True, help="Existing settings file opened by Cline MCP Configure"
    )
    p = sub.add_parser("uninstall-client", help="Remove MCP configuration for a specific client")
    p.add_argument("workspace", type=Path)
    p.add_argument("--client", choices=["cline"], required=True, help="Target client to unconfigure")
    p = sub.add_parser("inspect-client", help="Inspect MCP configuration for a specific client")
    p.add_argument("workspace", type=Path)
    p.add_argument("--client", choices=["cline"], required=True, help="Target client to inspect")
    p = sub.add_parser("backup", help="Consistent encrypted local backup with same-user key material")
    p.add_argument("destination", type=Path)
    p = sub.add_parser("restore-local", help="Restore same-user history into NEW inspection-only state")
    p.add_argument("backup", type=Path)
    p.add_argument("destination", type=Path)
    p = sub.add_parser("restore-files", help="Restore selected artifacts into a separate empty destination")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("destination", type=Path)
    p = sub.add_parser("issue-gateway-key", help="Issue an epoch-scoped enrollment credential, shown once")
    p.add_argument("--route", default="default")
    p.add_argument("--model", required=True, action="append")
    p = sub.add_parser("profile", help="Configure model routing profiles")
    p.add_argument("action", choices=["activate"])
    p.add_argument("--alias", required=True, help="Alias used by the client")
    p.add_argument(
        "--model", required=True, action="append", help="Real upstream model (repeat for fallback order)"
    )
    p = sub.add_parser("gateway", help="Run a local gateway; public hosting requires separate deployment")
    p.add_argument("--upstream", required=True, help="Trusted HTTPS chat/completions endpoint")
    p.add_argument("--key-env", default="VESSEL_UPSTREAM_KEY")
    p.add_argument("--model", required=True, action="append")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", default=8091, type=int)
    p = sub.add_parser("orbio", help="Inspect and manage first-class Orbio credentials and gateway status")
    p.add_argument("action", choices=["status", "set-key", "replace-key", "forget-key", "claim-key", "models"])
    p.add_argument("--key", help="Orbio API key (sk-orbio-...)")
    p.add_argument("--name", default="vessel-operator-key", help="Key name for claim-key")
    p = sub.add_parser("identity", help="Manage portable Operator Identity Cards for cross-system migration")
    p.add_argument("action", choices=["inspect", "import", "export"])
    p.add_argument("--pass-file", type=Path, help="Path to vessel-identity.json pass file")
    p.add_argument("--token", help="Base64url-encoded identity pass token (vessel-pass:...)")
    p.add_argument("--workspace", type=Path, help="Workspace directory")
    return parser


def output(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def main(argv=None):
    args = build_parser().parse_args(argv)
    service = None
    try:
        if args.command in {
            "launch",
            "companion-status",
            "stop-companion",
            "connection",
            "doctor",
            "startup",
            "identity",
        }:
            if args.workspace:
                from vessel.onboarding import local_path
                from vessel.registry import lookup
                from vessel.service import canonical

                registered = lookup(canonical(local_path(args.workspace)))
                if registered is None:
                    raise ValueError("This project is not enrolled. Run vessel setup first")
                if args.state and local_path(args.state) != registered:
                    raise ValueError("The supplied state does not match this project's registered authority")
                args.state = registered
        if args.command != "setup" and args.state is None:
            args.state = default_state()
        if args.command == "setup":
            from vessel.onboarding import wizard

            result = wizard(args)
        elif args.command in {"launch", "companion-status", "stop-companion", "connection"}:
            from vessel import desktop

            handler = {
                "launch": desktop.launch,
                "companion-status": desktop.status,
                "stop-companion": desktop.stop,
                "connection": desktop.connection,
            }[args.command]
            result = handler(args.state)
        elif args.command == "startup":
            from vessel.startup import configure

            result = configure(args.state, args.action)
        elif args.command == "doctor":
            from vessel import adapters, desktop
            from vessel.onboarding import load_profile

            profile = load_profile(args.state)
            service = Vessel(args.state)
            observed = service.status(profile["workspace"])
            orbio_secret = service.store.get("secrets", "orbio_credential")
            result = {
                "profile": profile,
                "configuration": adapters.inspect("cline", Path(profile["workspace"]), service.store.dir),
                "companion": desktop.status(args.state),
                "capture": observed["capture"],
                "observed_sessions": len(observed["sessions"]),
                "orbio": {
                    "configured": bool(orbio_secret and orbio_secret.get("key")),
                    "masked_key": orbio_secret.get("masked") if orbio_secret else None,
                },
                "notice": "Configuration alone does not verify native capture. Require a real Cline probe.",
            }
            if os.name == "nt":
                from vessel.startup import configure

                result["startup"] = configure(args.state, "status")
        elif args.command in {"install-client", "uninstall-client", "inspect-client"}:
            from vessel import adapters

            if args.command == "install-client":
                service = Vessel(args.state)
                service.status(args.workspace)
                service._writable()
                result = adapters.install(args.client, args.workspace, args.state, mcp_config=args.mcp_config)
                service.store.put("control", f"{args.client}_adapter", {"installed": True})
            elif args.command == "uninstall-client":
                result = adapters.uninstall(args.client, args.workspace, args.state)
            else:
                result = adapters.inspect(args.client, args.workspace, args.state)
        elif args.command == "restore-local":
            from vessel.storage import Store

            restored = Store.restore_local(args.backup, args.destination)
            result = {"restored": str(args.destination.resolve()), "mode": "inspection_only"}
            restored.close()
        else:
            service = Vessel(args.state)
            match args.command:
                case "dashboard":
                    import secrets

                    import uvicorn

                    from vessel.dashboard import approved_origin, create_app

                    service.close()
                    service = None
                    origin = approved_origin(args.origin)
                    token = secrets.token_urlsafe(36)
                    app = create_app(
                        args.state,
                        origin=origin,
                        token=token,
                        port=args.port,
                        ttl=args.ttl,
                        start_workers=True,
                    )
                    output(
                        {
                            "connect_url": f"{origin}/#connect={args.port}:{token}",
                            "expires_in_seconds": args.ttl,
                            "notice": "Open this private connection link in your browser. Keep this terminal running. Do not share the link.",
                        }
                    )
                    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
                    return 0
                case "enroll":
                    result = service.enroll(args.workspace, args.mission, args.restriction, args.required)
                case "status":
                    result = service.status(args.workspace)
                case "sessions":
                    result = service.store.list("sessions")
                case "devices":
                    result = list_devices(service)
                case "revoke-device":
                    result = revoke_device(service, args.device_id)
                case "start":
                    result = service.start(args.workspace, args.session)
                case "heartbeat":
                    while True:
                        result = service.heartbeat(args.run, args.epoch, revalidate=args.revalidate_policy)
                        args.revalidate_policy = False
                        if args.once:
                            break
                        output(
                            {
                                "lease": "renewed",
                                "epoch": result["execution_epoch"],
                                "expires_at": result["expires_at"],
                            }
                        )
                        time.sleep(5)
                case "companion":
                    from vessel.companion import run

                    service.close()
                    service = None
                    run(args.state, args.run, args.epoch, output)
                    return 0
                case "work-once" | "retry-capture" | "cleanup" | "pin" | "unpin":
                    from vessel.maintenance import Maintenance

                    maintenance = Maintenance(service)
                    if args.command == "work-once":
                        result = maintenance.work_once()
                    elif args.command == "retry-capture":
                        result = maintenance.retry(args.run)
                    elif args.command == "cleanup":
                        result = maintenance.cleanup(
                            dry_run=not args.apply, quota_pressure=args.quota_pressure
                        )
                    elif args.command == "pin":
                        result = maintenance.pin(args.checkpoint, args.note)
                    else:
                        result = maintenance.unpin(args.checkpoint)
                case "stop":
                    result = service.stop(args.run, attested=args.attest_stopped, note=args.note)
                case "dismiss-session":
                    result = service.dismiss_session(args.session, args.note)
                case "task":
                    result = service.task(
                        args.run,
                        args.id,
                        args.description,
                        status=args.status,
                        evidence=args.evidence,
                        dependencies=args.depends_on,
                    )
                case "proposals":
                    result = service.store.list("proposals")
                case "review-proposal":
                    result = service.review_proposal(
                        args.proposal,
                        args.decision,
                        args.note,
                        policy_revision=args.policy_revision,
                        run_id=args.run,
                        task_id=args.task_id,
                        evidence=args.evidence,
                        dependencies=args.depends_on,
                    )
                case "finish-run":
                    result = service.finish_run(args.run, args.outcome, args.note, evidence=args.evidence)
                case "cancel-recovery":
                    result = service.cancel_recovery(args.recovery, args.note)
                case "operations":
                    result = service.operations(args.run)
                case "resolve":
                    result = service.resolve_operation(args.operation, args.note)
                case "repair-capture":
                    result = service.repair_capture(args.note)
                case "checkpoint":
                    result = service.checkpoint(args.run)
                case "verify":
                    result = service.validate_checkpoint(args.checkpoint)
                case "context":
                    result = service.context(args.run)
                case "recover":
                    result = service.prepare_recovery(
                        args.checkpoint, args.session, args.request, context_budget=args.context_bytes
                    )
                case "handover":
                    result = service.handover(args.recovery, args.review_token)
                case "finish-handover":
                    result = service.finish_handover(args.recovery)
                case "repair-handover":
                    result = service.repair_handover(args.recovery, args.policy_revision, args.note)
                case "recovery-context":
                    result = service.recovery_context(args.recovery)
                case "confirm":
                    result = service.confirm_continuation(args.recovery, args.operation, args.note)
                case "policy":
                    result = service.policy(
                        restrictions=args.restriction,
                        allowed_models=args.allow_model,
                        recovery_allowed=None if args.recovery is None else args.recovery == "allow",
                    )
                case "environment":
                    from vessel.artifacts import Artifacts
                    from vessel.environment import findings

                    result = Artifacts(Path(service._enrollment()["workspace"]), service.store).environment()
                    result["findings"] = findings(result)
                case "declare-environment":
                    from vessel.environment import MAX_REQUIREMENTS_BYTES
                    from vessel.storage import _regular_file, safe_directory

                    requirements_path = args.requirements.absolute()
                    safe_directory(requirements_path.parent)
                    requirements = json.loads(_regular_file(requirements_path, MAX_REQUIREMENTS_BYTES))
                    result = service.declare_environment(requirements, args.note)
                case "verify-environment":
                    result = service.review_environment(args.note, args.model, args.context_bytes)
                case "backup":
                    result = service.backup(args.destination)
                case "restore-files":
                    from vessel.artifacts import Artifacts

                    enrollment = service._enrollment()
                    cp = service._get("checkpoints", args.checkpoint)
                    result = Artifacts(Path(enrollment["workspace"]), service.store).restore(
                        cp["manifest"], args.destination
                    )
                case "issue-gateway-key":
                    result = service.issue_gateway_credential(args.route, args.model)
                case "profile":
                    service._writable()
                    policy = service._get("control", "policy")
                    profiles = service.store.get("control", "gateway_profiles") or {}
                    if args.action == "activate":
                        if (
                            not args.alias.strip()
                            or len(args.alias) > 256
                            or any(ord(ch) < 32 for ch in args.alias)
                            or args.alias in policy["allowed_models"]
                            or not 1 <= len(args.model) <= 3
                            or len(set(args.model)) != len(args.model)
                            or not set(args.model) <= set(policy["allowed_models"])
                            or (args.alias not in profiles and len(profiles) >= 32)
                        ):
                            raise ValueError(
                                "Use a distinct alias and 1–3 distinct models allowed by current policy"
                            )
                        profiles[args.alias] = args.model
                        service.store.put("control", "gateway_profiles", profiles)
                        result = {
                            "activated": True,
                            "alias": args.alias,
                            "models": args.model,
                            "restart_gateway_required": True,
                        }
                case "gateway":
                    import uvicorn

                    from vessel.gateway import UpstreamRoute, create_app

                    key = os.environ.get(args.key_env)
                    if not key:
                        raise ValueError(f"Set {args.key_env} in the server environment before starting")

                    profiles = service.store.get("control", "gateway_profiles") or {}
                    route = UpstreamRoute(
                        endpoint=args.upstream,
                        api_key=key,
                        allowed_models=frozenset(args.model),
                        profiles={k: tuple(v) for k, v in profiles.items()},
                    )

                    # Create one Store per callback: SQLite connection/thread lifetime stays explicit.
                    def authorize(token):
                        instance = Vessel(args.state)
                        try:
                            return instance.authorize_gateway(token)
                        finally:
                            instance.close()

                    def audit(event):
                        instance = Vessel(args.state)
                        try:
                            instance.audit_gateway(event)
                        finally:
                            instance.close()

                    app = create_app(routes={"default": route}, authorize=authorize, audit=audit)
                    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
                    return 0
                case "orbio":
                    import asyncio

                    from vessel import extension_gateway
                    from vessel.orbio import RealOrbioAdapter, mask_key

                    adapter = RealOrbioAdapter()
                    if args.action == "status":
                        secret = service.store.get("secrets", "orbio_credential")
                        has_key = bool(secret and secret.get("key"))
                        masked = secret.get("masked") if has_key else None
                        version = secret.get("credential_version") if has_key else None
                        verified_at = secret.get("verified_at") if has_key else None
                        conn_status = asyncio.run(
                            adapter.connection_status(secret.get("key") if has_key else None)
                        )
                        gateway_cfg = service.store.get("control", extension_gateway.CONTROL) or {}
                        gw_status = extension_gateway.status(args.state)
                        result = {
                            "connected": has_key,
                            "masked_key": masked,
                            "credential_version": version,
                            "verified_at": verified_at,
                            "probe_status": "ok" if has_key else "unconfigured",
                            "gateway": {
                                "status": gw_status.get("status", "offline"),
                                "port": gateway_cfg.get("port", 8091),
                                "running": gw_status.get("running", False),
                                "models": gateway_cfg.get("models", list(extension_gateway.MODELS)),
                            },
                            "balance": conn_status.get(
                                "balance",
                                {"available": False, "amount": None, "currency": "CREDIT"},
                            ),
                            "mcp": conn_status.get("mcp", {"configured": False, "capabilities": []}),
                        }
                    elif args.action in {"set-key", "replace-key"}:
                        raw_key = args.key
                        if not raw_key:
                            import getpass

                            raw_key = getpass.getpass("Enter Orbio API Key: ").strip()
                        if not raw_key:
                            raise ValueError("Orbio API key is required")
                        asyncio.run(adapter.validate_credential(raw_key))
                        now = int(time.time())
                        secret = service.store.get("secrets", "orbio_credential")
                        version = (
                            f"v{int(secret.get('credential_version', 'v0')[1:]) + 1}"
                            if secret
                            else "v1"
                        )
                        service.store.put(
                            "secrets",
                            "orbio_credential",
                            {
                                "key": raw_key,
                                "masked": mask_key(raw_key),
                                "credential_version": version,
                                "verified_at": now,
                            },
                        )
                        ctrl = service.store.get("control", extension_gateway.CONTROL) or {}
                        ctrl["paused"] = False
                        service.store.put("control", extension_gateway.CONTROL, ctrl)
                        result = {
                            "status": "active",
                            "credential_version": version,
                            "masked_key": mask_key(raw_key),
                            "verified_at": now,
                        }
                    elif args.action == "forget-key":
                        service.store.delete("secrets", "orbio_credential")
                        ctrl = service.store.get("control", extension_gateway.CONTROL) or {}
                        ctrl["paused"] = True
                        service.store.put("control", extension_gateway.CONTROL, ctrl)
                        result = {
                            "status": "removed",
                            "paused": True,
                            "recovery_history_preserved": True,
                        }
                    elif args.action == "claim-key":
                        claim_res = asyncio.run(adapter.claim_key(args.name))
                        if not claim_res.get("success"):
                            result = claim_res
                        else:
                            raw_key = claim_res["key"]
                            asyncio.run(adapter.validate_credential(raw_key))
                            now = int(time.time())
                            version = "v1"
                            service.store.put(
                                "secrets",
                                "orbio_credential",
                                {
                                    "key": raw_key,
                                    "masked": mask_key(raw_key),
                                    "credential_version": version,
                                    "verified_at": now,
                                },
                            )
                            ctrl = service.store.get("control", extension_gateway.CONTROL) or {}
                            ctrl["paused"] = False
                            service.store.put("control", extension_gateway.CONTROL, ctrl)
                            result = {
                                "status": "claimed",
                                "credential_version": version,
                                "masked_key": mask_key(raw_key),
                                "verified_at": now,
                            }
                    elif args.action == "models":
                        secret = service.store.get("secrets", "orbio_credential")
                        raw_key = secret.get("key") if secret else None
                        models_list = asyncio.run(adapter.fetch_model_catalog(raw_key))
                        ctrl = service.store.get("control", extension_gateway.CONTROL) or {}
                        result = {
                            "active_model": (ctrl.get("models") or [extension_gateway.MODELS[0]])[0],
                            "gateway_models": ctrl.get("models") or list(extension_gateway.MODELS),
                            "models": models_list[:10],
                            "total_models": len(models_list),
                        }
                case "identity":
                    from vessel.identity import (
                        export_identity_pass,
                        import_identity_pass,
                        inspect_identity_pass,
                    )

                    if args.action == "inspect":
                        result = inspect_identity_pass(pass_file=args.pass_file, token=args.token)
                    elif args.action == "import":
                        result = import_identity_pass(service.store, pass_file=args.pass_file, token=args.token)
                    elif args.action == "export":
                        result = export_identity_pass(service.store, pass_file=args.pass_file)
                case _:
                    raise ValueError("Unknown command")
        output(result)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # Owner CLI errors contain no request bodies or upstream key values.
        print(
            json.dumps({"error": type(exc).__name__, "message": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    finally:
        if service:
            service.close()


if __name__ == "__main__":
    raise SystemExit(main())
