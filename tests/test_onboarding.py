"""Isolated setup, process lifetime and Windows startup checks; no native capture claims."""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from vessel import cli, desktop, onboarding, startup
from vessel.service import Vessel
from vessel.storage import Store


@pytest.fixture
def setup_paths(tmp_path):
    workspace = tmp_path / "project café's files"
    workspace.mkdir()
    (workspace / "app.py").write_text("# original application\n")
    config = tmp_path / "active profile" / "cline_mcp_settings.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"mcpServers": {"unrelated": {"command": "keep-me"}}}))
    return workspace, tmp_path / "private state", config


def make_plan(setup_paths, **kwargs):
    workspace, state, config = setup_paths
    return onboarding.prepare(
        workspace, state=state, mission="Implement the approved feature", mcp_config=config, **kwargs
    )


def test_setup_enrolls_installs_and_reruns_without_resetting_authority(setup_paths):
    workspace, state, config = setup_paths
    plan = make_plan(setup_paths)
    assert not state.exists()  # Planning does not create an authority or project hooks.
    result = onboarding.apply(plan)
    assert result["configuration"]["installed"]
    assert result["configuration"]["native_capture"] == "unverified"
    assert json.loads(config.read_text())["mcpServers"]["unrelated"] == {"command": "keep-me"}
    assert len(list((workspace / ".clinerules/hooks").iterdir())) == 9
    service = Vessel(state)
    before = service.policy()
    assert not service.store.list("runs") and not service.store.events()
    service.close()
    again = onboarding.prepare(workspace)  # Discover the actual original state and Cline settings.
    assert Path(again["state"]) == state
    assert onboarding.apply(again)["enrollment_id"] == result["enrollment_id"]
    service = Vessel(state)
    assert service.policy() == before and not service.store.list("runs")
    service.close()
    assert (workspace / "app.py").read_text() == "# original application\n"


@pytest.mark.parametrize("bad", ["not JSON", "[]", '{"mcpServers":5}', '{"x":1,"x":2}'])
def test_setup_rejects_bad_mcp_before_enrollment(setup_paths, bad):
    workspace, state, config = setup_paths
    config.write_text(bad)
    with pytest.raises(ValueError):
        make_plan(setup_paths)
    assert not state.exists() and not (workspace / ".clinerules").exists()
    assert config.read_text() == bad


def test_setup_preserves_conflicting_hooks_and_registry_authority(setup_paths, tmp_path):
    workspace, state, config = setup_paths
    original = config.read_bytes()
    hook = workspace / ".clinerules/hooks/PreToolUse.ps1"
    hook.parent.mkdir(parents=True)
    hook.write_text("# owner hook")
    with pytest.raises(ValueError, match="hooks conflict"):
        make_plan(setup_paths)
    assert config.read_bytes() == original and not state.exists()
    hook.unlink()
    onboarding.apply(make_plan(setup_paths))
    with pytest.raises(ValueError, match="already enrolled"):
        onboarding.prepare(workspace, state=tmp_path / "other state")
    with pytest.raises(ValueError, match="preserves the existing mission"):
        onboarding.prepare(workspace, mission="Replace mission silently")
    hook.write_text("# modified after installation")
    with pytest.raises(ValueError, match="adapter files changed"):
        onboarding.prepare(workspace)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"port": 80},
        {"port": 65536},
        {"ttl": 59},
        {"origin": "https://example.com/path"},
        {"origin": "http://remote.example"},
    ],
)
def test_bad_companion_settings_fail_before_install(setup_paths, kwargs):
    with pytest.raises(ValueError):
        make_plan(setup_paths, **kwargs)
    assert not setup_paths[1].exists()


def test_setup_rejects_model_editable_state_and_mcp_path(setup_paths):
    workspace, _, config = setup_paths
    with pytest.raises(ValueError, match="separate"):
        onboarding.prepare(workspace, state=workspace / ".state", mission="Work", mcp_config=config)
    local = workspace / "mcp.json"
    local.write_text("{}")
    with pytest.raises(ValueError, match="outside this project"):
        onboarding.prepare(workspace, mission="Work", mcp_config=local)


def test_wizard_review_can_cancel_without_mutating_files(setup_paths):
    workspace, state, config = setup_paths
    args = cli.build_parser().parse_args(
        [
            "--state",
            str(state),
            "setup",
            "--workspace",
            str(workspace),
            "--mission",
            "Work",
            "--mcp-config",
            str(config),
        ]
    )
    replies = iter(["", "", *(["n"] if os.name == "nt" else []), "n", "n"])
    result = onboarding.wizard(args, input_fn=lambda _: next(replies), emit=lambda _: None, interactive=True)
    assert result == {"status": "cancelled", "changes_applied": False}
    assert not state.exists() and not (workspace / ".clinerules").exists()


