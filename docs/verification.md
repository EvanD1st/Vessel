# Verification — Cline migration and local login

**14 September account update:** the hardcoded demo login described in earlier
results below is retired. Invite-only accounts, durable sessions, account controls
and local restart checks are documented in
[the current account verification](dashboard-accounts-verification-20260914.md).
Hosted deployment and dependency security remediation remain pending.

**14 September gateway update:** real Orbio inference passed with GPT-4.1 Mini
and GPT-4o Mini, including text/tool streaming, actual local tool execution and
result round trips, controlled HTTP/SSE fallback and no replay after commitment.
[Scope, receipts and provider compatibility findings](gateway-live-20260914.md).


Checked on Windows with Python 3.11.9, 10–14 September 2026. Version 0.5.0 is a
local developer preview. The latest live test establishes native recovery
evidence on the inspected patched Cline build, with user-supplied Chrome
confirmation of the succeeded recovery. Broader production validation remains pending.

## Completed checks

| Check | Result |
| --- | --- |
| Full Python suite | **298 passed**, two upstream deprecation warnings (September 14, guided setup and managed companion). |
| Python lint | Ruff passes for `src`, `tests`, `scripts`. |
| Local setup | `scripts/setup.ps1` completes; installed version 0.5.0; `pip check` passes. |
| Wheel | Builds successfully; new Cline/sanitization modules present, retired adapter absent; packaged Python matches source. |
| Cline hook launcher | Real PowerShell subprocess passes with synthetic payload, UTF-8, spaces and apostrophes in paths. |
| Cline MCP | Real stdio initialize, discovery of five tools and scoped status retrieval pass. |
| Installation | Exact ownership, unrelated MCP preservation, malformed JSON, edited files, conflicting hooks and repeated install/remove covered. |
| Native payload fixtures | SDK task/tool IDs preserved; missing IDs, unknown outcomes, foreign paths and malformed payloads remain explicit failures/gaps. |
| Watcher | Root edits, deletion, exclusions and incomplete scan behavior covered. |
| Recovery fixture drill | Succeeded; actual FastAPI tests pass before/after continuation; encrypted checkpoint and inspection-only backup/restore verified. |
| Native Cline recovery | Selected MCP handover retrieved by the observed destination; native edits and 9 passing tests verified; recovery recorded as succeeded. User-supplied Chrome Recovery screenshot confirms the badge for the tested destination/checkpoint. |
| Persistent browser pairing | Offline/restart renewal, revocation races, per-session expiry and stable receipt identity pass; 7 client transport/retry tests pass. |
| Live local pairing lifecycle | Nine real HTTP/client-helper checks passed across an actual companion restart; test devices revoked, native evidence unchanged. [Report](dashboard-lifecycle-live-20260914.md). |
| Guided setup and managed companion | 24 focused checks pass, including real hidden launch/restart, pair renewal and temporary Windows startup registration/removal. Existing project migrated with native evidence preserved. [Report](setup-verification-20260914.md). |
| Gateway fixtures | Primary failure/fallback success, split initial SSE errors, response bounds, eligible aliases and conservative no-replay classification covered. |
| Live gateway protocol | 11 real upstream calls passed in the final run; 69 gateway/runner automated checks pass. Native Cline routing is a separate remaining check. [Report](gateway-live-20260914.md). |
| Dashboard | TypeScript and production build pass. Python login/API scripts exercise the running local server. |
| Local login | Correct/incorrect credentials, forged cookie/header rejection, body/origin bounds, reload, logout revocation and existing account isolation pass. |
| Production auth boundary | Built Worker returns 404 for demo login, issues no session; demo password absent from browser JavaScript. |

The normal setup uses isolated build dependencies. A manual attempt with
`--no-build-isolation` failed because the environment's old setuptools lacked
`bdist_wheel`; the documented setup and ordinary wheel command succeeded.
The Sites build helper still has a Windows npm path-resolution problem; the
project's existing `npm.cmd run build` succeeds without dependency changes.

## Local drill evidence

Synthetic recovery report:
`.demo-runs/20260910-210653-0a4cc9/report.json`.
Recovery `recovery_38da3ead312ba110e8cdfef30170cfd1` succeeded at destination epoch 2.
The source FastAPI test passed; both destination tests passed. These are real
filesystem/test/storage operations driven by synthetic ledger events, with zero
inference requests.

