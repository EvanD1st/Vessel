"""Bounded checkpoint requests and retention; no automatic execution handover."""

from __future__ import annotations

import re
import sqlite3
import time

from vessel.service import Blocked, Vessel, identifier
from vessel.storage import _sync_directory, is_link

MAX_PENDING_SIGNALS = 1000
MAX_PENDING_BYTES = 64 * 1024 * 1024
CAPTURE_EVENTS = {"afterFileEdit", "afterAgentResponse", "preCompact", "stop", "sessionEnd"}


def enqueue(service: Vessel, run_id: str, epoch: int, name: str, seq: int, size: int, conn):
    """Called in the inbox transaction; metadata only, with no filesystem scan."""
    request = service.store.get("capture_requests", run_id, conn=conn)
    if request is None:
        request = {
            "id": run_id,
            "run_id": run_id,
            "epoch": epoch,
            "count": 0,
            "bytes": 0,
            "first_at": service.clock(),
            "due_at": service.clock() + 5,
            "version": 0,
            "status": "queued",
            "operation_id": identifier("capture"),
            "attempts": 0,
        }
    if request["count"] >= MAX_PENDING_SIGNALS or request["bytes"] + size > MAX_PENDING_BYTES:
        service._gap("automatic_capture_queue_overflow", conn)
        return
    request.update(
        count=request["count"] + 1,
        bytes=request["bytes"] + size,
        version=request["version"] + 1,
        last_seq=seq,
        last_reason=name,
    )
    service.store.put("capture_requests", run_id, request, conn=conn)