def test_cli_setup_and_doctor_report_unverified_native_capture(setup_paths, capsys):
    workspace, state, config = setup_paths
    args = ["--state", str(state)]
    assert (
        cli.main(
            [
                *args,
                "setup",
                "--yes",
                "--workspace",
                str(workspace),
                "--mission",
                "Work",
                "--mcp-config",
                str(config),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["configuration"]["installed"]
    assert cli.main([*args, "doctor"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["capture"]["state"] == "unknown" and result["observed_sessions"] == 0
    assert result["companion"]["running"] is False
    assert cli.main(["doctor", "--workspace", str(workspace)]) == 0
    assert json.loads(capsys.readouterr().out)["configuration"]["installed"]


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_real_managed_process_restart_reconnect_and_stop(setup_paths):
    workspace, state, _ = setup_paths
    port = free_port()
    onboarding.apply(make_plan(setup_paths, port=port))
    origin = "http://localhost:3000"
    before = (workspace / "app.py").read_bytes()
    try:
        started = desktop.launch(state)
        assert started["running"] and started["status"] == "ready"
        assert desktop.launch(state)["status"] == "already_running"
        link = desktop.connection(state)["connect_url"]
        token = link.rsplit(":", 1)[1]
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", headers={"Origin": origin}, timeout=10
        ) as client:
            response = client.post(
                "/v1/pair", json={"label": "Process fixture"}, headers={"Authorization": "Bearer " + token}
            )
            assert response.status_code == 200
            paired = response.json()
            snap = client.get("/v1/snapshot", headers={"Authorization": "Bearer " + paired["token"]}).json()
            assert snap["bridge"]["capture_worker_running"] is False and not snap["runs"]
            assert desktop.stop(state)["status"] == "stopped"
            assert desktop.status(state)["running"] is False
            assert desktop.stop(state)["status"] == "already_stopped"
            restarted = desktop.launch(state)
            assert restarted["instance"] != started["instance"]
            renewed = client.post(
                "/v1/renew", json={}, headers={"Authorization": "Bearer " + paired["credential"]}
            )
            assert renewed.status_code == 200
            assert renewed.json()["device_id"] == paired["device_id"]
            assert client.get("/v1/snapshot", headers={"Authorization": "Bearer " + token}).status_code == 401
        assert (workspace / "app.py").read_bytes() == before
        service = Vessel(state)
        assert not service.store.events() and not service.store.list("runs")
        service.close()
    finally:
        desktop.stop(state)


def test_occupied_port_does_not_replace_log_or_stop_owner(setup_paths):
    _, state, _ = setup_paths
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        onboarding.apply(make_plan(setup_paths, port=other.getsockname()[1]))
        (state / desktop.LOG).write_text("previous private output")
        with pytest.raises(ValueError, match="occupied"):
            desktop.launch(state)
        assert other.getsockname()[1] > 0
        assert (state / desktop.LOG).read_text() == "previous private output"
        assert desktop.status(state)["running"] is False


def test_stale_pid_and_old_stop_request_cannot_control_new_process(setup_paths):
    _, state, _ = setup_paths
    onboarding.apply(make_plan(setup_paths, port=free_port()))
    desktop._write(state / desktop.RUNTIME, {"pid": os.getpid(), "status": "ready", "instance": "a" * 32})
    desktop._write(state / desktop.STOP, {"instance": "a" * 32})
    assert desktop.status(state)["running"] is False
    try:
        current = desktop.launch(state)
        assert current["instance"] != "a" * 32 and current["running"]
    finally:
        desktop.stop(state)


class FakeRegistry:
    HKEY_CURRENT_USER = "current-user"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {"Unrelated": ("keep", self.REG_SZ)}

    def OpenKey(self, hive, key, reserved, access):
        assert hive == self.HKEY_CURRENT_USER and key == startup.RUN_KEY

        class Handle:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        handle = Handle()
        handle.access = access
        return handle

    CreateKeyEx = OpenKey

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def QueryValueEx(self, key, name):
        if not key.access & self.KEY_READ:
            raise PermissionError("Registry handle cannot query values")
        if name not in self.values:
            raise FileNotFoundError
        return self.values[name]

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = (value, kind)

    def DeleteValue(self, key, name):
        del self.values[name]


@pytest.fixture
def fake_startup(setup_paths, monkeypatch):
    _, state, _ = setup_paths
    onboarding.apply(make_plan(setup_paths))
    registry = FakeRegistry()
    monkeypatch.setattr(startup, "_windows_registry", lambda: registry)
    monkeypatch.setattr(
        startup, "command_for", lambda s, p: '"pythonw.exe" -m vessel.desktop --state "test state"'
    )
    return state, registry


def test_startup_is_opt_in_idempotent_and_removes_only_owned_entry(fake_startup):
    state, reg = fake_startup
    assert startup.configure(state, "status")["status"] == "disabled"
    for _ in range(2):
        assert startup.configure(state, "enable")["status"] == "enabled"
    assert len(reg.values) == 2
    for _ in range(2):
        assert startup.configure(state, "disable")["status"] == "disabled"
    assert reg.values == {"Unrelated": ("keep", reg.REG_SZ)}


def test_startup_refuses_unowned_or_modified_registry_entry(fake_startup):
    state, reg = fake_startup
    name = startup.name_for(state)
    reg.values[name] = ("not-owned", reg.REG_SZ)
    for action in ("enable", "disable"):
        with pytest.raises(ValueError, match="preserved"):
            startup.configure(state, action)
    assert startup.configure(state, "status")["status"] == "conflict"
    del reg.values[name]
    startup.configure(state, "enable")
    reg.values[name] = ("edited-by-user", reg.REG_SZ)
    with pytest.raises(ValueError, match="preserved"):
        startup.configure(state, "disable")
    assert reg.values[name][0] == "edited-by-user"


def test_failed_startup_registration_can_retry_without_claiming_success(fake_startup, monkeypatch):
    state, reg = fake_startup
    original = reg.SetValueEx
    monkeypatch.setattr(reg, "SetValueEx", lambda *a: (_ for _ in ()).throw(PermissionError("blocked")))
    with pytest.raises(PermissionError):
        startup.configure(state, "enable")
    assert startup.configure(state, "status")["status"] == "disabled"
    monkeypatch.setattr(reg, "SetValueEx", original)
    assert startup.configure(state, "enable")["status"] == "enabled"


@pytest.mark.skipif(os.name != "nt", reason="Windows interpreter and command quoting")
def test_startup_uses_pythonw_and_quoted_absolute_paths(setup_paths):
    _, state, _ = setup_paths
    profile = make_plan(setup_paths)["profile"]
    command = startup.command_for(state, profile)
    assert command == subprocess.list2cmdline(
        [str(Path(sys.executable).with_name("pythonw.exe")), "-m", "vessel.desktop", "--state", str(state)]
    )
    assert "api_key" not in command and "connect=" not in command
    with pytest.raises(ValueError, match="260"):
        startup.command_for(Path("C:/" + "x" * 300), profile)


def test_restored_state_cannot_enable_startup_or_setup(setup_paths):
    _, state, _ = setup_paths
    onboarding.apply(make_plan(setup_paths))
    store = Store(state)
    store.put("control", "restored", {"mode": "inspection_only"})
    store.close()
    with pytest.raises(ValueError, match="inspection-only"):
        onboarding.load_profile(state)
    with pytest.raises(ValueError, match="inspection-only"):
        make_plan(setup_paths)


def test_startup_recovers_interrupted_update_of_owned_command(fake_startup):
    state, reg = fake_startup
    startup.configure(state, "enable")
    old_command = reg.values[startup.name_for(state)][0]
    store = Store(state)
    store.put(
        "control",
        startup.RECEIPT,
        {
            "name": startup.name_for(state),
            "command": "interrupted-new-command",
            "previous_command": old_command,
        },
    )
    store.close()
    assert startup.configure(state, "enable")["status"] == "enabled"
    assert startup.configure(state, "disable")["status"] == "disabled"


@pytest.mark.skipif(os.name != "nt", reason="Real current-user Windows startup registration")
def test_real_windows_startup_entry_launches_and_is_removed(setup_paths, tmp_path):
    workspace, _, config = setup_paths
    state = tmp_path / "s"
    onboarding.apply(make_plan((workspace, state, config), port=free_port()))
    reg = startup._windows_registry()
    name = startup.name_for(state)
    assert startup._current(reg, name) is None
    try:
        assert startup.configure(state, "enable")["status"] == "enabled"
        command, kind = startup._current(reg, name)
        assert kind == reg.REG_SZ
        assert command == startup.command_for(state, onboarding.load_profile(state))
        # Exercise the exact registered command with no console and a foreign CWD.
        process = subprocess.Popen(
            command,
            cwd=tmp_path,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            current = desktop.status(state)
            if current["running"] and current.get("status") == "ready":
                break
            assert process.poll() is None, current
            time.sleep(0.1)
        else:
            pytest.fail("Registered startup command never became ready")
        assert startup.configure(state, "disable")["status"] == "disabled"
        assert startup._current(reg, name) is None
        assert desktop.status(state)["running"]  # Disabling startup is not a stop request.
    finally:
        desktop.stop(state)
        startup.configure(state, "disable")
    assert startup._current(reg, name) is None
