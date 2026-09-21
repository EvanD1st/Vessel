"""Owner-managed loopback gateway. The upstream key exists only in process memory."""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from vessel import desktop
from vessel.gateway import UpstreamRoute, create_app
from vessel.locking import ArtifactLock
from vessel.service import Vessel
from vessel.storage import safe_directory

CONTROL = "extension_gateway"
ENDPOINT = "https://api.orbio.so/api/v1/chat/completions"
MODELS = ("openai/gpt-4.1-mini", "openai/gpt-4o-mini")
KEY_ENV = "VESSEL_EXTENSION_ORBIO_KEY"


def resolve_endpoint(key: str | None) -> str:
    if key:
        if key.startswith("sk-or-"):
            return "https://openrouter.ai/api/v1/chat/completions"
        if key.startswith("sk-proj-"):
            return "https://api.openai.com/v1/chat/completions"
    return ENDPOINT


def lock_for(state):
    lock = ArtifactLock(state)
    lock.path = state / "extension-gateway.lock"
    return lock


def status(state):
    state = safe_directory(Path(state))
    try:
        with lock_for(state).hold(timeout=0):
            running = False
    except TimeoutError:
        running = True
    return {**desktop._read(state / "extension-gateway.json"), "running": running}


def stop(state, *, timeout=20):
    state = safe_directory(Path(state))
    current = status(state)
    if not current["running"]:
        return {"status": "stopped"}
    if not current.get("instance"):
        raise ValueError("Gateway startup is incomplete")
    desktop._write(state / "extension-gateway-stop.json", {"instance": current["instance"]})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        observed = status(state)
        if not observed["running"]:
            return {"status": "stopped"}
        if observed.get("instance") != current["instance"]:
            raise ValueError("Gateway instance changed")
        time.sleep(0.1)
    raise TimeoutError("Gateway stop pending")


def launch(state, key=None, *, timeout=20):
    state = safe_directory(Path(state))
    service = Vessel(state)
    try:
        config = service._get("control", CONTROL)
        if key is None:
            secret = service.store.get("secrets", "orbio_credential")
            if secret and isinstance(secret.get("key"), str):
                key = secret["key"]
    finally:
        service.close()
    if not isinstance(key, str) or not key or len(key) > 8192 or any(ch.isspace() for ch in key):
        raise ValueError("Invalid provider credential")
    if config["paused"]:
        raise ValueError("Gateway paused")
    current = status(state)
    if current["running"]:
        if (current.get("credential_version") == config["credential_version"] and current.get("port") == config["port"]
                and current.get("models") == config["models"] and current.get("status") == "ready"):
            return current
        raise ValueError("Stop the previous gateway before changing its configuration")
    (state / "extension-gateway-stop.json").unlink(missing_ok=True)
    env = {**os.environ, KEY_ENV: key}
    py_bin = sys.executable
    if os.name == "nt":
        full = shutil.which(py_bin) or py_bin
        w_bin = Path(full).with_name("pythonw.exe")
        if w_bin.is_file():
            py_bin = str(w_bin)
        else:
            w_which = shutil.which("pythonw.exe") or shutil.which("pythonw")
            if w_which:
                py_bin = w_which
    process = subprocess.Popen([py_bin, "-I", "-m", "vessel.extension_gateway", "--state", str(state)],
                               cwd=state, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0,
                               start_new_session=os.name != "nt")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = status(state)
        if current["running"] and current.get("status") == "ready":
            return current
        if process.poll() is not None:
            raise ValueError("Gateway could not start")
        time.sleep(0.1)
    # Ask only this newly created instance to stop. Never kill a process found by port.
    if current.get("pid") == process.pid and current.get("instance"):
        desktop._write(state / "extension-gateway-stop.json", {"instance": current["instance"]})
    raise TimeoutError("Gateway startup timed out")


def serve(state):
    import uvicorn

    state = safe_directory(Path(state))
    key = os.environ.pop(KEY_ENV, "")
    if not key:
        init_service = Vessel(state)
        try:
            secret = init_service.store.get("secrets", "orbio_credential")
            if secret and isinstance(secret.get("key"), str):
                key = secret["key"]
        finally:
            init_service.close()
    with lock_for(state).hold(timeout=2):
        service = Vessel(state)
        try:
            config = service._get("control", CONTROL)
            models = config.get("models")
            if (
                config.get("paused")
                or not isinstance(models, (list, tuple))
                or not models
                or any(not isinstance(m, str) or not m.strip() or any(ord(c) < 32 for c in m) for m in models)
            ):
                raise ValueError("Gateway configuration unavailable")
        finally:
            service.close()
        record = {"instance": uuid.uuid4().hex, "pid": os.getpid(), "status": "starting",
                  "port": config["port"], "credential_version": config["credential_version"], "models": config["models"]}
        desktop._write(state / "extension-gateway.json", record)

        def authorize(token):
            instance = Vessel(state)
            try:
                live = instance._get("control", CONTROL)
                if (live["paused"] or live["credential_version"] != config["credential_version"]
                        or live["models"] != config["models"] or live["port"] != config["port"]):
                    return None
                return instance.authorize_gateway(token)
            finally:
                instance.close()

        def audit(event):
            instance = Vessel(state)
            try:
                instance.audit_gateway(event)
            finally:
                instance.close()

        auto_candidates = tuple(list(dict.fromkeys(config["models"]))[:3])
        profiles = {"vessel-auto": auto_candidates} if "vessel-auto" not in config["models"] else {}
        endpoint = resolve_endpoint(key)
        app = create_app(routes={"default": UpstreamRoute(endpoint, key, frozenset(config["models"]),
                          profiles, config["credential_version"])},
                         authorize=authorize, audit=audit)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", config["port"]))
            server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="critical"))
            done = threading.Event()

            def watch():
                published = False
                while not done.wait(0.2):
                    if server.started and not published:
                        record["status"] = "ready"
                        desktop._write(state / "extension-gateway.json", record)
                        published = True
                    try:
                        requested = desktop._read(state / "extension-gateway-stop.json").get("instance")
                    except (ValueError, OSError):
                        requested = record["instance"]  # Broken control channel fails closed.
                    if requested == record["instance"]:
                        server.should_exit = True
            watcher = threading.Thread(target=watch, daemon=True)
            watcher.start()
            try:
                server.run(sockets=[listener])
            finally:
                done.set()
                watcher.join(timeout=2)
                record["status"] = "stopped"
                desktop._write(state / "extension-gateway.json", record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    try:
        serve(parser.parse_args().state)
    except Exception:
        sys.exit(1)  # Never write provider error bodies or keys to a log.
