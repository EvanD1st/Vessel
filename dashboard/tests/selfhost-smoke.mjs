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
  const download = await fetch(base + '/downloads/vessel.vsix', { method: 'HEAD' });
  if (!download.ok) throw new Error('Standalone public download was not served');
  const invalidSignup = await fetch(base + '/api/register', { method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' }, body: '{}' });
  if (invalidSignup.status !== 400) throw new Error('Invalid signup was not rejected');
  const validSignup = await fetch(base + '/api/register', { method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' }, body: JSON.stringify({ name: 'Smoke User', email: 'smoke@example.invalid', password: 'ValidPassword123!' }) });
  if (!validSignup.ok) throw new Error('Valid self-registration failed');
  const bad = await fetch(base + '/api/session', { method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' }, body: JSON.stringify({ email, password: 'invalid' }) });
  if (bad.ok) throw new Error('Invalid credentials were accepted');
  const success = await fetch(base + '/api/session', { method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' }, body: JSON.stringify({ email, password }) });
  if (!success.ok) throw new Error(`Owner login failed (${success.status})`);
  const cookie = success.headers.get('set-cookie')?.split(';')[0];
  if (!cookie) throw new Error('Session cookie missing');
  const account = await fetch(base + '/api/session', { headers: { ...proxyHeaders, cookie } });
  if ((await account.json()).user?.email !== email) throw new Error('Owner session was not restored');
  const smokeLogin = await fetch(base + '/api/session', {
    method: 'POST', headers: { ...proxyHeaders, 'content-type': 'application/json' },
    body: JSON.stringify({ email: 'smoke@example.invalid', password: 'ValidPassword123!' }),
  });
  if (!smokeLogin.ok) throw new Error('Registered user could not sign in');
  const smokeCookie = smokeLogin.headers.get('set-cookie')?.split(';')[0];
  if (!smokeCookie) throw new Error('Registered user session cookie missing');
  const saved = await fetch(base + '/api/connections', {
    method: 'POST', headers: { ...proxyHeaders, cookie: smokeCookie, 'content-type': 'application/json' },
    body: JSON.stringify({ enrollmentId: 'enrollment_smoke', label: 'Smoke companion', port: 8765 }),
  });
  const saveResult = await saved.json();
  if (!saved.ok || !saveResult.saved) throw new Error(`Connection label was not saved (${saved.status}: ${saveResult.error})`);
  const connections = await fetch(base + '/api/connections', { headers: { ...proxyHeaders, cookie: smokeCookie } });
  if (!(await connections.json()).connections?.some(item => item.enrollmentId === 'enrollment_smoke')) {
    throw new Error('Saved connection list did not include the new label');
  }
  const resetBody = JSON.stringify({ email });
  const resetHeaders = { ...proxyHeaders, 'content-type': 'application/json', 'cf-connecting-ip': '127.0.0.9' };
  for (let attempt = 0; attempt < 3; attempt++) {
    const response = await fetch(base + '/api/forgot-password', { method: 'POST', headers: resetHeaders, body: resetBody });
    if (!response.ok) throw new Error('Password reset request failed');
  }
  const resetToken = () => {
    const code = "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); print(c.execute(\"SELECT identifier FROM verification WHERE identifier LIKE 'reset-password:%'\").fetchone()[0])";
    const result = spawnSync(python, [...prefix, '-c', code, database], { encoding: 'utf8', timeout: 10000 });
    if (result.status !== 0) throw new Error('Could not inspect reset token fixture');
    return result.stdout.trim();
  };
  const beforeLimit = resetToken();
  const limited = await fetch(base + '/api/forgot-password', { method: 'POST', headers: resetHeaders, body: resetBody });
  if (!limited.ok || resetToken() !== beforeLimit) throw new Error('Reset limit replaced an existing token');
  await stop();
  await start();
  const restored = await fetch(base + '/api/session', { headers: { ...proxyHeaders, cookie } });
  if ((await restored.json()).user?.email !== email) throw new Error('Session did not persist across restart');
  console.log('Self-host smoke passed: migrations, signup, login, connections, reset limit, session restart');
} finally { await stop(); await rm(privateDir, { recursive: true, force: true }); }
