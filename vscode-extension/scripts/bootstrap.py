"""Offline runtime staging. No network, workspace code, provider keys or shell strings."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


@contextlib.contextmanager
def locked(path):
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b"0")
            stream.flush()
        deadline = time.monotonic() + 240
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError()
                time.sleep(0.2)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def run(args):
    subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=180, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def main():
    artifacts = Path(__file__).resolve().parent.parent / "runtime"
    raw = (artifacts / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    if (manifest["schema"] != 1 or sys.platform != manifest["platform"] or
            platform.machine().lower() not in {"amd64", "x86_64"} or minor not in manifest["python_minors"]):
        return {"ok": False, "code": "runtime_platform_unsupported"}
    for relative, expected in manifest["files"].items():
        item = (artifacts / relative).resolve(strict=True)
        if not item.is_relative_to(artifacts) or hashlib.sha256(item.read_bytes()).hexdigest() != expected:
            return {"ok": False, "code": "runtime_artifact_invalid"}
    storage = Path(sys.argv[1]).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    with locked(storage / "runtime.lock"):
        generation = hashlib.sha256(raw).hexdigest()[:24] + "-" + minor
        target = storage / "runtimes" / generation
        python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        receipt = target / "vessel-runtime.json"
        if not receipt.exists():
            run([sys.executable, "-I", "-m", "venv", str(target)])
            run([str(python), "-I", "-m", "pip", "--isolated", "install", "--disable-pip-version-check",
                 "--no-index", "--only-binary=:all:", "--find-links", str(artifacts / "wheels"),
                 "-r", str(artifacts / "requirements.txt"), f"vessel-continuity=={manifest['version']}"])
            run([str(python), "-I", "-c", "import vessel, vessel.extension_api; assert vessel.__version__ == '" + manifest["version"] + "'"])
            receipt.write_text(json.dumps({"schema": 1, "version": manifest["version"], "generation": generation}))
        run([str(python), "-I", "-c", "import vessel.extension_api"])
        active = storage / "runtime.json"
        previous = json.loads(active.read_text()) if active.exists() else None
        target_python = python
        if os.name == "nt":
            pythonw = target / "Scripts/pythonw.exe"
            if pythonw.is_file():
                target_python = pythonw
        result = {"schema": 1, "generation": generation, "python": str(target_python),
                  "python_version": platform.python_version(), "version": manifest["version"], "healthy": True}
        if previous and previous.get("generation") != generation:
            (storage / "runtime-previous.json").write_text(json.dumps(previous))
        temporary = storage / "runtime.json.next"
        temporary.write_text(json.dumps(result))
        os.replace(temporary, active)
        return {"ok": True, "runtime": result}


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except Exception:
        print(json.dumps({"ok": False, "code": "runtime_install_failed"}))
