import { env } from 'cloudflare:workers';
import { dashboardAuth } from '@/app/auth';
import { readBody, requestOrigin } from '@/lib/request-body';

export const dynamic = 'force-dynamic';

const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });

export async function POST(request: Request) {
  const url = new URL('/api/auth/reset-password', env.VESSEL_AUTH_URL);
  if (requestOrigin(request) !== url.origin)
    return json({ error: 'Invalid request origin.' }, 403);

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

  try {
    const headers = new Headers(request.headers);
    headers.delete('content-length');
    headers.set('content-type', 'application/json');
    if (url.protocol === 'http:') headers.set('cf-connecting-ip', '127.0.0.1');
    if (!headers.get('cf-connecting-ip')) headers.set('cf-connecting-ip', '0.0.0.0');

    const response = await dashboardAuth().handler(
      new Request(url, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          token: (body.token as string).trim(),
          newPassword: body.password,
        }),
      }),
    );

    const out = new Headers(response.headers);
    out.set('Cache-Control', 'no-store');
    out.delete('content-length');

    if (!response.ok) {
      const err = (await response.json().catch(() => ({}))) as { message?: string; error?: string };
      return Response.json(
        {
          error:
            err.message ||
            err.error ||
            'The password reset token is invalid or has expired. Please request a new one.',
        },
        { status: response.status, headers: out },
      );
    }

    return Response.json(
      { success: true, message: 'Password has been updated successfully.' },
      { status: 200, headers: out },
    );
  } catch {
    console.error('Password reset execution failed');
    return json({ error: 'Could not reset password. Try again shortly.' }, 503);
  }
}
