import hashlib
import os
import sqlite3
import subprocess
import sys

import pytest

from vessel.storage import Store


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "state")
    yield instance
    instance.close()


def test_durable_encrypted_records_and_transaction_rollback(store):
    store.put("mission", "first", {"text": "private recovery instruction"})
    with pytest.raises(RuntimeError):
        with store.transaction() as conn:
            store.put("mission", "rolled-back", {"text": "not committed"}, conn=conn)
            raise RuntimeError("simulated process failure before commit")
    assert store.get("mission", "rolled-back") is None
    with Store(store.dir) as restarted:
        assert restarted.get("mission", "first") == {"text": "private recovery instruction"}
    for path in store.dir.glob("vessel.sqlite3*"):
        assert b"private recovery instruction" not in path.read_bytes()
    assert b"private recovery instruction" not in store.seal({"text": "private recovery instruction"})


def test_ciphertext_tampering_and_record_swapping_rejected(store):
    store.put("mission", "one", {"text": "first"})
    store.put("mission", "two", {"text": "second"})
    payload = store.connection.execute("SELECT payload FROM documents WHERE id='one'").fetchone()[0]
    store.connection.execute("UPDATE documents SET payload=? WHERE id='two'", (payload,))
    with pytest.raises(ValueError, match="identity"):
        store.get("mission", "two")
    with pytest.raises(ValueError, match="integrity"):
        store.unseal(payload[:-6] + b"broken")


def test_duplicate_delivery_conflict_and_event_watermark(store):
    first = store.append_event("delivery-1", "run-1", 1, "intent", {"operation": "write"})
    assert first == (1, True)
    assert store.append_event("delivery-1", "run-1", 1, "intent", {"operation": "write"}) == (1, False)
    with pytest.raises(ValueError, match="Conflicting"):
        store.append_event("delivery-1", "run-2", 1, "intent", {"operation": "write"})
    store.append_event("delivery-2", "run-2", 2, "result", {"ok": True})
    assert len(store.events(through=1)) == 1
    assert store.events(run_id="run-2")[0]["seq"] == 2
    store.connection.execute("UPDATE events SET epoch=4 WHERE seq=1")
    with pytest.raises(ValueError, match="metadata"):
        store.events()


def test_active_wal_backup_restores_committed_state_and_blocks_authority(store, tmp_path):
    store.connection.execute("PRAGMA wal_autocheckpoint=0")
    store.put("mission", "one", {"text": "committed while WAL active"})
    blob = store.write_blob(b"saved project source")
    store.put("checkpoint", "one", {"blob": blob, "commit_state": "committed"})
    assert (store.dir / "vessel.sqlite3-wal").stat().st_size > 0
    result = store.backup(tmp_path / "backup")
    assert result["verified"] is True
    assert not (tmp_path / "backup" / "vessel.sqlite3-wal").exists()
    restored = Store.restore_local(tmp_path / "backup", tmp_path / "restored")
    try:
        assert restored.get("mission", "one")["text"] == "committed while WAL active"
        assert restored.read_blob(blob) == b"saved project source"
        assert restored.get("control", "restored")["inspection_only"] is True
    finally:
        restored.close()
    with pytest.raises(ValueError, match="already exists"):
        Store.restore_local(tmp_path / "backup", tmp_path / "restored")


def test_backup_tampering_and_future_schema_rejected(store, tmp_path):
    store.put("mission", "one", {"text": "authentic"})
    store.backup(tmp_path / "backup")
    database = tmp_path / "backup" / "vessel.sqlite3"
    with database.open("ab") as target:
        target.write(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        Store.restore_local(tmp_path / "backup", tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("PRAGMA user_version=999")
    with pytest.raises(ValueError, match="schema"):
        Store(store.dir)


def test_backup_authenticated_path_escape_rejected(store, tmp_path):
    store.backup(tmp_path / "backup")
    path = tmp_path / "backup" / "backup.manifest"
    manifest = store.unseal(path.read_bytes())
    manifest["files"]["../outside"] = "0" * 64
    path.write_bytes(store.seal(manifest))
    with pytest.raises(ValueError, match="invalid path"):
        Store.restore_local(tmp_path / "backup", tmp_path / "restored")


def test_blob_corruption_and_staging_crash_do_not_publish(store):
    def failure(stage):
        if stage == "after_blob_flush":
            raise RuntimeError("crash before blob publication")

    content = b"uncommitted project file"
    with pytest.raises(RuntimeError):
        store.write_blob(content, fault=failure)
    identifier = hashlib.sha256(content).hexdigest()
    assert not (store.blob_dir / f"{identifier}.blob").exists()
    committed = store.write_blob(content)
    (store.blob_dir / f"{committed}.blob").write_bytes(b"not authentic")
    with pytest.raises(ValueError, match="integrity"):
        store.read_blob(committed)
    with pytest.raises(ValueError):
        store.write_blob(content)


@pytest.mark.parametrize("stage", ["after_blob_flush", "after_blob_rename"])
def test_actual_process_exit_does_not_publish_checkpoint(tmp_path, stage):
    directory = tmp_path / "interrupted state"
    script = "\n".join(
        [
            "import os,sys",
            "from pathlib import Path",
            "from vessel.storage import Store",
            "store = Store(Path(sys.argv[1]))",
            "store.put('checkpoint', 'older', {'commit_state': 'committed'})",
            "def stop(stage):",
            "    if stage == sys.argv[2]: os._exit(73)",
            "store.write_blob(b'not a committed checkpoint', fault=stop)",
            "store.put('checkpoint', 'new', {'commit_state': 'committed'})",
        ]
    )
    process = subprocess.run([sys.executable, "-c", script, str(directory), stage], capture_output=True)
    assert process.returncode == 73, process.stderr.decode(errors="replace")
    with Store(directory) as restarted:
        assert restarted.get("checkpoint", "older")["commit_state"] == "committed"
        assert restarted.get("checkpoint", "new") is None
        assert len(restarted.list("checkpoint")) == 1


def test_quota_and_low_disk_preserve_existing_state(store, monkeypatch):
    store.put("checkpoint", "valid", {"state": "retained"})
    store.max_storage_bytes = store.storage_bytes()
    with pytest.raises(ValueError, match="quota"):
        store.put("checkpoint", "new", {"state": "not saved"})
    assert store.get("checkpoint", "valid") == {"state": "retained"}
    assert store.get("checkpoint", "new") is None
    store.max_storage_bytes = 1024 * 1024 * 1024
    from collections import namedtuple

    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("vessel.storage.shutil.disk_usage", lambda _: usage(100, 100, 0))
    with pytest.raises(ValueError, match="headroom"):
        store.write_blob(b"no space")


def test_state_directory_link_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError:
        pytest.skip("OS user cannot create symlinks")
    with pytest.raises(ValueError, match="Symlink|reparse"):
        Store(link)


def test_windows_key_is_dpapi_wrapped_or_posix_key_is_private(store):
    data = store.key_path.read_bytes()
    if os.name == "nt":
        assert data.startswith(b"VESSEL-DPAPI-1\n")
        assert len(data) > 60
    else:
        assert data.startswith(b"VESSEL-POSIX-1\n")
        assert store.key_path.stat().st_mode & 0o077 == 0
