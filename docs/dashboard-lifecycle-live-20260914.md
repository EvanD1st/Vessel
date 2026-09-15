# Local companion lifecycle checks — 14 September 2026

The running companion passed nine checks using real loopback HTTP requests and
the dashboard's actual TypeScript transport/pairing helpers. Its process was
stopped and restarted with the same state, origin and port. This was not an
automated Chrome UI test: both browser and desktop automation failed to initialize
with `failed to write kernel assets: The system cannot find the path specified`.

## Results

| Check | Observed result |
| --- | --- |
| CLI device revocation | Existing access and renewal rejected with HTTP 401. |
| Independent pairing | Another paired client retained access. |
| Forget while offline | Request failed and the client retained its pairing for retry. |
| Actual process restart | The saved pairing reconnected with a new access token after five failed offline attempts. |
| Temporary link rotation | The previous bridge's bootstrap token was rejected after restart. |
| Durable revocation | Revoked access and renewal remained rejected after restart. |
| Existing devices | Existing user device records retained their revocation state. |
| Native recovery evidence | Recovery, checkpoints, tasks, operations, lease and capture data were unchanged; app/test/README hashes matched. |
| Acknowledged Forget | Successful DELETE cleared the test client's pairing; subsequent access and renewal were rejected. |

The test ran from 08:08:17 to 08:09:26 UTC. Both temporary test devices were
revoked during cleanup; the user's pairing was not revoked. No native events or
owner workflow actions were injected. The event watermark remained 69, capture
remained healthy, and recovery
`recovery_f200a2f427c16a086e03ee6d80cd14ed` remained `succeeded`.

The companion was left running on port 8766 with the original eight-hour access
session lifetime. The local dashboard remains at `http://localhost:3000`.

## Browser observation

The user confirmed the updated connection flow works before this drill. After
the restart drill, the user reported "disconnected and connected back" and supplied
a Chrome screenshot of `localhost:3000`. The Overview shows Companion connected,
one connected companion, 12 saved checkpoints and Capture healthy for the Cline
recovery test. This confirms reconnection and the rendered connected state; the
report does not specify whether reconnection required any manual action.

The user then supplied a Chrome Recovery-page screenshot showing destination
`1789323748156_tfvfa`, the source checkpoint suffix `71360a`, and the `succeeded`
badge while the companion remained connected. These match the tested recovery's
destination and checkpoint. The final visual acceptance check is complete.
The stale general note below the recovery list claiming native continuation was
unverified was corrected to explain what a succeeded status means.

The client drill uses an in-memory storage shim and supplies Origin for Node's real fetch;
that automated portion does not establish browser storage, CORS enforcement or
local-network permission behavior.

## Evidence

- [Sanitized result](../scratch/dashboard-lifecycle-20260914/result.json)
- [Live drill script](../scratch/dashboard-lifecycle-20260914/live-check.mjs)
- [Pairing implementation and regression results](pairing-fixes-20260914.md)

Credentials were used only in process memory after reading the existing private
bridge log. The evidence files contain device identifiers and results, never raw
pairing credentials or access tokens. The drill script is opt-in and creates
temporary pairings; it expects a separately managed companion restart and must
not be run as an unattended unit test.
