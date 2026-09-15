"""Bounded workspace snapshots, integrity checks and non-destructive restoration."""

from __future__ import annotations

import ctypes
import hashlib
import os
import platform
import re
import stat
import uuid
from pathlib import Path, PurePosixPath
from typing import Callable

from .storage import Store, _atomic_write, _sync_directory, is_link, safe_directory

MAX_FILES = 1000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_SCAN_ENTRIES = 20000
EXCLUDED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    ".cline",
    ".clinerules",
    ".vscode",
    ".vessel",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "vendor",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    ".cache",
    "dist",
    "build",
    "coverage",
    ".tox",
    ".nox",
    ".idea",
    ".ssh",
    ".aws",
    ".azure",
    ".gcp",
}
EXCLUDED_SUFFIXES = {
    ".pem",
    ".key",
    ".p12",
    ".pfx",
    ".keystore",
    ".kdbx",
    ".crt",
    ".der",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".log",
}
LOCK_FILES = {
    "uv.lock",
    "poetry.lock",
    "Pipfile.lock",
    "requirements.txt",
    "requirements.lock",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "Cargo.lock",
    "go.sum",
}
SECRET_PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(rb"(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})"),
    re.compile(
        rb"(?im)^\s*(?:api[_-]?key|secret[_-]?key|access[_-]?token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_+/=-]{16,}"
    ),
]
WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("Artifact path is not a safe relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Artifact path traversal is not allowed")
    for part in path.parts:
        if part.endswith((".", " ")) or part.split(".")[0].lower() in WINDOWS_RESERVED:
            raise ValueError("Artifact path is unsafe on Windows")
        if any(ord(character) < 32 or character in '<>"|?*' for character in part):
            raise ValueError("Artifact path contains unsupported characters")
    return path.as_posix()


def _exclusion(relative: str, directory: bool = False) -> str | None:
    parts = PurePosixPath(relative).parts
    if any(part.lower() in EXCLUDED_DIRECTORIES for part in parts):
        return "excluded dependency, generated, configuration or secret directory"
    name = parts[-1].lower()
    if name.startswith(".env") or name in {
        ".npmrc",
        ".pypirc",
        ".netrc",
        "key.dat",
        "credentials",
        "credentials.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
        "id_rsa",
        "id_ed25519",
        "id_ecdsa",
        "id_dsa",
    }:
        return "excluded credential or environment file"
    if not directory and (PurePosixPath(name).suffix in EXCLUDED_SUFFIXES or name.endswith(("-wal", "-shm"))):
        return "excluded secret, generated binary, database or archive"
    return None


