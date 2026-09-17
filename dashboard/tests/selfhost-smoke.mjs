import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createServer } from 'node:net';
import { randomBytes } from 'node:crypto';

const root = resolve(import.meta.dirname, '..');
const privateDir = await mkdtemp(join(tmpdir(), 'vessel-selfhost-'));
const database = join(privateDir, 'account.sqlite3');
const python = process.env.VESSEL_TEST_PYTHON || (process.platform === 'win32' ? 'py' : 'python3');
const prefix = python === 'py' ? ['-3.11'] : [];
const run = (command, args, env = process.env) => {
  const result = spawnSync(command, args, { cwd: root, env, encoding: 'utf8', timeout: 20000 });
  if (result.status !== 0) throw new Error(`Self-host fixture command failed: ${command}`);
};
const port = await new Promise((resolvePort, reject) => {
  const server = createServer(); server.on('error', reject);
  server.listen(0, '127.0.0.1', () => {
    const address = server.address(); server.close(() => resolvePort(address.port));
  });
});
const base = `http://127.0.0.1:${port}`;
const publicOrigin = 'https://vessel.test.invalid';
const proxyHeaders = { origin: publicOrigin, 'x-forwarded-proto': 'https', 'x-forwarded-host': 'vessel.test.invalid' };
const env = { ...process.env, VESSEL_TARGET: 'node', VESSEL_SQLITE_PATH: database,
  VESSEL_OWNER_FILE_DIR: privateDir, VESSEL_AUTH_SECRET: randomBytes(48).toString('base64url'),
  VESSEL_AUTH_URL: publicOrigin, HOST: '127.0.0.1', PORT: String(port) };
let processHandle;
async function start() {
  processHandle = spawn(process.execPath, [join(root, 'dist/standalone/server.js')], { cwd: root, env, stdio: 'ignore' });
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (processHandle.exitCode !== null) throw new Error('Self-host server exited before readiness');
    try { const response = await fetch(base + '/setup-guide'); if (response.ok) return; } catch { /* startup */ }
    await new Promise(resolveTimeout => setTimeout(resolveTimeout, 150));
  }
  throw new Error('Self-host server startup timed out');
}
async function stop() {
  if (!processHandle || processHandle.exitCode !== null) return;
  processHandle.kill();
  await new Promise(resolveExit => { processHandle.once('exit', resolveExit); setTimeout(resolveExit, 5000); });
}
try {
  await writeFile(database, '');
  run(python, [...prefix, 'scripts/migrate-selfhost.py', '--database', database]);
  run(python, [...prefix, 'scripts/migrate-selfhost.py', '--database', database]);
  run(process.execPath, ['scripts/bootstrap-selfhost.mjs', 'fixture@example.invalid'], env);
  const { readdir } = await import('node:fs/promises');
  const name = (await readdir(privateDir)).find(item => item.startsWith('owner-login-'));
  const login = await readFile(join(privateDir, name), 'utf8');
  const email = /^Email: (.*)$/m.exec(login)?.[1];
  const password = /^Temporary password: (.*)$/m.exec(login)?.[1];
  if (!email || !password) throw new Error('Owner fixture unavailable');
  await start();
  const rejected = await fetch(base + '/api/auth/sign-up/email', { method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' }, body: '{}' });
  if (rejected.status !== 404) throw new Error('Public signup was not blocked');
  const bad = await fetch(base + '/api/session', { method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' }, body: JSON.stringify({ email, password: 'invalid' }) });
  if (bad.ok) throw new Error('Invalid credentials were accepted');
  const success = await fetch(base + '/api/session', { method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' }, body: JSON.stringify({ email, password }) });
  if (!success.ok) throw new Error(`Owner login failed (${success.status})`);
  const cookie = success.headers.get('set-cookie')?.split(';')[0];
  if (!cookie) throw new Error('Session cookie missing');
  const account = await fetch(base + '/api/session', { headers: { ...proxyHeaders, cookie } });
  if ((await account.json()).user?.email !== email) throw new Error('Owner session was not restored');
  await stop();
  await start();
  const restored = await fetch(base + '/api/session', { headers: { ...proxyHeaders, cookie } });
  if ((await restored.json()).user?.email !== email) throw new Error('Session did not persist across restart');
  console.log('Self-host smoke passed: migrations, invite-only, proxied HTTPS login, session restart');
} finally { await stop(); await rm(privateDir, { recursive: true, force: true }); }