class Maintenance:
    def __init__(self, service: Vessel, *, run_id=None, epoch=None):
        if (run_id is None) != (epoch is None):
            raise ValueError("Worker binding requires both run and epoch")
        self.service = service
        self.store = service.store
        self.binding = (run_id, epoch) if run_id is not None else None

    def work_once(self):
        """One worker per enrollment, OS-released lock and durable crash retry identity."""
        try:
            with self.store.artifacts.hold(timeout=0):
                return self._work_once()
        except TimeoutError:
            return {"status": "busy"}

    def _work_once(self):
        service = self.service
        try:
            return self._attempt_capture()
        except CaptureFailure as failure:
            pending, error = failure.pending, failure.error
            # One bounded control record uses reserved diagnostic headroom, so a
            # full logical quota cannot turn a failed request into an endless retry.
            with self.store.transaction() as conn:
                previous = self.store.get("control", "capture_worker_failure", conn=conn)
                operation_id = (pending.get("processing") or pending)["operation_id"]
                attempts = (
                    previous["attempts"] if previous and previous["operation_id"] == operation_id else 0
                ) + 1
                failure_state = {
                    "run_id": pending["run_id"],
                    "operation_id": operation_id,
                    "attempts": attempts,
                    "status": "blocked" if attempts >= 3 else "retry_wait",
                    "due_at": service.clock() + min(60, 5 * 2**attempts),
                    "error": type(error).__name__,
                }
                self.store.put("control", "capture_worker_failure", failure_state, conn=conn, critical=True)
                service._gap("automatic_checkpoint_failed", conn)
            return {"status": "failed", "retry": failure_state}

    def _attempt_capture(self):
        service = self.service
        with self.store.transaction() as conn:
            service._writable(conn)
            lease = service._get("control", "lease", conn)
            if self.binding and self.binding != (lease["holder_run_id"], lease["execution_epoch"]):
                raise Blocked("Execution transferred; restart the companion for the selected destination")
            if lease["status"] == "closed":
                return {"status": "finished"}
            # Old requests never migrate into the destination's authority. Their
            # underlying observations remain in the immutable event ledger.
            for stale in self.store.list("capture_requests", conn=conn):
                if stale["run_id"] != lease["holder_run_id"]:
                    conn.execute(
                        "DELETE FROM documents WHERE kind='capture_requests' AND id=?", (stale["id"],)
                    )
                    self.store.put(
                        "control",
                        "last_capture_cancellation",
                        {"run_id": stale["run_id"], "reason": "execution_transferred", "at": service.clock()},
                        conn=conn,
                        critical=True,
                    )
            pending = self.store.get("capture_requests", lease["holder_run_id"], conn=conn)
            if not pending or pending["due_at"] > service.clock():
                return {"status": "idle"}
            if pending["epoch"] != lease["execution_epoch"]:
                raise Blocked("Queued capture has a stale execution epoch")
            failure = self.store.get("control", "capture_worker_failure", conn=conn)
            operation_id = (pending.get("processing") or pending)["operation_id"]
            if failure and failure["operation_id"] == operation_id:
                if failure["status"] == "blocked":
                    return {"status": "blocked", "run_id": pending["run_id"], "attempts": failure["attempts"]}
                if failure["due_at"] > service.clock():
                    return {"status": "idle"}
        try:
            return self._capture_and_acknowledge(pending)
        except (OSError, ValueError, TimeoutError, sqlite3.Error) as error:
            raise CaptureFailure(pending, error) from error

    def _capture_and_acknowledge(self, pending):
        service = self.service
        with self.store.transaction() as conn:
            # Reload after reading the retry state; hooks can arrive meanwhile.
            pending = service._get("capture_requests", pending["id"], conn)
            if not pending.get("processing"):
                pending["processing"] = {k: pending[k] for k in ("operation_id", "count", "bytes", "version")}
            pending["status"] = "processing"
            self.store.put("capture_requests", pending["id"], pending, conn=conn)
        claim = pending["processing"]
        checkpoint = service._checkpoint(
            pending["run_id"], automatic=True, operation_id=claim["operation_id"]
        )
        with self.store.transaction() as conn:
            current = service._get("capture_requests", pending["id"], conn)
            if current["version"] == claim["version"]:
                conn.execute("DELETE FROM documents WHERE kind='capture_requests' AND id=?", (current["id"],))
            else:
                current.update(
                    count=current["count"] - claim["count"],
                    bytes=current["bytes"] - claim["bytes"],
                    status="queued",
                    processing=None,
                    first_at=service.clock(),
                    due_at=service.clock() + 5,
                    operation_id=identifier("capture"),
                    attempts=0,
                )
                self.store.put("capture_requests", current["id"], current, conn=conn)
            self.store.put(
                "control",
                "last_automatic_capture",
                {
                    "checkpoint_id": checkpoint["id"],
                    "at": service.clock(),
                    "eligible": not checkpoint["capture"]["blockers"],
                },
                conn=conn,
            )
            conn.execute("DELETE FROM documents WHERE kind='control' AND id='capture_worker_failure'")
        return {
            "status": "captured",
            "checkpoint_id": checkpoint["id"],
            "eligible": not checkpoint["capture"]["blockers"],
        }

    def retry(self, run_id):
        with self.store.artifacts.hold(), self.store.transaction() as conn:
            self.service._writable(conn)
            if self.service._get("control", "lease", conn)["holder_run_id"] != run_id:
                raise Blocked("Cannot retry a historical run's automatic capture")
            request = self.service._get("capture_requests", run_id, conn)
            request.update(status="queued", attempts=0, due_at=self.service.clock())
            self.store.put("capture_requests", run_id, request, conn=conn)
            conn.execute("DELETE FROM documents WHERE kind='control' AND id='capture_worker_failure'")
            return request

    def pin(self, checkpoint_id, note):
        if not note.strip():
            raise ValueError("A pin reason is required")
        with self.store.artifacts.hold(), self.store.transaction() as conn:
            self.service._writable(conn)
            self.service._get("checkpoints", checkpoint_id, conn)
            record = {"id": checkpoint_id, "note": note, "at": self.service.clock()}
            self.store.put("checkpoint_pins", checkpoint_id, record, conn=conn)
            return record

    def unpin(self, checkpoint_id):
        with self.store.transaction() as conn:
            self.service._writable(conn)
            conn.execute("DELETE FROM documents WHERE kind='checkpoint_pins' AND id=?", (checkpoint_id,))
        return {
            "checkpoint_id": checkpoint_id,
            "manual_pin_removed": True,
            "automatic_safety_pins_still_apply": True,
        }

    def cleanup(self, *, dry_run=True, keep_days=7, keep_count=50, grace_seconds=3600, quota_pressure=False):
        if keep_days < 0 or keep_count < 1 or grace_seconds < 0:
            raise ValueError("Invalid retention limits")
        with self.store.artifacts.hold():
            return self._cleanup(dry_run, keep_days, keep_count, grace_seconds, quota_pressure)

    def _cleanup(self, dry_run, keep_days, keep_count, grace, quota_pressure):
        service = self.service
        service._writable()
        checkpoints = sorted(
            self.store.list("checkpoints"), key=lambda cp: (cp["created_at"], cp["id"]), reverse=True
        )
        reasons = {cp["id"]: [] for cp in checkpoints}
        last_capture = self.store.get("control", "last_automatic_capture")
        if last_capture and last_capture["checkpoint_id"] in reasons:
            reasons[last_capture["checkpoint_id"]].append("latest_automatic_capture")
        for pin in self.store.list("checkpoint_pins"):
            if pin["id"] in reasons:
                reasons[pin["id"]].append("owner_pin")
        for recovery in self.store.list("recoveries"):
            if recovery["checkpoint_id"] in reasons:
                reasons[recovery["checkpoint_id"]].append("recovery_reference")
        for run in self.store.list("runs"):
            if run.get("source_checkpoint") in reasons:
                reasons[run["source_checkpoint"]].append("run_lineage_reference")
        unresolved = {
            op["run_id"]
            for run in self.store.list("runs")
            for op in service.operations(run["id"])
            if op["uncertain"]
        }
        in_progress_operations = {
            r["processing"]["operation_id"]
            for r in self.store.list("capture_requests")
            if r.get("processing")
        }
        newest_valid = None
        for cp in checkpoints:
            if cp["run_id"] in unresolved:
                reasons[cp["id"]].append("unresolved_operation_evidence")
            if cp.get("capture_operation") in in_progress_operations:
                reasons[cp["id"]].append("pending_capture_acknowledgment")
            if newest_valid is None and service.validate_checkpoint(cp["id"])["eligible"]:
                newest_valid = cp["id"]
                reasons[cp["id"]].append("latest_known_good")
        # Even before an eligible checkpoint exists, keep the newest inspection source.
        if checkpoints and newest_valid is None:
            reasons[checkpoints[0]["id"]].append("latest_available_inspection")
        retained = set()
        cutoff = service.clock() - keep_days * 86400
        for index, cp in enumerate(checkpoints):
            if reasons[cp["id"]]:
                retained.add(cp["id"])
            elif not quota_pressure and (index < keep_count or cp["created_at"] >= cutoff):
                retained.add(cp["id"])
                reasons[cp["id"]].append("ordinary_retention")
        removed = [cp["id"] for cp in checkpoints if cp["id"] not in retained]
        remaining = [cp for cp in checkpoints if cp["id"] in retained]
        references = {record["blob"] for cp in remaining for record in cp["manifest"]["files"]}
        # Artifact lock serializes writers, backups and restore-file reads. Metadata
        # deletion commits first. A crash before file GC leaves only harmless orphans.
        if not dry_run:
            with self.store.transaction() as conn:
                for checkpoint_id in removed:
                    conn.execute("DELETE FROM documents WHERE kind='checkpoints' AND id=?", (checkpoint_id,))
        deleted, reclaimed, reserved, deferred = [], 0, 0, []
        cutoff_real = time.time() - grace
        for path in sorted(self.store.blob_dir.iterdir()):
            if is_link(path) or not path.is_file():
                raise ValueError("Unexpected artifact entry; collection stopped")
            valid_blob = bool(re.fullmatch(r"[0-9a-f]{64}\.blob", path.name))
            staging = bool(re.fullmatch(r"\.[0-9a-f]{64}\.blob\.[0-9a-f]{32}\.staging", path.name))
            if not valid_blob and not staging:
                raise ValueError("Unknown artifact filename; collection stopped")
            size = path.stat().st_size
            unreferenced = staging or path.stem not in references
            if unreferenced and path.stat().st_mtime <= cutoff_real:
                # Resolve and validate each absolute deletion target under the enrolled blob directory.
                if path.resolve().parent != self.store.blob_dir.resolve():
                    raise ValueError("Artifact deletion target escaped its store")
                if not dry_run:
                    path.unlink()
                deleted.append(path.name)
                reclaimed += size
            else:
                reserved += size
                if unreferenced:
                    deferred.append(path.name)
        if not dry_run:
            _sync_directory(self.store.blob_dir)
            with self.store.transaction() as conn:
                conn.execute(
                    "UPDATE kv SET value=? WHERE key='blob_budget'",
                    (self.store.seal({"reserved_bytes": reserved}),),
                )
            # Checkpointing the WAL releases journal space without vacuuming a live DB.
            self.store.connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
        result = {
            "dry_run": dry_run,
            "removed_checkpoints": removed,
            "retained": {k: v for k, v in reasons.items() if k in retained},
            "removed_blobs": deleted,
            "deferred_blobs": deferred,
            "reclaimed_blob_bytes": reclaimed,
            "quota_shortened_retention": quota_pressure,
            "at": service.clock(),
        }
        if not dry_run:
            with self.store.transaction() as conn:
                try:
                    self.store.ensure_capacity(32768)
                    result["capacity"] = "available"
                except ValueError:
                    result["capacity"] = "pinned_or_grace_period_data_prevents_growth"
                    service._gap("storage_quota_requires_owner_action", conn)
                # Keep diagnostics small even when a cleanup affects many files.
                self.store.put(
                    "control",
                    "last_cleanup",
                    {
                        "at": result["at"],
                        "capacity": result["capacity"],
                        "removed_checkpoints": len(removed),
                        "removed_blobs": len(deleted),
                        "reclaimed_bytes": reclaimed,
                        "quota_shortened_retention": quota_pressure,
                    },
                    conn=conn,
                    critical=True,
                )
        return result


class CaptureFailure(Exception):
    def __init__(self, pending, error):
        self.pending, self.error = pending, error
        super().__init__(type(error).__name__)
