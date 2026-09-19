"""The version-specific shim preserves native evidence and original hook control."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vessel import cline_compat as compat
from vessel.cline import EventRejected, normalize_event
from vessel.service import Vessel


@pytest.fixture
def workspace(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return project


def bridge_event(
    workspace, *, result=False, root="session-1", conversation="conv-1", iteration=1, native_run="exec-1"
):
    call = {"id": "call_0", "name": "run_commands", "input": {"commands": ["python probe.py"]}}
    native = {
        "schema": 2, "rootSessionId": root, "conversationId": conversation,
        "agentId": "lead", "runId": native_run, "iteration": iteration, "toolCall": call,
    }
    if result:
        native["toolResult"] = {
            **call, "success": True,
            "output": [{"query": "python probe.py", "result": "READY", "success": True,
                        "completed": True, "exitCode": 0}],
        }
    return {
        "hookName": "PostToolUse" if result else "PreToolUse",
        "taskId": conversation, "workspaceRoots": [str(workspace)],
        "postToolUse" if result else "preToolUse": {"toolName": "run_commands", "success": True},
        "vesselCapture": native,
    }


def test_same_native_session_across_conversations_and_repeated_call_ids(workspace, tmp_path):
    service = Vessel(tmp_path / "state")
    try:
        service.enroll(workspace, "Probe capture")
        run = service.start(workspace, "session-1")
        for conversation, iteration in [("conv-1", 1), ("conv-1", 2), ("conv-2", 1)]:
            for result in [False, True]:
                event, gaps = normalize_event(bridge_event(
                    workspace, result=result, conversation=conversation, iteration=iteration
                ), workspace)
                assert gaps == []
                assert event["native_conversation_id"] == conversation
                service.observe(workspace, event, f"{conversation}-{iteration}-{result}")
        operations = service.operations(run["id"])
        assert len(operations) == 3
        assert all(service._successful_operation(op) for op in operations)
        assert service.status()["capture"]["state"] == "healthy"
        assert len(service.status()["sessions"]) == 1
        foreign, _ = normalize_event(bridge_event(workspace, root="another-session"), workspace)
        service.observe(workspace, foreign, "foreign")
        assert "unbound_native_tool_activity" in service.status()["capture"]["gaps"]
        assert len(service.operations(run["id"])) == 3
    finally:
        service.close()


def test_repeated_command_in_separate_executions_has_two_receipts(workspace, tmp_path):
    service = Vessel(tmp_path / "state")
    try:
        service.enroll(workspace, "Probe repeated turns")
        run = service.start(workspace, "session-1")
        # Reproduce the live collision: same task, conversation, agent, iteration,
        # call_0, command and output. Only the native SDK runId changes.
        for native_run in ["exec-1", "exec-2"]:
            for delivery in ["original", "retry"]:
                for result in [False, True]:
                    event, gaps = normalize_event(bridge_event(
                        workspace, native_run=native_run, result=result
                    ), workspace)
                    assert not gaps
                    assert event["native_run_id"] == native_run
                    service.observe(workspace, event, f"{native_run}-{delivery}-{result}")
        operations = service.operations(run["id"])
        assert len(operations) == 2
        assert all(service._successful_operation(op) for op in operations)
        assert service.status()["capture"]["state"] == "healthy"
    finally:
        service.close()


@pytest.mark.parametrize("mutation", [
    {"rootSessionId": None}, {"agentId": None}, {"iteration": None}, {"iteration": True},
    {"iteration": -1}, {"conversationId": "another"}, {"schema": True}, {"toolCall": None},
    {"schema": 1}, {"runId": None}, {"runId": ""}, {"runId": False},
])
def test_incomplete_or_mismatched_bridge_identity_is_rejected(workspace, mutation):
    payload = bridge_event(workspace)
    payload["vesselCapture"].update(mutation)
    with pytest.raises(EventRejected):
        normalize_event(payload, workspace)


@pytest.mark.parametrize("output", [
    [{"success": True, "result": "Tests passed!"}],
    [{"success": True, "completed": False, "exitCode": 0}],
    [{"success": True, "completed": True, "exitCode": None}],
    [{"success": True, "completed": True, "exitCode": False}],
    [{"success": True, "completed": True, "exitCode": "0"}],
    [], "READY", {"success": True},
])
def test_command_output_cannot_substitute_for_observed_completion(workspace, output):
    payload = bridge_event(workspace, result=True)
    payload["vesselCapture"]["toolResult"]["output"] = output
    event, gaps = normalize_event(payload, workspace)
    assert "native_tool_exit_status_unavailable" in gaps
    assert event["native_tool_success"] is False
    assert event["hook_event_name"] == "postToolUseFailure"


def test_mixed_batch_and_nested_tool_failures_are_not_success(workspace):
    payload = bridge_event(workspace, result=True)
    record = payload["vesselCapture"]["toolResult"]
    record["output"].append({"success": False, "completed": True, "exitCode": 2, "error": "failed"})
    event, gaps = normalize_event(payload, workspace)
    assert not gaps
    assert event["tool_output"]["exitCode"] == 2
    assert event["native_tool_success"] is False
    record["name"] = "read_files"
    record["output"] = [{"success": True}, {"success": False, "error": "missing file"}]
    event, _ = normalize_event(payload, workspace)
    assert event["hook_event_name"] == "postToolUseFailure"


def test_native_sidecar_secrets_and_outside_paths(workspace):
    payload = bridge_event(workspace)
    payload["vesselCapture"]["toolCall"]["input"]["api_key"] = "secret-value"
    event, _ = normalize_event(payload, workspace)
    assert "secret-value" not in json.dumps(event)
    payload["vesselCapture"]["toolCall"]["input"]["path"] = "../outside"
    with pytest.raises(EventRejected, match="outside_workspace"):
        normalize_event(payload, workspace)


def test_lifecycle_binding_does_not_require_a_tool_iteration(workspace):
    payload = bridge_event(workspace)
    payload["hookName"] = "TaskStart"
    del payload["vesselCapture"]["iteration"]
    del payload["vesselCapture"]["toolCall"]
    event, gaps = normalize_event(payload, workspace)
    assert event["conversation_id"] == "session-1"
    assert event["native_conversation_id"] == "conv-1"
    assert not gaps


def test_javascript_bridge_preserves_control_and_observed_exit_codes(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to exercise the actual bridge")
    helper = Path(compat.__file__).with_name("cline_bridge.cjs")
    script = r'''
const assert = require('node:assert/strict');
const bridge = require(process.argv[1]);
(async () => {
  const original = {cancel:true, contextModification:'owner policy'};
  const captured = [];
  const make = () => ({create:async () => ({isNoOp:false,run:async p => {captured.push(p);return original;}})});
  const snapshot = {conversationId:'native-conv',agentId:'lead',runId:'native-execution',iteration:3};
  const context = {snapshot,toolCall:{toolCallId:'call_0',toolName:'run_commands'},
    input:{commands:['probe']},result:{isError:false,output:[bridge.commandResult('probe',new bridge.CommandObservation('READY',0))]}};
  let selected='native-session';
  const scoped=bridge.factory(make,context,()=>selected);
  selected='different-visible-task';
  const runner = await scoped.create('PostToolUse');
  assert.equal(runner.isNoOp,false);
  assert.equal(await runner.run({taskId:'native-conv',postToolUse:{success:true}}),original);
  assert.equal(captured[0].taskId,'native-conv');
  assert.equal(captured[0].vesselCapture.rootSessionId,'native-session');
  assert.equal(captured[0].vesselCapture.schema,2);
  assert.equal(captured[0].vesselCapture.runId,'native-execution');
  assert.equal(captured[0].vesselCapture.toolResult.output[0].exitCode,0);
  assert.equal(captured[0].vesselCapture.toolResult.output[0].result,'READY');
  for (const exit of [undefined,null,'0',false,NaN]) {
    const r=bridge.commandResult('probe',new bridge.CommandObservation('claimed success',exit));
    assert.equal(r.exitCode,null);assert.equal(r.completed,false);
  }
  assert.deepEqual(bridge.commandResult('probe','partial output'),{query:'probe',result:'partial output',success:true});
  const denied = await bridge.factory(make,{...context,result:{isError:true,output:'denied'}},()=>'native-session').create();
  await denied.run({});assert.equal(captured[1].vesselCapture.toolResult.success,false);
  console.log('bridge contract passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
    completed = subprocess.run([node, "-e", script, str(helper)], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert "bridge contract passed" in completed.stdout


@pytest.fixture
def patch_target(tmp_path, monkeypatch):
    # An intentionally tiny bundle fixture covers patch ownership and atomic
    # publication. The installed real bundle is checked separately, never loaded
    # from a developer's extension directory by the portable suite.
    text = '''let r=Iut.create(await this.completeParams(e));return this[Ppt](r)
let o=Iut.toJSON(r);o.userPromptSubmit
function Eyr(t,e,r){let a=()=>new gFe({sessionWorkspaceRoot:r});eJh(o,i,a,e);tJh(o,i,a,e);a().create(1);a().create(2);a().create(3)}async function eJh(){}
r.hooks=Eyr(this.options.stateManager,this.options.emitHookMessage,e.cwd)
new hvr({stateManager:this.stateManager,emitHookMessage:e})
throw new ij(Q,N)}return q}finally{b.removeListener("line",L)}
return{query:f,result:h,success:!0}}catch(h)
'''
    original = text.encode()
    original_sha = compat.sha(original)
    # Inject this tiny fixture bundle into BUNDLE_SPECS so the patching logic
    # treats it as a known verified build with 4.1.17-style symbol names.
    fixture_spec = {
        "cline_version": "4.1.17",
        "patched_sha256": compat.sha(compat._apply_patch(text, {
            "proto_create": "Iut.create", "proto_tojson": "Iut.toJSON",
            "dispatch_sym": "Ppt", "hook_fn": "Eyr",
            "hook_fn_end": "async function eJh(",
            "session_cls": "gFe", "run_hooks_a": "eJh", "run_hooks_b": "tJh",
            "error_cls": "ij", "listener_var": "b", "statemanager_cls": "hvr",
        }).encode("utf-8")),
        "proto_create": "Iut.create", "proto_tojson": "Iut.toJSON",
        "dispatch_sym": "Ppt", "hook_fn": "Eyr",
        "hook_fn_end": "async function eJh(",
        "session_cls": "gFe", "run_hooks_a": "eJh", "run_hooks_b": "tJh",
        "error_cls": "ij", "listener_var": "b", "statemanager_cls": "hvr",
    }
    monkeypatch.setitem(compat.BUNDLE_SPECS, original_sha, fixture_spec)
    monkeypatch.setattr(compat, "ORIGINAL_SHA256", original_sha)
    extension = tmp_path / "extension"
    dist = extension / "next" / "dist"
    dist.mkdir(parents=True)
    (extension / "package.json").write_text(json.dumps({
        "publisher": "saoudrizwan", "name": "claude-dev", "version": "4.1.17"
    }))
    bundle = dist / "extension.js"
    bundle.write_bytes(original)
    return extension, tmp_path / "backup", bundle, original


def test_patch_install_repeat_restore_and_reinstall(patch_target):
    extension, backup, bundle, original = patch_target
    compat.install(extension, backup)
    patched = bundle.read_bytes()
    assert patched != original
    assert (backup / "extension.js.original").read_bytes() == original
    assert compat.install(extension, backup)["installed"]
    compat.restore(extension, backup)
    assert bundle.read_bytes() == original
    assert not bundle.with_name(compat.BRIDGE_NAME).exists()
    compat.install(extension, backup)
    assert bundle.read_bytes() == patched


def test_unsupported_build_refused_without_modifying_extension(patch_target):
    extension, backup, bundle, original = patch_target
    changed = original + b"modified"
    bundle.write_bytes(changed)
    with pytest.raises(ValueError, match="Unsupported"):
        compat.install(extension, backup)
    assert bundle.read_bytes() == changed
    assert not (backup / "patch.json").exists()


@pytest.mark.parametrize("target", ["bundle", "helper"])
def test_edited_patched_files_are_preserved(patch_target, target):
    extension, backup, bundle, _ = patch_target
    compat.install(extension, backup)
    path = bundle if target == "bundle" else bundle.with_name(compat.BRIDGE_NAME)
    path.write_bytes(path.read_bytes() + b"// owner edit")
    changed = path.read_bytes()
    with pytest.raises(ValueError):
        compat.restore(extension, backup)
    assert path.read_bytes() == changed


def test_interrupted_publication_is_resumable(patch_target, monkeypatch):
    extension, backup, bundle, original = patch_target
    write = compat._atomic_write

    def fail_publication(path, data, **kwargs):
        if path == bundle:
            raise OSError("interrupted")
        write(path, data, **kwargs)

    monkeypatch.setattr(compat, "_atomic_write", fail_publication)
    with pytest.raises(OSError):
        compat.install(extension, backup)
    assert bundle.read_bytes() == original
    monkeypatch.setattr(compat, "_atomic_write", write)
    assert compat.install(extension, backup)["installed"]
