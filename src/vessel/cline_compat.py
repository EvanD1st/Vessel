"""Reversible, exact-bundle compatibility patch for Cline 4.1.17 and above.

This is a local compatibility bridge, not an upstream Cline release. Refuse
unknown versions/content rather than guessing minified symbols after updates.
Each verified bundle stores its own patch spec (symbol names, hashes) so the
patch is deterministic and auditable without inspecting live minified code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from vessel.locking import ArtifactLock
from vessel.storage import _atomic_write, _regular_file, safe_directory

# Kept for backward-compat: the 4.1.17 original is still the primary key.
ORIGINAL_SHA256 = "d07c9ff15be2952dbe95d5571f13b06edb73053d9557ef853611c3edc426b2d8"
PATCHED_SHA256 = "445539d40ac0ac40d9b3b080ccf322101bd5b54b4ee74d17171e5c133ff0b49c"
MAX_BUNDLE = 100 * 1024 * 1024
MARKER = 'const __vesselCaptureBridge=require("./vessel-capture-bridge.cjs");'
BRIDGE_NAME = "vessel-capture-bridge.cjs"

# Minimum supported Cline version (inclusive). Versions below this are refused.
MIN_SUPPORTED_VERSION = (4, 1, 17)

# Per-bundle patch specifications keyed by the SHA-256 of the *original* bundle.
# Each entry describes the minified symbols for that build so the patch is
# deterministic across machines without re-inspecting the extension at runtime.
BUNDLE_SPECS: dict[str, dict] = {
    # Cline 4.1.17 (Windows, win32) — verified 2026-09-14
    "d07c9ff15be2952dbe95d5571f13b06edb73053d9557ef853611c3edc426b2d8": {
        "cline_version": "4.1.17",
        "patched_sha256": "445539d40ac0ac40d9b3b080ccf322101bd5b54b4ee74d17171e5c133ff0b49c",
        "proto_create": "Iut.create",
        "proto_tojson": "Iut.toJSON",
        "dispatch_sym": "Ppt",
        "hook_fn": "Eyr",
        "hook_fn_end": "async function eJh(",
        "session_cls": "gFe",
        "run_hooks_a": "eJh",
        "run_hooks_b": "tJh",
        "error_cls": "ij",
        "listener_var": "b",
        "statemanager_cls": "hvr",
    },
    # Cline 4.1.19 (Windows, win32) — verified 2026-09-19
    "bb853c9e401e2c9ce451a061afc596680f553c546bbd4e25a3e136e576382072": {
        "cline_version": "4.1.19",
        "patched_sha256": "c96f7c0ef55f5070f190e39b675b517dcebc017cbfb7615c15436e831ab98295",
        "proto_create": "ZLe.create",
        "proto_tojson": "ZLe.toJSON",
        "dispatch_sym": "_ft",
        "hook_fn": "xbr",
        "hook_fn_end": "async function Zr0(",
        "session_cls": "ZFe",
        "run_hooks_a": "Zr0",
        "run_hooks_b": "en0",
        "error_cls": "Ij",
        "listener_var": "x",
        "statemanager_cls": "f1r",
    },
}


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a dotted version string into a comparable tuple."""
    try:
        return tuple(int(x) for x in str(version_str).split("."))
    except (ValueError, AttributeError):
        return (0,)


