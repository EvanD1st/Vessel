'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  companion,
  short,
  type Session,
  type Snapshot,
  type Receipt,
} from '@/lib/vessel';

type Field = {
  key: string;
  label: string;
  kind?: 'text' | 'textarea' | 'number' | 'select' | 'checkbox';
  options?: string[];
  optional?: boolean;
  hint?: string;
};
export type ActionSpec = {
  id: string;
  name: string;
  title: string;
  description: string;
  button: string;
  fields: Field[];
  payload: Record<string, unknown>;
  snapshot: Snapshot;
};
const note: Field = {
  key: 'note',
  label: 'Your review note',
  kind: 'textarea',
  hint: 'Record what you checked and the evidence you relied on.',
};
const evidence: Field = {
  key: 'evidence',
  label: 'Observed successful operation',
  optional: true,
  hint: 'Select a receipt from this run. A claimed result alone is insufficient.',
};
const session: Field = {
  key: 'session_id',
  label: 'Native Cline task ID',
  hint: 'Use the exact task ID reported by Cline hooks or the sessions command.',
};
const budget: Field = {
  key: 'context_bytes',
  label: 'Verified context budget (bytes)',
  kind: 'number',
  hint: 'Reserve room for the client, tools and model output. Maximum 1,048,576.',
};
const configs: Record<
  string,
  { title: string; description: string; button: string; fields: Field[] }
> = {
  start: {
    title: 'Bind a new conversation',
    description:
      'Bind one fresh Cline conversation to this enrolled project. Start capture after binding.',
    button: 'Bind conversation',
    fields: [session],
  },
  'keep-capturing': {
    title: 'Start background capture',
    description:
      'Keep this exact run and execution epoch alive while the companion is running.',
    button: 'Start capture',
    fields: [],
  },
  'revalidate-policy': {
    title: 'Review the current policy',
    description:
      'Renew the active run using the mission and restrictions shown below.',
    button: 'Approve current policy',
    fields: [],
  },
  stop: {
    title: 'Record writer shutdown',
    description:
      'Stop the source task and its background processes in Cline before recording this attestation. This button does not stop Cline.',
    button: 'Record stopped writer',
    fields: [
      {
        key: 'attested',
        label: 'I stopped the native writer and its background processes.',
        kind: 'checkbox',
      },
      note,
    ],
  },
  task: {
    title: 'Assign or update a task',
    description:
      'Keep work explicit. Completed tasks require observed success, and dependencies must finish before work becomes active.',
    button: 'Save task',
    fields: [
      { key: 'task_id', label: 'Task ID' },
      { key: 'description', label: 'Task description', kind: 'textarea' },
      {
        key: 'status',
        label: 'Task state',
        kind: 'select',
        options: ['pending', 'active', 'blocked', 'done'],
      },
      {
        key: 'dependencies',
        label: 'Dependency task IDs',
        optional: true,
        hint: 'Separate existing task IDs with commas. Leave empty for no dependencies.',
      },
      evidence,
    ],
  },
  'review-proposal': {
    title: 'Review agent proposal',
    description:
      'Agent text is an unverified claim. Accepting a mission keeps existing restrictions. Claimed task completion requires independent observed evidence.',
    button: 'Record decision',
    fields: [note],
  },
  checkpoint: {
    title: 'Capture a checkpoint',
    description:
      'Capture the stopped run and current project files. Verification may still identify blockers that prevent recovery.',
    button: 'Capture checkpoint',
    fields: [],
  },
  'prepare-recovery': {
    title: 'Prepare recovery for review',
    description:
      'Check this selected checkpoint, current project files, environment and policy. This prepares a plan; execution ownership transfers only after a separate review.',
    button: 'Prepare recovery plan',
    fields: [session, budget],
  },
  handover: {
    title: 'Approve execution handover',
    description:
      'Transfer execution from the stopped source to the reviewed destination conversation. Old gateway credentials are revoked; this does not launch Cline or prove continuation.',
    button: 'Transfer execution',
    fields: [],
  },
  confirm: {
    title: 'Confirm observed continuation',
    description:
      'Record independent successful tool evidence from the destination run. Loading context alone does not prove work continued.',
    button: 'Confirm continuation',
    fields: [{ key: 'operation_id', label: 'Destination operation ID' }, note],
  },
  'cancel-recovery': {
    title: 'Cancel pending recovery',
    description:
      'Cancel this recovery before ownership transfers. Once execution has transferred, close the destination run instead.',
    button: 'Cancel this recovery',
    fields: [note],
  },
  'finish-run': {
    title: 'Close this stopped run',
    description:
      'Completion requires all tasks done and an independently observed successful acceptance test. Cancellation preserves unfinished work and evidence.',
    button: 'Close run',
    fields: [
      {
        key: 'outcome',
        label: 'Outcome',
        kind: 'select',
        options: ['completed', 'cancelled'],
      },
      evidence,
      note,
    ],
  },
  'review-environment': {
    title: 'Review the local environment',
    description:
      'Confirm that required services, dependencies, secret references and the chosen model are available on this host.',
    button: 'Record environment review',
    fields: [{ key: 'model', label: 'Verified model name' }, budget, note],
  },
  'repair-capture': {
    title: 'Record capture repair',
    description:
      'First repair the underlying capture problem and reconcile missing work. This records your review; it does not fix the editor or prove missing events never happened.',
    button: 'Record reviewed repair',
    fields: [note],
  },
  'resolve-operation': {
    title: 'Reconcile an uncertain operation',
    description:
      'Inspect the actual result and external side effects before recording your conclusion. Do not automatically replay the tool.',
    button: 'Record reconciliation',
    fields: [note],
  },
};
export function makeAction(
  name: string,
  snapshot: Snapshot,
  payload: Record<string, unknown> = {},
): ActionSpec {
  const config = configs[name];
  if (!config) throw new Error('Unknown owner action');
  const fields = [...config.fields];
  if (
    name === 'review-proposal' &&
    payload.decision === 'accept' &&
    ['task', 'task_update'].includes(String(payload.proposal_kind))
  )
    fields.unshift({ key: 'task_id', label: 'Assign task ID' }, evidence);
  const clean = { ...payload };
  delete clean.proposal_kind;
  return {
    id: crypto.randomUUID(),
    name,
    ...config,
    fields,
    snapshot,
    payload: { run_id: snapshot.lease?.holder_run_id, ...clean },
  };
}

