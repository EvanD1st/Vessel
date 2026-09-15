# Background capture and retention

The owner starts `vessel companion --run RUN_ID --epoch EPOCH` for one selected
run. A separate heartbeat thread renews the lease every 5 seconds while the
artifact worker checks for due work once per second. Neither thread selects a
replacement run. Transfer ends the companion; start a new instance for the
explicitly reviewed destination. There is no Windows login service or editor
process fencing. Multiple companion instances serialize artifact work with the
same OS file lock.

## Durable capture requests

The normalized ledger events `afterFileEdit`, `afterAgentResponse`, `preCompact`, `stop` and `sessionEnd`
enqueue small metadata in the same transaction as the event acknowledgment.
The event body stays in the encrypted event ledger; no bulk artifact scan occurs
on this path. Duplicate delivery IDs do not add pending work. Signals coalesce
until five seconds after the first request. A busy worker or retry can delay the
actual capture beyond that interval.

Cline lifecycle hooks map to normalized stop/session-end events. Separately,
the companion compares a bounded eligible-file inventory every five seconds,
including root files, renames and deletions. Changes enqueue a file-capture signal;
they do not fabricate native tool receipts. Secrets, editor configuration and
generated directories are excluded. Incomplete scans record a capture gap.

At most 1,000 pending signals or 64 MiB of their payloads are represented in a
request. Overflow preserves existing pending work and records a capture gap.
Ledger processing itself is synchronous; all committed observations remain
available even if an automatic capture request overflows.

The worker persists a claim before scanning. Its stable operation ID determines
one checkpoint ID. A restart after checkpoint commit but before acknowledgment
reuses that checkpoint. Signals arriving during the scan remain pending for the
next capture and make the first snapshot unsuitable for continuation. Heartbeat
renewals alone do not invalidate a scan; ownership, policy or writer-state changes
do. Historical run requests are canceled without changing their event evidence.

An active-writer snapshot is explicitly inspection-only. An automatic snapshot
can become a continuation candidate when the owner has already stopped and
attested the writer and the capture checks pass. Cline stop/session-end events
alone never certify shutdown. All recovery preflight and review steps still apply.

## Failures and repair

Capture, claim and acknowledgment failures retry after 10 and 20 seconds, then
block on the third failure. A bounded control record uses reserved diagnostic
headroom, so exhausting the logical quota does not reset the retry counter.
If the filesystem cannot write diagnostics at all, the process fails rather than
acknowledging successful capture. Errors retain their type, without raw payloads.

Inspect `status`, repair storage or integration problems, reconcile missing
effects, and run `retry-capture --run RUN_ID`. Retry does not clear capture gaps.
Owner-reviewed `repair-capture` followed by a fresh checkpoint is needed for a
new healthy continuation candidate. Old immutable checkpoints preserve their gaps.

## Retention and collection

The companion applies ordinary retention every five minutes. Owner `cleanup`
defaults to a preview; `cleanup --apply` commits it. Defaults retain both every
checkpoint created in the last seven days and at least the newest fifty.
`--quota-pressure` may remove ordinary retained checkpoints, with that choice
recorded in status. It is an explicit owner operation in this release.

Additional pins retain:

- The latest checkpoint that passes capture and artifact verification, or the
  newest inspection snapshot if no known-good checkpoint exists.
- The latest acknowledged automatic capture and any committed capture awaiting
  worker acknowledgment after a crash.
- Owner pins, recovery sources and run lineage references.
- Checkpoints for runs with unresolved operations. Their events are also retained.

Recovery and lineage references are conservatively retained even after a
handover succeeds. Audit metadata is not pruned. These pins can prevent further
growth under the 1 GiB quota; cleanup reports degradation instead of deleting the
only good source. Removing an owner pin never removes an automatic safety pin.

Collection holds the artifact lock, deletes checkpoint references transactionally,
then removes only unreferenced managed blob/staging files older than one hour.
It validates absolute deletion targets inside the blob directory and rejects
unexpected files or links. A crash after reference deletion leaves recoverable
orphans. Shared blobs stay while any retained checkpoint references them.
Backup and restoration hold the same lock through their file reads; an in-progress
backup therefore pins its complete source snapshot until publication finishes.

Collection reconciles reserved blob bytes and checkpoints the SQLite WAL. It
does not vacuum a live database or remove the event ledger. Physical database
allocation, pinned data or the grace period can still prevent quota recovery.
Restored inspection-only history cannot run a worker or pruning operation.

## Evidence and timing

`status` shows queue and retry state, cleanup counts, last committed checkpoint
age and last verified local backup age. These timestamps describe recorded
verification, not current external disk availability or continuous native capture.

`scripts/benchmark_capture.py` runs 30 synthetic 32 KiB events through the installed
command hook and actual OS shell, then captures one coalesced checkpoint. It
measures process startup, validation, encryption, commit and exit. It records
whether p95 meets the 250 ms target; it does not verify Cline's scheduling or
failure handling, identify the storage medium, or make a performance guarantee.
