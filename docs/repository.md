# Repository setup

This repository contains the Python companion/owner CLI in `src/vessel`, its
tests and setup scripts, and the browser dashboard in `dashboard`.

Clone it, then follow the root README for Python setup and
`dashboard/README.md` for dashboard setup. Dashboard accounts are invite-only;
the local setup generates a random signing secret and temporary owner password.
There are no working passwords or API keys in the repository.

Keep `.dev.vars`, `.env`, local databases, companion keys, browser pairing
credentials, backups and private native canary state outside commits. These
files and generated dependencies/build output are ignored. The dashboard's
`.env.example` contains names and empty placeholders only. Its existing
`.openai/hosting.json` is non-secret build configuration, not deployment
authorization; pushing code does not publish the hosted dashboard.

The GitHub workflow runs the Python tests/lint and dashboard pairing tests,
lint, type checks and build. Account integration tests need a running local
dashboard and disposable database; run them following `dashboard/README.md`.
Real inference and native Cline tests remain owner-operated and use separately
configured provider credentials.

Verification documents reference local diagnostic reports and canary paths.
Those private reports are intentionally excluded from the repository; their
links are available only in the original test workspace. The documented native
gateway tool retry and model-switch verification are still pending.

This is a developer preview. Existing dependency advisories and broader
production validation remain recorded in the verification documents.
