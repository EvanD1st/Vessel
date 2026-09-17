import { env } from 'cloudflare:workers';
import { dashboardAuth } from '@/app/auth';
import { readBody, requestOrigin } from '@/lib/request-body';

export const dynamic = 'force-dynamic';

const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });

export async function POST(request: Request) {
  const url = new URL('/api/auth/sign-up/email', env.VESSEL_AUTH_URL);
  if (requestOrigin(request) !== url.origin)
    return json({ error: 'Invalid request origin.' }, 403);

  let body: Record<string, unknown>;
  try {
    body = await readBody(request);
    if (
      Object.keys(body).some((k) => !['name', 'email', 'password'].includes(k)) ||
      typeof body.name !== 'string' ||
      !body.name.trim() ||
      body.name.trim().length > 80 ||
      typeof body.email !== 'string' ||
      body.email.length > 254 ||
      !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(body.email.trim()) ||
      typeof body.password !== 'string' ||
      body.password.length < 8 ||
      body.password.length > 128
    ) {
      throw new Error('fields');
    }
  } catch {
    return json(
      { error: 'Provide a valid name, email, and password (minimum 8 characters).' },
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
          name: (body.name as string).trim(),
          email: (body.email as string).trim().toLowerCase(),
          password: body.password,
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
            response.status === 429
              ? 'Too many registration attempts. Please wait a moment and try again.'
              : err.message || err.error || 'Could not register account. Email may already be registered.',
        },
        { status: response.status, headers: out },
      );
    }

    return Response.json({ success: true }, { status: 201, headers: out });
  } catch {
    console.error('Registration failed');
    return json({ error: 'Registration is temporarily unavailable.' }, 503);
  }
}
