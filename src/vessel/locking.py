"""Cross-process artifact publication/collection lock, released by the OS on exit."""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from vessel.storage import is_link


class ArtifactLock:
    def __init__(self, directory: Path):
        self.path = directory / "artifact.lock"
        self.local = threading.RLock()
        self.depth = threading.local()

    @contextmanager
    def hold(self, *, timeout=30):
        acquired = self.local.acquire(timeout=timeout)
        if not acquired:
            raise TimeoutError("Artifact worker is busy")
        stream = None
        try:
            depth = getattr(self.depth, "value", 0)
            if depth:
                self.depth.value = depth + 1
                try:
                    yield
                finally:
                    self.depth.value -= 1
                return
            if self.path.exists() and is_link(self.path):
                raise ValueError("Artifact lock path cannot be a link")
            descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            stream = os.fdopen(descriptor, "r+b", buffering=0)
            if self.path.stat().st_size == 0:
                stream.write(b"0")
            deadline = time.monotonic() + timeout
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Artifact worker is busy") from None
                    time.sleep(0.05)
            self.depth.value = 1
            try:
                yield
            finally:
                self.depth.value = 0
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            if stream:
                stream.close()
            self.local.release()
