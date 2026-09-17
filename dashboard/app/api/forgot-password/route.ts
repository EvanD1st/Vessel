import { env } from 'cloudflare:workers';
import { dashboardAuth } from '@/app/auth';
import { readBody, requestOrigin } from '@/lib/request-body';

export const dynamic = 'force-dynamic';

const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });

export async function POST(request: Request) {
  const url = new URL('/api/auth/forget-password', env.VESSEL_AUTH_URL);
  if (requestOrigin(request) !== url.origin)
    return json({ error: 'Invalid request origin.' }, 403);

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

  try {
    const headers = new Headers(request.headers);
    headers.delete('content-length');
    headers.set('content-type', 'application/json');
    if (url.protocol === 'http:') headers.set('cf-connecting-ip', '127.0.0.1');
    if (!headers.get('cf-connecting-ip')) headers.set('cf-connecting-ip', '0.0.0.0');

    await dashboardAuth().handler(
      new Request(url, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          email: (body.email as string).trim().toLowerCase(),
          redirectTo: '/reset-password',
        }),
      }),
    );

    // Always return a neutral success message to prevent user enumeration attacks
    return json({
      success: true,
      message: 'If an account exists with this email, a reset link has been dispatched.',
    });
  } catch {
    console.error('Password reset request failed');
    return json({ error: 'Could not process reset request. Try again shortly.' }, 503);
  }
}
