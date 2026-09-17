"""Reversible, exact-bundle compatibility patch for Cline 4.1.17 on VS Code.

This is a local compatibility bridge, not an upstream Cline release. Refuse
unknown versions/content rather than guessing minified symbols after updates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from vessel.locking import ArtifactLock
from vessel.storage import _atomic_write, _regular_file, safe_directory

ORIGINAL_SHA256 = "d07c9ff15be2952dbe95d5571f13b06edb73053d9557ef853611c3edc426b2d8"
PATCHED_SHA256 = "445539d40ac0ac40d9b3b080ccf322101bd5b54b4ee74d17171e5c133ff0b49c"
MAX_BUNDLE = 100 * 1024 * 1024
MARKER = 'const __vesselCaptureBridge=require("./vessel-capture-bridge.cjs");'
BRIDGE_NAME = "vessel-capture-bridge.cjs"


def inspect(extension, backup=None, *, platform=None):
    """Read-only version/build inspection. A matching version alone is insufficient."""
    result = {
        "version": None, "platform": platform or sys.platform, "supported": False,
        "mode": "unsupported", "state": "unsupported", "bundle_sha256": None,
        "original_sha256": ORIGINAL_SHA256, "compatibility_version": "3",
        "supported_platforms": ["win32"], "reload_required": False,
        "evidence": "docs/native-cline-live-20260913.md", "verified_date": "2026-09-14",
        "capabilities": ["native_session_id", "native_tool_id", "observed_command_exit"],
        "restore_available": False,
    }
    try:
        package = json.loads(_regular_file(Path(extension) / "package.json", 1024 * 1024))
        result["version"] = package.get("version")
        bundle, bridge = paths(Path(extension))
        current = _regular_file(bundle, MAX_BUNDLE)
        result["bundle_sha256"] = sha(current)
        if result["platform"] != "win32":
            return result
        helper = Path(__file__).with_name("cline_bridge.cjs").read_bytes()
        expected = PATCHED_SHA256
        if backup and (Path(backup) / "patch.json").exists():
            original = _regular_file(Path(backup) / "extension.js.original", MAX_BUNDLE)
            receipt = json.loads(_regular_file(Path(backup) / "patch.json", 16384))
            expected = sha(patched_bundle(original))
            result["restore_available"] = (
                receipt.get("bundle") == str(bundle)
                and receipt.get("patched_sha256") == expected
                and receipt.get("bridge_sha256") == sha(helper)
            )
        if sha(current) == ORIGINAL_SHA256 and (not bridge.exists() or result["restore_available"]):
            result.update(supported=True, mode="verified_patch", state="patch_required", reload_required=True)
        elif sha(current) == expected and _regular_file(bridge, 65536) == helper:
            result.update(supported=True, mode="verified_patch", state="patched")
    except (OSError, ValueError, KeyError, TypeError):
        pass  # An unrecognized, incomplete or modified build remains unsupported.
    return result


def plan(extension, backup):
    extension, backup = Path(extension).absolute(), Path(backup).absolute()
    if backup.is_relative_to(extension) or extension.is_relative_to(backup):
        raise ValueError("Keep the compatibility backup outside the extension directory")
    result = inspect(extension, backup)
    if not result["supported"]:
        raise ValueError("Unsupported Cline build")
    return {**result, "extension": str(extension), "backup": str(backup),
            "changes": ["next/dist/extension.js", "next/dist/" + BRIDGE_NAME]}


def verify(extension, backup=None):
    result = inspect(extension, backup)
    if result["state"] != "patched":
        raise ValueError("Cline compatibility verification failed")
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Cline bridge contract changed; no files modified")
    return text.replace(before, after, 1)


def patched_bundle(original):
    if sha(original) != ORIGINAL_SHA256:
        raise ValueError("Unsupported Cline bundle; expected the verified 4.1.17 build")
    text = original.decode("utf-8")
    # Keep the additional native data through the legacy protobuf round trip.
    text = _replace(
        text,
        "let r=Iut.create(await this.completeParams(e));return this[Ppt](r)",
        "let r=Iut.create(await this.completeParams(e));"
        "if(e.vesselCapture)r.vesselCapture=e.vesselCapture;return this[Ppt](r)",
    )
    text = _replace(
        text,
        "let o=Iut.toJSON(r);o.userPromptSubmit",
        "let o=Iut.toJSON(r);if(r.vesselCapture)o.vesselCapture=r.vesselCapture;o.userPromptSubmit",
    )
    start, end = text.index("function Eyr("), text.index("async function eJh(")
    bridge = text[start:end]
    bridge = _replace(
        bridge,
        "function Eyr(t,e,r){",
        "function Eyr(t,e,r,vesselGetSessionId){"
        "let vesselSessionId;const vesselRoot=()=>vesselSessionId??=(vesselGetSessionId?.());",
    )
    bridge = _replace(
        bridge,
        "a=()=>new gFe({sessionWorkspaceRoot:r})",
        "a=vesselContext=>__vesselCaptureBridge.factory("
        "()=>new gFe({sessionWorkspaceRoot:r}),vesselContext,vesselRoot)",
    )
    bridge = _replace(bridge, "eJh(o,i,a,e)", "eJh(o,i,()=>a(o),e)")
    bridge = _replace(bridge, "tJh(o,i,a,e)", "tJh(o,i,()=>a(o),e)")
    if bridge.count("a().create(") != 3:
        raise ValueError("Cline hook factory contract changed")
    bridge = bridge.replace("a().create(", "a(o).create(")
    text = text[:start] + bridge + text[end:]
    text = _replace(
        text,
        "r.hooks=Eyr(this.options.stateManager,this.options.emitHookMessage,e.cwd)",
        "r.hooks=Eyr(this.options.stateManager,this.options.emitHookMessage,e.cwd,this.options.getSessionId)",
    )
    text = _replace(
        text,
        "new hvr({stateManager:this.stateManager,emitHookMessage:",
        "new hvr({stateManager:this.stateManager,"
        "getSessionId:()=>this.sessions.getActiveSession()?.sessionId,emitHookMessage:",
    )
    # At this precise branch VS Code has completed the foreground execution.
    # Preserve undefined exit status as unknown, including missing integration.
    text = _replace(
        text,
        'throw new ij(Q,N)}return q}finally{b.removeListener("line",L)}',
        'throw new ij(Q,N)}return new __vesselCaptureBridge.CommandObservation(q,Q)'
        '}finally{b.removeListener("line",L)}',
    )
    text = _replace(
        text,
        "return{query:f,result:h,success:!0}}catch(h)",
        "return __vesselCaptureBridge.commandResult(f,h)}catch(h)",
    )
    return (MARKER + "\n" + text).encode("utf-8")


def paths(extension):
    extension = safe_directory(extension)
    package = json.loads(_regular_file(extension / "package.json", 1024 * 1024))
    if (package.get("publisher"), package.get("name"), package.get("version")) != (
        "saoudrizwan", "claude-dev", "4.1.17"
    ):
        raise ValueError("This compatibility patch supports Cline 4.1.17 only")
    dist = safe_directory(extension / "next" / "dist")
    return dist / "extension.js", dist / BRIDGE_NAME


def install(extension, backup):
    bundle, bridge = paths(extension)
    backup = safe_directory(backup, create=True)
    with ArtifactLock(backup).hold():
        original_path = backup / "extension.js.original"
        receipt_path = backup / "patch.json"
        current = _regular_file(bundle, MAX_BUNDLE)
        helper = Path(__file__).with_name("cline_bridge.cjs").read_bytes()
        if receipt_path.exists():
            receipt = json.loads(_regular_file(receipt_path, 16384))
            if receipt.get("bundle") != str(bundle):
                raise ValueError("Backup belongs to a different extension")
            original = _regular_file(original_path, MAX_BUNDLE)
            patched = patched_bundle(original)
            if receipt.get("patched_sha256") != sha(patched) or receipt.get("bridge_sha256") != sha(helper):
                raise ValueError("Patch receipt changed; inspect before reinstalling")
            if current == patched and _regular_file(bridge, 65536) == helper:
                return {"installed": True, "reload_required": True, "backup": str(backup)}
            # A crash after durable backup/receipt but before bundle publication is
            # resumable; edited or updated third-party files are never overwritten.
            if current != original or (bridge.exists() and _regular_file(bridge, 65536) != helper):
                raise ValueError("Installed patch changed; original files preserved")
        else:
            patched = patched_bundle(current)  # Validate everything before writing.
            original = current
            if bridge.exists():
                raise ValueError("Compatibility helper path is already occupied")
            if original_path.exists() and _regular_file(original_path, MAX_BUNDLE) != original:
                raise ValueError("Backup conflict; original files preserved")
            _atomic_write(original_path, original, exclusive=True)
            receipt = {
                "schema": 1, "version": "4.1.17", "bundle": str(bundle),
                "original_sha256": sha(original), "patched_sha256": sha(patched),
                "bridge_sha256": sha(helper),
            }
            _atomic_write(receipt_path, json.dumps(receipt, indent=2).encode(), exclusive=True)
        if _regular_file(bundle, MAX_BUNDLE) != original:
            raise ValueError("Cline changed during patch preparation; retry after inspection")
        _atomic_write(bridge, helper, exclusive=True)
        _atomic_write(bundle, patched)
        return {"installed": True, "reload_required": True, "backup": str(backup)}


def restore(extension, backup):
    bundle, bridge = paths(extension)
    backup = safe_directory(backup)
    with ArtifactLock(backup).hold():
        receipt = json.loads(_regular_file(backup / "patch.json", 16384))
        original = _regular_file(backup / "extension.js.original", MAX_BUNDLE)
        if receipt.get("bundle") != str(bundle) or sha(original) != ORIGINAL_SHA256:
            raise ValueError("Backup does not match this extension")
        current = _regular_file(bundle, MAX_BUNDLE)
        if current != original and sha(current) != receipt["patched_sha256"]:
            raise ValueError("Cline changed since patching; refusing to overwrite it")
        if bridge.exists() and sha(_regular_file(bridge, 65536)) != receipt["bridge_sha256"]:
            raise ValueError("Compatibility helper was edited; refusing to remove it")
        if current != original:
            _atomic_write(bundle, original)
        if bridge.exists():
            bridge.unlink()
        return {"restored": True, "reload_required": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "restore"])
    parser.add_argument("--extension", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    args = parser.parse_args()
    result = (install if args.action == "install" else restore)(args.extension, args.backup)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
