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

export type OrbioStatus = {
  connected: boolean;
  masked_key: string | null;
  credential_version: string | null;
  status: 'active' | 'paused' | 'not_configured' | 'invalid';
  probe_status: string;
  verified_at: number | null;
  gateway: {
    status: string;
    port: number;
    base_url: string;
    models: string[];
    running: boolean;
    active_model?: string;
    smart_routing?: boolean;
  };
  balance: {
    available: boolean;
    amount: number | null;
    currency: string;
    reason?: string;
  };
  usage: {
    available: boolean;
    amount: number | null;
    currency: string;
    reason?: string;
  };
  mcp: {
    configured: boolean;
    capabilities: string[];
  };
  last_error: string | null;
};

export type OrbioModel = {
  id: string;
  name: string;
  context_length: number;
  pricing: { prompt: string; completion: string; [key: string]: unknown };
  recommended?: boolean;
  description?: string;
};

export async function getOrbioStatus(session: Session): Promise<OrbioStatus> {
  return companion<OrbioStatus>(session, '/v1/orbio/status');
}

export async function connectOrbioKey(
  session: Session,
  key: string,
): Promise<{
  status: string;
  credential_version: string;
  masked_key: string;
  verified_at: number;
}> {
  return companion(session, '/v1/orbio/credentials', { key }, 'POST');
}

export async function replaceOrbioKey(
  session: Session,
  key: string,
): Promise<{
  status: string;
  credential_version: string;
  masked_key: string;
  verified_at: number;
}> {
  return companion(session, '/v1/orbio/replace', { key }, 'POST');
}

export async function forgetOrbioKey(session: Session): Promise<{
  status: string;
  paused: boolean;
  recovery_history_preserved: boolean;
}> {
  return companion(session, '/v1/orbio/credentials', undefined, 'DELETE');
}

export async function refreshOrbioStatus(
  session: Session,
): Promise<OrbioStatus> {
  return companion<OrbioStatus>(session, '/v1/orbio/refresh', {}, 'POST');
}

export async function claimOrbioKey(
  session: Session,
  name?: string,
): Promise<{
  status: string;
  credential_version?: string;
  masked_key?: string;
  verified_at?: number;
  message?: string;
  url?: string;
}> {
  return companion(session, '/v1/orbio/claim', { name }, 'POST');
}

export async function getOrbioModels(session: Session): Promise<{
  models: OrbioModel[];
  active_model: string;
  gateway_models: string[];
  smart_routing: boolean;
}> {
  return companion(session, '/v1/orbio/models');
}

export async function updateOrbioRouting(
  session: Session,
  params: {
    activeModel: string;
    smartRouting?: boolean;
    fallbackModels?: string[];
  },
): Promise<{
  status: string;
  active_model: string;
  gateway_models: string[];
  smart_routing: boolean;
}> {
  return companion(
    session,
    '/v1/orbio/routing',
    {
      active_model: params.activeModel,
      smart_routing: params.smartRouting ?? false,
      fallback_models: params.fallbackModels,
    },
    'POST',
  );
}

export type OrbioUsageAnalytics = {
  has_key: boolean;
  usage: {
    available: boolean;
    usage?: number;
    total_credits?: number;
    remaining_credits?: number;
    percent_used?: number;
    rate_limits?: {
      requests_per_minute?: number;
      tokens_per_minute?: number;
    };
    limit?: number | null;
    label?: string | null;
    reason?: string;
  };
  wallet: OrbioWalletInfo;
};

export type OrbioWalletInfo = {
  wallet_address: string | null;
  holdings: number;
  tier: number;
  tier_name: string;
  tier_perks: {
    multiplier: number;
    routing_priority: string;
    description: string;
  };
};

export async function getOrbioUsage(
  session: Session,
): Promise<OrbioUsageAnalytics> {
  return companion<OrbioUsageAnalytics>(session, '/v1/orbio/usage');
}

