# Cline 4.1.17 local capture compatibility

This is a **local, reversible compatibility patch**, not an upstream Cline
release or production certification. It is restricted to the inspected Windows
Cline 4.1.17 SDK bundle with SHA-256
`d07c9ff15be2952dbe95d5571f13b06edb73053d9557ef853611c3edc426b2d8`.
The legacy runtime and different builds are not covered.

## What was wrong

The VS Code SDK host explicitly disables SDK file hooks. Its remaining command
hook bridge omits native tool IDs; its protobuf conversion drops additional
fields. The internal `conversationId` can change between turns in a single
visible task. The persisted transcript confirms that the September 11 READY and
implementation turns belonged to root session `1789100488010_o16l2`. Treating
those changing conversation IDs as separate user tasks was an adapter error.

The terminal tool also returns a successful outer envelope for some incomplete
executions and for batches containing failures. Text saying tests passed cannot
prove a successful command.

The repeated live command exposed another collision: Cline can reuse the same
conversation, agent, iteration and `call_0` across separate executions. The SDK
creates a new `runId` for every execution and exposes it in the hook snapshot.
Sidecar schema 2 now preserves that native ID; schema 1 is rejected for new
observations because it cannot distinguish those executions.

## What the patch does

- Adds a `vesselCapture` sidecar to the existing hook JSON, preserving it through
  protobuf serialization. Existing hook parameters and control responses remain
  in place; hook enablement and approvals are unchanged.
- Captures the root session from the native VS Code session controller and pins
  it for the hook instance. VESSEL binds that stable root ID and separately
  retains the original internal conversation ID.
- Preserves the native agent, execution `runId`, iteration and tool-call ID.
  Tool receipts use `[conversation, agent, nativeRun, iteration, toolCall]`.
  Separate executions have separate receipts; duplicate delivery of the same
  native call remains idempotent.
- Retains VS Code foreground terminal completion codes in structured command
  results. Missing exit status, detached execution, unsupported executor modes,
  failed batch entries and malformed IDs remain explicit failures or capture gaps.
- Does not read inference keys, change providers, execute additional commands,
  fabricate events, repair old capture gaps, or move historical events to a run.

The foreground VS Code terminal mode is the supported command path for this
patch. Background execution lacks the new completion fields and remains blocked
for verified shell receipts. If VS Code cannot observe an exit code, diagnose
shell integration before proceeding; do not substitute printed success text.

## Install or restore

Run from the VESSEL root. The existing installation was patched with:

```powershell
.\.venv\Scripts\python.exe -m vessel.cline_compat install --extension C:\Users\USER\.vscode\extensions\saoudrizwan.claude-dev-4.1.17 --backup C:\Users\USER\AppData\Local\VESSEL\cline-compat\4.1.17-d07c9ff15be2-v3
```

Then run **Developer: Reload Window** in VS Code. The patch is not active inside
an already loaded extension host. Do this while Cline is idle.

The installer validates the exact bundle, backs it up before publishing, and
refuses unknown or edited files. An interrupted publication can be resumed.
Restore uses the same command with `restore` instead of `install`, followed by
another window reload. The original bundle and patch receipt remain in the
backup directory. Cline updates can replace the patch; new builds require their
own compatibility review. Distributing a supported upstream integration remains
separate work; this version-specific local patch must not be advertised as one.

## Isolated live check

`scripts/prepare_capture_probe.py --root .cline-capture-check-v3` prepares
`.cline-capture-check-v3/project` and its separate `private-state`.
It installs only observation hooks, does not change
MCP settings, and refuses to overwrite an existing probe. No synthetic events
are injected. The original `.cline-canary` stays available for inspection.

1. Open `.cline-capture-check-v3/project` in VS Code and reload the window. Enable
   Cline hooks. In a fresh Cline task send:

   > VESSEL capture check. Reply with exactly READY. Do not use tools, read or edit files, or run commands.

2. From the repository root, inspect and bind the **observed root session ID**:

   ```powershell
   .\vessel.cmd --state .cline-capture-check-v3\private-state sessions
   .\vessel.cmd --state .cline-capture-check-v3\private-state start .cline-capture-check-v3\project --session OBSERVED_SESSION_ID
   ```

3. In that same Cline task, ask it to run only:

   ```powershell
   & 'C:/Users/USER/Downloads/VESSEL/.venv/Scripts/python.exe' 'C:/Users/USER/Downloads/VESSEL/.cline-capture-check-v3/project/probe.py'
   ```

   Do not edit files, install dependencies or start a background process. Approve
   the ordinary tool request in Cline if prompted. MCP is not needed for this probe.
   Do not append a status-printing expression. Review the captured command and
   output as well as its exit code: a compound PowerShell command can finish with
   zero even after an earlier command failed. Forward slashes avoid Markdown
   consuming backslashes before dot-prefixed directory names when copying.

4. Inspect `status --workspace .cline-capture-check-v3\project` and
   `operations --run RUN_ID` with the same state prefix. Require events on the
   bound root session, matched native intent/result, observed exit code zero,
   and no capture gaps. Repeat the command in another turn of the **same task**
   to check stable identity and repeated provider IDs. Require two successful
   operations with distinct native execution IDs. A fresh task must retain
   its different root ID and must not inherit the existing run.

5. Only after this passes, prepare a separate full recovery canary. Do not clear
   the old run's gaps or relabel its events. Checkpoint, MCP handover and actual
   continuation still require the [native recovery test](native-cline-test.md).

## Checks

The portable Python tests exercise scoped IDs, missing/false/non-numeric exit
codes, failed batches, unknown outcomes, secret sanitization, version/hash
rejection, backup ownership, restore and interrupted installation. Node checks
the helper's preservation of hook control responses.

`scripts/verify_cline_patch.cjs PATCHED_BUNDLE HELPER` additionally executes the
actual patched hook and terminal functions with isolated VS Code fixtures,
including the protobuf round trip and changing active-session selection. This
does not load VS Code or invoke inference, and is **not** a native live pass.

The final live command check passed on September 13: three distinct receipts
cover two SDK executions and a repeated call in iteration 2. After the PC restart
led to a different native task, the owner closed the previous test run and bound
the observed task prospectively. A reviewed capture repair followed successful
native validation of that binding. The previous checkpoint retains its blockers,
and historical events remain unchanged. No synthetic native events were injected.
See [recorded results](verification.md) for the exact evidence and remaining
file-edit/checkpoint/handover/continuation checks.
