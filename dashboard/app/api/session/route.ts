import { env } from 'cloudflare:workers';
import { dashboardAuth } from '@/app/auth';
import { readBody } from '@/lib/request-body';
export const dynamic = 'force-dynamic';
const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });

// Only these operations are exposed: no public signup or raw plugin admin API.
async function sessionRequest(
  request: Request,
  operation: string,
  body?: Record<string, unknown>,
) {
  const url = new URL('/api/auth/' + operation, env.VESSEL_AUTH_URL);
  if (new URL(request.url).origin !== url.origin)
    return json({ error: 'Invalid request origin.' }, 403);
  const headers = new Headers(request.headers);
  headers.delete('content-length');
  if (body) headers.set('content-type', 'application/json');
  if (url.protocol === 'http:') headers.set('cf-connecting-ip', '127.0.0.1');
  // Missing edge metadata must not silently disable the login limiter.
  if (!headers.get('cf-connecting-ip')) headers.set('cf-connecting-ip', '0.0.0.0');
  const response = await dashboardAuth().handler(
    new Request(url, {
      method: operation === 'get-session' ? 'GET' : 'POST',
      headers,
      ...(body ? { body: JSON.stringify(body) } : {}),
    }),
  );
  const out = new Headers(response.headers);
  out.set('Cache-Control', 'no-store');
  out.delete('content-length');
  if (!response.ok) {
    await response.text();
    return Response.json(
      {
        error:
          response.status === 429
            ? 'Too many attempts. Wait a minute and try again.'
            : 'Email or password is incorrect, or this account is disabled.',
      },
      { status: response.status, headers: out },
    );
  }
  const data = (await response.json()) as {
    user?: {
      id: string;
      email: string;
      name: string;
      role?: string;
      mustChangePassword: boolean;
      banned?: boolean;
    };
  } | null;
  return Response.json(
    operation === 'get-session'
      ? {
          user:
            data?.user && !data.user.banned
              ? {
                  userId: data.user.id,
                  email: data.user.email,
                  displayName: data.user.name,
                  role: data.user.role ?? 'user',
                  mustChangePassword: data.user.mustChangePassword,
                }
              : null,
        }
      : { signedIn: operation !== 'sign-out' },
    { headers: out },
  );
}
export async function GET(request: Request) {
  try {
    return await sessionRequest(request, 'get-session');
  } catch {
    console.error('Account session storage failed');
    return json(
      { error: 'Account storage is unavailable. Try again shortly.' },
      503,
    );
  }
}
export async function POST(request: Request) {
  let body: Record<string, unknown>;
  try {
    body = await readBody(request);
    if (
      Object.keys(body).some((k) => !['email', 'password'].includes(k)) ||
      typeof body.email !== 'string' ||
      body.email.length > 254 ||
      typeof body.password !== 'string' ||
      body.password.length > 128
    )
      throw new Error('fields');
  } catch {
    return json(
      { error: 'Enter a valid email and password from this site.' },
      400,
    );
  }
  try {
    return await sessionRequest(request, 'sign-in/email', {
      ...body,
      email: (body.email as string).trim().toLowerCase(),
    });
  } catch {
    console.error('Account login storage failed');
    return json({ error: 'Sign-in is temporarily unavailable.' }, 503);
  }
}
export async function DELETE(request: Request) {
  if (request.headers.get('origin') !== new URL(request.url).origin)
    return json({ error: 'Invalid request origin.' }, 403);
  try {
    return await sessionRequest(request, 'sign-out', {});
  } catch {
    return json({ error: 'Could not sign out. Try again.' }, 503);
  }
}
