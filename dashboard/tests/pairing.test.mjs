import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { afterEach, test } from 'node:test';
import ts from 'typescript';

// Run the real browser transport and pairing coordinator without a DOM or network.
const compile = (name) =>
  ts.transpileModule(
    readFileSync(new URL(`../lib/${name}.ts`, import.meta.url), 'utf8'),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.ES2022,
      },
    },
  ).outputText;
const moduleUrl = (source) =>
  'data:text/javascript;base64,' + Buffer.from(source).toString('base64');
const vesselUrl = moduleUrl(compile('vessel'));
const { accountStorage } = await import(moduleUrl(compile('account-storage')));
const pairingUrl = moduleUrl(
  compile('pairing').replace(/from ['"]\.\/vessel['"]/, `from '${vesselUrl}'`),
);
const {
  pairCompanion,
  resumePairing,
  savePairing,
  readPairing,
  removePairing,
  startReconnection,
} = await import(pairingUrl);
const originalFetch = globalThis.fetch;

void test('account switches cannot read or delete another account pairing', () => {
  const local = storage();
  const a = accountStorage(local, 'owner-a');
  const b = accountStorage(local, 'owner-b');
  a.setItem('vessel_pairing_test', 'private-a');
  assert.equal(b.getItem('vessel_pairing_test'), null);
  b.removeItem('vessel_pairing_test');
  assert.equal(a.getItem('vessel_pairing_test'), 'private-a');
});
void test('only explicitly migrated demo owner inherits legacy pairing', () => {
  const local = storage();
  local.setItem('vessel_pairing_test', 'legacy-private');
  assert.equal(accountStorage(local, 'another-owner').getItem('vessel_pairing_test'), null);
  const owner = accountStorage(local, 'local_seedy');
  assert.equal(owner.getItem('vessel_pairing_test'), 'legacy-private');
  assert.equal(local.getItem('vessel_pairing_test'), null);
  assert.equal(owner.getItem('vessel_pairing_test'), 'legacy-private');
});
afterEach(() => {
  globalThis.fetch = originalFetch;
});
const grant = {
  token: 'a'.repeat(48),
  credential: 'c'.repeat(48),
  device_id: 'd'.repeat(24),
  enrollment_id: 'enrollment_example',
  expires_at: 99999,
};
const pairing = {
  credential: grant.credential,
  deviceId: grant.device_id,
  enrollmentId: grant.enrollment_id,
  port: 8765,
};
const snapshot = {
  enrollment: { id: grant.enrollment_id },
  bridge: { device_id: grant.device_id, expires_at: grant.expires_at },
};
const reply = (body, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => body,
});
function storage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    values,
  };
}
const tick = () => new Promise((resolve) => setImmediate(resolve));

void test('pairing saves only the durable credential, never the access token or old bootstrap', async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return reply(url.endsWith('/v1/pair') ? grant : snapshot);
  };
  const result = await pairCompanion(
    { port: 8765, token: 'bootstrap-only' },
    'My browser',
  );
  const local = storage();
  local.setItem('vessel_token_' + grant.enrollment_id, 'old-bootstrap');
  savePairing(local, result.pairing);
  assert.deepEqual(readPairing(local, grant.enrollment_id), pairing);
  assert.equal(local.getItem('vessel_token_' + grant.enrollment_id), null);
  assert.ok(!JSON.stringify([...local.values]).includes(grant.token));
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(
    requests[1].options.headers.Authorization,
    'Bearer ' + grant.token,
  );
});

void test('offline resume renews with POST before reading with the new access session', async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return reply(url.endsWith('/v1/renew') ? grant : snapshot);
  };
  await resumePairing(pairing);
  assert.equal(requests[0].options.method, 'POST');
  assert.equal(
    requests[0].options.headers.Authorization,
    'Bearer ' + grant.credential,
  );
  assert.equal(requests[1].options.method, 'GET');
  assert.equal(
    requests[1].options.headers.Authorization,
    'Bearer ' + grant.token,
  );
});

void test('failed DELETE preserves the pairing; acknowledged revocation clears it', async () => {
  const local = storage();
  savePairing(local, pairing);
  globalThis.fetch = async (url, options) => {
    assert.ok(url.endsWith('/v1/devices/current'));
    assert.equal(options.method, 'DELETE');
    return reply({ error: 'Companion unavailable' }, 503);
  };
  await assert.rejects(removePairing(local, pairing), /Companion unavailable/);
  assert.deepEqual(readPairing(local, pairing.enrollmentId), pairing);
  globalThis.fetch = async () => reply({ status: 'revoked' });
  await removePairing(local, pairing);
  assert.equal(readPairing(local, pairing.enrollmentId), null);
});

void test('a saved pairing cannot silently reconnect to a different enrollment', async () => {
  globalThis.fetch = async () =>
    reply({ ...grant, enrollment_id: 'enrollment_wrong' });
  await assert.rejects(resumePairing(pairing), /different saved project/);
});

void test('startup failure retries with backoff and connects after the companion starts', async () => {
  const pending = [];
  const delays = [];
  const timers = {
    set: (f, delay) => {
      pending.push(f);
      delays.push(delay);
      return pending.length;
    },
    clear: () => {},
  };
  let online = false;
  let connected;
  const errors = [];
  globalThis.fetch = async (url) => {
    if (!online) throw new Error('Not started');
    return reply(url.endsWith('/v1/renew') ? grant : snapshot);
  };
  const stop = startReconnection(
    () => resumePairing(pairing),
    (value) => {
      connected = value;
    },
    (e) => errors.push(e),
    timers,
  );
  pending.shift()();
  await tick();
  assert.equal(connected, undefined);
  assert.equal(errors.length, 1);
  assert.deepEqual(delays, [0, 1000]);
  online = true;
  pending.shift()();
  await tick();
  assert.equal(connected.pairing.deviceId, pairing.deviceId);
  assert.equal(pending.length, 0);
  stop();
});

void test('disconnect cancels an in-flight reconnect without publishing its late result', async () => {
  let finish;
  let fire;
  const response = new Promise((resolve) => {
    finish = resolve;
  });
  const connected = [];
  const stop = startReconnection(
    () => response,
    (r) => connected.push(r),
    () => {},
    {
      set: (fn) => {
        fire = fn;
        return 1;
      },
      clear: () => {},
    },
  );
  fire();
  await tick();
  stop();
  finish({ session: 'late' });
  await tick();
  assert.deepEqual(connected, []);
});

void test('invalid persisted data is ignored instead of sending credentials to an arbitrary port', () => {
  const local = storage();
  local.setItem(
    'vessel_pairing_' + pairing.enrollmentId,
    JSON.stringify({ ...pairing, port: 80 }),
  );
  assert.equal(readPairing(local, pairing.enrollmentId), null);
});
