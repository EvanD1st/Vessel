"""Durable background capture, bounded retries and conservative blob collection."""

import hashlib
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest
from test_service import observe
from test_service import project as project

from vessel.artifacts import Artifacts
from vessel.maintenance import Maintenance
from vessel.service import Blocked, Vessel
from vessel.storage import Store


def signal(project, event="afterAgentResponse", **fields):
    service, workspace, _, _ = project
    return observe(service, workspace, "source-conversation", event, **fields)


def stop(project):
    service, _, run, _ = project
    service.stop(run["id"], attested=True, note="Fixture writer and background tasks stopped")


def snapshots(project, count):
    service, workspace, run, clock = project
    stop(project)
    result = []
    for index in range(count):
        (workspace / "app.py").write_text(f"version = {index}\n")
        clock[0] += 1
        result.append(service.checkpoint(run["id"]))
    return result


def test_hooks_coalesce_without_artifact_reads_and_survive_restart(project, monkeypatch):
    service, _, run, clock = project
    original = Artifacts.capture

    def forbidden(*args, **kwargs):
        raise AssertionError("Hook path must never scan workspace files")

    monkeypatch.setattr(Artifacts, "capture", forbidden)
    for _ in range(30):
        signal(project)
    pending = service.store.get("capture_requests", run["id"])
    assert pending["count"] == 30
    assert Maintenance(service).work_once()["status"] == "idle"
    monkeypatch.setattr(Artifacts, "capture", original)
    clock[0] += 5
    restarted = Vessel(service.store.dir, clock=lambda: clock[0])
    try:
        result = Maintenance(restarted).work_once()
        assert result["status"] == "captured"
        assert not result["eligible"]
        cp = restarted.store.get("checkpoints", result["checkpoint_id"])
        assert "writer_not_stopped_inspection_only" in cp["capture"]["blockers"]
        assert restarted.store.get("control", "lease")["status"] == "active"
        assert not restarted.store.list("capture_requests")
        assert len(restarted.store.list("checkpoints")) == 1
    finally:
        restarted.close()


def test_duplicate_hook_does_not_duplicate_pending_work(project):
    service, workspace, run, _ = project
    payload = {"conversation_id": "source-conversation", "hook_event_name": "afterFileEdit"}
    service.observe(workspace, payload, "same-delivery")
    assert service.observe(workspace, payload, "same-delivery")["duplicate"]
    assert service.store.get("capture_requests", run["id"])["count"] == 1


@pytest.mark.parametrize("limit", ["MAX_PENDING_SIGNALS", "MAX_PENDING_BYTES"])
def test_queue_overflow_preserves_pending_evidence_and_degrades_capture(project, monkeypatch, limit):
    service, _, run, _ = project
    signal(project)
    first = service.store.get("capture_requests", run["id"])
    monkeypatch.setattr(
        "vessel.maintenance." + limit, first["count"] if limit.endswith("SIGNALS") else first["bytes"]
    )
    signal(project)
    assert service.store.get("capture_requests", run["id"]) == first
    assert "automatic_capture_queue_overflow" in service.status()["capture"]["gaps"]
    assert len(service.store.events(run_id=run["id"])) == 3


def test_paused_capture_can_be_eligible_but_native_stop_alone_is_not(project):
    service, _, _, clock = project
    signal(project, "stop")
    clock[0] += 5
    assert not Maintenance(service).work_once()["eligible"]
    stop(project)
    signal(project, "stop")
    clock[0] += 5
    result = Maintenance(service).work_once()
    assert result["eligible"]
    assert service.validate_checkpoint(result["checkpoint_id"])["eligible"]


def test_arrivals_during_capture_remain_pending_for_next_snapshot(project, monkeypatch):
    service, _, run, clock = project
    signal(project)
    clock[0] += 5
    original = Artifacts.capture

    def arriving(artifacts, *args, **kwargs):
        signal(project)
        return original(artifacts, *args, **kwargs)

    monkeypatch.setattr(Artifacts, "capture", arriving)
    result = Maintenance(service).work_once()
    cp = service.store.get("checkpoints", result["checkpoint_id"])
    assert "events_arrived_during_capture" in cp["capture"]["blockers"]
    assert service.store.get("capture_requests", run["id"])["count"] == 1
    monkeypatch.setattr(Artifacts, "capture", original)
    clock[0] += 5
    assert Maintenance(service).work_once()["status"] == "captured"
    assert len(service.store.list("checkpoints")) == 2
    assert not service.store.list("capture_requests")


def test_heartbeat_during_capture_does_not_invalidate_snapshot(project, monkeypatch):
    service, _, run, clock = project
    signal(project)
    clock[0] += 5
    original = Artifacts.capture

    def heartbeat(artifacts, *args, **kwargs):
        service.heartbeat(run["id"], 1)
        return original(artifacts, *args, **kwargs)

    monkeypatch.setattr(Artifacts, "capture", heartbeat)
    assert Maintenance(service).work_once()["status"] == "captured"


