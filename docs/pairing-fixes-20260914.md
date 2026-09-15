# Pairing review fixes — 14 September 2026

The seven reviewed issues are fixed locally. The bridge was restarted on port
8766 with the existing native-test state. The original native recovery remains
`succeeded`, its event watermark remains 69, and the disposable app/test bytes
still match its verified final checkpoint.

## Implemented behavior

- A temporary private link pairs each browser with its own durable credential.
  Short-lived access tokens stay in memory; the paired credential stays in that
  browser's local storage. Only digests and metadata are stored by the companion.
- Reconnection uses POST `/v1/renew` before reading status. A pairing survives
  offline time and bridge restart when state, port and approved origin are retained.
- Each snapshot reports the requesting access session's expiry and renewal time.
- Startup connection failures retry with bounded backoff; cancellation prevents
  a late reply from restoring an abandoned connection. Owner actions are never retried.
- Forget uses DELETE `/v1/devices/current` and waits for acknowledgement before
  removing the credential. A network failure retains the pairing for retry.
- Renewal, session issuance and owner revocation use serialized database write
  transactions. Revocation blocks existing sessions as well as future renewal;
  owner actions recheck device authorization inside each write transaction.
- Device listing includes usable IDs and labels, including old prototype rows.
  Revocation preserves a tombstone and reports unknown IDs instead of false success.
- Request receipts are scoped to the device and survive access-token renewal.

## Verification

| Check | Result |
| --- | --- |
| Full Python suite | 274 passed; two existing upstream deprecation warnings. |
| Browser transport/pairing tests | 7 passed via `npm run test:pairing`. |
| TypeScript | `tsc --noEmit` passed. |
| Python and frontend lint | Ruff and oxlint passed. |
| Dashboard production build | Passed. |
| Restarted local bridge | Snapshot and device-list endpoints returned HTTP 200. |
| Existing native test evidence | Recovery succeeded; original checkpoint, app and tests preserved. |

Regression coverage includes a week offline followed by restart, independent
browser revocation, renewal concurrent with CLI revocation, revocation between
middleware and an owner write, receipt lookup after token rotation, rejected
origin changes, correct POST/DELETE transport, failed-revocation credential
retention, reconnect backoff and late-response cancellation.

## Upgrade and remaining limits

Restart the bridge, then pair once using its newly printed private link. Earlier
temporary `vessel_token_...` entries are not durable pairings. Subsequent reloads
renew access without copying another link. This does not change the separate
dashboard login session, start a companion automatically at Windows login, or
publish the dashboard. Browser storage removal or device revocation requires
pairing again. The user subsequently confirmed the updated connection works.
The [live lifecycle drill](dashboard-lifecycle-live-20260914.md) also passed real
process-restart, retry and revocation checks using the client helpers. The user
then reported reconnection and supplied a Chrome Overview screenshot showing
Companion connected and Capture healthy. A subsequent Chrome Recovery screenshot
confirmed the succeeded badge for the tested destination and source checkpoint.
Broader browser interaction and production validation remain separate.

See [connection and device commands](dashboard.md) and the
[local test procedure](local-testing.md).
