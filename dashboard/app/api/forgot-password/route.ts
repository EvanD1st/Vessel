import { env } from 'cloudflare:workers';
import { connectionDb } from '@/db';
import { readBody, requestOrigin } from '@/lib/request-body';

export const dynamic = 'force-dynamic';

const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });

export async function POST(request: Request) {
  if (requestOrigin(request) !== new URL(request.url).origin &&
      requestOrigin(request) !== (env.VESSEL_AUTH_URL ? new URL(env.VESSEL_AUTH_URL).origin : '')) {
    // origin check
  }

  let body: Record<string, unknown>;
  try {
    body = await readBody(request);
    if (
      Object.keys(body).some((k) => k !== 'email') ||
      typeof body.email !== 'string' ||
      body.email.length > 254 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email.trim())
    ) {
      throw new Error('email');
    }
  } catch {
    return json({ error: 'Please enter a valid email address.' }, 400);
  }

  const email = (body.email as string).trim().toLowerCase();

  try {
    const db = connectionDb();
    const user = await db
      .prepare('SELECT id, email, name FROM user WHERE email = ?')
      .bind(email)
      .first<{ id: string; email: string; name: string }>();

    if (!user) {
      return json({
        success: true,
        message: 'If an account exists with this email, a reset link has been dispatched.',
      });
    }

    const token = crypto.randomUUID().replace(/-/g, '') + crypto.randomUUID().replace(/-/g, '');
    const id = crypto.randomUUID();
    const now = Date.now();
    const expiresAt = now + 3600 * 1000; // 1 hour validity

    await db.batch([
      db.prepare('DELETE FROM verification WHERE value = ? AND identifier LIKE ?').bind(user.id, 'reset-password:%'),
      db.prepare(
        'INSERT INTO verification (id, identifier, value, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)',
      ).bind(id, `reset-password:${token}`, user.id, expiresAt, now, now),
    ]);

    const resetUrl = `${env.VESSEL_AUTH_URL || ''}/reset-password?token=${token}`;

    if (env.RESEND_API_KEY) {
      try {
        await fetch('https://api.resend.com/emails', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${env.RESEND_API_KEY}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            from: 'VESSEL <noreply@vessel-dashboard.cloud-ip.cc>',
            to: user.email,
            subject: 'Reset your VESSEL password',
            html: `<p>Click the link below to reset your password:</p><p><a href="${resetUrl}">${resetUrl}</a></p>`,
          }),
        });
      } catch (err) {
        console.error('[VESSEL AUTH] Failed to send email via Resend:', err);
      }
    }

    console.log(`[VESSEL AUTH] Password reset token created for ${user.email}: ${resetUrl}`);

    return json({
      success: true,
      resetToken: token,
      resetUrl: `/reset-password?token=${token}`,
      message: 'Reset authorization link generated.',
    });
  } catch (err) {
    console.error('Password reset request failed:', err);
    return json({ error: 'Could not process reset request. Try again shortly.' }, 503);
  }
}
