# Dashboard accounts verification — 14 September 2026

Implemented invite-only local accounts using Better Auth 1.7.4 and the Drizzle
D1 adapter. Removed hardcoded demo authentication. The existing Site and its
hosted access policy were left unchanged.

## Evidence

The real local HTTP/D1 suite passed 13 groups, including the optional restart:
anonymous/forged-identity rejection; no signup/raw admin endpoints; login and
cookie flags; existing session after an actual dashboard process restart;
origin/body bounds; owner account creation; mandatory temporary-password change;
password-change revocation; connection read/delete isolation; private-field
rejection and 20-label bound; expiry/cookie renewal; disable/enable/reset/end
sessions; recent-owner login requirements; expired session/logout rejection;
concurrent login rate limiting.

The suite creates disposable accounts, simulates elapsed login-rate windows
between groups, checks the actual limit separately, and deletes its exact
fixtures. All four pre-existing connection labels were preserved.

Nine browser pairing tests pass, including account namespaces and explicit
legacy-owner migration. Native companion capture/recovery artifacts were not
used as synthetic auth evidence and are outside these tests.

The final run also verifies browser-style sign-out without a Content-Type header.
Twelve standard groups pass; the separate actual process restart makes thirteen.
The prepared owner login was verified without changing its temporary password.
Its required password-change gate works, and no disposable test accounts remain.
The signing secret is absent from built JavaScript.

The native preservation check still matches the earlier protected ledger, project
file hashes and MCP configuration: event watermark 69, succeeded recovery, healthy
capture. No native Cline task was resumed by the account work.

TypeScript, application lint and the production build pass. The Sites build
wrapper could not locate its npm helper on Windows; the project's own
`npm.cmd run build` completed successfully.

The local owner uses `admin@vessel.local` with a randomly generated temporary
password, requires a password change, and inherits `local_seedy` only through
the explicit local migration option. There is no remotely accessible owner
bootstrap endpoint.

## Boundaries

Chrome automation was unavailable: only the in-app browser was connected, and
the user's Chrome preference was preserved. HTTP/rendering checks passed, but
the new Account settings page still needs the user's visual/interaction check.

The dependency audit reports 14 existing framework/tooling findings (8 high,
6 moderate), involving the React server/Vinext framework stack and development
tooling. The added Better Auth packages are not listed by that audit. Resolve
the outstanding advisories and rerun the release checks before production.
No automatic breaking dependency upgrades or hosted deployment were performed.

A full Windows sign-out/sign-in startup test remains outstanding from step 2;
its registry registration and exact startup launch command were verified earlier.
