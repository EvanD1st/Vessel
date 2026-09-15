// Real local HTTP + D1 integration. Uses disposable accounts, no companion calls.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { resolve } from 'node:path';
import { getPlatformProxy } from 'wrangler';
import { hashPassword } from 'better-auth/crypto';
const base = 'http://localhost:3000';
const proxy = await getPlatformProxy({ configPath: resolve('dist/server/wrangler.json'), persist: { path: resolve('.wrangler/state/v3') }, experimental: { disableDevRegistry: true } });
const db = proxy.env.DB;
const tag = 'auth-test-' + randomUUID();
const ownerId = tag + '-owner';
const ownerEmail = tag + '@example.test';
const memberEmail = tag + '-member@example.test';
const password = randomUUID() + 'Aa!';
const ids = [ownerId];
let count = 0;
const pass = label => { count++; console.log('PASS: ' + label); };
const jar = () => ({ cookie: '' });
async function call(j, path, body, method = body ? 'POST' : 'GET', extras = {}) {
  const response = await fetch(base + path, { method, headers: { Origin: base, 'Content-Type': 'application/json', ...(j?.cookie ? { Cookie: j.cookie } : {}), ...extras }, ...(body ? { body: JSON.stringify(body) } : {}) });
  const cookies = response.headers.getSetCookie();
  if (j && cookies.length) j.cookie = cookies.map(x => x.split(';')[0]).join('; ');
  const text = await response.text();
  let data; try { data = JSON.parse(text); } catch { data = null; }
  return { status: response.status, data, text, cookies };
}
// Simulate elapsed time between test groups; test the real login bucket limit
// separately below. No cooldown bypass exists in the application itself.
async function expireLoginBucket() {
  await db.prepare('UPDATE rate_limit SET last_request = ? WHERE key = ?').bind(Date.now() - 120000, '127.0.0.1|/sign-in/email').run();
}
async function login(j, email, passphrase) {
  await expireLoginBucket();
  const result = await call(j, '/api/session', { email, password: passphrase });
  assert.equal(result.status, 200, 'Login failed: ' + result.status);
  return result;
}
const originalLabels = JSON.stringify((await db.prepare('SELECT * FROM connections ORDER BY owner_id, enrollment_id').all()).results);
try {
  const now = Date.now();
  await db.batch([
    db.prepare("INSERT INTO user (id,name,email,email_verified,created_at,updated_at,role,banned,must_change_password) VALUES (?, 'Auth test owner', ?, 0, ?, ?, 'admin', 0, 0)").bind(ownerId, ownerEmail, now, now),
    db.prepare("INSERT INTO account (id,account_id,provider_id,user_id,password,created_at,updated_at) VALUES (?, ?, 'credential', ?, ?, ?, ?)").bind(randomUUID(), ownerId, ownerId, await hashPassword(password), now, now),
  ]);
  assert.equal((await call(null, '/api/connections')).status, 401);
  assert.equal((await call(null, '/api/connections', undefined, 'GET', { 'oai-authenticated-user-id': ownerId, Cookie: 'vessel_local_session=forged' })).status, 401);
  for (const path of ['/api/auth/sign-up/email', '/api/auth/admin/create-user', '/api/auth/admin/impersonate-user']) assert.equal((await call(null, path, {})).status, 404);
  assert.equal((await call(null, '/api/account/users', { action: 'create', email: memberEmail, name: 'Unauthorized' })).status, 403);
  pass('anonymous, forged identity, public signup and raw admin routes rejected');
  const owner = jar();
  const signed = await login(owner, ownerEmail, password);
  assert(signed.cookies.some(c => /HttpOnly/i.test(c) && /SameSite=Strict/i.test(c) && /Max-Age=604800/i.test(c)));
  assert(!signed.text.includes(password));
  assert(!('token' in signed.data));
  assert.equal((await call(owner, '/api/connections')).status, 200);
  assert.equal((await call(owner, '/api/account/users')).status, 200);
  pass('real password login, private persistent cookie and owner authorization');
  if (process.argv.includes('--restart-check')) {
    console.log('RESTART CHECK READY: restart only the local dashboard, then press Enter here.');
    await new Promise(resolve => process.stdin.once('data', resolve));
    process.stdin.pause();
    assert.equal((await call(owner, '/api/connections')).status, 200);
    pass('existing cookie survives a real dashboard process restart');
  }
  const badOrigin = await call(owner, '/api/account/users', { action: 'create', name: 'Member', email: memberEmail }, 'POST', { Origin: 'https://foreign.example' });
  assert([400, 403].includes(badOrigin.status));
  assert.equal((await call(owner, '/api/session', undefined, 'DELETE', { Origin: 'https://foreign.example' })).status, 403);
  assert.equal((await call(owner, '/api/session', { email: ownerEmail, password: 'x'.repeat(5000) })).status, 400);
  pass('cross-origin mutations and oversized requests rejected');
  const created = await call(owner, '/api/account/users', { action: 'create', name: 'Test member', email: memberEmail });
  assert.equal(created.status, 200, 'Invite account failed: ' + created.status);
  assert(created.data.temporaryPassword);
  const memberRow = await db.prepare('SELECT id, must_change_password FROM user WHERE email = ?').bind(memberEmail).first();
  ids.push(memberRow.id);
  assert.equal(memberRow.must_change_password, 1);
  assert.equal((await call(owner, '/api/account/users', { action: 'create', name: 'Duplicate', email: memberEmail })).status, 400);
  const member = jar();
  await login(member, memberEmail, created.data.temporaryPassword);
  assert.equal((await call(member, '/api/connections')).status, 401);
  assert.equal((await call(member, '/api/account/users')).status, 403);
  assert((await call(member, '/')).text.includes('Choose your password'));
  pass('owner creates account; temporary password cannot open workspace or owner controls');
  const newPassword = randomUUID() + 'aA!';
  assert.equal((await call(member, '/api/account/password', { currentPassword: 'incorrect', newPassword })).status, 400);
  assert.equal((await call(member, '/api/account/password', { currentPassword: created.data.temporaryPassword, newPassword })).status, 200);
  assert.equal((await call(member, '/api/connections')).status, 401);
  await expireLoginBucket();
  assert.equal((await call(jar(), '/api/session', { email: memberEmail, password: created.data.temporaryPassword })).status, 401);
  await login(member, memberEmail, newPassword);
  assert.equal((await call(member, '/api/connections')).status, 200);
  assert.equal((await call(member, '/api/account/users', { action: 'create', email: tag + '-attacker@example.test', name: 'Attacker' })).status, 403);
  pass('password change revokes sessions, retires temporary password, preserves member-only access');
  const enrollment = 'enrollment_' + tag;
  assert.equal((await call(owner, '/api/connections', { enrollmentId: enrollment, label: 'Owner-only label', port: 8766 })).status, 200);
  assert(!(await call(member, '/api/connections')).data.connections.some(c => c.enrollmentId === enrollment));
  await call(member, '/api/connections', { enrollmentId: enrollment }, 'DELETE');
  assert((await call(owner, '/api/connections')).data.connections.some(c => c.enrollmentId === enrollment));
  pass('connection labels isolated between accounts, including deletion attempts');
  assert.equal((await call(owner, '/api/connections', { enrollmentId: enrollment, label: 'Reject private data', port: 8766, token: 'never-store-this' })).status, 400);
  for (let i = 1; i < 20; i++) assert.equal((await call(owner, '/api/connections', { enrollmentId: enrollment + '_' + i, label: 'Test limit', port: 8766 })).status, 200);
  assert.equal((await call(owner, '/api/connections', { enrollmentId: enrollment + '_20', label: 'Over limit', port: 8766 })).status, 409);
  assert.equal((await call(owner, '/api/connections', { enrollmentId: enrollment, label: 'Updated at limit', port: 8766 })).status, 200);
  pass('private fields rejected and 20-label bound preserved');
  await db.prepare('UPDATE session SET updated_at = ?, expires_at = ? WHERE user_id = ?').bind(Date.now() - 2 * 86400000, Date.now() + 2 * 86400000, memberRow.id).run();
  const renewed = await call(member, '/api/session');
  assert.equal(renewed.status, 200);
  assert(renewed.cookies.length > 0, 'Renewal must refresh browser cookie');
  const renewal = await db.prepare('SELECT expires_at FROM session WHERE user_id = ?').bind(memberRow.id).first();
  assert(renewal.expires_at > Date.now() + 6 * 86400000);
  pass('active session renews its database expiry and browser cookie');
  await call(owner, '/api/account/users', { action: 'disable', userId: memberRow.id });
  assert.equal((await call(member, '/api/connections')).status, 401);
  await expireLoginBucket();
  assert.equal((await call(jar(), '/api/session', { email: memberEmail, password: newPassword })).status, 403);
  await call(owner, '/api/account/users', { action: 'enable', userId: memberRow.id });
  await login(member, memberEmail, newPassword);
  await call(owner, '/api/account/users', { action: 'revoke', userId: memberRow.id });
  assert.equal((await call(member, '/api/connections')).status, 401);
  await login(member, memberEmail, newPassword);
  const reset = await call(owner, '/api/account/users', { action: 'reset', userId: memberRow.id });
  assert.equal(reset.status, 200);
  assert.equal((await call(member, '/api/connections')).status, 401);
  await expireLoginBucket();
  assert.equal((await call(jar(), '/api/session', { email: memberEmail, password: newPassword })).status, 401);
  await login(member, memberEmail, reset.data.temporaryPassword);
  assert.equal((await call(member, '/api/connections')).status, 401);
  pass('disable, enable, end sessions and owner password reset enforced on server');
  assert.equal((await call(owner, '/api/account/users', { action: 'disable', userId: ownerId })).status, 400);
  await db.prepare('UPDATE session SET created_at = ? WHERE user_id = ?').bind(Date.now() - 16 * 60000, ownerId).run();
  assert.equal((await call(owner, '/api/account/users')).status, 403);
  pass('owner cannot disable owner accounts; sensitive actions require recent login');
  // Browser fetch(DELETE) sends no Content-Type by default.
  const signedOut = await fetch(base + '/api/session', { method: 'DELETE', headers: { Origin: base, Cookie: owner.cookie } });
  assert.equal(signedOut.status, 200);
  assert.equal((await call(owner, '/api/connections')).status, 401);
  await db.prepare('UPDATE session SET expires_at = ? WHERE user_id = ?').bind(Date.now() - 1000, memberRow.id).run();
  assert.equal((await call(member, '/api/session')).data.user, null);
  pass('logout and expired sessions rejected');
  await expireLoginBucket();
  const attempts = await Promise.all(Array.from({ length: 8 }, () => call(jar(), '/api/session', { email: tag + '-missing@example.test', password: 'invalid-password' })));
  assert(attempts.filter(x => x.status === 401).length <= 5);
  assert(attempts.some(x => x.status === 429));
  pass('concurrent login rate limit enforced');
  console.log('PASS: ' + count + ' account integration groups');
} finally {
  // Clean only this test's exact fixture identities, including partial creates.
  const member = await db.prepare('SELECT id FROM user WHERE email = ?').bind(memberEmail).first();
  if (member && !ids.includes(member.id)) ids.push(member.id);
  for (const id of ids) await db.batch([
    db.prepare('DELETE FROM connections WHERE owner_id = ?').bind(id),
    db.prepare('DELETE FROM session WHERE user_id = ?').bind(id),
    db.prepare('DELETE FROM account WHERE user_id = ?').bind(id),
    db.prepare('DELETE FROM user WHERE id = ?').bind(id),
    db.prepare('DELETE FROM rate_limit WHERE key = ?').bind('account-mutation:' + id),
  ]);
  await expireLoginBucket();
  assert.equal(JSON.stringify((await db.prepare('SELECT * FROM connections ORDER BY owner_id, enrollment_id').all()).results), originalLabels, 'Existing labels changed');
  await proxy.dispose();
}
