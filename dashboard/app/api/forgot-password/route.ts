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

    const authUrl =
      (typeof process !== 'undefined' ? process.env.VESSEL_AUTH_URL : undefined) ||
      env.VESSEL_AUTH_URL ||
      '';
    const resetUrl = `${authUrl}/reset-password?token=${token}`;

    const resendApiKey =
      (typeof process !== 'undefined' ? process.env.RESEND_API_KEY : undefined) ||
      env.RESEND_API_KEY;
    const resendFrom =
      (typeof process !== 'undefined' ? process.env.RESEND_FROM : undefined) ||
      env.RESEND_FROM ||
      'VESSEL <onboarding@resend.dev>';

    if (resendApiKey) {
      try {
        const emailRes = await fetch('https://api.resend.com/emails', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${resendApiKey}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            from: resendFrom,
            to: user.email,
            subject: 'Reset your VESSEL master password',
            html: `
              <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace; background-color: #0c1015; color: #e2e8f0; padding: 32px; border-radius: 8px; max-width: 540px; margin: 0 auto; border: 1px solid #1e293b;">
                <h2 style="color: #8bc6ad; margin-top: 0; letter-spacing: 1px;">VESSEL SECURITY // CIPHER RECOVERY</h2>
                <p style="color: #94a3b8; font-size: 14px; line-height: 1.6;">A master password reset was requested for operator account <strong>${user.email}</strong>.</p>
                <div style="margin: 28px 0; text-align: center;">
                  <a href="${resetUrl}" style="background-color: #8bc6ad; color: #0b1015; padding: 14px 28px; text-decoration: none; font-weight: bold; border-radius: 6px; display: inline-block; letter-spacing: 0.5px;">
                    RESET PASSWORD AUTHORIZATION &rarr;
                  </a>
                </div>
                <p style="color: #64748b; font-size: 12px; line-height: 1.5;">If you did not initiate this request, you can safely ignore this transmission. Your current password remains secure. This authorization link expires in 1 hour.</p>
                <hr style="border: 0; border-top: 1px solid #1e293b; margin: 24px 0;" />
                <p style="color: #475569; font-size: 11px; word-break: break-all;">Fallback URL: ${resetUrl}</p>
              </div>
            `,
          }),
        });
        if (!emailRes.ok) {
          const errData = await emailRes.text();
          console.error('[VESSEL AUTH] Resend API error:', errData);
        } else {
          console.log(`[VESSEL AUTH] Password reset email dispatched to ${user.email}`);
        }
      } catch (err) {
        console.error('[VESSEL AUTH] Failed to send email via Resend:', err);
      }
    }

    return json({
      success: true,
      message: 'If an account exists with this email, a reset authorization link has been dispatched to your inbox.',
    });
  } catch (err) {
    console.error('Password reset request failed:', err);
    return json({ error: 'Could not process reset request. Try again shortly.' }, 503);
  }
}
