// Local-only database migration and first-owner bootstrap. Never targets hosting.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createHash, randomBytes, randomUUID } from 'node:crypto';
import { getPlatformProxy } from 'wrangler';
import { hashPassword } from 'better-auth/crypto';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const value = (name) => {
  const i = args.indexOf(name);
  return i < 0 ? undefined : args[i + 1];
};
const email = value('--email')?.trim().toLowerCase();
const reset = args.includes('--reset-owner');
const migrateOnly = args.includes('--migrate-only');
const inheritDemo = args.includes('--migrate-demo-labels');
const name = value('--name') || 'Workspace owner';
if (
  !migrateOnly &&
  (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 254)
)
  throw new Error(
    'Use --email owner@example.com [--name "Owner"] to create the first owner, or --migrate-only.',
  );
const secretPath = resolve(root, '.dev.vars');
try {
  const vars = await readFile(secretPath, 'utf8');
  if (
    !/^VESSEL_AUTH_SECRET=.{32,}$/m.test(vars) ||
    !/^VESSEL_AUTH_URL=/m.test(vars)
  )
    throw new Error(
      'Existing .dev.vars needs VESSEL_AUTH_SECRET and VESSEL_AUTH_URL; it was preserved.',
    );
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
  await writeFile(
    secretPath,
    `VESSEL_AUTH_URL=http://localhost:3000\nVESSEL_AUTH_SECRET=${randomBytes(48).toString('base64url')}\n`,
    { flag: 'wx', mode: 0o600 },
  );
}
// getPlatformProxy expects the version directory; the Vite plugin appends v3
// itself. Point both tools at the same database, preserving existing labels.
const proxy = await getPlatformProxy({
  configPath: resolve(root, 'dist/server/wrangler.json'),
  persist: { path: resolve(root, '.wrangler/state/v3') },
  experimental: { disableDevRegistry: true },
});
try {
  const db = proxy.env.DB;
  await db
    .prepare(
      'CREATE TABLE IF NOT EXISTS vessel_local_migrations (name TEXT PRIMARY KEY, hash TEXT NOT NULL)',
    )
    .run();
  const journal = JSON.parse(
    await readFile(resolve(root, 'drizzle/meta/_journal.json'), 'utf8'),
  );
  for (const entry of journal.entries) {
    const sql = await readFile(
      resolve(root, 'drizzle', entry.tag + '.sql'),
      'utf8',
    );
    const hash = createHash('sha256').update(sql).digest('hex');
    const applied = await db
      .prepare('SELECT hash FROM vessel_local_migrations WHERE name = ?')
      .bind(entry.tag)
      .first();
    if (applied) {
      if (applied.hash !== hash)
        throw new Error('Previously applied migration changed: ' + entry.tag);
      continue;
    }
    let statements = sql
      .split('--> statement-breakpoint')
      .map((s) => s.trim())
      .filter(Boolean);
    // Adopt only the exact table previously installed by setup-dashboard.ps1.
    if (
      entry.idx === 0 &&
      (await db
        .prepare(
          "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'connections'",
        )
        .first())
    ) {
      const columns = (await db.prepare('PRAGMA table_info(connections)').all())
        .results;
      const expected = [
        ['owner_id', 'TEXT', 1, 1],
        ['enrollment_id', 'TEXT', 1, 2],
        ['label', 'TEXT', 1, 0],
        ['port', 'INTEGER', 1, 0],
        ['updated_at', 'INTEGER', 1, 0],
      ];
      if (
        JSON.stringify(
          columns.map((c) => [c.name, c.type, c.notnull, c.pk]),
        ) !== JSON.stringify(expected)
      )
        throw new Error(
          'Existing connection schema differs; no migration was applied.',
        );
      statements = [];
    }
    await db.batch([
      ...statements.map((sql) => db.prepare(sql)),
      db
        .prepare('INSERT INTO vessel_local_migrations VALUES (?, ?)')
        .bind(entry.tag, hash),
    ]);
    console.log('Applied local migration: ' + entry.tag);
  }
  if (!migrateOnly) {
    const owner = await db
      .prepare("SELECT id, email FROM user WHERE role = 'admin'")
      .first();
    if (owner && !reset) {
      console.log('Owner already exists; credentials and labels preserved.');
    } else {
      if (reset && (!owner || owner.email !== email))
        throw new Error('--reset-owner requires the existing owner email.');
      if (!owner && (await db.prepare('SELECT id FROM user LIMIT 1').first()))
        throw new Error(
          'Existing accounts require an explicit owner repair; bootstrap refused.',
        );
      const id = owner?.id || (inheritDemo ? 'local_seedy' : randomUUID());
      const password = randomBytes(24).toString('base64url') + 'aA!';
      const hash = await hashPassword(password);
      const now = Date.now();
      // Create the output before changing the DB, so a disk-full error cannot
      // leave a reset owner with an unrecoverable random password.
      await mkdir(resolve(root, '.wrangler'), { recursive: true });
      const loginFile = resolve(
        root,
        '.wrangler',
        'owner-login-' + randomUUID() + '.txt',
      );
      await writeFile(
        loginFile,
        `VESSEL local owner\nEmail: ${email}\nTemporary password: ${password}\n\nOpen http://localhost:3000 and replace this password immediately.\nThis file is local, ignored by Git, and not a production credential.\n`,
        { flag: 'wx', mode: 0o600 },
      );
      if (owner) {
        await db.batch([
          db
            .prepare(
              "UPDATE account SET password = ?, updated_at = ? WHERE user_id = ? AND provider_id = 'credential'",
            )
            .bind(hash, now, id),
          db
            .prepare(
              'UPDATE user SET must_change_password = 1, banned = 0, updated_at = ? WHERE id = ?',
            )
            .bind(now, id),
          db.prepare('DELETE FROM session WHERE user_id = ?').bind(id),
        ]);
      } else {
        await db.batch([
          db
            .prepare(
              "INSERT INTO user (id, name, email, email_verified, created_at, updated_at, role, banned, must_change_password) VALUES (?, ?, ?, 0, ?, ?, 'admin', 0, 1)",
            )
            .bind(id, name, email, now, now),
          db
            .prepare(
              "INSERT INTO account (id, account_id, provider_id, user_id, password, created_at, updated_at) VALUES (?, ?, 'credential', ?, ?, ?, ?)",
            )
            .bind(randomUUID(), id, id, hash, now, now),
        ]);
      }
      console.log('Owner ready. Private temporary login file: ' + loginFile);
    }
  }
  console.log(
    'Local account setup complete. Restart the dashboard after the first setup.',
  );
} finally {
  await proxy.dispose();
}
