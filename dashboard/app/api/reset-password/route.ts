import { hashPassword } from 'better-auth/crypto';
import { connectionDb } from '@/db';
import { readBody } from '@/lib/request-body';

export const dynamic = 'force-dynamic';

const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });

export async function POST(request: Request) {
  let body: Record<string, unknown>;
  try {
    body = await readBody(request);
    if (
      Object.keys(body).some((k) => !['token', 'password'].includes(k)) ||
      typeof body.token !== 'string' ||
      !body.token.trim() ||
      typeof body.password !== 'string' ||
      body.password.length < 8 ||
      body.password.length > 128
    ) {
      throw new Error('fields');
    }
  } catch {
    return json(
      { error: 'Provide a valid reset token and new password (minimum 8 characters).' },
      400,
    );
  }

  const token = (body.token as string).trim();
  const password = body.password as string;

  try {
    const db = connectionDb();
    const record = await db
      .prepare('SELECT id, value, expires_at FROM verification WHERE identifier = ?')
      .bind(`reset-password:${token}`)
      .first<{ id: string; value: string; expires_at: number }>();

    if (!record || Number(record.expires_at) < Date.now()) {
      return json(
        {
          error:
            'The password reset token is invalid or has expired. Please request a new one.',
        },
        400,
      );
    }

    const userId = record.value;
    const hash = await hashPassword(password);
    const now = Date.now();

    await db.batch([
      db
        .prepare(
          "UPDATE account SET password = ?, updated_at = ? WHERE user_id = ? AND provider_id = 'credential'",
        )
        .bind(hash, now, userId),
      db
        .prepare('UPDATE user SET must_change_password = 0, updated_at = ? WHERE id = ?')
        .bind(now, userId),
      db.prepare('DELETE FROM verification WHERE id = ?').bind(record.id),
      db.prepare('DELETE FROM session WHERE user_id = ?').bind(userId),
    ]);

    console.log(`[VESSEL AUTH] Password reset successfully executed for user ${userId}`);

    return json({
      success: true,
      message: 'Master password has been updated successfully.',
    });
  } catch (err) {
    console.error('Password reset execution failed:', err);
    return json({ error: 'Could not reset password. Try again shortly.' }, 503);
  }
}