def test_quota_failure_retries_are_bounded_across_restarts(project):
    service, _, run, clock = project
    signal(project)
    clock[0] += 5
    for attempt in range(1, 4):
        instance = Vessel(service.store.dir, clock=lambda: clock[0])
        try:
            instance.store.max_storage_bytes = 1
            result = Maintenance(instance).work_once()
            assert result["status"] == "failed"
            assert result["retry"]["attempts"] == attempt
            assert Maintenance(instance).work_once()["status"] == ("blocked" if attempt == 3 else "idle")
            clock[0] = result["retry"]["due_at"]
        finally:
            instance.close()
    assert not service.store.list("checkpoints")
    assert Maintenance(service).work_once()["status"] == "blocked"
    assert "automatic_checkpoint_failed" in service.status()["capture"]["gaps"]
    service.heartbeat(run["id"], 1)
    Maintenance(service).retry(run["id"])
    assert Maintenance(service).work_once()["status"] == "captured"
    # Retrying does not silently erase evidence of a prior gap.
    assert service.status()["capture"]["state"] == "degraded"


def test_crash_after_commit_reuses_durable_operation_and_releases_lock(project):
    service, _, _, clock = project
    signal(project)
    stop(project)
    clock[0] += 5
    code = """
import os, sys
from pathlib import Path
from vessel.service import Vessel
from vessel.maintenance import Maintenance
s = Vessel(Path(sys.argv[1]), clock=lambda: float(sys.argv[2]))
original = s._checkpoint
def crash(stage):
    if stage == 'after_checkpoint_commit':
        os._exit(71)
def checkpoint(*args, **kwargs):
    return original(*args, fault=crash, **kwargs)
s._checkpoint = checkpoint
Maintenance(s).work_once()
"""
    result = subprocess.run([sys.executable, "-c", code, str(service.store.dir), str(clock[0])], timeout=20)
    assert result.returncode == 71
    first = service.store.list("checkpoints")
    assert len(first) == 1
    assert (
        "pending_capture_acknowledgment"
        in Maintenance(service).cleanup(quota_pressure=True)["retained"][first[0]["id"]]
    )
    result = Maintenance(service).work_once()
    assert result["checkpoint_id"] == first[0]["id"]
    assert result["eligible"]
    assert len(service.store.list("checkpoints")) == 1


def test_two_workers_do_not_capture_concurrently(project):
    service, _, _, clock = project
    signal(project)
    clock[0] += 5
    other = Vessel(service.store.dir, clock=lambda: clock[0])
    try:
        with service.store.artifacts.hold():
            assert Maintenance(other).work_once()["status"] == "busy"
        assert Maintenance(other).work_once()["status"] == "captured"
    finally:
        other.close()


def test_transfer_cancels_old_pending_work_without_rebinding_it(project):
    service, _, run, _ = project
    signal(project)
    cp = snapshots(project, 1)[0]
    recovery = service.prepare_recovery(cp["id"], "destination", "transfer")
    service.handover(recovery["id"], recovery["review_token"])
    assert Maintenance(service).work_once()["status"] == "idle"
    assert not service.store.list("capture_requests")
    assert service.status()["automatic_capture"]["last_cancellation"]["run_id"] == run["id"]
    assert len(service.store.events(run_id=run["id"])) == 2
    with pytest.raises(Blocked, match="historical"):
        Maintenance(service).retry(run["id"])


def test_retention_keeps_latest_fifty_even_when_old(project):
    service, _, _, clock = project
    checkpoints = snapshots(project, 55)
    clock[0] += 8 * 86400
    result = Maintenance(service).cleanup()
    assert len(result["retained"]) == 50
    assert set(result["removed_checkpoints"]) == {cp["id"] for cp in checkpoints[:5]}
    assert len(service.store.list("checkpoints")) == 55  # Default is a preview.


def test_retention_keeps_recent_checkpoints_beyond_count_floor(project):
    service, _, _, clock = project
    checkpoints = snapshots(project, 5)
    clock[0] += 6 * 86400
    result = Maintenance(service).cleanup(keep_count=1)
    assert len(result["retained"]) == 5
    clock[0] += 2 * 86400
    result = Maintenance(service).cleanup(keep_count=1)
    assert list(result["retained"]) == [checkpoints[-1]["id"]]