Installed-hook smoke benchmark:
`.demo-runs/capture-20260910-211324-f69cea/report.json`.
Five synthetic 32 KiB observations coalesced into one eligible automatic
checkpoint. Whole-process acknowledgment p50 was 1,009 ms and p95 1,185 ms on this
run. The 250 ms target was **not met**. This small smoke sample is not a stable
performance characterization; shell/Python startup remains optimization work.

## Actual Cline setup

Prepared project: `.cline-canary/authentication-task`.
Private state: `.cline-canary/private-state`.
Enrollment: `enrollment_7ba628335f264850a1ea8ff369ddd090`.
The user identified `C:\Users\USER\.cline\data\settings\cline_mcp_settings.json`
as the active Cline configuration. Nine hooks and server `vessel-857944557785`
were installed there and inspected as configured. No provider key was read,
copied or tested, and no synthetic event was injected into this native canary.

Cline 4.1.17's installed SDK and legacy payload builders were inspected. The
legacy implementation lacks the tool IDs required for verified receipt pairing;
it is not certified by passing SDK fixtures. Follow the
[real native test](native-cline-test.md) to establish the active runtime, observed
source/destination IDs, selected handover retrieval and successful continuation.

Earlier native test history and enrollment were preserved. Owned retired hooks
and MCP entries were removed without warnings. Superseded documents, fixtures
and generated packages are under `.migration-archive/2026-09-10`.

## Native attempt on 11 September: blocked

The run `run_cc79cd9874da4d77bf7a976983bc1273` was bound to the READY-probe internal
conversation `conv_1789100488922_l4vsnct`. Implementation events carry the unbound
internal conversation `conv_1789100506339_hc01zqr`. At diagnosis the ledger held 26 actual events:
three from the probe and 23 from the implementation task. Its Cline 4.1.17
`PreToolUse` / `PostToolUse` command-hook payloads omitted native tool IDs.
Capture is degraded with `native_tool_id_unavailable`; no verified operations
belong to the bound run. Neither events nor ownership were reassigned.

Independent owner-side verification of the existing authentication project's
tests passes: **14 passed**. Password reset remains a 501 placeholder. This
confirms the current app tests, not native Cline receipt capture or recovery.
Existing files, enrollment, gaps and checkpoints were preserved; no capture
repair or synthetic native event was applied.

The capture error now explains missing native IDs and shows the bound and other
observed unbound task IDs. Binding preserves previously observed session
metadata. Future unbound tool/file activity during an open lease degrades
capture immediately; harmless destination READY probes do not. The test guide
now requires a correctly paired read-only tool probe before implementation.
The active command-hook contract needed an adapter compatibility solution.

**Identity correction:** inspection of Cline's native persisted transcript later
confirmed both internal conversations are turns of root session
`1789100488010_o16l2`. The prior description of the user doing implementation in
a different task was too strong. The adapter had used a per-turn conversation
ID as the visible-task identity. Existing ledger attribution has not been changed.

Diagnostic patch validation: 87 focused Cline/service/owner/bridge tests passed,
then all 19 bridge tests passed after adding the HTTP error regression (88
distinct tests across those modules). Ruff passes. The full-suite, wheel and
dashboard build results above predate this Python diagnostic patch. A running
bridge must be restarted to load it; existing immutable failed review receipts
keep their original message. No browser client changes or deployment were made.

## Local compatibility patch and native capture checks

A version-specific [local capture fix](cline-capture-fix.md) is now installed in
the Cline 4.1.17 Windows SDK bundle. Its original bytes are backed up outside
the project. The patch preserves native fields through hook protobuf
serialization, pins the visible task's root session and retains observed
foreground terminal exit codes. Unknown, detached and failed command outcomes
are not promoted to success. This is a local extension compatibility patch;
Cline updates and other builds require separate review.

The exact patched bundle passed Node syntax and isolated contract checks for
12 hook events, protobuf preservation, root-session binding across internal
conversation changes, task-selection changes and terminal completion/error
states, and distinct SDK execution IDs when all other call identifiers repeat.
These are fixtures, not a native live pass. The current native probe
workspace is `.cline-capture-check-v3/project`, with private state alongside it.
It contains only a print probe, README and observation hooks. No MCP settings
or provider configuration were changed and no synthetic event was injected.
VS Code must reload before a new native READY/tool probe can verify the patch.

