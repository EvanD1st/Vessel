"""Encrypted local persistence. Metadata identifiers and Fernet timestamps stay visible.

Windows keys are protected by user-scoped DPAPI. On POSIX the local-preview key
is a 0600 file inside a 0700 directory. Local backups include that recovery
material: they are NOT portable wallet-owned exports. Maintenance collects only
unpinned artifacts; quota pressure preserves recovery sources and rejects writes.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import shutil
import sqlite3
import stat
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from cryptography.fernet import Fernet, InvalidToken

SCHEMA_VERSION = 1
MAX_STORAGE_BYTES = 1024 * 1024 * 1024
DISK_HEADROOM = 16 * 1024 * 1024
MAX_BLOB_BYTES = 2 * 1024 * 1024
MAX_RECORD_BYTES = 8 * 1024 * 1024
MAX_BACKUP_BYTES = 1024 * 1024 * 1024


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def is_link(path: Path) -> bool:
    """Also reject Windows junctions and other reparse points."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def safe_directory(path: Path, *, create: bool = False) -> Path:
    path = Path(os.path.abspath(path))
    for part in reversed((path, *path.parents)):
        if part.exists() or part.is_symlink():
            if is_link(part):
                raise ValueError(f"Symlink or reparse directory is not allowed: {part}")
            if not part.is_dir():
                raise ValueError(f"Expected directory: {part}")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise ValueError(f"Directory does not exist: {path}")
    return path


