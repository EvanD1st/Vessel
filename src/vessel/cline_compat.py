"""Reversible, exact-bundle compatibility patch for Cline 4.1.17 on VS Code.

This is a local compatibility bridge, not an upstream Cline release. Refuse
unknown versions/content rather than guessing minified symbols after updates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from vessel.locking import ArtifactLock
from vessel.storage import _atomic_write, _regular_file, safe_directory

ORIGINAL_SHA256 = "d07c9ff15be2952dbe95d5571f13b06edb73053d9557ef853611c3edc426b2d8"
MAX_BUNDLE = 100 * 1024 * 1024
MARKER = 'const __vesselCaptureBridge=require("./vessel-capture-bridge.cjs");'
BRIDGE_NAME = "vessel-capture-bridge.cjs"


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
