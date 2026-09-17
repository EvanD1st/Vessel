import { randomBytes, randomUUID, scrypt } from 'node:crypto';
import { writeFile, mkdir } from 'node:fs/promises';
import { isAbsolute } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { promisify } from 'node:util';

const scryptAsync = promisify(scrypt);
async function hashPassword(password) {
  const salt = randomBytes(16).toString('hex');
  const key = await scryptAsync(password.normalize('NFKC'), salt, 64, {
    N: 16384, r: 16, p: 1, maxmem: 128 * 16384 * 16 * 2,
  });
  return `${salt}:${key.toString('hex')}`;
}

const email = process.argv[2]?.trim().toLowerCase();
const databasePath = process.env.VESSEL_SQLITE_PATH;
const outputDir = process.env.VESSEL_OWNER_FILE_DIR;
if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || !databasePath || !isAbsolute(databasePath) || !outputDir || !isAbsolute(outputDir)) {
  throw new Error('Pass owner email; set absolute VESSEL_SQLITE_PATH and VESSEL_OWNER_FILE_DIR.');
}
const db = new DatabaseSync(databasePath, { timeout: 5000, enableForeignKeyConstraints: true });
const existing = db.prepare("SELECT id FROM user WHERE role = 'admin'").get();
if (existing) { console.log('Owner exists; account and credentials preserved.'); process.exit(0); }
if (db.prepare('SELECT id FROM user LIMIT 1').get()) throw new Error('Existing users need owner repair; bootstrap refused.');
const password = randomBytes(24).toString('base64url') + 'aA!';
const hash = await hashPassword(password);
const id = randomUUID(), now = Date.now();
await mkdir(outputDir, { recursive: true, mode: 0o700 });
const file = `${outputDir}/owner-login-${randomUUID()}.txt`;
await writeFile(file, `VESSEL owner\nEmail: ${email}\nTemporary password: ${password}\nChange it after your first sign-in.\n`, { flag: 'wx', mode: 0o600 });
db.exec('BEGIN IMMEDIATE');
try {
  db.prepare("INSERT INTO user (id, name, email, email_verified, created_at, updated_at, role, banned, must_change_password) VALUES (?, ?, ?, 1, ?, ?, 'admin', 0, 1)")
    .run(id, 'Workspace owner', email, now, now);
  db.prepare("INSERT INTO account (id, account_id, provider_id, user_id, password, created_at, updated_at) VALUES (?, ?, 'credential', ?, ?, ?, ?)")
    .run(randomUUID(), id, id, hash, now, now);
  db.exec('COMMIT');
} catch (error) { db.exec('ROLLBACK'); throw error; }
console.log(`Owner created. Private one-time login file: ${file}`);