def _is_supported_version(version_str: str) -> bool:
    """Return True if the Cline version is at or above MIN_SUPPORTED_VERSION."""
    return _parse_version(version_str) >= MIN_SUPPORTED_VERSION


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
        current_sha = sha(current)
        result["bundle_sha256"] = current_sha
        if result["platform"] != "win32":
            return result
        helper = Path(__file__).with_name("cline_bridge.cjs").read_bytes()

        spec = BUNDLE_SPECS.get(current_sha)
        if spec is not None:
            # Current file is a known original — patch is needed.
            result["original_sha256"] = current_sha
            result.update(supported=True, mode="verified_patch", state="patch_required", reload_required=True)
            if backup and (Path(backup) / "patch.json").exists():
                original = _regular_file(Path(backup) / "extension.js.original", MAX_BUNDLE)
                receipt = json.loads(_regular_file(Path(backup) / "patch.json", 16384))
                expected = spec["patched_sha256"]
                result["restore_available"] = (
                    receipt.get("bundle") == str(bundle)
                    and receipt.get("patched_sha256") == expected
                    and receipt.get("bridge_sha256") == sha(helper)
                )
        else:
            # Current may be a patched version — look up via backup original.
            if backup and (Path(backup) / "patch.json").exists():
                original = _regular_file(Path(backup) / "extension.js.original", MAX_BUNDLE)
                receipt = json.loads(_regular_file(Path(backup) / "patch.json", 16384))
                original_sha = sha(original)
                orig_spec = BUNDLE_SPECS.get(original_sha)
                if orig_spec is not None:
                    expected = orig_spec["patched_sha256"]
                    result["restore_available"] = (
                        receipt.get("bundle") == str(bundle)
                        and receipt.get("patched_sha256") == expected
                        and receipt.get("bridge_sha256") == sha(helper)
                    )
                    if current_sha == expected and _regular_file(bridge, 65536) == helper:
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
        raise ValueError(
            f"Cline bridge contract changed; no files modified (pattern count != 1: {before[:60]!r})"
        )
    return text.replace(before, after, 1)


def patched_bundle(original):
    """Apply the compatibility patch to an original Cline bundle.

    Determines the correct patch spec from the bundle's SHA-256, then applies
    the minimal additive source-level modifications. Raises ValueError if the
    bundle is not one of the verified builds.
    """
    original_sha = sha(original)
    spec = BUNDLE_SPECS.get(original_sha)
    if spec is None:
        known = ", ".join(s["cline_version"] for s in sorted(
            BUNDLE_SPECS.values(), key=lambda s: _parse_version(s["cline_version"])
        ))
        raise ValueError(
            f"Unsupported Cline bundle (sha256={original_sha[:16]}\u2026); "
            f"verified builds: {known}"
        )
    return _apply_patch(original.decode("utf-8"), spec).encode("utf-8")