def test_quota_pins_owner_recovery_and_only_known_good_checkpoint(project):
    service, _, run, _ = project
    first, recovery_source, good = snapshots(project, 3)
    maintenance = Maintenance(service)
    maintenance.pin(first["id"], "Owner-selected release")
    service.prepare_recovery(recovery_source["id"], "destination", "pending-review")
    with service.store.transaction() as conn:
        service._gap("fixture_missing_hook", conn)
    inspection = service.checkpoint(run["id"])
    result = maintenance.cleanup(dry_run=False, quota_pressure=True, grace_seconds=0)
    assert result["retained"][first["id"]] == ["owner_pin"]
    assert "recovery_reference" in result["retained"][recovery_source["id"]]
    assert "latest_known_good" in result["retained"][good["id"]]
    assert inspection["id"] in result["removed_checkpoints"]
    assert service.validate_checkpoint(good["id"])["eligible"]
    maintenance.unpin(first["id"])
    assert first["id"] in maintenance.cleanup(quota_pressure=True)["removed_checkpoints"]


def test_unresolved_operation_evidence_pins_its_checkpoints(project):
    service, workspace, _, _ = project
    first, second = snapshots(project, 2)
    observe(
        service, workspace, "source-conversation", "preToolUse", tool_use_id="uncertain", tool_name="Shell"
    )
    result = Maintenance(service).cleanup(quota_pressure=True)
    for cp in (first, second):
        assert "unresolved_operation_evidence" in result["retained"][cp["id"]]
    operation_id = service.operations(first["run_id"])[0]["id"]
    service.resolve_operation(operation_id, "Owner reconciled the external effect")
    assert first["id"] in Maintenance(service).cleanup(quota_pressure=True)["removed_checkpoints"]


def test_shared_blobs_grace_period_and_budget_reconciliation(project):
    service, workspace, run, clock = project
    (workspace / "shared.py").write_text("shared = True\n")
    first, second = snapshots(project, 2)
    orphan = service.store.write_blob(b"uncommitted orphan")
    orphan_path = service.store.blob_dir / (orphan + ".blob")
    maintenance = Maintenance(service)
    result = maintenance.cleanup(dry_run=False, quota_pressure=True)
    assert first["id"] in result["removed_checkpoints"]
    assert orphan_path.name in result["deferred_blobs"]
    assert orphan_path.exists()
    os.utime(orphan_path, (time.time() - 7200, time.time() - 7200))
    result = maintenance.cleanup(dry_run=False, quota_pressure=True)
    assert orphan_path.name in result["removed_blobs"]
    assert not orphan_path.exists()
    assert service.validate_checkpoint(second["id"])["eligible"]
    reserved = service.store.unseal(
        service.store.connection.execute("SELECT value FROM kv WHERE key='blob_budget'").fetchone()[0]
    )
    assert reserved["reserved_bytes"] == sum(p.stat().st_size for p in service.store.blob_dir.iterdir())


def test_crash_between_metadata_deletion_and_blob_gc_is_recoverable(project):
    service, _, _, clock = project
    first, second = snapshots(project, 2)
    code = """
import os, sys
from pathlib import Path
from vessel.service import Vessel
from vessel.maintenance import Maintenance
s = Vessel(Path(sys.argv[1]), clock=lambda: float(sys.argv[2]))
def crash(*args, **kwargs):
    os._exit(72)
Path.unlink = crash
Maintenance(s).cleanup(dry_run=False, quota_pressure=True, grace_seconds=0)
"""
    result = subprocess.run([sys.executable, "-c", code, str(service.store.dir), str(clock[0])], timeout=20)
    assert result.returncode == 72
    assert service.store.get("checkpoints", first["id"]) is None
    assert service.validate_checkpoint(second["id"])["eligible"]
    result = Maintenance(service).cleanup(dry_run=False, quota_pressure=True, grace_seconds=0)
    assert result["removed_blobs"]
    assert service.validate_checkpoint(second["id"])["eligible"]