export default function OwnerAction({
  spec,
  session,
  onClose,
  onResult,
}: {
  spec: ActionSpec;
  session: Session;
  onClose: () => void;
  onResult: (message: string) => void;
}) {
  const [values, setValues] = useState<Record<string, unknown>>(() =>
    Object.fromEntries(
      spec.fields.map((field) => [
        field.key,
        spec.payload[field.key] ??
          (field.kind === 'checkbox'
            ? false
            : field.kind === 'select'
              ? (field.options?.[0] ?? '')
              : field.kind === 'number'
                ? 24000
                : ''),
      ]),
    ),
  );
  const [reviewed, setReviewed] = useState(false),
    [busy, setBusy] = useState(false),
    [attempted, setAttempted] = useState(false);
  const [receipt, setReceipt] = useState<Receipt | null>(null),
    [error, setError] = useState(''),
    [unknown, setUnknown] = useState(false);
  const snapshot = spec.snapshot;
  const selectedRecovery = snapshot.recoveries.find(
    (r) => r.id === spec.payload.recovery_id,
  );
  async function submit(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reviewed || busy || attempted) return;
    const payload = { ...spec.payload, ...values };
    for (const field of spec.fields) {
      if (field.kind === 'number')
        payload[field.key] = Number(values[field.key]);
      if (field.optional && !values[field.key]) delete payload[field.key];
    }
    if (spec.name === 'task')
      payload.dependencies = fieldText(values.dependencies)
        .split(',')
        .map((v) => v.trim())
        .filter(Boolean);
    if (spec.name === 'prepare-recovery') payload.idempotency_key = spec.id;
    setBusy(true);
    setAttempted(true);
    setError('');
    try {
      const result = await companion<Receipt>(session, '/v1/actions', {
        request_id: spec.id,
        action: spec.name,
        payload,
        policy_revision: snapshot.policy.revision,
        execution_epoch: snapshot.lease?.execution_epoch ?? null,
      });
      receive(result);
    } catch (error) {
      setUnknown(true);
      setError(
        `${error instanceof Error ? error.message : 'Connection interrupted'}. The outcome is unknown. Check the receipt before taking another action.`,
      );
    } finally {
      setBusy(false);
    }
  }
  function receive(result: Receipt) {
    setError('');
    setReceipt(result);
    setUnknown(result.status === 'started');
    if (result.status === 'succeeded')
      onResult(
        result.warning ?? `${spec.title}: saved by your local companion.`,
      );
    else if (result.status === 'started')
      setError(
        'This request was recorded, but its final outcome is unknown. Inspect current state; do not repeat it blindly.',
      );
    else {
      setError(
        result.error ??
          'The companion blocked this action. Close this review, refresh, and inspect the current state.',
      );
      onResult('The action was blocked. Current state has been refreshed.');
    }
  }
  async function checkReceipt() {
    setBusy(true);
    try {
      receive(await companion<Receipt>(session, `/v1/requests/${spec.id}`));
    } catch (error) {
      setError(
        error instanceof Error ? error.message : 'Could not read the receipt.',
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent className="owner-dialog">
        <DialogHeader>
          <DialogTitle>{spec.title}</DialogTitle>
          <DialogDescription>{spec.description}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="owner-form">
          <div className="review-context">
            <strong>{snapshot.policy.mission}</strong>
            <p>
              Policy {snapshot.policy.revision} · Execution{' '}
              {snapshot.lease?.execution_epoch ?? 'not started'}
            </p>
            <ul>
              {snapshot.policy.restrictions.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
            {spec.payload.checkpoint_id ? (
              <p>
                Selected checkpoint:{' '}
                <code>{fieldText(spec.payload.checkpoint_id)}</code>
              </p>
            ) : null}
            {selectedRecovery && (
              <div>
                <p>
                  Source: {short(selectedRecovery.checkpoint_id)} · Destination:{' '}
                  <code>{selectedRecovery.destination_session}</code>
                </p>
                <p>
                  Prepared policy {selectedRecovery.preflight.policy_revision} ·
                  Source execution {selectedRecovery.preflight.expected_epoch} ·
                  Context{' '}
                  {selectedRecovery.preflight.context_bytes.toLocaleString()} /{' '}
                  {selectedRecovery.preflight.context_budget.toLocaleString()}{' '}
                  bytes
                </p>
                <p>
                  {selectedRecovery.preflight.blockers.length
                    ? `Blocked: ${selectedRecovery.preflight.blockers.join(', ')}`
                    : 'Preflight reported no blockers. Review the context before transferring.'}
                </p>
                <details>
                  <summary>
                    Inspect recovery context and project differences
                  </summary>
                  <pre>
                    {JSON.stringify(
                      {
                        context: selectedRecovery.preflight.context,
                        workspace_differences:
                          selectedRecovery.preflight.workspace_differences,
                      },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </div>
            )}
            {spec.name === 'review-proposal' && (
              <div className="proposal-text">
                <p>
                  Decision: <strong>{String(spec.payload.decision)}</strong>
                </p>
                <pre>
                  {JSON.stringify(
                    snapshot.proposals.find(
                      (p) => p.id === spec.payload.proposal_id,
                    )?.payload,
                    null,
                    2,
                  )}
                </pre>
              </div>
            )}
          </div>
          {spec.fields.map((field) => (
            <div className="form-field" key={field.key}>
              {field.kind === 'checkbox' ? (
                <label className="check-label" htmlFor={`action-${field.key}`}>
                  <Checkbox
                    id={`action-${field.key}`}
                    checked={values[field.key] === true}
                    onCheckedChange={(checked) =>
                      setValues({ ...values, [field.key]: checked })
                    }
                    disabled={attempted}
                    required
                  />
                  {field.label}
                </label>
              ) : (
                <>
                  <label htmlFor={`action-${field.key}`}>
                    {field.label}
                    {field.optional ? ' (optional)' : ''}
                  </label>
                  {field.key === 'evidence' || field.key === 'operation_id' ? (
                    <NativeSelect
                      id={`action-${field.key}`}
                      value={fieldText(values[field.key])}
                      onChange={(event) =>
                        setValues({
                          ...values,
                          [field.key]: event.target.value,
                        })
                      }
                      disabled={attempted}
                      required={!field.optional}
                    >
                      <NativeSelectOption value="">
                        Select an observed operation
                      </NativeSelectOption>
                      {snapshot.operations
                        .filter(
                          (op) =>
                            op.run_id ===
                              (selectedRecovery?.destination_run_id ??
                                spec.payload.run_id) &&
                            !op.uncertain &&
                            op.intent &&
                            op.result,
                        )
                        .map((op) => (
                          <NativeSelectOption key={op.id} value={op.id}>
                            {op.native_id} · {short(op.id)}
                          </NativeSelectOption>
                        ))}
                    </NativeSelect>
                  ) : field.kind === 'select' ? (
                    <NativeSelect
                      id={`action-${field.key}`}
                      value={String(values[field.key])}
                      onChange={(event) =>
                        setValues({
                          ...values,
                          [field.key]: event.target.value,
                        })
                      }
                      disabled={attempted}
                    >
                      {field.options?.map((option) => (
                        <NativeSelectOption key={option} value={option}>
                          {option}
                        </NativeSelectOption>
                      ))}
                    </NativeSelect>
                  ) : field.kind === 'textarea' ? (
                    <Textarea
                      id={`action-${field.key}`}
                      value={String(values[field.key])}
                      onChange={(event) =>
                        setValues({
                          ...values,
                          [field.key]: event.target.value,
                        })
                      }
                      required={!field.optional}
                      disabled={attempted}
                      maxLength={8192}
                      rows={3}
                    />
                  ) : (
                    <Input
                      id={`action-${field.key}`}
                      type={field.kind === 'number' ? 'number' : 'text'}
                      min={field.kind === 'number' ? 1024 : undefined}
                      max={field.kind === 'number' ? 1048576 : undefined}
                      value={String(values[field.key])}
                      onChange={(event) =>
                        setValues({
                          ...values,
                          [field.key]: event.target.value,
                        })
                      }
                      disabled={attempted}
                      required={!field.optional}
                      maxLength={field.key === 'task_id' ? 128 : 512}
                    />
                  )}
                </>
              )}
              {field.hint && <small>{field.hint}</small>}
            </div>
          ))}
          {!attempted && (
            <label
              className="check-label review-check"
              htmlFor="owner-action-review"
            >
              <Checkbox
                id="owner-action-review"
                checked={reviewed}
                onCheckedChange={setReviewed}
                required
              />
              I reviewed the selected action, current mission and restrictions.
            </label>
          )}
          {error && (
            <div role="alert" className="notice error">
              {error}
            </div>
          )}
          {receipt?.status === 'succeeded' && (
            <output className="notice success">
              {receipt.warning ??
                'Saved. The workspace now reflects the companion’s current state.'}
            </output>
          )}
          <div className="dialog-actions">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={onClose}
            >
              {attempted ? 'Close review' : 'Cancel'}
            </Button>
            {unknown && (
              <Button type="button" disabled={busy} onClick={checkReceipt}>
                Check request receipt
              </Button>
            )}
            {!attempted && (
              <Button type="submit" disabled={!reviewed || busy}>
                {spec.button}
              </Button>
            )}
            {busy && <output>Waiting for companion…</output>}
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function fieldText(value: unknown): string {
  return typeof value === 'string' || typeof value === 'number'
    ? String(value)
    : '';
}