def _regular_file(path: Path, limit: int) -> bytes:
    if is_link(path) or not path.is_file():
        raise ValueError(f"Expected regular file, not a link: {path}")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError(f"File exceeds allowed size or type: {path.name}")
        value = source.read(limit + 1)
        after = path.lstat()
        if is_link(path) or (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError(f"File changed identity while reading: {path.name}")
    if len(value) > limit:
        raise ValueError(f"File exceeds allowed size: {path.name}")
    return value


def _sync_directory(path: Path) -> None:
    # Windows file handles are flushed with fsync before os.replace. Directory
    # fsync is unavailable there; actual power-loss guarantees depend on the FS.
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _atomic_write(
    path: Path, data: bytes, *, exclusive: bool = False, fault: Callable[[str], None] | None = None
) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.staging")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(data)
            target.flush()
            os.fsync(target.fileno())
        if fault:
            fault("after_blob_flush")
        if exclusive:
            # Hard-link publication gives create-if-absent semantics across processes.
            # The contents are already durable before any DB row can reference them.
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
            temporary.unlink()
        else:
            os.replace(temporary, path)
        _sync_directory(path.parent)
        if fault:
            fault("after_blob_rename")
    except BaseException:
        # Staging remains after a real kill; these files are never referenced.
        temporary.unlink(missing_ok=True)
        raise


def _dpapi(data: bytes, *, decrypt: bool = False) -> bytes:
    """User-scoped Windows Data Protection API with UI explicitly disabled."""
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    memory = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    incoming = DataBlob(len(data), memory)
    outgoing = DataBlob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [
        ctypes.POINTER(DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DataBlob),
    ]
    function.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not function(ctypes.byref(incoming), None, None, None, None, 1, ctypes.byref(outgoing)):
        raise OSError(ctypes.get_last_error(), "Windows key protection failed for this OS user")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        kernel32.LocalFree(outgoing.pbData)


class Store:
    def __init__(self, state_dir: Path, clock: Callable[[], float] = time.time):
        self.dir = safe_directory(Path(state_dir), create=True)
        if os.name != "nt" and self.dir.stat().st_mode & 0o077:
            raise ValueError("Local state directory must have permissions 0700")
        self.clock = clock
        self.db_path = self.dir / "vessel.sqlite3"
        self.key_path = self.dir / "key.dat"
        self.blob_dir = safe_directory(self.dir / "blobs", create=True)
        self._lock = threading.RLock()
        from vessel.locking import ArtifactLock

        self.artifacts = ArtifactLock(self.dir)
        self.max_storage_bytes = MAX_STORAGE_BYTES
        self._fernet = Fernet(self._load_key())
        for candidate in (self.db_path, self.dir / "vessel.sqlite3-wal", self.dir / "vessel.sqlite3-shm"):
            if candidate.exists() and (is_link(candidate) or not candidate.is_file()):
                raise ValueError("Database path is not a regular file")
        self._connection = sqlite3.connect(
            self.db_path, timeout=15, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        if os.name != "nt":
            self.db_path.chmod(0o600)
        self._connection.execute("PRAGMA busy_timeout=15000")
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA trusted_schema=OFF")
        version = self._connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            self.close()
            raise ValueError(f"Unsupported state schema version: {version}")
        with self.transaction() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value BLOB NOT NULL)")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents (kind TEXT NOT NULL, id TEXT NOT NULL, "
                "payload BLOB NOT NULL, PRIMARY KEY(kind,id))"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, "
                "delivery_id TEXT UNIQUE NOT NULL, run_id TEXT NOT NULL, epoch INTEGER NOT NULL, "
                "kind TEXT NOT NULL, digest TEXT NOT NULL, payload BLOB NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS events_run ON events(run_id,seq)")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            row = connection.execute("SELECT value FROM kv WHERE key='encryption_check'").fetchone()
            if row:
                if self.unseal(row[0]) != {"format": "vessel-state", "schema": 1}:
                    raise ValueError("Invalid state encryption marker")
            else:
                connection.execute(
                    "INSERT INTO kv(key,value) VALUES('encryption_check',?)",
                    (self.seal({"format": "vessel-state", "schema": 1}),),
                )
            budget = connection.execute("SELECT value FROM kv WHERE key='blob_budget'").fetchone()
            if budget is None:
                # One-time initialization/migration, never a scan on ordinary hook deliveries.
                reserved = sum(path.stat().st_size for path in self.blob_dir.iterdir() if path.is_file())
                connection.execute(
                    "INSERT INTO kv(key,value) VALUES('blob_budget',?)",
                    (self.seal({"reserved_bytes": reserved}),),
                )

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def _load_key(self) -> bytes:
        if not self.key_path.exists():
            if self.db_path.exists():
                raise ValueError("State key is missing; restore documented local recovery material")
            raw = Fernet.generate_key()
            wrapped = b"VESSEL-DPAPI-1\n" + _dpapi(raw) if os.name == "nt" else b"VESSEL-POSIX-1\n" + raw
            _atomic_write(self.key_path, wrapped, exclusive=True)
        wrapped = _regular_file(self.key_path, 16384)
        if wrapped.startswith(b"VESSEL-DPAPI-1\n") and os.name == "nt":
            return _dpapi(wrapped.split(b"\n", 1)[1], decrypt=True)
        if wrapped.startswith(b"VESSEL-POSIX-1\n") and os.name != "nt":
            if self.key_path.stat().st_mode & 0o077:
                raise ValueError("Local key must have permissions 0600")
            return wrapped.split(b"\n", 1)[1]
        raise ValueError("Recovery key is unavailable on this operating system/user")

    def seal(self, obj: Any) -> bytes:
        data = canonical_json(obj)
        if len(data) > MAX_RECORD_BYTES:
            raise ValueError("Encrypted record exceeds 8 MiB limit")
        return self._fernet.encrypt(data)

    def unseal(self, ciphertext: bytes) -> Any:
        if len(ciphertext) > MAX_RECORD_BYTES * 2:
            raise ValueError("Encrypted record exceeds limit")
        try:
            return json.loads(self._fernet.decrypt(ciphertext))
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Encrypted state failed integrity verification") from error

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._connection.in_transaction:
                raise RuntimeError("Nested storage transactions are not supported; pass conn explicitly")
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                self._connection.commit()
            except BaseException:
                self._connection.rollback()
                raise

    def _bound(self, kind: str, identifier: str, ciphertext: bytes) -> Any:
        value = self.unseal(ciphertext)
        if (
            not isinstance(value, dict)
            or value.get("binding") != [kind, identifier]
            or "payload" not in value
        ):
            raise ValueError("Encrypted record does not match its identity")
        return value["payload"]

    def get(self, kind: str, id: str, conn: sqlite3.Connection | None = None) -> dict | None:
        with self._lock:
            row = (
                (conn or self.connection)
                .execute("SELECT payload FROM documents WHERE kind=? AND id=?", (kind, id))
                .fetchone()
            )
            return self._bound(kind, id, row[0]) if row else None

    def put(
        self,
        kind: str,
        id: str,
        payload: dict,
        conn: sqlite3.Connection | None = None,
        *,
        critical: bool = False,
    ) -> None:
        if not isinstance(payload, dict):
            raise ValueError("Document payload must be an object")
        encrypted = self.seal({"binding": [kind, id], "payload": payload})
        if critical:
            if kind != "control" or len(encrypted) > 16384:
                raise ValueError("Emergency metadata must be a bounded control record")
        else:
            self.ensure_capacity(len(encrypted) + 32768)
        if conn is None:
            with self.transaction() as active:
                self.put(kind, id, payload, conn=active, critical=critical)
            return
        conn.execute(
            "INSERT INTO documents(kind,id,payload) VALUES(?,?,?) "
            "ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload",
            (kind, id, encrypted),
        )

    def delete(self, kind: str, id: str, conn: sqlite3.Connection | None = None) -> None:
        if conn is None:
            with self.transaction() as active:
                self.delete(kind, id, conn=active)
            return
        conn.execute("DELETE FROM documents WHERE kind=? AND id=?", (kind, id))

    def list(self, kind: str, conn: sqlite3.Connection | None = None) -> list[dict]:
        with self._lock:
            rows = (
                (conn or self.connection)
                .execute("SELECT id,payload FROM documents WHERE kind=? ORDER BY id", (kind,))
                .fetchall()
            )
            return [self._bound(kind, row[0], row[1]) for row in rows]

    def append_event(
        self,
        delivery_id: str,
        run_id: str,
        epoch: int,
        kind: str,
        payload: dict,
        conn: sqlite3.Connection | None = None,
    ) -> tuple[int, bool]:
        if conn is None:
            with self.transaction() as active:
                return self.append_event(delivery_id, run_id, epoch, kind, payload, conn=active)
        identity = {
            "delivery_id": delivery_id,
            "run_id": run_id,
            "epoch": epoch,
            "kind": kind,
            "payload": payload,
        }
        fingerprint = digest(identity)
        row = conn.execute(
            "SELECT seq,digest,payload FROM events WHERE delivery_id=?", (delivery_id,)
        ).fetchone()
        if row:
            old = self._bound("event", delivery_id, row[2])
            if row[1] != fingerprint or old != identity:
                raise ValueError("Conflicting duplicate event delivery ID")
            return row[0], False
        encrypted = self.seal({"binding": ["event", delivery_id], "payload": identity})
        self.ensure_capacity(len(encrypted) + 32768)
        cursor = conn.execute(
            "INSERT INTO events(delivery_id,run_id,epoch,kind,digest,payload) VALUES(?,?,?,?,?,?)",
            (delivery_id, run_id, epoch, kind, fingerprint, encrypted),
        )
        return int(cursor.lastrowid), True

    def events(
        self, run_id: str | None = None, through: int | None = None, conn: sqlite3.Connection | None = None
    ) -> list[dict]:
        clauses, arguments = [], []
        if run_id is not None:
            clauses.append("run_id=?")
            arguments.append(run_id)
        if through is not None:
            clauses.append("seq<=?")
            arguments.append(through)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            rows = (conn or self.connection).execute(
                "SELECT * FROM events" + where + " ORDER BY seq", arguments
            )
            result = []
            for row in rows:
                value = self._bound("event", row["delivery_id"], row["payload"])
                if (value["run_id"], value["epoch"], value["kind"], digest(value)) != (
                    row["run_id"],
                    row["epoch"],
                    row["kind"],
                    row["digest"],
                ):
                    raise ValueError("Event metadata failed integrity verification")
                result.append({"seq": row["seq"], **value})
            return result

    def storage_bytes(self) -> int:
        total = 0
        for root, directories, files in os.walk(self.dir, followlinks=False):
            for directory in directories:
                if is_link(Path(root) / directory):
                    raise ValueError("Unexpected link in local state")
            for name in files:
                path = Path(root) / name
                if is_link(path):
                    raise ValueError("Unexpected link in local state")
                total += path.stat().st_size
        return total

    def ensure_capacity(self, additional: int) -> None:
        row = self.connection.execute("SELECT value FROM kv WHERE key='blob_budget'").fetchone()
        reserved = self.unseal(row[0])["reserved_bytes"] if row else 0
        # Account for live DB/WAL growth with a fixed number of stats. Blob reservations
        # include temporary publication space and survive crashes. Locked GC reconciles them.
        database_bytes = 0
        for path in (
            self.db_path,
            self.key_path,
            self.dir / "vessel.sqlite3-wal",
            self.dir / "vessel.sqlite3-shm",
        ):
            if path.exists():
                if is_link(path):
                    raise ValueError("Unexpected link in local state")
                database_bytes += path.stat().st_size
        if reserved + database_bytes + additional > self.max_storage_bytes:
            raise ValueError("Local storage quota reached; existing recovery sources were preserved")
        if shutil.disk_usage(self.dir).free < additional + DISK_HEADROOM:
            raise ValueError("Insufficient disk headroom for durable capture")

    def write_blob(self, content: bytes, fault: Callable[[str], None] | None = None) -> str:
        with self.artifacts.hold():
            return self._write_blob(content, fault)

    def _write_blob(self, content: bytes, fault: Callable[[str], None] | None = None) -> str:
        if len(content) > MAX_BLOB_BYTES:
            raise ValueError("Artifact exceeds 2 MiB limit")
        identifier = hashlib.sha256(content).hexdigest()
        path = self.blob_dir / f"{identifier}.blob"
        if path.exists():
            if self.read_blob(identifier) != content:
                raise ValueError("Existing blob is corrupt")
            return identifier
        ciphertext = self.seal(
            {"binding": ["blob", identifier], "payload": base64.b64encode(content).decode("ascii")}
        )
        with self._lock:
            # Reserve conservatively before touching files; interrupted copies cannot
            # silently exceed the budget. Duplicate racing writers may over-reserve.
            with self.transaction() as connection:
                self.ensure_capacity(2 * len(ciphertext) + 32768)
                row = connection.execute("SELECT value FROM kv WHERE key='blob_budget'").fetchone()
                budget = self.unseal(row[0])
                budget["reserved_bytes"] += 2 * len(ciphertext)
                connection.execute("UPDATE kv SET value=? WHERE key='blob_budget'", (self.seal(budget),))
            _atomic_write(path, ciphertext, exclusive=True, fault=fault)
        if self.read_blob(identifier) != content:
            raise ValueError("Stored blob failed verification")
        return identifier

    def read_blob(self, identifier: str) -> bytes:
        if (
            not isinstance(identifier, str)
            or len(identifier) != 64
            or any(c not in "0123456789abcdef" for c in identifier)
        ):
            raise ValueError("Invalid artifact blob identifier")
        encrypted = _regular_file(self.blob_dir / f"{identifier}.blob", MAX_BLOB_BYTES * 3)
        encoded = self._bound("blob", identifier, encrypted)
        try:
            value = base64.b64decode(encoded, validate=True)
        except (TypeError, ValueError) as error:
            raise ValueError("Invalid encrypted blob payload") from error
        if len(value) > MAX_BLOB_BYTES or hashlib.sha256(value).hexdigest() != identifier:
            raise ValueError("Artifact digest failed verification")
        return value

    def backup(self, destination: Path) -> dict:
        with self.artifacts.hold():
            return self._backup(destination)

    def _backup(self, destination: Path) -> dict:
        destination = Path(os.path.abspath(destination))
        if (
            destination == self.dir
            or destination.is_relative_to(self.dir)
            or self.dir.is_relative_to(destination)
        ):
            raise ValueError("Backup destination must be separate from state directory")
        safe_directory(destination.parent, create=True)
        if destination.exists():
            raise ValueError("Backup destination already exists")
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.staging")
        staging.mkdir(mode=0o700)
        try:
            with self._lock:
                if self.connection.in_transaction:
                    raise ValueError("Backup cannot run inside a write transaction")
                target_db = staging / "vessel.sqlite3"
                target = sqlite3.connect(target_db)
                try:
                    self.connection.backup(target)
                    # Verify every checkpoint reference in the exact DB snapshot,
                    # including blobs missing from the directory enumeration.
                    for kind, record_id, payload in target.execute(
                        "SELECT kind,id,payload FROM documents WHERE kind='checkpoints'"
                    ):
                        checkpoint = self._bound(kind, record_id, payload)
                        for record in checkpoint.get("manifest", {}).get("files", []):
                            self.read_blob(record["blob"])
                finally:
                    target.close()
                # The artifact lock pins the complete snapshot through verified
                # publication. Concurrent collectors cannot remove its blobs.
                blob_destination = staging / "blobs"
                blob_destination.mkdir(mode=0o700)
                files = {}
                for source in sorted(self.blob_dir.iterdir()):
                    if source.name.endswith(".staging"):
                        continue
                    identifier = source.stem
                    self.read_blob(identifier)
                    data = _regular_file(source, MAX_BLOB_BYTES * 3)
                    _atomic_write(blob_destination / source.name, data)
                    files[f"blobs/{source.name}"] = hashlib.sha256(data).hexdigest()
                key_data = _regular_file(self.key_path, 16384)
                _atomic_write(staging / "key.dat", key_data)
                with target_db.open("rb+") as source:
                    files["vessel.sqlite3"] = hashlib.file_digest(source, "sha256").hexdigest()
                    os.fsync(source.fileno())
                files["key.dat"] = hashlib.sha256(key_data).hexdigest()
                manifest = {
                    "format": "vessel-local-backup",
                    "schema_version": 1,
                    "created_at": self.clock(),
                    "custody": "same-os-user-local-recovery",
                    "files": files,
                }
                _atomic_write(staging / "backup.manifest", self.seal(manifest))
                _sync_directory(staging)
                os.rename(staging, destination)
                _sync_directory(destination.parent)
                return {
                    "path": str(destination),
                    "created_at": manifest["created_at"],
                    "verified": True,
                    "custody": manifest["custody"],
                    "files": len(files),
                }
        except BaseException:
            # Preserve staging for diagnosis, but never publish a successful backup.
            raise

    @classmethod
    def restore_local(cls, backup_dir: Path, destination_dir: Path) -> "Store":
        backup_dir = safe_directory(Path(backup_dir))
        destination_dir = Path(os.path.abspath(destination_dir))
        if destination_dir.exists():
            raise ValueError("Restore destination already exists; current state is never overwritten")
        if destination_dir.is_relative_to(backup_dir) or backup_dir.is_relative_to(destination_dir):
            raise ValueError("Restore destination must be separate from backup")
        safe_directory(destination_dir.parent, create=True)
        key_data = _regular_file(backup_dir / "key.dat", 16384)
        if key_data.startswith(b"VESSEL-DPAPI-1\n") and os.name == "nt":
            raw_key = _dpapi(key_data.split(b"\n", 1)[1], decrypt=True)
        elif key_data.startswith(b"VESSEL-POSIX-1\n") and os.name != "nt":
            raw_key = key_data.split(b"\n", 1)[1]
        else:
            raise ValueError("Backup key is not recoverable by this operating system/user")
        try:
            manifest = json.loads(
                Fernet(raw_key).decrypt(_regular_file(backup_dir / "backup.manifest", 8 * 1024 * 1024))
            )
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Backup manifest failed authentication") from error
        if manifest.get("format") != "vessel-local-backup" or manifest.get("schema_version") != 1:
            raise ValueError("Unsupported backup format")
        files = manifest.get("files")
        if (
            not isinstance(files, dict)
            or not {"key.dat", "vessel.sqlite3"}.issubset(files)
            or len(files) > 100002
        ):
            raise ValueError("Invalid backup file manifest")
        total = 0
        for relative, expected in files.items():
            allowed = relative in {"key.dat", "vessel.sqlite3"} or (
                isinstance(relative, str)
                and relative.startswith("blobs/")
                and relative.endswith(".blob")
                and len(relative) == 75
                and all(c in "0123456789abcdef" for c in relative[6:-5])
            )
            if not allowed:
                raise ValueError("Backup contains an invalid path")
            path = backup_dir / relative
            safe_directory(path.parent)
            data = _regular_file(
                path, MAX_BACKUP_BYTES if relative == "vessel.sqlite3" else MAX_BLOB_BYTES * 3
            )
            total += len(data)
            if total > MAX_BACKUP_BYTES or hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("Backup exceeds limits or failed integrity verification")
        staging = destination_dir.with_name(f".{destination_dir.name}.{uuid.uuid4().hex}.staging")
        staging.mkdir(mode=0o700)
        for relative in files:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            data = _regular_file(
                backup_dir / relative,
                MAX_BACKUP_BYTES if relative == "vessel.sqlite3" else MAX_BLOB_BYTES * 3,
            )
            if hashlib.sha256(data).hexdigest() != files[relative]:
                raise ValueError("Backup changed during restoration")
            _atomic_write(target, data)
        restored = cls(staging)
        try:
            if restored.connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Restored database failed integrity check")
            restored.events()
            for row in restored.connection.execute("SELECT kind,id,payload FROM documents"):
                restored._bound(row[0], row[1], row[2])
            for blob in restored.blob_dir.glob("*.blob"):
                restored.read_blob(blob.stem)
            with restored.transaction() as connection:
                connection.execute(
                    "INSERT OR REPLACE INTO kv(key,value) VALUES('restored_history',?)",
                    (restored.seal({"restored_at": time.time(), "requires_fresh_authority": True}),),
                )
                restored.put(
                    "control",
                    "restored",
                    {"inspection_only": True, "restored_at": time.time()},
                    conn=connection,
                )
        finally:
            restored.close()
        os.rename(staging, destination_dir)
        _sync_directory(destination_dir.parent)
        return cls(destination_dir)

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