The user reloaded VS Code and completed the native READY probe. Its three real
events (session start, prompt and stop) contain `vesselCapture` schema 1 with
root session `1789129995980_s0qp2` and internal conversation
`conv_1789129996762_2qew5ly`; all have zero capture gaps. This confirms the patched
bridge is loaded and delivering native session identity. On September 12 the
owner bound that observed root to `run_5390a07b8d634e17a6d56f641eb8754c`, epoch 1.
The original three events remain unbound historical observations.

On September 12 the user ran the actual probe in that same Cline task. Native
events 4–8 belong to the bound run despite the internal conversation changing
to `conv_1789243407757_kack491`. Events 6 and 7 form operation
`1350ffd40d579e138fc9d3af09f46f68a83cf6f95b15a39beb36e304dc32e0e4`, with native
scope `["conv_1789243407757_kack491","agent_1789243407757_waxnz3",1,"call_0"]`.
The result contains observed `completed: true`, integer `exitCode: 0` and
`VESSEL_TOOL_PROBE` output. The service reports `verified_success: true`,
`uncertain: false`, capture `healthy`, no gaps and a current companion heartbeat.
That single command was captured successfully. The repeat exposed a remaining
identity defect: native events 11 and 12 reused the same conversation, agent,
iteration and `call_0`, so they collapsed into the first operation. The earlier
healthy report was insufficient. An owner diagnostic now records
`native_execution_id_missing_repeated_turn_collision` against the original run,
with sequences 6, 7, 11 and 12 as evidence. Its capture state is degraded; all
historical events and attribution are unchanged.

Schema 2 preserves `snapshot.runId`, which the inspected SDK regenerates on each
execution. The old schema is rejected for new observations. The patched helper
was installed with backup `4.1.17-d07c9ff15be2-v3`, after restoring the owned v2
patch. Real READY events in the previous folder now include schema 2 and native
run IDs, proving the helper is loaded. The final repeated-command results appear
below. Full checkpoint/MCP handover/continuation was still unverified at this stage;
the later isolated recovery result is recorded below.

The current Cline-focused suite passes **59 tests**, including two successful
operations with reused IDs and distinct SDK executions, plus duplicate-delivery
idempotency. The full suite passes **262 tests** in 102.83 seconds; Ruff and the
installed bundle's syntax and isolated contract checks pass. The captured
full-suite output is `scratch/cline-compat-review/v3-pytest.txt`.
The v3 wheel builds successfully; packaged `cline.py`, `cline_compat.py` and
`cline_bridge.cjs` match source byte for byte. Its SHA-256 is
`9cb8f03608fec91fb006b75c1dd543773da366b0aebc5809433d5cced3e42900`.

The fresh v3 workspace recorded READY as events 1–3 for root task
`1789245220688_o8rfn`, internal conversation `conv_1789245221608_sq99i4l` and
native SDK run `run_cjE08RMo`, all schema 2 with no gaps. The owner then bound it
to `run_393ea1aaa830488eba6bec11de262b6f`, epoch 1, and started its companion.
Those original READY events retain their unbound attribution. Two later command
turns produced distinct native scopes with SDK IDs `run_1i1rNYL0` and
`run_0uSjmK02`, while conversation, agent, iteration and `call_0` stayed the same.
Events 6/7 and 11/12 now form two separate operations, confirming the identity
collision is fixed in real Cline activity.

Both captured command strings had lost the slash before `.venv` and
`.cline-capture-check-v3`, and appended `; $LASTEXITCODE`. Their output contains
`CommandNotFoundException`. Although VS Code reported whole-command exit zero,
these are **not successful Python probes**. The evidence report records the
identity result separately from failed command validation. The corrected
command uses forward-slash paths and no appended status expression.

After the user's battery-related PC restart, the installed patch hashes and
saved ledger were verified unchanged. The companion initially resumed the same
run and epoch. Cline then performed the corrected command in task
`1789259176298_d9fgq`, which had not been bound. Its native events 13–17 were
preserved as unbound observations; VESSEL correctly raised
`unbound_native_tool_activity`. The command itself printed `VESSEL_TOOL_PROBE`
and had observed exit zero, but it was not attributed to the previous run.

The owner stopped and cancelled the interrupted pre-restart run, retaining
diagnostic checkpoint `checkpoint_2d34f1ec94d645718a1ead4bca41906b`. It still has
`unbound_native_tool_activity` and `capture_health_not_healthy` blockers. The
observed new task was bound prospectively to
`run_2cd3fe1305294ed0908ff9a8e2aad6e5`, epoch 2, with its companion running.

