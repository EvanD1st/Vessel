# Dashboard and local companion

Open the [private VESSEL dashboard](https://vessel-continuity.jamesevan393.chatgpt.site).
The first private deployment succeeded on 8 September 2026.

For the default enrollment, launch its connection with:

```powershell
.\vessel.cmd dashboard --origin 'https://vessel-continuity.jamesevan393.chatgpt.site'
```

The VESSEL dashboard is a private Sites application. It uses account sign-in
for access; this is not wallet authentication or cryptographic wallet ownership.
The Python companion runs on the same computer as the browser. One enrolled
project connects per browser tab. The site cannot restart Cline or run arbitrary
shell commands on that computer.

## Connection

1. Install the Python package or run `scripts/setup.ps1` in this repository.
2. Enroll the approved project and install its Cline hooks/MCP using the main
   README commands. Keep private companion state outside the project.
3. Sign in to the dashboard. Start `vessel dashboard --origin HTTPS_SITE_ORIGIN`.
   For a non-default state directory use `vessel --state PRIVATE_STATE dashboard
   --origin HTTPS_SITE_ORIGIN`. Local site development may use
   `http://localhost:3000` as its explicitly approved origin.
4. Open the printed private link, or paste it into Connect a companion. Only its
   fragment contains the session key. The page immediately removes the fragment
   from its current history entry. Never share the link. For sign-in redirects
   that lose the fragment, paste the original CLI link after sign-in.
5. Approve your browser's local network request if prompted. A supported browser,
   the running local terminal and a matching site origin are all required.
6. Bind a fresh native conversation, or select the existing active run and start
   capture. Automatic capture runs while the bridge process and computer remain
   available. Disconnecting the browser does not stop the companion's worker.

The printed pairing link and access sessions default to one hour. `--ttl` permits
60 to 28,800 seconds and `--port` permits 1024 to 65535. Connecting exchanges the
temporary link for a distinct browser credential and a short-lived access session.
The browser retains its pairing credential until you revoke or clear it. Reloading
automatically renews access, including after extended time offline. The bridge must
be restarted with the same private state, port and approved dashboard origin.
If the browser opens before the bridge, it retries with backoff up to 30 seconds.
These retries read status and renew access; they never replay owner actions. The
bridge supports only `127.0.0.1`, checks Host and exact Origin, requires a strong
bearer key, disables caching and limits JSON action bodies to 128 KiB. Local
network permission differs between browsers; see the primary
[MDN local network access reference](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access).
Chrome reached the local-device access permission prompt. The complete hosted
HTTPS-to-loopback browser flow has not yet been verified.

## Data and authority

The hosted D1 database stores only owner-scoped connection labels, enrollment
IDs, local ports and update timestamps (up to 20 labels per account). It never
stores a bridge key, upstream key, project file, checkpoint or task payload.
The browser reads live status directly from the enrolled companion; task and
recovery text therefore stays between that machine and the browser. The session
access token is held in memory. Only the persistent browser credential, device ID,
enrollment ID and port are kept in this browser's local storage. They are never
sent to the hosted label database. The companion stores credential digests and
device metadata in its encrypted state. Browser storage is scoped to the dashboard
origin; use a trusted browser profile, and revoke a device if its credential is lost.

**Disconnect** ends this tab's connection without revoking pairing or stopping
capture. Reloading can reconnect. **Forget** revokes this browser's device first,
then removes its local pairing and saved label. If the companion is unavailable,
the credential and label are retained so revocation can be retried. Other paired
browsers are unaffected. An owner can list and revoke a lost device from PowerShell:

```powershell
.\vessel.cmd --state PRIVATE_STATE devices
.\vessel.cmd --state PRIVATE_STATE revoke-device DEVICE_ID_FROM_LIST
```

The list includes IDs, labels, creation/last-use times and revocation state. A
revocation blocks existing access sessions and future renewal. It is serialized
with renewal, so a concurrent request cannot restore the revoked pairing. Expired
access sessions alone do not remove the pairing.

When upgrading the earlier temporary-token prototype, restart the bridge and pair
once using its new printed link. Old `vessel_token_...` browser entries are not
treated as durable credentials; successful pairing removes the corresponding old
entry. Legacy device rows remain listable and revocable by the owner.

Bridge requests choose from a fixed owner-action allowlist. They cannot supply
arbitrary paths, methods, shell commands, SQL or inference credentials. Every
write transaction checks the reviewed policy revision and execution epoch.
Only authority changes committed by the action itself are followed across its
subsequent transactions. Competing changes fail closed.

Each request has an encrypted durable receipt scoped to the paired device (or the
temporary bootstrap session for direct owner API use).
Duplicate inputs reuse a completed receipt; changed inputs with the same request
ID are rejected. After an interrupted request, a `started` receipt is an unknown
outcome, not permission to retry. Refresh and inspect state; receipt lookup never
replays an action. Session renewal and bridge restart preserve the device's receipt
scope, so an owner can inspect an earlier request without executing it again.

Agent proposals remain claims. Acceptance adds an owner review and can assign a
task; claimed success alone cannot certify completion. Task dependencies must be
existing tasks in that run and form an acyclic graph. Active/completed tasks
require their dependencies to be done. Finishing a stopped run closes its lease,
revokes gateway credentials and preserves the task history. A new task increments
the epoch and starts with unknown capture health until new activity is observed.

## Verification and limits

Automated tests exercise origin/Host/session denial, expiry, offline renewal,
restart, independent device revocation, renewal/revocation races, body bounds, durable
request replay protection, policy races, responsive status during slow actions,
and the synthetic checkpoint-to-handover-to-continuation path. The local Sites
API check uses real D1 plus the scaffold's mock local sign-in, verifies foreign
account read/delete isolation and forged-header rejection, and removes its own
fixture records. This does not establish production authentication behavior.

Production sign-in and disconnected rendering were observed in Chrome. The
read/navigation WebMCP tools registered in the in-app browser, returned disconnected
status, navigated a valid section, and rejected invalid section/extra-field inputs.
Connected owner actions and local network permission still require verification.
Native Cline continuation passed the isolated local test on patched Cline 4.1.17
Windows, with nine passing tests and user-supplied Chrome confirmation of the
succeeded recovery. See the [native report](native-cline-live-20260913.md) and
[local pairing lifecycle checks](dashboard-lifecycle-live-20260914.md). Other
builds and the full hosted flow need separate validation. WebMCP exposes no
privileged owner mutation. Wallet recovery, live Orbio funding,
and cross-machine operation remain separate work. Optional current-user Windows
sign-in startup is available through the [managed companion setup](guided-setup.md).