def _identity(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _opened_path(descriptor: int, fallback: Path) -> Path:
    if os.name == "nt":
        import msvcrt
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        function = kernel32.GetFinalPathNameByHandleW
        function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        function.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = function(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise ValueError("Cannot establish opened file scope")
        result = buffer.value
        if result.startswith("\\\\?\\UNC\\"):
            result = "\\\\" + result[8:]
        elif result.startswith("\\\\?\\"):
            result = result[4:]
        return Path(result).resolve()
    proc_fd = Path(f"/proc/self/fd/{descriptor}")
    if proc_fd.exists():
        return proc_fd.resolve()
    return fallback.resolve(strict=True)


class Artifacts:
    def __init__(self, workspace: Path, store: Store):
        # Verification/restoration of saved blobs still works after the source directory is lost.
        absolute = Path(os.path.abspath(workspace))
        self.workspace = safe_directory(absolute) if absolute.exists() or absolute.is_symlink() else absolute
        self.store = store

    def _inventory(self) -> tuple[dict[str, tuple], list[dict], list[str]]:
        files: dict[str, tuple] = {}
        excluded: list[dict] = []
        issues: list[str] = []
        scanned = 0
        pending = [self.workspace]
        while pending:
            current = pending.pop()
            try:
                if is_link(current) or not current.resolve().is_relative_to(self.workspace):
                    raise ValueError("Directory scope changed")
                with os.scandir(current) as stream:
                    # Limit enumeration itself before sorting: large directories
                    # cannot create an unbounded memory allocation.
                    entries = []
                    for entry in stream:
                        scanned += 1
                        if scanned > MAX_SCAN_ENTRIES:
                            issues.append("Workspace scan entry limit reached")
                            excluded.append(
                                {
                                    "path": current.relative_to(self.workspace).as_posix(),
                                    "reason": "remaining entries omitted by scan limit",
                                }
                            )
                            return files, excluded, issues
                        entries.append(entry)
                for entry in sorted(entries, key=lambda item: item.name.casefold()):
                    path = Path(entry.path)
                    relative = path.relative_to(self.workspace).as_posix()
                    try:
                        _relative(relative)
                        if is_link(path):
                            excluded.append({"path": relative, "reason": "symlink or reparse point"})
                            continue
                        if path == self.store.dir or path.is_relative_to(self.store.dir):
                            excluded.append({"path": relative, "reason": "VESSEL state storage"})
                            continue
                        info = path.stat(follow_symlinks=False)
                        directory = stat.S_ISDIR(info.st_mode)
                        reason = _exclusion(relative, directory)
                        if reason:
                            excluded.append({"path": relative, "reason": reason})
                        elif directory:
                            pending.append(path)
                        elif not stat.S_ISREG(info.st_mode):
                            excluded.append({"path": relative, "reason": "non-regular file"})
                        elif info.st_size > MAX_FILE_BYTES:
                            excluded.append({"path": relative, "reason": "2 MiB file size limit"})
                        elif len(files) >= MAX_FILES:
                            excluded.append({"path": relative, "reason": "1000 file count limit"})
                        else:
                            files[relative] = _identity(info)
                    except (OSError, ValueError) as error:
                        excluded.append({"path": relative, "reason": str(error)})
                        issues.append(f"Could not safely inspect {relative}")
            except (OSError, ValueError) as error:
                issues.append(f"Directory scan failed: {error}")
        return files, excluded, issues

    def _read(self, relative: str) -> tuple[bytes, tuple]:
        relative = _relative(relative)
        path = self.workspace / relative
        if _exclusion(relative):
            raise ValueError("Artifact is excluded by capture policy")
        safe_directory(path.parent)
        if is_link(path) or not path.resolve(strict=True).is_relative_to(self.workspace):
            raise ValueError("Artifact escaped the approved workspace")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as source:
            opened = _opened_path(source.fileno(), path)
            if not opened.is_relative_to(self.workspace) or opened.is_relative_to(self.store.dir):
                raise ValueError("Opened artifact escaped the approved workspace")
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
                raise ValueError("Artifact exceeds permitted file type or size")
            data = source.read(MAX_FILE_BYTES + 1)
            after = os.fstat(source.fileno())
        if len(data) > MAX_FILE_BYTES or _identity(before) != _identity(after):
            raise ValueError("Artifact changed during bounded read")
        safe_directory(path.parent)
        if is_link(path) or _identity(path.stat()) != _identity(after):
            raise ValueError("Artifact path changed during capture")
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            raise ValueError("Artifact contains a recognizable credential; omitted entirely")
        return data, _identity(after)

    def capture(
        self, required_paths: list[str] | None = None, fault: Callable[[str], None] | None = None
    ) -> dict:
        with self.store.artifacts.hold():
            return self._capture(required_paths, fault)

    def _capture(self, required_paths, fault):
        required = [_relative(value) for value in (required_paths or [])]
        if len(required) > MAX_FILES:
            raise ValueError("Too many required artifact paths")
        manifest: dict = {}
        for attempt in range(2):
            inventory, excluded, issues = self._inventory()
            captured, total = [], 0
            for relative, identity in sorted(inventory.items()):
                try:
                    content, observed = self._read(relative)
                    if observed != identity:
                        issues.append(f"Artifact changed before read: {relative}")
                    if total + len(content) > MAX_TOTAL_BYTES:
                        excluded.append({"path": relative, "reason": "50 MiB total capture limit"})
                        continue
                    if fault:
                        fault("after_read")
                    blob = self.store.write_blob(content, fault=fault)
                    captured.append(
                        {
                            "path": relative,
                            "digest": hashlib.sha256(content).hexdigest(),
                            "blob": blob,
                            "size": len(content),
                        }
                    )
                    total += len(content)
                except (OSError, ValueError) as error:
                    excluded.append({"path": relative, "reason": str(error)})
                    # A recognized secret is an intentional exclusion. Storage
                    # failure or unexpected read failure means degraded capture.
                    if "recognizable credential" not in str(error):
                        issues.append(f"Artifact capture failed: {relative}: {error}")
            after, after_excluded, after_issues = self._inventory()
            if inventory != after:
                issues.append("Workspace changed during capture")
            issues.extend(after_issues)
            for record in captured:
                try:
                    content, _ = self._read(record["path"])
                    if hashlib.sha256(content).hexdigest() != record["digest"]:
                        issues.append(f"Artifact content changed during capture: {record['path']}")
                except (OSError, ValueError) as error:
                    issues.append(f"Artifact no longer stable: {record['path']}: {error}")
            names = {item["path"] for item in captured}
            # Include newly excluded files as evidence of observed coverage.
            known_exclusions = {(item["path"], item["reason"]) for item in excluded}
            excluded.extend(
                item for item in after_excluded if (item["path"], item["reason"]) not in known_exclusions
            )
            manifest = {
                "schema_version": 1,
                "files": captured,
                "excluded": excluded,
                "stable": not issues,
                "missing": sorted(set(required) - names),
                "required_paths": required,
                "issues": list(dict.fromkeys(issues)),
                "total_bytes": total,
                "attempts": attempt + 1,
                "scope": "approved local project files; no external services or databases",
            }
            if manifest["stable"]:
                break
        return manifest

    def _records(self, manifest: dict) -> list[dict]:
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
            raise ValueError("Unsupported artifact manifest schema")
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) > MAX_FILES:
            raise ValueError("Invalid artifact file manifest or file count")
        total, names = 0, set()
        for record in files:
            if not isinstance(record, dict):
                raise ValueError("Invalid artifact record")
            relative = _relative(record.get("path"))
            normalized = relative.casefold()
            if normalized in names or _exclusion(relative):
                raise ValueError("Manifest contains a duplicate or excluded path")
            if any(normalized.startswith(name + "/") or name.startswith(normalized + "/") for name in names):
                raise ValueError("Manifest contains colliding file and directory paths")
            names.add(normalized)
            size = record.get("size")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0 or size > MAX_FILE_BYTES:
                raise ValueError("Artifact file exceeds permitted size")
            total += size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("Artifact manifest exceeds 50 MiB capture limit")
            blob = record.get("blob")
            if not isinstance(blob, str) or len(blob) != 64 or any(c not in "0123456789abcdef" for c in blob):
                raise ValueError("Invalid artifact blob identifier")
            if record.get("digest") != blob:
                raise ValueError("Artifact digest does not match blob identity")
        return files

    def verify(self, manifest: dict) -> list[str]:
        try:
            records = self._records(manifest)
        except (ValueError, TypeError) as error:
            return [str(error)]
        blockers = []
        if manifest.get("stable") is not True:
            blockers.append("Artifact capture is best-effort or unstable")
        missing = manifest.get("missing", [])
        if not isinstance(missing, list):
            blockers.append("Invalid required artifact coverage")
        elif missing:
            blockers.append("Required artifacts missing: " + ", ".join(str(value) for value in missing))
        try:
            required = {_relative(value) for value in manifest.get("required_paths", [])}
            uncovered = required - {record["path"] for record in records}
            if uncovered and not missing:
                blockers.append("Required artifacts missing: " + ", ".join(sorted(uncovered)))
        except (ValueError, TypeError) as error:
            blockers.append(f"Invalid required artifact coverage: {error}")
        for record in records:
            try:
                content = self.store.read_blob(record["blob"])
                if len(content) != record["size"]:
                    raise ValueError("Artifact size does not match manifest")
            except (OSError, ValueError) as error:
                blockers.append(f"Corrupt or missing artifact {record['path']}: {error}")
        return blockers

    def diff(self, manifest: dict) -> dict:
        records = self._records(manifest)
        current, excluded, issues = self._inventory()
        missing, changed = [], []
        for record in records:
            if record["path"] not in current:
                missing.append(record["path"])
                continue
            try:
                data, _ = self._read(record["path"])
                if hashlib.sha256(data).hexdigest() != record["digest"]:
                    changed.append(record["path"])
            except (OSError, ValueError):
                changed.append(record["path"])
        expected = {record["path"] for record in records}
        return {
            "missing": missing,
            "changed": changed,
            "extra": sorted(set(current) - expected),
            "issues": issues,
            "excluded": excluded,
        }

    def restore(self, manifest: dict, destination: Path) -> dict:
        with self.store.artifacts.hold():
            return self._restore(manifest, destination)

    def _restore(self, manifest: dict, destination: Path) -> dict:
        blockers = self.verify(manifest)
        if blockers:
            raise ValueError("Cannot restore invalid capture: " + "; ".join(blockers))
        destination = Path(os.path.abspath(destination))
        for protected in (self.workspace, self.store.dir):
            if (
                destination == protected
                or destination.is_relative_to(protected)
                or protected.is_relative_to(destination)
            ):
                raise ValueError("Restore destination must be separate from workspace and state")
        safe_directory(destination.parent, create=True)
        if destination.exists():
            safe_directory(destination)
            if any(destination.iterdir()):
                raise ValueError(
                    "Restore destination must be new or empty; existing work is never overwritten"
                )
        staging = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.staging")
        staging.mkdir(mode=0o700)
        for record in self._records(manifest):
            target = staging / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _atomic_write(target, self.store.read_blob(record["blob"]))
        if destination.exists():
            destination.rmdir()  # Fails closed if new content appeared.
        os.rename(staging, destination)
        _sync_directory(destination.parent)
        return {"destination": str(destination), "files": len(manifest["files"]), "restored": True}

    def environment(self) -> dict:
        from vessel.environment import inspect_requirements

        locks = {}
        errors = []
        for name in sorted(LOCK_FILES):
            path = self.workspace / name
            if path.exists():
                try:
                    data, _ = self._read(name)
                    locks[name] = hashlib.sha256(data).hexdigest()
                except (OSError, ValueError) as error:
                    errors.append(f"Could not inspect dependency file {name}: {error}")
        declared = inspect_requirements(self)
        client = declared["requirements"]["client"]
        return {
            "schema_version": 2,
            "os": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "lock_digests": locks,
            "errors": errors,
            "client_version": client["version"] if client else "unverified",
            "client_capabilities": client["capabilities"] if client else [],
            "client_provenance": "owner_declared" if client else "unverified",
            "services": declared["requirements"]["services"],
            "secret_references": declared["requirements"]["secret_references"],
            "database_schema": declared["requirements"]["databases"],
            "git": {"status": "not inspected"},
            "dependency_status": "lock digests observed; installed dependencies require owner preflight",
            **declared,
        }