**Live command capture passed.** Two subsequent user turns produced three
successful foreground probe executions. The receipt pairs are 20/21, 25/26 and
27/28. Their native scopes share conversation `conv_1789259177218_lhxcutb`,
agent `agent_1789259176947_82ktmd` and provider ID `call_0`, while SDK run IDs
`run_J4fpwNIJ` and `run_zSslywlp` distinguish executions; iteration 2 also
distinguishes the third call within the latter execution. All three have the
exact expected command, observed completion and integer exit zero, expected
probe output, a matched intent/result and no uncertainty or event gaps.

After reviewing these native receipts and the resolved binding mismatch, the
owner recorded an explicit capture repair for current work. Current capture is
`healthy`, with no gaps and `repair_evidence: owner_attested`. This review does
not manufacture or reassign observations: events 13–17 remain unbound, and the
previous checkpoint remains blocked byte for byte. No synthetic native events
were injected. Detailed results:
`scratch/cline-compat-review/v3-final-live-evidence.json`.

This command-only check established live command-capture evidence for the patched
Cline 4.1.17 Windows SDK build. The separate native recovery test below supplies
the subsequent file-edit, checkpoint, retrieval and continuation evidence.

## Native recovery on 13–14 September

The isolated test in `.cline-recovery-live-20260913/authentication-task` used
Cline's existing OpenAI-compatible inference connection and model
`aion-labs/aion-3.0-mini`. Source task `1789260154728_4cx4u` implemented
registration/login and passed five tests. After native stop, user completion and
shutdown evidence, checkpoint `checkpoint_dfafca82f2f34783bcf7e53afb71360a` passed
integrity and recovery checks with no blockers.

Observed fresh task `1789323748156_tfvfa` received epoch 2 through reviewed recovery
`recovery_f200a2f427c16a086e03ee6d80cd14ed`. Native receipt pair 35/36 retrieved that
exact selected handover. Destination file edits implemented the pending reset
task. A provider `ECONNRESET` interrupted execution; the same root task resumed
from saved files with a new SDK execution ID and completed its tests.

Native foreground pytest pair 67/68 has observed completion, integer exit zero,
and **9 passed, 2 upstream warnings in 4.15s**. All five original tests and original
registration/login definitions are preserved. Four new tests cover reset success,
old-password rejection, new-password login, invalid/expired tokens and token reuse.
File reconstruction from successful native edits matches saved redacted contents;
actual bytes match the final automatic checkpoint. Known failed reads/editor
requests have explicit owner reconciliation and remain failed receipts.

Recovery is recorded as **succeeded**, both tasks are done, and the run is
completed. Final checkpoint `checkpoint_b550ea80ffe941bd98ddd0edff7ec9b1` is eligible
with no blockers at event watermark 69. Capture is healthy without gaps or
unresolved operations. No native observations were synthesized or reassigned.
The saved result and file hashes were rechecked after the usage interruption.

The actual bridge snapshot API returned HTTP 200, the correct enrollment and
workspace, healthy capture and this exact recovery as `succeeded`. UI automation
could not start. The user confirmed connection and supplied Chrome screenshots
showing the exact final checkpoint with no blockers, healthy capture after
reconnection, and the Recovery page's succeeded badge for destination
`1789323748156_tfvfa` and the selected source checkpoint. See the
[detailed report](native-cline-live-20260913.md). This is
evidence for the inspected patched 4.1.17 Windows build, not other Cline builds
or production readiness. No VESSEL runtime code or disposable app was edited by
the owner during this final evidence review.

## Still pending

- Broader Cline-version coverage and live gateway alias/stream/tool compatibility.
- Hook-process latency optimization and broader production validation.
- Broader production validation of the
  [implemented pairing, renewal and revocation fixes](pairing-fixes-20260914.md).
  The real HTTP/client-helper lifecycle drill passed. After the restart drill,
  the user reported reconnection and supplied a Chrome Overview screenshot showing
  Companion connected and Capture healthy, followed by the Recovery page's succeeded badge.
- Production application login; fixed demo credentials are local-development only.
- Full Windows sign-out/sign-in validation of optional companion startup; the
  exact registered command and cleanup have passed real local checks.
- Funding pauses, cooldowns, capability checks, key onboarding, routing UI,
  wallet ownership and real provider funding/rotation integrations.
- Claude Code support after the Cline workflow.

The hosted Site was not redeployed in this change. Its platform authentication
and access policy remain in effect. Browser automation handoff was unavailable;
login behavior was verified through real HTTP requests, not browser UI automation.
