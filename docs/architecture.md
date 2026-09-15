# Local developer preview decisions

These decisions describe implemented behavior. The current [README](../README.md)
defines the Cline preview and its remaining milestones. Superseded design documents
are preserved in `.migration-archive`. Hosted ownership/funding is not complete.

## Authority and execution

One state directory enrolls one canonical local workspace. A per-OS-user registry,
outside the project, rejects a second independent enrollment for that workspace.
It defaults to `%LOCALAPPDATA%\VESSEL\registry` on Windows. Operators may configure
`VESSEL_REGISTRY_DIR`; tests isolate it. Parallel production authorities with
different registry settings and shared cross-machine workspaces are unsupported.

SQLite `BEGIN IMMEDIATE` transactions serialize lease ownership and compare the
expected epoch/policy revision. The lease expires after 30 seconds. An owner-run
heartbeat command renews it every five seconds. Expiration blocks managed work;
it never authorizes automatic takeover. An owner must stop the native task and
record shutdown evidence. Hooks observe Cline and do not enforce an OS sandbox.

Recovery selection is immutable and owner scoped. Review tokens bind the selected
checkpoint, destination, preflight, current policy and expected epoch. A durable
outbox keeps admissions paused across interrupted local credential revocation.
Startup retries pending entries only if current policy still permits it.
Policy changes require owner review through `repair-handover`. New native
activity after an attested stop invalidates that evidence; late source activity
after takeover degrades capture.

The local CLI is the owner authority. MCP provides explicit reads and unattributed
proposals. It cannot approve its own mission, bind a run or verify completion.
This separation does not contain a malicious process with the same OS privileges
that invokes the CLI itself. Policy and keys stay outside the enrolled project;
wallet ownership is not implemented.

## Checkpoint durability and limits

Private payloads use maintained `cryptography` Fernet authenticated encryption.
Envelopes bind ciphertext to record/blob identity. SQLite uses WAL and FULL
synchronous writes. Events are acknowledged only after commit; receive sequence
does not establish native execution order. Native tool receipts are reconciled
by operation ID. Missing/conflicting evidence remains uncertain. Shell exit
codes are checked before an observation can support completion.

A checkpoint freezes paused source state and a watermark, captures bounded files
without an open DB write transaction, publishes flushed immutable blobs, then
commits state and references in one transaction. Capture checks file identity,
opened-handle scope, hashes and before/after manifests, retrying once for
instability. Incomplete capture cannot qualify for continuation. Process-exit
tests cover abandoned staged writes. Power-loss behavior on the user's filesystem
is not certified; Windows lacks the POSIX directory-fsync operation used elsewhere.

Capture limits are 1,000 files, 2 MiB/file, 50 MiB total and 20,000 scanned entries.
Credentials, environment files, dependency/generated trees, databases and config
backups are excluded. Required excluded files block continuation. Secret patterns
cannot identify every credential; keep secrets out of project source/hook text.

Hook observations are durably recorded synchronously, including a bounded
automatic capture request. A separate worker coalesces requests for 5 seconds.
Running-writer snapshots are inspection-only; manual continuation candidates
require shutdown evidence. The worker fixes its run/epoch at launch and exits
after handover. A process lock serializes capture publication, backup, file
restoration and collection; the operating system releases it after a crash.

Retention keeps the last 7 days and at least 50 checkpoints, subject to explicit
quota-pressure cleanup. Safety pins protect the latest known-good checkpoint,
owner pins, recovery and run lineage references, unresolved-operation evidence,
and pending capture acknowledgments. Metadata deletion commits before orphan
blob removal, with a one-hour grace period. Event and audit history is retained.
Durable blob-space reservations include staging and survive crashes; collection
reconciles the ledger to actual retained bytes. Quota checks use DB/WAL stats and
persisted reservations without scanning artifacts on hook deliveries. If retained
data prevents growth, capture degrades and controlled admissions stop.
See [maintenance and repair](maintenance.md).

## Environment and context

The automatic manifest observes OS, architecture, companion Python, dependency-file
digests, declared Python distribution versions and migration-file digests. Owner
declarations record expected client capabilities, service/secret availability and
database schema. These declarations are not live probes. Required unavailable or
unverified resources and schema/package mismatches block approval and recovery;
optional gaps remain informational. [Environment requirements](environment.md)
documents the bounded format, provenance and manifest-version compatibility gate.
Git inspection and automatic service/client/credential checks remain pending.
`verify-environment` records evidence,
a compatible model identifier and a conservative byte budget after reserving
wrappers, tools and output. The system blocks if essential context exceeds that
budget or observed requirements change. Automatic tokenization and provider
capability discovery are deferred.

File restoration writes only to a separate new/empty destination. Extra current
files are shown for review. Changed or missing captured files require repair or
a new checkpoint; unrelated work is never automatically overwritten.

## Keys and backup

Windows uses current-user DPAPI. POSIX uses a documented 0700 state directory
and 0600 key file. IDs, event types, digests, sizes, database structure and Fernet
timestamps remain visible; payloads and artifact bytes are encrypted.

Backup uses SQLite Online Backup plus verified immutable blobs and an authenticated
manifest. The local backup contains protected key material and targets the same
Windows user/machine. POSIX backups include the local file key and must be
protected like private state. Neither is a portable wallet-owned export. Keep
a separate backup before relying on disk-loss recovery.

Restored state is permanently inspection-only. It cannot resurrect leases,
credentials, permissions or spending authority. Restore files into a separate
project, enroll fresh state and reconnect credentials. A backup cannot reset
spending. Gateway receipts are not a monetary reservation/reconciliation ledger,
so no hard spending cap is advertised.

Schema version 1 is implemented. Future versions, altered ciphertext and unsafe
backup paths are rejected. General migrations and portable key wrapping are later work.

## Gateway and external dependencies

The FastAPI gateway is prepared and tested with a fake HTTPX upstream. It uses
explicit HTTPS routes, epoch/enrollment bearer credentials, current authority,
model allowlists, and bounded streams/bodies/concurrency. There are no paid
retries or model switches. Partial-stream failures are uncertain. Attribution
stays at enrollment level with `run_id=None` until correlation is established.

No public gateway, live Cline inference route, Orbio management authorization
or wallet service has been deployed. The dashboard is implemented as a private
Sites application with a local owner bridge; see [dashboard boundaries](dashboard.md).
`UnsupportedOrbioAdapter` exposes
unavailable operations explicitly. See [gateway details](gateway.md) and
[Cline verification](cline.md).
