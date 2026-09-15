import { companion, type Session, type Snapshot } from './vessel';

export type Pairing = {
  enrollmentId: string;
  deviceId: string;
  port: number;
  credential: string;
};
type Grant = {
  enrollment_id: string;
  device_id: string;
  token: string;
  expires_at: number;
};
export type Connected = {
  session: Session;
  snapshot: Snapshot;
  pairing: Pairing;
};
const key = (id: string) => `vessel_pairing_${id}`;

export function readPairing(
  storage: Pick<Storage, 'getItem'>,
  enrollmentId: string,
): Pairing | null {
  try {
    const p = JSON.parse(
      storage.getItem(key(enrollmentId)) || 'null',
    ) as Pairing | null;
    if (
      !p ||
      p.enrollmentId !== enrollmentId ||
      !/^[a-f0-9]{24}$/.test(p.deviceId) ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(p.credential) ||
      !Number.isInteger(p.port) ||
      p.port < 1024 ||
      p.port > 65535
    )
      return null;
    return p;
  } catch {
    return null;
  }
}
export function savePairing(
  storage: Pick<Storage, 'setItem' | 'removeItem'>,
  p: Pairing,
) {
  storage.setItem(key(p.enrollmentId), JSON.stringify(p));
  storage.removeItem(`vessel_token_${p.enrollmentId}`);
}
export function forgetPairing(
  storage: Pick<Storage, 'removeItem'>,
  enrollmentId: string,
) {
  storage.removeItem(key(enrollmentId));
  storage.removeItem(`vessel_token_${enrollmentId}`);
}
async function accepted(pairing: Pairing, grant: Grant): Promise<Connected> {
  if (
    grant.enrollment_id !== pairing.enrollmentId ||
    grant.device_id !== pairing.deviceId
  )
    throw new Error(
      'This companion belongs to a different saved project or device.',
    );
  const session = { port: pairing.port, token: grant.token };
  const snapshot = await companion<Snapshot>(session, '/v1/snapshot');
  if (
    snapshot.enrollment?.id !== pairing.enrollmentId ||
    snapshot.bridge?.device_id !== pairing.deviceId
  )
    throw new Error(
      'The companion identity does not match this saved pairing.',
    );
  return { session, snapshot, pairing };
}
export async function pairCompanion(
  bootstrap: Session,
  label: string,
): Promise<Connected> {
  const grant = await companion<Grant & { credential: string }>(
    bootstrap,
    '/v1/pair',
    { label },
    'POST',
  );
  const pairing = {
    enrollmentId: grant.enrollment_id,
    deviceId: grant.device_id,
    port: bootstrap.port,
    credential: grant.credential,
  };
  return accepted(pairing, grant);
}
export async function resumePairing(pairing: Pairing): Promise<Connected> {
  const grant = await companion<Grant>(
    { port: pairing.port, token: pairing.credential },
    '/v1/renew',
    {},
    'POST',
  );
  return accepted(pairing, grant);
}
export async function revokePairing(pairing: Pairing): Promise<void> {
  await companion(
    { port: pairing.port, token: pairing.credential },
    '/v1/devices/current',
    undefined,
    'DELETE',
  );
}
export async function removePairing(
  storage: Pick<Storage, 'removeItem'>,
  pairing: Pairing,
) {
  await revokePairing(pairing);
  forgetPairing(storage, pairing.enrollmentId);
}

/** Retry reads/renewal while the companion starts; never replay owner actions. */
export function startReconnection<T>(
  attempt: () => Promise<T | null>,
  connected: (value: T) => void,
  failed: (error: unknown) => void,
  timers: { set: typeof setTimeout; clear: typeof clearTimeout } = {
    set: setTimeout,
    clear: clearTimeout,
  },
) {
  let stopped = false;
  let delay = 1000;
  let timer: ReturnType<typeof setTimeout>;
  async function run() {
    if (stopped) return;
    try {
      const result = await attempt();
      if (stopped) return;
      if (result) {
        connected(result);
        return;
      }
    } catch (error) {
      if (stopped) return;
      failed(error);
    }
    timer = timers.set(() => {
      void run();
    }, delay);
    delay = Math.min(delay * 2, 30000);
  }
  timer = timers.set(() => {
    void run();
  }, 0);
  return () => {
    stopped = true;
    timers.clear(timer);
  };
}
