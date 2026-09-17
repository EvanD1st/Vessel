# VESSEL — continuity for VS Code + Cline

Version **0.5.0**, local developer preview. The [VS Code extension](vscode-extension/README.md) provides a reviewed setup and recovery flow for the verified Cline 4.1.17 Windows bundle. VESSEL records an enrolled project's
work, saves encrypted checkpoints, and prepares a reviewed handover to a fresh
Cline task. Users code in **VS Code with Cline** and inspect continuity through
the owner CLI or the browser dashboard. Cline is the only active editor adapter;
Claude Code is deferred.

For cloning, repository checks and excluded private files, see
[repository setup](docs/repository.md). Login passwords, provider keys and native
test state are not included.

For the installed Cline 4.1.17 Windows build, use the [local capture compatibility
patch](docs/cline-capture-fix.md) before the live test. It fixes missing tool IDs,
per-turn identity changes, reused tool-call IDs and missing foreground command
exit codes. A Cline update requires a new compatibility check; the patch is not
an upstream release.

Native source-to-destination recovery now has **verified local evidence** on the
patched Cline 4.1.17 Windows build: the fresh task retrieved its selected handover,
implemented pending work and passed all nine tests. Recovery is recorded as
`succeeded`, also confirmed on Chrome's Recovery page by the user's screenshot. See the
[live recovery report](docs/native-cline-live-20260913.md) and
[verification history](docs/verification.md). This result does not establish
production readiness or compatibility with other Cline builds. Configuration
health alone is never presented as native verification.

## Start locally

Run from this folder in PowerShell, with Python 3.11+ installed:

```powershell
.\scripts\setup.ps1
.\vessel.cmd --version
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe scripts\demo.py
```

The demo uses synthetic ledger events and real FastAPI tests, checkpoint storage,
handover and backup/restore. It makes **no inference requests** and does not change
your editor's global settings. Reports are saved under `.demo-runs`.
See [local dashboard setup and testing](docs/local-testing.md).

For a real project, run `.\scripts\setup-project.ps1` after dependency setup.
The wizard enrolls the project, installs Cline hooks/MCP and saves companion
settings. It offers background launch and optional Windows sign-in startup.
See [guided setup and everyday commands](docs/guided-setup.md).

## Connect Cline

1. Open VS Code and Cline. In Cline settings, select **OpenRouter**, enter your own
   provider key there, and choose a model. Inference is billed by the provider.
   Do not paste the key into VESSEL's companion connection form.
   [Cline's OpenRouter instructions](https://docs.cline.bot/provider-config/openrouter)
2. Enroll one local project with private state **outside** the project.
3. Open **Cline → MCP Servers → Configure MCP Servers**. Use the actual settings
   file opened by your installed Cline version. Different profiles and runtimes
   use different locations; VESSEL requires its explicit path.
4. Install the adapter and enable its command hooks in Cline. Reload its MCP
   server if necessary. Unrelated MCP entries are preserved; conflicting hooks
   and malformed settings stop installation for review.

```powershell
$vesselProject = 'C:\Projects\MyAgentTask'
$vesselState = "$env:LOCALAPPDATA\VESSEL\my-cline-task"
$clineMcpConfig = 'C:\REPLACE\WITH\CLINES\CONFIG\cline_mcp_settings.json'
.\vessel.cmd --state $vesselState enroll $vesselProject --mission 'Implement and test the approved task'
.\vessel.cmd --state $vesselState install-client $vesselProject --client cline --mcp-config $clineMcpConfig
.\vessel.cmd --state $vesselState inspect-client $vesselProject --client cline
```

Send the harmless probe in a fresh Cline task, inspect `sessions`, bind the
**observed exact task ID**, and start its companion before doing approved work.
See [Cline setup and compatibility](docs/cline.md) and the
[first real recovery test](docs/native-cline-test.md) for the complete sequence.

For an isolated FastAPI project:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_cline_canary.py
# After opening Cline's MCP settings file:
.\.venv\Scripts\python.exe scripts\prepare_cline_canary.py --mcp-config $clineMcpConfig
```

This uses `.cline-canary/authentication-task` and `.cline-canary/private-state`.
Rerunning preserves the existing enrollment and project. Earlier test history
is not rebound to a new client.

## What is implemented

| Area | Current behavior |
| --- | --- |
| Owner authority | One workspace, explicit native task binding, execution epochs, policy review and revocation. |
| Cline adapter | Nine command hooks, native task/tool ID parsing, read/proposal-only MCP, ownership checks on install/remove. |
| Capture | Encrypted event ledger, conservative tool outcomes, bounded artifacts, root-file changes and deletions detected. |
| Checkpoints | Integrity, required artifacts, capture gaps, pins, retention, same-user inspection-only backups. |
| Recovery | Stopped-source evidence, environment/context review, explicit destination, selected handover and continuation evidence. |
| Dashboard | Persistent browser pairing, renewable access sessions, reconnect retry, owner device revocation, tasks, checkpoints and recovery status. |
| Guided setup | Original-enrollment discovery, Cline configuration, saved launch settings, background companion management and optional Windows sign-in startup. |
| Gateway | OpenAI-compatible preview; real two-model switching, streaming, tool/result round trips and controlled fallback verified. [Live scope](docs/gateway-live-20260914.md). |

The watcher triggers file capture; it cannot prove which tool ran or that tests
passed. Payloads without native tool IDs are marked incomplete. Stop Cline and
its background commands before attesting shutdown; owner actions do not stop it.

Direct OpenRouter use does not pass through VESSEL's gateway. For that separate
option, see the [gateway guide](docs/gateway.md). The local dashboard now uses a
[invite-only account login](docs/dashboard-accounts.md); the hosted preview uses platform
sign-in. Both are separate from inference credentials. Files and
encryption keys stay locally. Remote extension hosts need separate setup review.

## Remaining production work

- Broader Cline-version coverage beyond the verified local recovery test.
- Native Cline-through-gateway and broader model compatibility, durable funding pauses, cooldowns,
  provider-key onboarding and routing configuration UI.
- Production validation of browser pairing and revocation. Pairing now survives
  access-session expiry and companion restart; access sessions still default to
  one hour. See [pairing and device management](docs/dashboard.md).
- Wallet ownership, real Orbio management, spending reconciliation and broader
  production validation. No wallet, top-up or balance API is invented.
- Claude Code support after Cline validation.

[Verification results](docs/verification.md) distinguish fixture tests from live
evidence. The [fallback plan](VESSEL_FALLBACK_IMPLEMENTATION_PLAN.md) remains a
roadmap. See [architecture](docs/architecture.md), [environment](docs/environment.md),
[maintenance](docs/maintenance.md) and [dashboard details](docs/dashboard.md).

Superseded design documents and build output are preserved under
`.migration-archive`, outside active source. Private historical state is retained;
no historical event is relabeled as Cline evidence.
