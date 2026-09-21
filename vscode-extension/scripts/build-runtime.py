"""Build pinned, offline installation artifacts. Only this developer step uses PyPI."""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("--python-minor", action="append", default=[])
args = parser.parse_args()
destination = root / "vscode-extension" / "runtime"
destination.mkdir(exist_ok=True)
lock = root / "requirements.lock"
excluded = {"pytest", "pytest-asyncio", "ruff", "iniconfig", "pluggy", "Pygments"}
requirements = "\n".join(line for line in lock.read_text().splitlines() if line.split("==")[0] not in excluded)
(destination / "requirements.txt").write_text(requirements + "\n")
wheelhouse = destination / "wheels"
wheelhouse.mkdir(exist_ok=True)
for old_wheel in wheelhouse.glob("vessel_continuity-*.whl"):
    old_wheel.unlink()
# Pure-Python wheel with deterministic bytes; no build backend downloads or user venv changes.
project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
version = project["version"]
info = f"vessel_continuity-{version}.dist-info"
contents = {"vessel/" + p.name: p.read_bytes() for p in sorted((root / "src/vessel").iterdir()) if p.suffix in {".py", ".cjs"}}
metadata = ["Metadata-Version: 2.1", "Name: vessel-continuity", f"Version: {version}", "Requires-Python: >=3.11"]
metadata += ["Requires-Dist: " + dependency for dependency in project["dependencies"]]
contents[info + "/METADATA"] = ("\n".join(metadata) + "\n\n").encode()
contents[info + "/WHEEL"] = b"Wheel-Version: 1.0\nGenerator: vessel-offline-builder\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
contents[info + "/entry_points.txt"] = b"[console_scripts]\nvessel = vessel.cli:main\n"
record = io.StringIO(newline="")
writer = csv.writer(record, lineterminator="\n")
for name, data in contents.items():
    writer.writerow([name, "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("="), len(data)])
writer.writerow([info + "/RECORD", "", ""])
contents[info + "/RECORD"] = record.getvalue().encode()
with zipfile.ZipFile(wheelhouse / f"vessel_continuity-{version}-py3-none-any.whl", "w", compression=zipfile.ZIP_DEFLATED) as wheel:
    for name, data in contents.items():
        item = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        wheel.writestr(item, data)
minors = args.python_minor or ["3.11", "3.12", "3.13", "3.14"]
for minor in minors:
    subprocess.run([sys.executable, "-m", "pip", "download", "--only-binary=:all:", "--platform", "win_amd64", "--python-version", minor,
                    "--dest", str(wheelhouse), "-r", str(destination / "requirements.txt")], check=True)
files = {str(p.relative_to(destination)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in sorted(wheelhouse.glob("*.whl"))}
files["requirements.txt"] = hashlib.sha256((destination / "requirements.txt").read_bytes()).hexdigest()
manifest = {"schema": 1, "package": "vessel-continuity", "version": version, "platform": "win32", "arch": "x64",
            "python_minors": minors, "files": files}
(destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({"wheels": len(files) - 1, "python_minors": minors}))
