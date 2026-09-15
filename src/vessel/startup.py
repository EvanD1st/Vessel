"""Opt-in, current-user Windows logon registration with exact ownership checks."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from vessel.locking import ArtifactLock
from vessel.onboarding import load_profile, local_path
from vessel.storage import Store, safe_directory

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RECEIPT = "windows_startup"


def _windows_registry():
    if os.name != "nt":
        raise ValueError("Automatic sign-in startup is currently available on Windows only")
    import winreg

    return winreg


def name_for(state):
    return "VESSEL-" + hashlib.sha256(os.path.normcase(str(state)).encode()).hexdigest()[:16]


def command_for(state, profile):
    _windows_registry()
    pythonw = Path(profile["python"]).with_name("pythonw.exe")
    if not pythonw.is_file():
        raise ValueError("Windows startup needs pythonw.exe beside the configured interpreter")
    args = [str(pythonw), "-m", "vessel.desktop", "--state", str(state)]
    if any(any(ord(ch) < 32 for ch in arg) for arg in args):
        raise ValueError("Startup paths contain control characters")
    command = subprocess.list2cmdline(args)
    if len(command) > 260:
        raise ValueError(
            "Windows startup command exceeds 260 characters; use shorter installation/state paths"
        )
    return command


def _current(reg, name):
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ) as key:
            return reg.QueryValueEx(key, name)
    except FileNotFoundError:
        return None


def configure(state, action):
    if action not in {"enable", "disable", "status"}:
        raise ValueError("Choose startup enable, disable or status")
    reg = _windows_registry()
    state = safe_directory(local_path(state))
    name = name_for(state)
    lock = ArtifactLock(state)
    lock.path = state / "startup-config.lock"
    with lock.hold():
        store = Store(state)
        try:
            receipt = store.get("control", RECEIPT)
            current = _current(reg, name)
            owned_commands = (
                {receipt.get("command"), receipt.get("previous_command")} - {None}
                if receipt and receipt.get("name") == name
                else set()
            )
            owned = bool(current and current[1] == reg.REG_SZ and current[0] in owned_commands)
            if action == "status":
                return {
                    "status": "enabled" if owned else "conflict" if current else "disabled",
                    "name": name,
                    "scope": "current_windows_user",
                }
            if current is not None and not owned:
                raise ValueError("Startup entry differs from VESSEL's receipt; existing value was preserved")
            if action == "disable":
                if current is not None:
                    with reg.OpenKey(
                        reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_READ | reg.KEY_SET_VALUE
                    ) as key:
                        # Recheck immediately before deleting only our one named value.
                        if reg.QueryValueEx(key, name) != current:
                            raise ValueError("Startup entry changed during removal")
                        reg.DeleteValue(key, name)
                return {
                    "status": "disabled",
                    "name": name,
                    "notice": "Future sign-in startup is disabled. A running companion is not stopped.",
                }
            command = command_for(state, load_profile(state))
            if current == (command, reg.REG_SZ):
                store.put("control", RECEIPT, {"name": name, "command": command})
                return {"status": "enabled", "name": name, "scope": "current_windows_user"}
            # Keep a pending exact-command receipt before publication. A crash can
            # be resumed without treating an unowned registry value as ours.
            previous = receipt
            store.put(
                "control",
                RECEIPT,
                {"name": name, "command": command, "previous_command": current[0] if owned else None},
            )
            try:
                with reg.CreateKeyEx(reg.HKEY_CURRENT_USER, RUN_KEY, 0, reg.KEY_SET_VALUE) as key:
                    if _current(reg, name) != current:
                        raise ValueError("Startup entry changed during registration")
                    reg.SetValueEx(key, name, 0, reg.REG_SZ, command)
            except Exception:
                if _current(reg, name) != (command, reg.REG_SZ):
                    if previous:
                        store.put("control", RECEIPT, previous)
                    else:
                        store.delete("control", RECEIPT)
                raise
            store.put("control", RECEIPT, {"name": name, "command": command})
            return {
                "status": "enabled",
                "name": name,
                "scope": "current_windows_user",
                "notice": "The companion starts hidden at sign-in. Windows may delay or disable startup entries.",
            }
        finally:
            store.close()
