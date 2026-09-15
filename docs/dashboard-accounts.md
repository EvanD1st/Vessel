# Invite-only dashboard accounts

Step 3 replaces the local fixed demo password with individual accounts.
Only an owner creates accounts. There is no public registration route, social
login, or emailed invitation/reset workflow.

## Sign in and create member accounts

Create the local owner using the setup commands below. Open
http://localhost:3000 in Chrome and use the chosen owner email with the random
temporary password from the private file produced by setup. Replace that
password (12–128 characters), then sign in again.

Open **Account settings** and use **Invite-only accounts** to create members.
Give each generated temporary password privately to its intended recipient.
Members must choose their own password before accessing the workspace.
No working login credentials are included in this repository.

## Set up another local installation

From the repository root:

```powershell
.\scripts\setup-dashboard.ps1
cd dashboard
node scripts/setup-accounts.mjs --email owner@example.com --name "Owner"
npm.cmd run dev
```

The setup creates a random signing secret in ignored `.dev.vars`, applies each
local migration once, and writes a random temporary password to an ignored file
under `.wrangler`. It does not print the password or send anything to hosting.
Keep the signing secret stable across restarts. Setup reruns preserve it and
existing accounts. Migration hashes are checked before rerunning.

Only when intentionally adopting the former local demo's labels/pairing, add
`--migrate-demo-labels` when creating the first owner. Otherwise the owner receives
a new ID and cannot claim legacy records. Public visitors cannot bootstrap owners.

## Forgotten passwords and account access

The owner can reset a member's password from Account settings. A reset immediately
invalidates their current password and sessions and generates another temporary
password. Disabled members cannot log in until enabled. **End sessions** logs out
a member on all dashboard sessions without changing their password.

For a forgotten local owner password, run from `dashboard`:

```powershell
node scripts/setup-accounts.mjs --email YOUR_EXISTING_OWNER_EMAIL --reset-owner
```

This explicitly resets the existing local owner, revokes its sessions and prints
a new private file path. It is not a hosted reset tool. Protect OS access to the
local database, signing secret and bootstrap files. Remove temporary login files
after choosing your permanent password.

## Session and data behavior

- Better Auth 1.7.4 handles password hashing/checking and session cookies; D1 holds
  durable sessions. Password and account state changes use atomic D1 batches.
- Sessions last seven days, renew after a day of activity, and survive a dashboard
  restart. Cookies are HttpOnly, SameSite=Strict, and Secure on HTTPS.
- Sign-out revokes the current session. Password changes/resets revoke all sessions.
  Owner administration requires a login within the last 15 minutes.
- Every account API checks identity and permissions on the server. Browser tabs
  recheck identity every 30 seconds and on focus/account changes; they pause their
  workspace when validation is unavailable.
- Login rate limits are durable and concurrency-safe. Local development ignores
  client forwarding headers. Hosted deployment must provide a trusted edge IP;
  missing metadata uses a shared bucket rather than disabling limits.
- Connection labels and saved browser pairings are scoped to the account.
  Credentials remain on the local browser/companion, not in hosted D1.
- Disabling dashboard accounts does not revoke an independently issued companion
  device credential or stop Cline/capture. Use **Forget connection** or the
  companion owner's device revocation commands separately.
- Email is an owner-assigned login identifier; no email verification/delivery
  service is configured. Workspace membership does not grant wallet ownership.

## Before production release

The public hosted Site has not changed. Its current access policy still requires
the existing ChatGPT gate. Do not assume publishing this code removes that gate.

Configure a new hosted `VESSEL_AUTH_SECRET` and the exact HTTPS
`VESSEL_AUTH_URL`; do not copy a local secret/password. Apply the append-only
D1 migrations, provision the first owner through a trusted administrative
deployment process, and verify the intended Site audience and edge IP handling.
Keep local bootstrap files and all `.dev.vars` files out of deployment archives.

Address the existing dependency audit findings and validate HTTPS cookies,
recovery/account revocation, browser interaction and hosted session persistence.
This local test establishes account functionality, not production readiness.
