# VESSEL dashboard

The dashboard connects directly to an enrolled local companion. Project files,
encryption keys, provider keys and companion credentials are not stored in D1.
D1 holds dashboard accounts, password hashes, sessions, rate limits and
account-scoped connection labels.

## Local setup

Use Node.js 22.13+ and the pinned lockfile. From the repository root:

```powershell
.\scripts\setup-dashboard.ps1
cd dashboard
node scripts/setup-accounts.mjs --email owner@example.com --name "Workspace owner"
npm.cmd run dev
```

Open http://localhost:3000 in Chrome. The setup command prints the path of a
private temporary login file under `.wrangler`. Sign in, choose your own password,
then sign in again. There is no fixed password or public signup. Existing owners
are preserved on setup reruns. See [account setup](../docs/dashboard-accounts.md)
for migration, password recovery and session behavior.

Open **Account settings** to create member accounts, reset their passwords,
disable/enable them or end their dashboard sessions. Owner actions require a
sign-in within the last 15 minutes. No invitation email is sent; the owner gives
the generated temporary password to the intended person.

## Verification

With the local server running:

```powershell
npm.cmd run test:accounts
npm.cmd run test:pairing
npm.cmd run lint
npx.cmd tsc --noEmit
npm.cmd run build
```

The account tests use disposable accounts and real local HTTP/D1 requests. They
test permissions, temporary passwords, revocation, renewal, rate limits, connection
isolation and label bounds, then remove their exact fixtures. They simulate elapsed
time in the local login rate bucket between groups; run them only on localhost.
The old Python login/API scripts forward to this same suite.

An actual process restart was also verified with
`node scripts/verify-accounts.mjs --restart-check` in an interactive terminal.
The tester pauses while the dashboard is restarted and then reuses its original
cookie. See [results](../docs/dashboard-accounts-verification-20260914.md).

## Companion access

Use the guided setup/launcher from [the companion guide](../docs/guided-setup.md).
Pairing credentials persist locally under an account-specific browser namespace;
short access tokens stay in memory and are renewed. Disconnect pauses this tab;
**Forget connection** revokes the browser device. Dashboard account disabling
ends dashboard sessions but does not revoke independently issued companion
credentials. Use the companion's device revocation controls for that.

The owner explicitly migrated from the former local demo keeps its saved labels
and browser pairing. Different dashboard accounts cannot automatically reuse them.
One OS/browser profile is not a security boundary between untrusted people.

## Release status

This account implementation is built and tested locally. The hosted Site has not
been redeployed and still uses its existing ChatGPT access gate. A production
release needs distinct secrets, the exact HTTPS origin, schema migrations,
trusted owner provisioning, access-policy review and deployment verification.
The dependency audit also reports existing framework/tooling advisories, including
high-severity findings; these must be resolved before production release.

Native Cline recovery has passed the isolated live canary. Funding and broader
production validation remain separate. Chrome was not connected to automation
during the new account UI check; manual browser verification is still required.
