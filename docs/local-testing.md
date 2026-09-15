# Set up and test VESSEL locally on Windows

Use PowerShell. Python 3.11+ is required; Node.js 22.13+ is needed only for the
local web dashboard. No wallet, Orbio account or paid inference key is needed for
these local tests. The existing checkout already contains its Python environment
and dashboard dependencies.

For guided setup of a real project after dependency installation, run
`.\scripts\setup-project.ps1`. It offers background companion launch and optional
Windows sign-in startup. See the [setup guide](guided-setup.md). The disposable
demo below remains available for tests without inference.

## 1. Set up the local companion

```powershell
cd C:\Users\USER\Downloads\VESSEL
.\scripts\setup.ps1
.\vessel.cmd --version
```

Expected version: `0.5.0`. The setup installs the pinned Python dependencies and
the editable VESSEL package. If Python is not on PATH on another installation,
pass its full path with `-Python 'C:\Path\To\python.exe'`.

## 2. Run the tests and recovery demo

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\python.exe scripts\demo.py
```

The source suite covers local persistence, checkpoints, recovery authority, owner
actions, environment checks, gateway fixtures and the bridge. The demo prints a
JSON report with `recovery_status: "succeeded"`, `backup_restore_verified: true`,
one initial FastAPI test and two continuation tests. Each run creates a separate
folder under `.demo-runs`; it does not overwrite your application.

**Cline observations are synthetic.** Real FastAPI tests, encrypted storage,
checkpoints, restart, handover and backup/restore run locally. The demo does not
prove native Cline continuation, live provider billing or wallet recovery.

## 3. Prepare the dashboard

Run once, or after dashboard source changes, while the development server is stopped:

```powershell
.\scripts\setup-dashboard.ps1
```

This builds the dashboard and applies its local account/connection migrations.
Existing labels are preserved; hosted data is untouched. On a new installation,
create the first owner once:

```powershell
cd C:\Users\USER\Downloads\VESSEL\dashboard
node scripts/setup-accounts.mjs --email owner@example.com --name "Owner"
npm.cmd run dev
```

The setup prints a private temporary-login file path. Open
[localhost:3000](http://localhost:3000) in Chrome, sign in with that account, choose
your own password, and sign in again. The fixed demo password has been retired.
This computer's already-created owner uses `admin@vessel.local`; see
[the account guide](dashboard-accounts.md) for its temporary file and exact steps.
Sessions persist across restarts, last seven days and renew with activity.
Accounts are invite-only; owner creation and password resets are available under
**Account settings**. Account login, companion pairing and provider keys are separate.
The hosted preview has not been redeployed.

## 4. Connect a disposable demo

In a **third PowerShell terminal**, run:

```powershell
cd C:\Users\USER\Downloads\VESSEL
.\scripts\run-dashboard-demo.ps1
```

This creates a fresh tested recovery demo, prints its report location, and starts
a local bridge on `127.0.0.1:8765`. Copy its printed `connect_url` into the dashboard's
**Connect a companion** form. Use a label such as `Local demo`, then select
**Connect companion**. If Chrome asks for local-device access, allow it to connect
to your companion. Keep both terminals running; keep the private link to yourself.

Expected dashboard data: the fixture mission, source and destination runs, recorded
tasks/operations, a saved checkpoint, and the successful fixture recovery. The
demo's worker stops after the drill, so an expired heartbeat is expected. Use
**Start capture** for the selected current run to restart background capture.
Capture health and native Cline verification remain separate indicators.

If the web app prints another port, match it explicitly:

```powershell
.\scripts\run-dashboard-demo.ps1 -Origin 'http://localhost:3001'
```

If bridge port 8765 is occupied, add `-Port 8766`. To prepare a demo without starting
a server, use `-PrepareOnly`. After pairing once, refreshing the page renews access
automatically using this browser's saved device credential. Ctrl+C stops each
terminal's server. Restart the bridge with the same state, port and origin to
reconnect without another link; the browser retries while the bridge starts.
Stopping the bridge
does not delete the demo or its report.

You can also use the [published private dashboard](https://vessel-continuity.jamesevan393.chatgpt.site)
with the same local demo by passing its exact origin to `-Origin`. That path uses
platform account sign-in and Chrome's local-access permission instead of local mock auth.

## Additional dashboard checks

With the local web server running on port 3000 and at least one free saved-label
slot in its demo account, run in a separate terminal:

```powershell
cd C:\Users\USER\Downloads\VESSEL\dashboard
..\.venv\Scripts\python.exe scripts\verify-api.py
npm.cmd run lint
npm.cmd run test:pairing
npx.cmd tsc --noEmit
..\.venv\Scripts\python.exe scripts\verify-login.py
```

The API check uses the real local D1 database and synthetic account fixtures. It
cleans up only its own test records and preserves existing labels. For a real Cline project, use
the separate [native canary procedure](cline.md) and [environment requirements](environment.md).

For a focused pairing check, start the bridge with `--ttl 60`, connect once, and
leave the dashboard open past one minute: access should renew without a new link.
Close the tab, wait past the access lifetime, then reopen it: it should reconnect.
Stop the bridge, reload the page, then restart the bridge with the same state,
port and origin: retry should connect automatically. Finally, run `devices` and
`revoke-device DEVICE_ID` through the owner CLI: that browser must lose access
and fail to renew, while another paired browser remains connected. The login
cookie is separate and may require signing in again.
