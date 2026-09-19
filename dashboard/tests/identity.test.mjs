import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
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
  createIdentityCard,
  serializeIdentityPass,
  parseIdentityPass,
} = await import(vesselUrl);

const pairingUrl = moduleUrl(
  compile('pairing').replace("from './vessel';", `from '${vesselUrl}';`),
);
const {
  readPairing,
  importPairingFromIdentity,
} = await import(pairingUrl);

class MemoryStorage {
  constructor() {
    this.map = new Map();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  setItem(key, value) {
    this.map.set(key, String(value));
  }
  removeItem(key) {
    this.map.delete(key);
  }
}

void test('createIdentityCard generates compliant schema and deterministic fingerprint', () => {
  const card = createIdentityCard({
    operator: {
      id: 'usr_abc123',
      name: 'James Operator',
      email: 'james@example.com',
      role: 'admin',
    },
    origin: 'https://vessel-dashboard.cloud-ip.cc',
    pairing: {
      enrollmentId: 'enr_857944557785',
      deviceId: '0123456789abcdef01234567',
      port: 8090,
      credential: 'vsl_cred_test_secret_token_1234567890',
    },
    issuedAt: 1726760000000,
  });

  assert.equal(card.format, 'vessel-operator-identity');
  assert.equal(card.version, 1);
  assert.equal(card.operator.id, 'usr_abc123');
  assert.equal(card.operator.email, 'james@example.com');
  assert.equal(card.origin, 'https://vessel-dashboard.cloud-ip.cc');
  assert.equal(card.enrollmentId, 'enr_857944557785');
  assert.equal(card.port, 8090);
  assert.ok(card.fingerprint.startsWith('vsl-id-'));
  assert.ok(card.fingerprint.includes('usrabc'));
});

void test('serializeIdentityPass and parseIdentityPass round-trip correctly', () => {
  const original = createIdentityCard({
    operator: {
      id: 'usr_xyz789',
      name: 'Agent Operator',
      email: 'agent@example.com',
    },
    origin: 'https://vessel-dashboard.cloud-ip.cc',
    pairing: {
      enrollmentId: 'enr_999888777666',
      deviceId: 'abcdef0123456789abcdef01',
      port: 8090,
      credential: 'token_pass_abc_123_456_789_000',
    },
  });

  const pass = serializeIdentityPass(original);
  assert.ok(pass.startsWith('vessel-pass:'));

  const parsed = parseIdentityPass(pass);
  assert.equal(parsed.format, original.format);
  assert.equal(parsed.operator.id, original.operator.id);
  assert.equal(parsed.operator.email, original.operator.email);
  assert.equal(parsed.enrollmentId, original.enrollmentId);
  assert.equal(parsed.deviceId, original.deviceId);
  assert.equal(parsed.port, original.port);
  assert.equal(parsed.pairingCredential, original.pairingCredential);
  assert.equal(parsed.fingerprint, original.fingerprint);

  // Also round-trips from pure JSON string
  const fromJson = parseIdentityPass(JSON.stringify(original));
  assert.equal(fromJson.fingerprint, original.fingerprint);
});

void test('parseIdentityPass rejects tampered or invalid passes', () => {
  assert.throws(() => parseIdentityPass('not-a-valid-pass'), /Invalid Identity Card/);
  assert.throws(() => parseIdentityPass('{}'), /Unsupported Identity Card format/);
  assert.throws(
    () =>
      parseIdentityPass(
        JSON.stringify({
          format: 'vessel-operator-identity',
          version: 1,
          operator: { id: '', email: '' },
          origin: 'https://vessel-dashboard.cloud-ip.cc',
        }),
      ),
    /missing required operator credentials/,
  );
  assert.throws(
    () =>
      parseIdentityPass(
        JSON.stringify({
          format: 'vessel-operator-identity',
          version: 1,
          operator: { id: '123', email: 'test@example.com' },
          origin: 'https://vessel-dashboard.cloud-ip.cc',
          port: 99999,
        }),
      ),
    /invalid companion port/,
  );
});

void test('importPairingFromIdentity stores valid pairing and enables readPairing', () => {
  const storage = new MemoryStorage();
  const card = createIdentityCard({
    operator: {
      id: 'usr_portable',
      name: 'Moving User',
      email: 'move@example.com',
    },
    origin: 'https://vessel-dashboard.cloud-ip.cc',
    pairing: {
      enrollmentId: 'enr_transfer1234',
      deviceId: '1234567890abcdef12345678',
      port: 8090,
      credential: 'secret_credential_token_moving_system',
    },
  });

  const imported = importPairingFromIdentity(storage, card);
  assert.ok(imported);
  assert.equal(imported.enrollmentId, 'enr_transfer1234');
  assert.equal(imported.port, 8090);

  // Verify readPairing can now re-hydrate the connection in the new environment
  const loaded = readPairing(storage, 'enr_transfer1234');
  assert.ok(loaded);
  assert.equal(loaded.enrollmentId, 'enr_transfer1234');
  assert.equal(loaded.deviceId, '1234567890abcdef12345678');
  assert.equal(loaded.port, 8090);
  assert.equal(loaded.credential, 'secret_credential_token_moving_system');
});
