import { hashPassword } from 'better-auth/crypto';
import { connectionDb } from '@/db';
import { readBody } from '@/lib/request-body';
import {
  activeAccount,
  allowAccountMutation,
  accountJson as json,
} from '@/lib/account-operations';
export const dynamic = 'force-dynamic';
export async function GET(request: Request) {
  try {
    if (!(await activeAccount(request, true)))
      return json(
        {
          error: 'Owner access requires a sign-in within the last 15 minutes.',
        },
        403,
      );
    const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0);
    if (!Number.isSafeInteger(offset) || offset < 0)
      return json({ error: 'Invalid page.' }, 400);
    const db = connectionDb();
    const rows = await db
      .prepare(
        'SELECT id, name, email, role, banned, must_change_password AS mustChangePassword FROM user ORDER BY created_at, id LIMIT 50 OFFSET ?',
      )
      .bind(offset)
      .all();
    const total = await db
      .prepare('SELECT count(*) AS count FROM user')
      .first<{ count: number }>();
    return json({ users: rows.results, total: total?.count ?? 0 });
  } catch {
    return json({ error: 'Accounts are temporarily unavailable.' }, 503);
  }
}
export async function POST(request: Request) {
  try {
    const owner = await activeAccount(request, true);
    if (!owner)
      return json(
        {
          error: 'Owner access requires a sign-in within the last 15 minutes.',
        },
        403,
      );
    const body = await readBody(request);
    if (!(await allowAccountMutation(owner.user.id)))
      return json({ error: 'Too many account changes. Wait a minute.' }, 429);
    if (body.action === 'create') {
      if (
        Object.keys(body).some(
          (k) => !['action', 'email', 'name'].includes(k),
        ) ||
        typeof body.name !== 'string' ||
        !body.name.trim() ||
        body.name.length > 80 ||
        typeof body.email !== 'string' ||
        body.email.length > 254 ||
        !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email.trim())
      )
        return json({ error: 'Enter a name and valid email address.' }, 400);
      const password = crypto.randomUUID() + 'aA!';
      const id = crypto.randomUUID();
      const email = body.email.trim().toLowerCase();
      const now = Date.now();
      const hash = await hashPassword(password);
      // D1 batch is atomic: never leave an invited account without its password
      // if hashing or linking fails. Role and activation state are server-owned.
      await connectionDb().batch([
        connectionDb().prepare("INSERT INTO user (id, name, email, email_verified, created_at, updated_at, role, banned, must_change_password) VALUES (?, ?, ?, 0, ?, ?, 'user', 0, 1)").bind(id, body.name.trim(), email, now, now),
        connectionDb().prepare("INSERT INTO account (id, account_id, provider_id, user_id, password, created_at, updated_at) VALUES (?, ?, 'credential', ?, ?, ?, ?)").bind(crypto.randomUUID(), id, id, hash, now, now),
      ]);
      return json({
        created: true,
        email,
        temporaryPassword: password,
      });
    }
    if (
      Object.keys(body).some((k) => !['action', 'userId'].includes(k)) ||
      typeof body.userId !== 'string' ||
      !['disable', 'enable', 'reset', 'revoke'].includes(String(body.action))
    )
      return json({ error: 'Choose an account and an available action.' }, 400);
    const db = connectionDb();
    const target = await db
      .prepare('SELECT id, email, role FROM user WHERE id = ?')
      .bind(body.userId)
      .first<{ id: string; email: string; role: string }>();
    if (!target || target.role !== 'user')
      return json({ error: 'Owner accounts cannot be changed here.' }, 400);
    if (body.action === 'reset') {
      const password = crypto.randomUUID() + 'aA!';
      const hash = await hashPassword(password);
      await db.batch([
        db
          .prepare(
            "UPDATE account SET password = ?, updated_at = ? WHERE user_id = ? AND provider_id = 'credential'",
          )
          .bind(hash, Date.now(), target.id),
        db
          .prepare(
            'UPDATE user SET must_change_password = 1, updated_at = ? WHERE id = ?',
          )
          .bind(Date.now(), target.id),
        db.prepare('DELETE FROM session WHERE user_id = ?').bind(target.id),
      ]);
      return json({
        reset: true,
        email: target.email,
        temporaryPassword: password,
      });
    }
    if (body.action === 'revoke') {
      await db
        .prepare('DELETE FROM session WHERE user_id = ?')
        .bind(target.id)
        .run();
    } else {
      await db.batch([
        db
          .prepare('UPDATE user SET banned = ?, updated_at = ? WHERE id = ?')
          .bind(body.action === 'disable' ? 1 : 0, Date.now(), target.id),
        db.prepare('DELETE FROM session WHERE user_id = ?').bind(target.id),
      ]);
    }
    return json({ updated: true });
  } catch {
    return json(
      {
        error:
          'Could not update the account. Check for an existing email and try again.',
      },
      400,
    );
  }
}