def _apply_patch(text: str, spec: dict) -> str:
    """Apply the version-specific patch steps to the decoded bundle text."""
    pc = spec["proto_create"]
    pt = spec["proto_tojson"]
    ds = spec["dispatch_sym"]
    hf = spec["hook_fn"]
    he = spec["hook_fn_end"]
    sc = spec["session_cls"]
    ra = spec["run_hooks_a"]
    rb = spec["run_hooks_b"]
    ec = spec["error_cls"]
    lv = spec["listener_var"]
    sm = spec["statemanager_cls"]

    # 1. Preserve vesselCapture through the protobuf create round-trip.
    text = _replace(
        text,
        f"let r={pc}(await this.completeParams(e));return this[{ds}](r)",
        f"let r={pc}(await this.completeParams(e));"
        f"if(e.vesselCapture)r.vesselCapture=e.vesselCapture;return this[{ds}](r)",
    )

    # 2. Preserve vesselCapture through the protobuf toJSON serialization.
    text = _replace(
        text,
        f"let o={pt}(r);o.userPromptSubmit",
        f"let o={pt}(r);if(r.vesselCapture)o.vesselCapture=r.vesselCapture;o.userPromptSubmit",
    )

    # 3-7. Patch the hook factory function in-place.
    start = text.index(f"function {hf}(")
    end = text.index(he)
    bridge = text[start:end]

    bridge = _replace(
        bridge,
        f"function {hf}(t,e,r){{",
        f"function {hf}(t,e,r,vesselGetSessionId){{"
        "let vesselSessionId;const vesselRoot=()=>vesselSessionId??=(vesselGetSessionId?.());",
    )
    bridge = _replace(
        bridge,
        f"a=()=>new {sc}({{sessionWorkspaceRoot:r}})",
        f"a=vesselContext=>__vesselCaptureBridge.factory("
        f"()=>new {sc}({{sessionWorkspaceRoot:r}}),vesselContext,vesselRoot)",
    )
    bridge = _replace(bridge, f"{ra}(o,i,a,e)", f"{ra}(o,i,()=>a(o),e)")
    bridge = _replace(bridge, f"{rb}(o,i,a,e)", f"{rb}(o,i,()=>a(o),e)")
    if bridge.count("a().create(") != 3:
        raise ValueError("Cline hook factory contract changed")
    bridge = bridge.replace("a().create(", "a(o).create(")
    text = text[:start] + bridge + text[end:]

    # 8. Pass getSessionId into the hooks factory call-site.
    text = _replace(
        text,
        f"r.hooks={hf}(this.options.stateManager,this.options.emitHookMessage,e.cwd)",
        f"r.hooks={hf}(this.options.stateManager,this.options.emitHookMessage,e.cwd,this.options.getSessionId)",
    )

    # 9. Inject getSessionId into the session config builder.
    text = _replace(
        text,
        f"new {sm}({{stateManager:this.stateManager,emitHookMessage:",
        f"new {sm}({{stateManager:this.stateManager,"
        "getSessionId:()=>this.sessions.getActiveSession()?.sessionId,emitHookMessage:",
    )

    # 10. Wrap the command exit-code in a CommandObservation for precise capture.
    text = _replace(
        text,
        f'throw new {ec}(Q,N)}}return q}}finally{{{lv}.removeListener("line",L)}}',
        f'throw new {ec}(Q,N)}}return new __vesselCaptureBridge.CommandObservation(q,Q)'
        f'}}finally{{{lv}.removeListener("line",L)}}',
    )

    # 11. Reroute the command result through the bridge helper.
    text = _replace(
        text,
        "return{query:f,result:h,success:!0}}catch(h)",
        "return __vesselCaptureBridge.commandResult(f,h)}catch(h)",
    )

    return MARKER + "\n" + text


def paths(extension):
    extension = safe_directory(extension)
    package = json.loads(_regular_file(extension / "package.json", 1024 * 1024))
    publisher = package.get("publisher")
    name = package.get("name")
    version = package.get("version")
    if (publisher, name) != ("saoudrizwan", "claude-dev"):
        raise ValueError("This compatibility patch supports the saoudrizwan.claude-dev extension only")
    if not _is_supported_version(version):
        raise ValueError(
            f"Cline {version} is below the minimum supported version "
            f"{'.'.join(str(x) for x in MIN_SUPPORTED_VERSION)}; "
            "upgrade Cline to the latest release"
        )
    dist = safe_directory(extension / "next" / "dist")
    return dist / "extension.js", dist / BRIDGE_NAME


def _package_version(extension):
    """Read the version string from the extension's package.json."""
    try:
        package = json.loads(_regular_file(Path(extension) / "package.json", 1024 * 1024))
        return package.get("version", "unknown")
    except (OSError, ValueError):
        return "unknown"


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
            original_sha = sha(original)
            spec = BUNDLE_SPECS.get(original_sha)
            if bridge.exists():
                raise ValueError("Compatibility helper path is already occupied")
            if original_path.exists() and _regular_file(original_path, MAX_BUNDLE) != original:
                raise ValueError("Backup conflict; original files preserved")
            _atomic_write(original_path, original, exclusive=True)
            receipt = {
                "schema": 1,
                "version": spec["cline_version"] if spec else _package_version(extension),
                "bundle": str(bundle),
                "original_sha256": original_sha, "patched_sha256": sha(patched),
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
        original_sha = sha(original)
        if receipt.get("bundle") != str(bundle):
            raise ValueError("Backup does not match this extension")
        if original_sha not in BUNDLE_SPECS:
            raise ValueError("Backup original does not match any verified bundle")
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

