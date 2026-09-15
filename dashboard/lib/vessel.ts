export type Connection = {
  enrollmentId: string;
  label: string;
  port: number;
  updatedAt: number;
};
export type Run = {
  id: string;
  native_session_id: string;
  execution_epoch: number;
  status: string;
};
export type Task = {
  id: string;
  run_id: string;
  description: string;
  status: string;
  evidence?: string;
  dependencies: string[];
  verification_status: string;
};
export type Proposal = {
  id: string;
  kind: string;
  payload: {
    mission?: string;
    description?: string;
    constraints?: string[];
    claimed_status?: string;
  };
  decision?: string;
  provenance: string;
  owner_review?: string;
};
export type Operation = {
  id: string;
  run_id: string;
  native_id: string;
  uncertain: boolean;
  intent: unknown;
  result: unknown;
  resolution?: unknown;
};
export type Checkpoint = {
  id: string;
  run_id: string;
  created_at: number;
  capture: { blockers: string[]; health: { state: string } };
  capture_seconds: number;
};
export type Recovery = {
  id: string;
  checkpoint_id: string;
  destination_session: string;
  status: string;
  review_token: string;
  destination_run_id?: string;
  preflight: {
    blockers: string[];
    context_bytes: number;
    context_budget: number;
    policy_revision: number;
    expected_epoch: number;
    workspace_differences: unknown;
    context: {
      mission: string;
      constraints: string[];
      tasks: Task[];
      instructions: string;
    };
  };
};
export type Snapshot = {
  version: string;
  enrollment: { id: string; workspace: string; agent_id: string };
  lease: null | {
    holder_run_id: string;
    execution_epoch: number;
    status: string;
    policy_revision: number;
    expires_at: number;
  };
  lease_stale: boolean;
  policy: {
    revision: number;
    mission: string;
    restrictions: string[];
    allowed_models: string[];
    recovery_allowed: boolean;
    authority: string;
  };
  capture: { state: string; gaps: string[]; last_observation: number | null };
  runs: Run[];
  sessions: { id: string; active: boolean; run_id?: string }[];
  tasks: Task[];
  proposals: Proposal[];
  operations: Operation[];
  checkpoints: Checkpoint[];
  recoveries: Recovery[];
  recovery_window: {
    last_checkpoint_at: number | null;
    last_verified_backup: null | { created_at: number };
    notice: string;
  };
  automatic_capture: { pending: unknown[]; failure: unknown };
  bridge: {
    expires_at: number;
    device_id?: string;
    renew_after: number;
    capture_worker_running: boolean;
    worker_error: string | null;
  };
};
export type Session = { port: number; token: string };
export class CompanionError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
  }
}
export type Receipt = {
  id?: string;
  status?: 'started' | 'succeeded' | 'blocked';
  error?: string;
  warning?: string;
  result?: unknown;
};
export function connectionLink(value: string): Session {
  let raw = value.trim();
  if (raw.includes('://')) {
    const url = new URL(raw);
    raw = url.hash.slice(1);
  }
  const match = /^connect=(\d{4,5}):([A-Za-z0-9_-]{32,128})$/.exec(
    raw.replace(/^#/, ''),
  );
  if (!match || Number(match[1]) < 1024 || Number(match[1]) > 65535)
    throw new Error(
      'Paste the complete connection link printed by the companion.',
    );
  return { port: Number(match[1]), token: match[2] };
}
export async function companion<T>(
  session: Session,
  path: string,
  body?: unknown,
  method: 'GET' | 'POST' | 'DELETE' = body === undefined ? 'GET' : 'POST',
): Promise<T> {
  const options: RequestInit & { targetAddressSpace: string } = {
    method,
    mode: 'cors',
    credentials: 'omit',
    cache: 'no-store',
    referrerPolicy: 'no-referrer',
    redirect: 'error',
    headers: {
      Authorization: `Bearer ${session.token}`,
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    signal: AbortSignal.timeout(method === 'GET' ? 15000 : 120000),
    targetAddressSpace: 'loopback',
  };
  const response = await fetch(
    `http://127.0.0.1:${session.port}${path}`,
    options,
  );
  const data = await response.json();
  if (!response.ok && !(data && typeof data === 'object' && 'status' in data))
    throw new CompanionError(
      data &&
        typeof data === 'object' &&
        'error' in data &&
        typeof data.error === 'string'
        ? data.error
        : `Companion returned ${response.status}`,
      response.status,
    );
  return data as T;
}
export const when = (time: number | null | undefined) =>
  time ? new Date(time * 1000).toLocaleString() : 'Not reported';
export const short = (value: string | undefined) =>
  value
    ? value.length > 22
      ? `${value.slice(0, 12)}…${value.slice(-6)}`
      : value
    : '—';
