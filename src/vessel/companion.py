"""Explicit owner-started companion; fixed run binding and one artifact worker."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from vessel.artifacts import Artifacts
from vessel.maintenance import Maintenance
from vessel.service import Blocked, Vessel


class WorkspaceWatcher:
    """Bounded artifact inventory, never a substitute for native tool receipts."""

    def __init__(self, artifacts):
        self.artifacts = artifacts
        self.previous = None

    def poll(self):
        inventory, _, issues = self.artifacts._inventory()
        if issues:
            raise Blocked("Workspace watcher could not inspect all eligible files")
        changed = self.previous is not None and inventory != self.previous
        self.previous = inventory
        return changed


def run(state_dir: Path, run_id: str, epoch: int, emit=print):
    stop = threading.Event()
    failures = []

    def heartbeat():
        service = None
        try:
            service = Vessel(state_dir)
            while not stop.is_set():
                lease = service._get("control", "lease")
                if lease["holder_run_id"] != run_id or lease["execution_epoch"] != epoch:
                    failures.append("execution_transferred_restart_companion_for_destination")
                    stop.set()
                    return
                if lease["status"] == "closed":
                    stop.set()
                    return
                if lease["status"] == "active":
                    service.heartbeat(run_id, epoch)
                # A paused native writer may still need a queued continuation candidate.
                stop.wait(5)
        except (OSError, ValueError, sqlite3.Error) as error:
            failures.append(type(error).__name__)
            stop.set()
        finally:
            if service:
                service.close()

    service = Vessel(state_dir)
    try:
        service._writable()
        lease = service._get("control", "lease")
        if lease["holder_run_id"] != run_id or lease["execution_epoch"] != epoch:
            raise Blocked("Companion must bind to the explicitly selected current run/epoch")
        workspace = Path(service._enrollment()["workspace"])
    except Exception:
        service.close()
        raise
    worker = threading.Thread(target=heartbeat, name="vessel-heartbeat", daemon=True)
    worker.start()

    watcher = WorkspaceWatcher(Artifacts(workspace, service.store))
    maintenance = Maintenance(service, run_id=run_id, epoch=epoch)
    next_cleanup = service.clock() + 300
    next_activity_check = service.clock()

    try:
        while not stop.is_set():
            now = service.clock()
            if now >= next_activity_check:
                next_activity_check = now + 5
                try:
                    changed = watcher.poll()
                except (OSError, ValueError):
                    changed = False
                    with service.store.transaction() as conn:
                        service._gap("workspace_watcher_incomplete", conn)
                if changed:
                    from vessel.maintenance import enqueue

                    with service.store.transaction() as conn:
                        lease = service._get("control", "lease", conn)
                        if (lease["holder_run_id"], lease["execution_epoch"]) != (run_id, epoch):
                            break
                        if lease["status"] == "closed":
                            break
                        if lease["status"] == "paused":
                            service._gap("files_changed_after_attested_stop", conn)
                            current = service._get("runs", run_id, conn)
                            current.pop("stop_evidence", None)
                            service.store.put("runs", run_id, current, conn=conn)
                        enqueue(service, run_id, epoch, "workspaceChanged", 0, 0, conn)

            result = maintenance.work_once()
            if result["status"] == "finished":
                break
            if result["status"] not in {"idle", "busy", "blocked"}:
                emit(result)
            if service.clock() >= next_cleanup:
                cleanup = maintenance.cleanup(dry_run=False)
                emit(
                    {
                        "maintenance": "retention",
                        "removed_checkpoints": len(cleanup["removed_checkpoints"]),
                        "reclaimed_bytes": cleanup["reclaimed_blob_bytes"],
                    }
                )
                next_cleanup = service.clock() + 300
            stop.wait(1)
    finally:
        stop.set()
        worker.join(timeout=10)
        service.close()
    if failures:
        raise Blocked("Companion stopped: " + failures[0])
