# Guided project setup

VESSEL provides a local setup wizard and a managed background companion. Users
work in VS Code + Cline and view their enrolled project in the dashboard. Run
these commands in PowerShell from the VESSEL installation folder.

## First installation

Install Python 3.11+ and run the existing dependency setup once:

```powershell
.\scripts\setup.ps1
.\scripts\setup-project.ps1
```

The second command starts the wizard. `vessel setup` or `.\vessel.cmd setup` opens
the same wizard when the package is already installed. It asks for:

1. The project folder you will open in VS Code.
2. A mission for a new enrollment. Existing enrollment and mission are preserved.
3. The full path opened by **Cline → MCP Servers → Configure MCP Servers**.
4. The dashboard origin and companion port. Local defaults are
   `http://localhost:3000` and `8765`.
5. Whether to enable Windows sign-in startup, and whether to launch now.

It displays the chosen settings before applying them. Selecting **n** at the
review leaves the project, enrollment and Cline settings unchanged. Windows
startup defaults to no change; declining it on a later setup does not disable an
existing registration. Use the explicit disable command below for that.

New private state is kept under `%LOCALAPPDATA%\VESSEL\projects\<project-id>`.
Rerunning setup discovers the project's original state through its enrollment
registry, including projects enrolled manually. `--state` can select a private
location explicitly, but cannot create a second authority for an enrolled project.
Private state and the project must be separate directories.

The wizard installs nine observation hooks and one project-specific MCP entry.
It preserves unrelated entries and refuses conflicting hooks, malformed settings
or edited owned files. It saves the dashboard address, port, access lifetime and
interpreter for future launches. Inference credentials are entered in Cline.
The wizard does not configure inference, patch the extension or bind a task.

## Complete the Cline connection

Open the same project folder in VS Code. Enable Cline hooks and run **Developer:
Reload Window** while Cline is idle. Confirm the MCP server named in the setup
result is connected. Keep other projects' VESSEL servers disabled while using this
project; setup lists other enabled entries but does not change them.

Choose your provider/model and enter its key in Cline. The verified local Windows
path currently requires the [Cline 4.1.17 compatibility patch](cline-capture-fix.md).
Other builds require a fresh compatibility check. Setup success reports configured
hooks, not verified native capture.

Start a fresh Cline task with this prompt:

> VESSEL capture check. Reply with exactly READY. Do not use tools, read or edit files, or run commands.

Then follow the [native probe and binding procedure](native-cline-test.md). Bind
the exact observed task ID and review a real tool receipt before doing protected
work. The dashboard can then start capture for that explicitly selected run.

## Everyday companion commands

Use the project folder to find its saved state automatically:

```powershell
$vesselProject = 'C:\Projects\MyApp'
.\vessel.cmd doctor --workspace $vesselProject
.\vessel.cmd launch --workspace $vesselProject
.\vessel.cmd companion-status --workspace $vesselProject
.\vessel.cmd connection --workspace $vesselProject
.\vessel.cmd stop-companion --workspace $vesselProject
```

Launch runs the companion in the background and prints its private pairing link.
An already-running managed companion is reused. `connection` shows the current
link again; do not share it. Pair once in the dashboard. Saved browser pairings
continue to work across subsequent launches with the same origin, port and state.

The companion writes its original private link and diagnostics to `companion.log`
inside private state. `companion-status` gives that path without exposing the link.
Pairing links and access sessions default to one hour; durable pairings survive
their expiry. For a new browser after the temporary link expires, stop and launch
the companion to issue a fresh link. Existing paired browsers do not need one.

`stop-companion` requests shutdown of the exact managed instance. It never kills
an arbitrary PID. A stale process record cannot appear active after a restart.
An occupied port causes an explicit startup failure; no unrelated listener is
stopped and the previous private log is preserved.

If a terminal is already running the older `vessel dashboard` command, stop that
terminal's bridge once before using `launch` on its port. Managed status and stop
commands control only the new managed launcher. After a restart, review the native
task and lease before starting capture; capture does not resume automatically.

## Optional Windows sign-in startup

```powershell
.\vessel.cmd startup enable --workspace $vesselProject
.\vessel.cmd startup status --workspace $vesselProject
.\vessel.cmd startup disable --workspace $vesselProject
```

Enable registers one entry for the current Windows user, using the installed
`pythonw.exe` and the exact state directory. It needs no administrator account and
opens no terminal window. It starts the companion at sign-in, not before sign-in.
Windows may delay or disable startup entries; status checks VESSEL's registration,
not Windows' separate startup policy. The registry command is bounded to 260
characters as required by [Microsoft's Run-key documentation](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys).

Disable removes only the exact VESSEL-owned entry and leaves a running companion
alone. To stop it too, use `stop-companion`. Edited or unowned startup entries are
reported as conflicts and preserved. Moving/deleting the Python installation or
private state requires setup/registration repair.

Windows startup launches the companion only. For the **local development
dashboard**, prepare it using [local testing](local-testing.md), then separately
run `npm.cmd run dev` in the dashboard folder. This feature does not start that
development server, VS Code, a Cline task or a model request.

## Scripted setup

For an explicitly chosen folder and active MCP profile:

```powershell
.\vessel.cmd setup --yes --workspace 'C:\Projects\MyApp' --mission 'Implement and test the approved feature' --mcp-config 'C:\Users\Me\.cline\data\settings\cline_mcp_settings.json' --origin 'http://localhost:3000' --port 8765
```

`--yes` skips prompts. It does not opt into launch or Windows startup; add
`--launch` or `--startup` explicitly. Existing projects can omit the mission and MCP
path when their owned enrollment/configuration is available. The PowerShell wrapper
offers `-Workspace`, `-State`, `-Mission`, `-McpConfig`, `-Origin`, `-Port`, `-Ttl`,
`-NonInteractive`, `-Launch` and `-EnableStartup`.

## Verification scope

The setup checks exercise preservation, conflicts, malformed inputs, cancellation,
original-state discovery, real background process launch/stop/restart, pair renewal,
occupied ports, stale PID/stop records, and exact startup ownership. On Windows they
also create an isolated temporary Run entry, invoke its actual command with no
console from another working directory, and remove it. A complete Windows
sign-out/sign-in cycle and other Cline builds remain separate validation.
