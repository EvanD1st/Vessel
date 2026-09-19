import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { afterEach, test } from 'node:test';
import ts from 'typescript';

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
const {
  getOrbioStatus,
  connectOrbioKey,
  replaceOrbioKey,
  forgetOrbioKey,
  refreshOrbioStatus,
} = await import(vesselUrl);

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

const mockSession = {
  port: 8090,
  token: 'mock-admission-token-12345',
};

const urlToString = (url) =>
  typeof url === 'string' ? url : url instanceof URL ? url.href : String(url);

void test('getOrbioStatus issues authenticated GET /v1/orbio/status', async () => {
  let calledUrl = '';
  let calledHeaders = {};
  globalThis.fetch = async (url, init) => {
    calledUrl = urlToString(url);
    calledHeaders = init?.headers || {};
    return {
      ok: true,
      status: 200,
      json: async () => ({
        connected: true,
        masked_key: 'sk-orbio-••••7x9k',
        status: 'active',
        probe_status: 'ok',
        gateway: {
          status: 'healthy',
          port: 8091,
          base_url: 'http://127.0.0.1:8091/v1/chat/completions',
          models: ['anthropic/claude-3-5-sonnet-20241022'],
          running: true,
        },
        balance: { available: true, amount: 42.5, currency: 'CREDIT' },
        usage: { available: false, amount: null, currency: 'CREDIT' },
        mcp: { configured: true, capabilities: ['orbio:balance'] },
        last_error: null,
      }),
    };
  };

  const status = await getOrbioStatus(mockSession);
  assert.equal(calledUrl, 'http://127.0.0.1:8090/v1/orbio/status');
  assert.equal(calledHeaders.Authorization, 'Bearer mock-admission-token-12345');
  assert.equal(status.connected, true);
  assert.equal(status.masked_key, 'sk-orbio-••••7x9k');
  assert.equal(status.probe_status, 'ok');
  assert.equal(status.balance.amount, 42.5);
});

void test('connectOrbioKey issues POST /v1/orbio/credentials and receives masked key', async () => {
  let calledMethod = '';
  let calledBody = null;
  globalThis.fetch = async (url, init) => {
    calledMethod = init?.method;
    calledBody = JSON.parse(init?.body);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        status: 'active',
        credential_version: 'v1',
        masked_key: 'sk-orbio-••••abcd',
        verified_at: 1700000000,
      }),
    };
  };

  const res = await connectOrbioKey(mockSession, 'sk-orbio-live-test-1234abcd');
  assert.equal(calledMethod, 'POST');
  assert.equal(calledBody.key, 'sk-orbio-live-test-1234abcd');
  assert.equal(res.masked_key, 'sk-orbio-••••abcd');
  assert.equal(res.status, 'active');
});

void test('replaceOrbioKey issues POST /v1/orbio/replace', async () => {
  let calledUrl = '';
  let calledMethod = '';
  let calledBody = null;
  globalThis.fetch = async (url, init) => {
    calledUrl = urlToString(url);
    calledMethod = init?.method;
    calledBody = JSON.parse(init?.body);
    return {
      ok: true,
      status: 200,
      json: async () => ({
        status: 'active',
        credential_version: 'v2',
        masked_key: 'sk-orbio-••••zzzz',
        verified_at: 1700000100,
      }),
    };
  };

  const res = await replaceOrbioKey(mockSession, 'sk-orbio-new-key-zzzz');
  assert.equal(calledUrl, 'http://127.0.0.1:8090/v1/orbio/replace');
  assert.equal(calledMethod, 'POST');
  assert.equal(calledBody.key, 'sk-orbio-new-key-zzzz');
  assert.equal(res.masked_key, 'sk-orbio-••••zzzz');
});

void test('forgetOrbioKey issues DELETE /v1/orbio/credentials', async () => {
  let calledUrl = '';
  let calledMethod = '';
  globalThis.fetch = async (url, init) => {
    calledUrl = urlToString(url);
    calledMethod = init?.method;
    return {
      ok: true,
      status: 200,
      json: async () => ({
        status: 'removed',
        paused: true,
        recovery_history_preserved: true,
      }),
    };
  };

  const res = await forgetOrbioKey(mockSession);
  assert.equal(calledUrl, 'http://127.0.0.1:8090/v1/orbio/credentials');
  assert.equal(calledMethod, 'DELETE');
  assert.equal(res.status, 'removed');
  assert.equal(res.recovery_history_preserved, true);
});

void test('refreshOrbioStatus issues POST /v1/orbio/refresh', async () => {
  let calledUrl = '';
  let calledMethod = '';
  globalThis.fetch = async (url, init) => {
    calledUrl = urlToString(url);
    calledMethod = init?.method;
    return {
      ok: true,
      status: 200,
      json: async () => ({
        connected: true,
        masked_key: 'sk-orbio-••••7x9k',
        status: 'active',
        probe_status: 'ok',
        gateway: {
          status: 'healthy',
          port: 8091,
          models: ['anthropic/claude-3-5-sonnet-20241022'],
          running: true,
        },
        balance: { available: false, amount: null, currency: 'CREDIT' },
        usage: { available: false, amount: null, currency: 'CREDIT' },
        mcp: { configured: false, capabilities: [] },
        last_error: null,
      }),
    };
  };

  const res = await refreshOrbioStatus(mockSession);
  assert.equal(calledUrl, 'http://127.0.0.1:8090/v1/orbio/refresh');
  assert.equal(calledMethod, 'POST');
  assert.equal(res.connected, true);
});

void test('regression: raw Orbio keys never enter D1 connection schema or API payload', () => {
  // Verify D1 connection schema contains only label and local network metadata
  const schemaSource = readFileSync(
    new URL('../db/schema.ts', import.meta.url),
    'utf8',
  );
  // Verify connections table has only ownerId, enrollmentId, label, port, updatedAt
  assert.match(schemaSource, /export const connections = sqliteTable\(/);
  assert.ok(!schemaSource.includes('orbio'));
  assert.ok(!schemaSource.includes('api_key'));
  assert.ok(!schemaSource.includes('secret'));

  // Verify connection API route rejects extra fields (including keys/tokens)
  const routeSource = readFileSync(
    new URL('../app/api/connections/route.ts', import.meta.url),
    'utf8',
  );
  assert.ok(
    routeSource.includes("!['enrollmentId', 'label', 'port'].includes(k)"),
  );
});

void test('regression: Orbio status returns masked key only, never raw key', async () => {
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    json: async () => ({
      connected: true,
      masked_key: 'sk-orbio-••••1234',
      status: 'active',
      probe_status: 'ok',
      gateway: { status: 'healthy', port: 8091, models: [], running: true },
      balance: { available: false, amount: null, currency: 'CREDIT' },
      usage: { available: false, amount: null, currency: 'CREDIT' },
      mcp: { configured: false, capabilities: [] },
      last_error: null,
    }),
  });

  const status = await getOrbioStatus(mockSession);
  assert.equal(status.masked_key, 'sk-orbio-••••1234');
  assert.ok(!('key' in status));
  assert.ok(!('raw_key' in status));
  assert.ok(!('token' in status));
});
