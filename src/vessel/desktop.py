"""Managed local companion lifetime; startup never binds a task or resumes capture."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

from vessel.locking import ArtifactLock
from vessel.onboarding import load_profile, local_path
from vessel.storage import _atomic_write, _regular_file, is_link, safe_directory

RUNTIME = "companion-runtime.json"
STOP = "companion-stop.json"
LOG = "companion.log"


def _lock(state):
    lock = ArtifactLock(state)
    lock.path = state / "companion-process.lock"
    return lock


def _read(path):
    if not path.exists():
        return {}
    for _ in range(5):
        try:
            return json.loads(_regular_file(path, 16384))
        except PermissionError:
            time.sleep(0.05)
        except OSError:
            break
    return {}


def _write(path, value):
    if path.exists() and is_link(path):
        raise ValueError("Companion control file cannot be a link")
    _atomic_write(path, json.dumps(value, indent=2).encode())


def status(state):
    state = safe_directory(local_path(state))
    # The OS releases this lock even on power loss or forced termination; PID
    # reuse and a stale runtime file cannot make a stopped process look alive.
    try:
        with _lock(state).hold(timeout=0):
            running = False
    except TimeoutError:
        running = True
    result = _read(state / RUNTIME)
    return {**result, "running": running, "log": str(state / LOG)}


def connection(state):
    state = safe_directory(local_path(state))
    runtime = status(state)
    if not runtime["running"] or runtime.get("status") != "ready":
        raise ValueError("Companion is not ready. Run vessel launch with this state")
    path = state / LOG
    if is_link(path):
        raise ValueError("Companion log cannot be a link")
    with path.open(encoding="utf-8") as stream:
        first = stream.readline(16384)
    link = json.loads(first)
    if link.get("instance") != runtime.get("instance"):
        raise ValueError("Companion restarted while reading its link; retry")
    if time.time() >= link["expires_at"]:
        raise ValueError("Pairing link expired. Existing pairings still work; stop and launch for a new link")
    return {
        "connect_url": link["connect_url"],
        "expires_at": link["expires_at"],
        "notice": "Use this private link to pair once. Do not share it.",
    }


def launch(state, *, timeout=20):
    state = safe_directory(local_path(state))
    profile = load_profile(state)
    current = status(state)
    if current["running"]:
        if any(current.get(key) != profile[key] for key in ("origin", "port", "ttl", "python")):
            raise ValueError("A companion with different settings is running. Stop it before launching again")
        conn = {}
        try:
            conn = connection(state)
        except Exception:
            pass
        return {**current, "status": "already_running", "connect_url": conn.get("connect_url")}
    (state / STOP).unlink(missing_ok=True)
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0
    python_bin = profile["python"]
    if os.name == "nt":
        full = shutil.which(python_bin) or python_bin
        w_bin = Path(full).with_name("pythonw.exe")
        if w_bin.is_file():
            python_bin = str(w_bin)
        else:
            w_which = shutil.which("pythonw.exe") or shutil.which("pythonw")
            if w_which:
                python_bin = w_which
    process = subprocess.Popen(
        [python_bin, "-m", "vessel.desktop", "--state", str(state)],
        cwd=state,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        start_new_session=os.name != "nt",
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = status(state)
        if current["running"] and current.get("status") == "ready":
            return {**current, **connection(state)}
        if process.poll() is not None:
            raise ValueError(current.get("error") or "Companion could not start; check the saved interpreter")
        time.sleep(0.1)
    raise TimeoutError("Companion is still starting. Check companion-status before launching again")


def stop(state, *, timeout=20):
    state = safe_directory(local_path(state))
    current = status(state)
    if not current["running"]:
        return {"status": "already_stopped"}
    instance = current.get("instance")
    if not isinstance(instance, str) or len(instance) != 32:
        raise ValueError("Companion startup is incomplete; check status and retry")
    _write(state / STOP, {"instance": instance})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = status(state)
        if not current["running"]:
            return {"status": "stopped"}
        if current.get("instance") != instance:
            raise ValueError("Another companion started during shutdown; it was not stopped")
        time.sleep(0.1)
    raise TimeoutError("Shutdown is still pending. Check companion-status; no process was forcibly killed")


def serve(state):
    import uvicorn

    from vessel.dashboard import create_app

    state = safe_directory(local_path(state))
    profile = load_profile(state)
    lock = _lock(state)
    try:
        # A status probe briefly takes the same lock. Give that probe time to
        # release it rather than mistaking it for another serving process.
        with lock.hold(timeout=2):
            instance = uuid.uuid4().hex
            record = {
                "instance": instance,
                "pid": os.getpid(),
                "status": "starting",
                "origin": profile["origin"],
                "port": profile["port"],
                "ttl": profile["ttl"],
                "python": profile["python"],
                "started_at": time.time(),
            }
            _write(state / RUNTIME, record)
            try:
                # Bind before rotating the private log. Never connect to or kill
                # an unrelated process when the requested port is occupied.
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                    if os.name == "nt":
                        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    try:
                        listener.bind(("127.0.0.1", profile["port"]))
                    except OSError as error:
                        raise ValueError(
                            "Companion port is occupied or unavailable. Choose a free port or stop its owner."
                        ) from error
                    token = secrets.token_urlsafe(36)
                    app = create_app(
                        state,
                        origin=profile["origin"],
                        token=token,
                        port=profile["port"],
                        ttl=profile["ttl"],
                        start_workers=True,
                    )
                    log_path = state / LOG
                    if log_path.exists() and (is_link(log_path) or not log_path.is_file()):
                        raise ValueError("Companion log must be a regular file")
                    with log_path.open("w", encoding="utf-8", buffering=1) as log:
                        if os.name != "nt":
                            log_path.chmod(0o600)
                        log.write(
                            json.dumps(
                                {
                                    "instance": instance,
                                    "connect_url": f"{profile['origin']}/#connect={profile['port']}:{token}",
                                    "expires_at": time.time() + profile["ttl"],
                                }
                            )
                            + "\n"
                        )
                        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                            server = uvicorn.Server(
                                uvicorn.Config(app, access_log=False, log_level="warning")
                            )
                            done = threading.Event()

                            def watch():
                                published = False
                                while not done.wait(0.2):
                                    if server.started and not published:
                                        record["status"] = "ready"
                                        _write(state / RUNTIME, record)
                                        published = True
                                    try:
                                        if _read(state / STOP).get("instance") == instance:
                                            server.should_exit = True
                                    except (OSError, ValueError):
                                        pass  # A malformed stop request cannot grant control.

                            watcher = threading.Thread(target=watch, daemon=True)
                            watcher.start()
                            try:
                                server.run(sockets=[listener])
                            finally:
                                done.set()
                                watcher.join(timeout=2)
                record["status"] = "stopped"
                _write(state / RUNTIME, record)
                return 0
            except Exception as error:
                record.update(status="failed", error=str(error))
                _write(state / RUNTIME, record)
                return 1
    except TimeoutError:
        return 0  # A launch at Windows sign-in never duplicates an existing managed instance.


def find_default_state() -> Path | None:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "VESSEL" / "projects"
    if base.exists():
        candidates = [d for d in base.iterdir() if d.is_dir() and (d / "vessel.sqlite3").is_file()]
        if candidates:
            candidates.sort(key=lambda d: (d / "vessel.sqlite3").stat().st_mtime, reverse=True)
            return candidates[0]
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=False, type=Path)
    parser.add_argument("uri", nargs="*", default=[])
    args = parser.parse_args()
    target_state = args.state or find_default_state()
    if not target_state:
        return 1
    try:
        return serve(target_state)
    except Exception:
        return 1  # pythonw has no console; launch/status report a missing/invalid profile.


if __name__ == "__main__":
    raise SystemExit(main())
