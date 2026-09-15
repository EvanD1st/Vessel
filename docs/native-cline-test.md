# First real Cline recovery test

This is the repeatable live acceptance procedure. The
[13–14 September report](native-cline-live-20260913.md) records verified native
retrieval, edits and nine passing tests on the patched Windows build; its recovery
is succeeded, with visible dashboard confirmation pending. The owner configures
inference in Cline and operates its tasks and tool approvals. Automated fixture
tests do not need a provider key.

The 11 September attempt is **blocked**: the installed Cline 4.1.17 command hooks
omitted native tool IDs, and the adapter mistook per-turn conversation IDs for
stable task IDs. Preserve that run and project. Do not retry recovery or clear its
capture gaps. A compatible capture path must pass the checks below in a separate
test before implementation resumes. The [local compatibility patch and isolated
capture check](cline-capture-fix.md) are now available; reload VS Code after
installing the patch. See [recorded results](verification.md).

## Prepare and connect

From the VESSEL root in PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_cline_canary.py
$vesselProject = (Resolve-Path '.cline-canary\authentication-task').Path
$vesselState = (Resolve-Path '.cline-canary\private-state').Path
# Replace with the actual file opened by Cline's MCP Configure action.
$clineMcpConfig = 'C:\REPLACE\cline_mcp_settings.json'
.\.venv\Scripts\python.exe scripts\prepare_cline_canary.py --mcp-config $clineMcpConfig
.\vessel.cmd --state $vesselState inspect-client $vesselProject --client cline
```

Open `$vesselProject` in VS Code, enable the installed Cline hooks, and verify the
VESSEL MCP server connects. Configure inference using [the setup guide](cline.md).
In a **fresh Cline task**, send:

> VESSEL live capture probe. Reply with exactly READY. Do not use tools, read or edit files, or run commands.

Then inspect actual capture:

```powershell
.\vessel.cmd --state $vesselState sessions
.\vessel.cmd --state $vesselState status --workspace $vesselProject
```

Record the exact observed task ID, Cline/VS Code version, active runtime and model.
Missing events stop the test. Once the probe is recorded:

```powershell
.\vessel.cmd --state $vesselState start $vesselProject --session SOURCE_TASK_ID
.\vessel.cmd --state $vesselState dashboard --origin 'http://localhost:3000' --port 8766 --ttl 28800
```

Keep the bridge running. Open the local dashboard in Chrome, connect its private
`connect_url` under **Cline live test**, select the returned run and Start capture.
Alternatively run `companion --run RUN_ID --epoch EPOCH` in another terminal. Use
the same state prefix for every command. Avoid duplicate companion workers.

## Verify tool capture before implementation

Stay in the **same Cline task** whose exact ID was bound. A READY reply checks
conversation capture only. It does not establish tool receipt compatibility.
Send this small probe before asking Cline to implement anything:

> In this same task, run only the Python interpreter listed in the project README with `-c "print('VESSEL_TOOL_PROBE')"`. Do not edit files, install dependencies or start a server. Report the actual exit status.

Inspect `operations --run RUN_ID` and `status --workspace $vesselProject` using
the same state prefix. Require a matching native intent/result pair, an explicit
zero exit status, no capture gaps and attribution to the bound task. A successful
terminal message or a configured MCP server alone does not pass this check.
Repeat the same command in a second user turn of that same task. Require two
separate operations with distinct native SDK execution IDs, even when the
conversation, iteration and provider tool-call ID are reused.
If the hooks omit IDs, stop here for adapter compatibility work. Neither refresh
nor `repair-capture` can reconstruct missing native evidence.

## Source work and checkpoint

Only after the tool probe passes, send Cline in that **same task**:

> Read this project's README. Implement registration and login in the disposable FastAPI app, with tests. Use the existing Python interpreter listed in the README and an in-memory demo store. No external services, real user data, dependency installation or background servers. Leave password reset unimplemented and clearly list it as pending. Run the tests and report the actual result.

Inspect `operations --run RUN_ID`, tasks and changed files. Require native tool
IDs, matching intent/result receipts and an explicit successful test exit status.
The watcher alone cannot prove those operations. Missing native IDs or unknown
outcomes pause the test for compatibility diagnosis.

Record the pending task and inspect the environment. Replace all uppercase
placeholders with actual evidence. BUDGET is the available byte budget after
client/tool/output reserves, not the model's advertised token window.

```powershell
.\vessel.cmd --state $vesselState task --run RUN_ID --id password-reset --description 'Implement and test password reset'
.\vessel.cmd --state $vesselState verify-environment --model MODEL_ID --context-bytes BUDGET --note 'Describe actual runtime and model-capacity checks'
```

See [environment requirements](environment.md). After Cline finishes, stop its
commands and any background processes, then capture the stopped source:

```powershell
.\vessel.cmd --state $vesselState stop --run RUN_ID --attest-stopped --note 'Describe verified source shutdown'
.\vessel.cmd --state $vesselState checkpoint --run RUN_ID
.\vessel.cmd --state $vesselState verify --checkpoint CHECKPOINT_ID
```

Review integrity, capture gaps and eligibility before proceeding.

## Fresh destination and continuation

Start a fresh Cline task, repeat only the harmless probe and observe its exact ID.
Do not let it edit files yet. Prepare and review the plan before using its token:

```powershell
.\vessel.cmd --state $vesselState recover --checkpoint CHECKPOINT_ID --session DESTINATION_TASK_ID --request cline-live-1 --context-bytes BUDGET
.\vessel.cmd --state $vesselState handover --recovery RECOVERY_ID --review-token REVIEW_TOKEN
```

Start capture for the returned destination run and epoch. In that task, send:

> Call the VESSEL MCP tool vessel_get_recovery_context with recovery_id RECOVERY_ID. Inspect that handover and the existing project. Implement the pending password reset task using the existing local environment, then run all tests. Report the actual result and leave any failure explicit.

Require the selected handover retrieval, real destination events, new edits and a
matching successful test receipt. Then confirm:

```powershell
.\vessel.cmd --state $vesselState confirm --recovery RECOVERY_ID --operation OPERATION_ID --note 'Describe observed destination continuation'
```

The dashboard must show that same recovery as succeeded. Record results in
`docs/verification.md` with evidence identifiers and limitations, never keys or
private connection links. Missing evidence must not be replaced with synthetic
events. Persistent pairing, automatic renewal/reconnection and device revocation
remain queued after this test; a local pass does not establish production readiness.
