# Guided setup and managed companion verification — 14 September 2026

Step 2 is implemented: guided local project enrollment, Cline configuration,
saved companion settings, background launch/status/stop, and optional Windows
sign-in startup. See the [user guide](guided-setup.md).

## Checks

| Check | Result |
| --- | --- |
| Full Python suite | 298 passed, two existing upstream deprecation warnings, 81.28 seconds. |
| Final focused setup/process/startup suite | 24 passed, 17.52 seconds, after final profile revalidation/error-message adjustments. |
| Python lint | Ruff passed for src, tests and scripts. |
| PowerShell wrapper | Parses successfully; actual unattended setup and rerun preserved the enrolled live project and reused its active Cline profile. |
| Wheel | Built successfully; onboarding, desktop, startup, registry and CLI modules match current source byte for byte. |
| Real process lifecycle | Background launch, duplicate-launch detection, stop, restart and renewal of a pre-restart pairing passed. |
| Real Windows startup registration | An isolated current-user Run entry launched its exact pythonw command with no console from another working directory; the entry was removed and the companion stopped. |
| Test cleanup | No temporary pytest startup registrations remain. |
| Existing project | Managed companion ready on port 8766; authenticated snapshot HTTP 200, healthy capture, original recovery succeeded. |

The first full run exhausted C: disk headroom and failed. After space was freed,
the full run passed. The storage threshold was not weakened. No cleanup of the
saved native recovery was performed.

Regression checks cover malformed/duplicate Cline JSON, hook conflicts, edited
owned files, state separation, original-authority discovery, preservation on
reruns, cancelled review, invalid origins/ports/lifetimes, stale PIDs and stop
requests, occupied ports, startup ownership conflicts and interrupted registration.
Real tests caught and fixed a transient status-lock startup race and the Windows
query permission needed to recheck a registry value before removal.

## Existing live project

The existing `.cline-recovery-live-20260913/authentication-task` now uses the saved
managed-launch profile and remains enrolled under
`enrollment_86920b29fc394223a06722da66c172b7`. The active Cline MCP settings file and
owned hook configuration were reused without changing their bytes. The profile
retains origin `http://localhost:3000`, port 8766 and the eight-hour test lifetime.
Windows sign-in startup remains **disabled** for this project; it is an explicit
owner option in the wizard or `startup enable` command.

The original native event watermark remains 69. Hash comparisons confirmed the
enrollment, policy, capture health, lease, adapter control, runs, sessions, tasks,
operations, checkpoints, recoveries and native event digests remained unchanged.
Application, test, README and active MCP settings bytes also match their baseline.
The managed companion does not resume capture or bind a task automatically.

Local evidence:

- [Preservation comparison](../scratch/setup-native-preservation.json)
- [Managed companion result](../scratch/setup-managed-result.json)
- [Focused regression tests](../tests/test_onboarding.py)

The built wheel has SHA-256
`67ce6f9ad7b9ec4935b10a803cca5062530d1fc61a7b59475665376a5fff8e5e`.

## Remaining limits

A complete Windows sign-out/sign-in cycle was not performed. Windows can defer
or disable Run entries independently; the test verifies registration and the
actual command's launch behavior. Startup applies to the companion only, not the
local dashboard development server or Cline. The documented Cline compatibility
patch and real native evidence gate remain required. No hosted deployment or
production authentication change was made.
