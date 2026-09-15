import { hashPassword, verifyPassword } from 'better-auth/crypto';
import { connectionDb } from '@/db';
import { readBody } from '@/lib/request-body';
import {
  activeAccount,
  allowAccountMutation,
  accountJson as json,
} from '@/lib/account-operations';
export const dynamic = 'force-dynamic';
export async function POST(request: Request) {
  try {
    const current = await activeAccount(request);
    if (!current)
      return json({ error: 'Sign in again to change your password.' }, 401);
    const body = await readBody(request);
    if (
      Object.keys(body).some(
        (k) => !['currentPassword', 'newPassword'].includes(k),
      ) ||
      typeof body.currentPassword !== 'string' ||
      body.currentPassword.length > 128 ||
      typeof body.newPassword !== 'string' ||
      body.newPassword.length < 12 ||
      body.newPassword.length > 128 ||
      body.newPassword === body.currentPassword
    )
      return json(
        { error: 'Choose a different password with 12–128 characters.' },
        400,
      );
    if (!(await allowAccountMutation(current.user.id)))
      return json({ error: 'Too many attempts. Wait a minute.' }, 429);
    const db = connectionDb();
    const old = await db
      .prepare(
        "SELECT password FROM account WHERE user_id = ? AND provider_id = 'credential'",
      )
      .bind(current.user.id)
      .first<{ password: string }>();
    if (
      !old?.password ||
      !(await verifyPassword({
        hash: old.password,
        password: body.currentPassword,
      }))
    )
      return json({ error: 'Your current password is incorrect.' }, 400);
    const password = await hashPassword(body.newPassword);
    const now = Date.now();
    // Compare old hash and live session inside an atomic D1 batch so concurrent
    // owner resets/disables cannot be overwritten by stale password requests.
    const results = await db.batch([
      db
        .prepare(`UPDATE account SET password = ?, updated_at = ? WHERE user_id = ? AND password = ?
        AND EXISTS (SELECT 1 FROM session WHERE id = ? AND expires_at > ?)
        AND EXISTS (SELECT 1 FROM user WHERE id = ? AND banned = 0)`)
        .bind(
          password,
          now,
          current.user.id,
          old.password,
          current.session.id,
          now,
          current.user.id,
        ),
      db
        .prepare(`UPDATE user SET must_change_password = 0, updated_at = ? WHERE id = ?
        AND EXISTS (SELECT 1 FROM account WHERE user_id = ? AND password = ?)`)
        .bind(now, current.user.id, current.user.id, password),
      db
        .prepare(
          `DELETE FROM session WHERE user_id = ? AND EXISTS (SELECT 1 FROM account WHERE user_id = ? AND password = ?)`,
        )
        .bind(current.user.id, current.user.id, password),
    ]);
    if (!results[0].meta.changes)
      return json(
        { error: 'Your account changed during this request. Sign in again.' },
        409,
      );
    return json({ changed: true, signInAgain: true });
  } catch {
    return json(
      {
        error:
          'Could not change your password. Check your input and try again.',
      },
      400,
    );
  }
}