export async function linkOrbioWallet(
  session: Session,
  walletAddress?: string,
  action: 'connect' | 'disconnect' = 'connect',
): Promise<{
  status: string;
  wallet: OrbioWalletInfo;
}> {
  return companion(
    session,
    '/v1/orbio/wallet',
    { wallet_address: walletAddress, action },
    'POST',
  );
}


export type OperatorIdentityCard = {
  format: 'vessel-operator-identity';
  version: 1;
  operator: {
    id: string;
    name: string;
    email: string;
    role?: string;
  };
  origin: string;
  enrollmentId?: string;
  deviceId?: string;
  port?: number;
  pairingCredential?: string;
  issuedAt: number;
  fingerprint: string;
};

export function createIdentityCard(params: {
  operator: { id: string; name: string; email: string; role?: string };
  origin: string;
  pairing?: {
    enrollmentId: string;
    deviceId: string;
    port: number;
    credential: string;
  } | null;
  issuedAt?: number;
}): OperatorIdentityCard {
  const issuedAt = params.issuedAt ?? Date.now();
  const rawData = `${params.operator.id}:${params.operator.email}:${params.origin}:${params.pairing?.enrollmentId || ''}:${params.pairing?.deviceId || ''}:${issuedAt}`;
  let hash = 0;
  for (let i = 0; i < rawData.length; i++) {
    hash = ((hash << 5) - hash) + rawData.charCodeAt(i);
    hash |= 0;
  }
  const hex = Math.abs(hash).toString(16).padStart(8, '0');
  const shortId = params.operator.id.replace(/[^a-zA-Z0-9]/g, '').slice(0, 6) || 'root';
  const fingerprint = `vsl-id-${hex}-${shortId}`;

  return {
    format: 'vessel-operator-identity',
    version: 1,
    operator: {
      id: params.operator.id,
      name: params.operator.name,
      email: params.operator.email,
      role: params.operator.role,
    },
    origin: params.origin,
    enrollmentId: params.pairing?.enrollmentId,
    deviceId: params.pairing?.deviceId,
    port: params.pairing?.port,
    pairingCredential: params.pairing?.credential,
    issuedAt,
    fingerprint,
  };
}

export function serializeIdentityPass(card: OperatorIdentityCard): string {
  const jsonStr = JSON.stringify(card);
  if (typeof Buffer !== 'undefined') {
    return `vessel-pass:${Buffer.from(jsonStr, 'utf8').toString('base64url')}`;
  }
  const bytes = new TextEncoder().encode(jsonStr);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return `vessel-pass:${btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')}`;
}

export function parseIdentityPass(input: string): OperatorIdentityCard {
  let jsonString = input.trim();
  if (jsonString.startsWith('vessel-pass:')) {
    const encoded = jsonString.slice('vessel-pass:'.length).trim();
    if (typeof Buffer !== 'undefined') {
      jsonString = Buffer.from(encoded, 'base64url').toString('utf8');
    } else {
      const base64 = encoded.replace(/-/g, '+').replace(/_/g, '/');
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i);
      }
      jsonString = new TextDecoder().decode(bytes);
    }
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(jsonString);
  } catch {
    throw new Error('Invalid Identity Card data: not valid JSON or pass code.');
  }

  if (!parsed || typeof parsed !== 'object') {
    throw new Error('Invalid Identity Card format.');
  }

  const card = parsed as Partial<OperatorIdentityCard>;
  if (card.format !== 'vessel-operator-identity' || card.version !== 1) {
    throw new Error('Unsupported Identity Card format or version.');
  }

  if (!card.operator || !card.operator.id || !card.operator.email) {
    throw new Error('Identity Card missing required operator credentials.');
  }

  if (!card.origin || typeof card.origin !== 'string') {
    throw new Error('Identity Card missing origin configuration.');
  }

  if (card.port !== undefined && (typeof card.port !== 'number' || card.port < 1024 || card.port > 65535)) {
    throw new Error('Identity Card contains an invalid companion port.');
  }

  return card as OperatorIdentityCard;
}


