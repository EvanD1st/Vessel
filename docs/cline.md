# VS Code + Cline setup and compatibility

The 0.5 adapter targets Cline in a local VS Code extension host. Use one project
folder and one enabled VESSEL MCP server for this test. Keep other enrolled
projects' servers disabled in Cline while working on this one.

## Inference setup

In Cline settings, choose OpenRouter, enter the provider key and select a model.
Use the exact model ID and capacity reported by your provider. Provider usage and
availability still apply. VESSEL does not need that key for capture or recovery.
[Official provider setup](https://docs.cline.bot/provider-config/openrouter)

The optional VESSEL gateway uses Cline's OpenAI Compatible provider instead:
[gateway instructions and limits](gateway.md). A dashboard companion key, a
VESSEL inference token and an OpenRouter key authorize different services.

## Install into the actual Cline profile

The [guided setup wizard](guided-setup.md) combines enrollment and adapter
installation while preserving the original authority on reruns. The commands
below remain available for explicit owner control.

Enroll the project using the README commands. Open Cline's MCP Servers screen,
choose Configure, then Configure MCP Servers. Pass that existing JSON file's
path to `install-client --mcp-config`.
[Cline MCP instructions](https://docs.cline.bot/mcp/mcp-overview)

The installer adds a workspace-specific stdio server and nine scripts under
`.clinerules/hooks`: TaskStart, TaskResume, TaskCancel, TaskComplete, TaskError,
PreToolUse, PostToolUse, UserPromptSubmit and SessionShutdown. Windows uses `.ps1`
scripts with UTF-8 encoding; other platforms use executable shell scripts.
The launcher uses the actual Python interpreter from the VESSEL environment.

Enable hooks in Cline's hook controls and verify the MCP server connects. A VS
Code profile can use a different settings file from Cline's shared data directory.
VESSEL does not guess between them. A project-local
`.vscode/cline_mcp_settings.json` is not a substitute for the configured file.
Installation does not enable arbitrary tool auto-approval or change PowerShell's
execution policy. Existing hook conflicts require a reviewed combined hook.

```powershell
.\vessel.cmd --state $vesselState inspect-client $vesselProject --client cline
.\vessel.cmd --state $vesselState uninstall-client $vesselProject --client cline
```

The private manifest records only VESSEL's entry and hook hashes. Uninstall
removes exact owned entries and preserves unrelated servers. Edited owned files
stop removal for review.

## Native evidence gate

Cline **4.1.17** was inspected on this Windows installation on 10 September 2026.
Its package contains legacy and SDK implementations; the version alone does not
establish the payload contract delivered to command hooks. The package also
contains SDK event logging and a command-hook bridge that uses legacy-shaped
payloads. Passing SDK fixtures does not verify the extension's command hooks.
The public hooks page currently redirects to SDK
plugin documentation rather than providing a complete command-hook contract.

SDK payloads carry `taskId`, `agent_id` and native tool IDs. VESSEL preserves the
task ID and namespaces each actual tool ID with its actual agent ID. It never
infers IDs from names, ordering, time or prompt similarity. Legacy payloads
without tool IDs produce `native_tool_id_unavailable`. Successful results need
an explicit native success value; passing shell receipts also need an explicit
zero exit status. Completion text alone is insufficient.

`inspect-client` can report `configuration_health: configured` while
`native_capture: unverified`. Missing hooks, unknown outcomes and capture gaps
pause recovery. Do not use `repair-capture` to waive missing native evidence.
Record a repair only after diagnosing and verifying the source of the gap.

Run the [native recovery test](native-cline-test.md). If the active runtime omits
required IDs or outcomes, stop at that gate and record the compatibility limit.
Fixture events must not fill the gap.

The [13–14 September live test](native-cline-live-20260913.md) now records native
source and destination edits, retrieval of the selected MCP handover, and nine
passing destination tests on the patched 4.1.17 Windows SDK build. Its recovery
is `succeeded`, with user-supplied Chrome confirmation. This build-specific
evidence does not certify other runtimes or production readiness.

The live 11 September 2026 attempt received `PreToolUse` / `PostToolUse` payloads
with names, parameters and results but no native tool ID. It is blocked on
native verification. A [reversible compatibility patch](cline-capture-fix.md)
is available for the exact installed 4.1.17 Windows SDK bundle. It preserves
native IDs through protobuf conversion, binds the stable root session and
retains observed foreground command exit codes. It requires a VS Code reload
and an isolated live probe. The original failed run remains unchanged.
Do not force the extension's hidden runtime override as
a claimed fix: the installed next bundle also contains a legacy-shaped command
hook bridge. Require a real, correctly attributed tool probe before building.