def test_backup_excludes_concurrent_cleanup_and_keeps_its_sources(project, tmp_path, monkeypatch):
    service, _, _, clock = project
    first, _ = snapshots(project, 2)
    other = Vessel(service.store.dir, clock=lambda: clock[0])
    entered, release, gc_done = threading.Event(), threading.Event(), threading.Event()
    original = service.store._backup
    errors = []

    def slow_backup(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(service.store, "_backup", slow_backup)

    def backup():
        try:
            service.store.backup(tmp_path / "backup")
        except Exception as error:
            errors.append(error)

    def cleanup():
        try:
            Maintenance(other).cleanup(dry_run=False, quota_pressure=True, grace_seconds=0)
            gc_done.set()
        except Exception as error:
            errors.append(error)

    backing = threading.Thread(target=backup)
    collecting = threading.Thread(target=cleanup)
    try:
        backing.start()
        assert entered.wait(5)
        collecting.start()
        assert not gc_done.wait(0.15)
        release.set()
        backing.join(15)
        collecting.join(15)
        assert not backing.is_alive() and not collecting.is_alive()
        assert not errors
        restored = Store.restore_local(tmp_path / "backup", tmp_path / "restored")
        try:
            checkpoint = restored.get("checkpoints", first["id"])
            assert checkpoint
            for record in checkpoint["manifest"]["files"]:
                assert hashlib.sha256(restored.read_blob(record["blob"])).hexdigest() == record["digest"]
        finally:
            restored.close()
    finally:
        release.set()
        backing.join(15)
        if collecting.ident:
            collecting.join(15)
        other.close()


def test_quota_pressure_never_removes_only_good_source_or_clears_gap(project):
    service, _, run, _ = project
    cp = snapshots(project, 1)[0]
    service.store.max_storage_bytes = 1
    result = Maintenance(service).cleanup(dry_run=False, quota_pressure=True, grace_seconds=0)
    assert cp["id"] in result["retained"]
    assert result["capacity"] == "pinned_or_grace_period_data_prevents_growth"
    assert "storage_quota_requires_owner_action" in service.status()["capture"]["gaps"]
    assert service.validate_checkpoint(cp["id"])["eligible"]


def test_restored_history_cannot_run_worker_or_cleanup(project, tmp_path):
    service, _, _, _ = project
    signal(project)
    service.store.backup(tmp_path / "backup")
    Store.restore_local(tmp_path / "backup", tmp_path / "restored").close()
    restored = Vessel(tmp_path / "restored")
    try:
        with pytest.raises(Blocked, match="inspection"):
            Maintenance(restored).work_once()
        with pytest.raises(Blocked, match="inspection"):
            Maintenance(restored).cleanup(dry_run=False)
    finally:
        restored.close()


def test_unknown_artifact_entry_stops_collection_without_touching_external_file(project, tmp_path):
    service, _, _, _ = project
    snapshots(project, 1)
    outside = tmp_path / "outside.txt"
    outside.write_text("Preserve this file")
    (service.store.blob_dir / "unknown.data").write_text("Not a managed artifact")
    with pytest.raises(ValueError, match="Unknown artifact"):
        Maintenance(service).cleanup(dry_run=False, grace_seconds=0)
    assert outside.read_text() == "Preserve this file"


def test_real_companion_process_heartbeats_captures_and_exits_after_transfer(project):
    service, _, run, _ = project
    service.clock = time.time
    service.store.clock = time.time
    service.heartbeat(run["id"], 1)
    initial_expiry = service.store.get("control", "lease")["expires_at"]
    signal(project)
    process = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "vessel",
            "--state",
            str(service.store.dir),
            "companion",
            "--run",
            run["id"],
            "--epoch",
            "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not service.store.get("control", "last_automatic_capture"):
            assert process.poll() is None
            time.sleep(0.1)
        capture = service.store.get("control", "last_automatic_capture")
        assert capture and not capture["eligible"]
        assert service.store.get("control", "lease")["expires_at"] > initial_expiry
        stop(project)
        checkpoint = service.checkpoint(run["id"])
        recovery = service.prepare_recovery(checkpoint["id"], "destination", "companion-transfer")
        destination = service.handover(recovery["id"], recovery["review_token"])
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 1
        assert '"status": "captured"' in stdout
        assert "transferred" in stderr.lower()
        assert service.store.get("control", "lease")["holder_run_id"] == destination["destination_run_id"]
        assert len(service.store.list("checkpoints")) == 2
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)


def test_recovery_window_distinguishes_checkpoint_and_verified_backup_age(project, tmp_path):
    service, _, _, clock = project
    assert service.status()["recovery_window"]["checkpoint_age_seconds"] is None
    snapshots(project, 1)
    clock[0] += 10
    service.backup(tmp_path / "verified-backup")
    clock[0] += 5
    window = service.status()["recovery_window"]
    assert window["checkpoint_age_seconds"] == 15
    assert window["backup_age_seconds"] == 5
    assert window["last_verified_backup"]["verified"]


def test_sqlite_capture_failure_is_visible_and_retried(project, monkeypatch):
    service, _, _, clock = project
    signal(project)
    clock[0] += 5

    def disk_failure(*args, **kwargs):
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr(service, "_checkpoint", disk_failure)
    result = Maintenance(service).work_once()
    assert result["status"] == "failed"
    assert result["retry"]["error"] == "OperationalError"
    assert result["retry"]["attempts"] == 1
    assert service.store.list("checkpoints") == []


@pytest.mark.parametrize("character", ["x", "\U0001f680"])
def test_emergency_health_summary_stays_bounded_at_full_logical_quota(project, character):
    service, _, _, _ = project
    service.store.max_storage_bytes = 1
    for index in range(100):
        with service.store.transaction() as conn:
            service._gap(f"fixture_{index}_" + character * 120, conn)
    health = service.status()["capture"]
    assert health["state"] == "degraded"
    assert len(health["gaps"]) == 64
