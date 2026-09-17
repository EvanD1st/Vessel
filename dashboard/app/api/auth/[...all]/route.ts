import { dashboardAuth } from '@/app/auth';

export function handleAuth(req: Request) {
  const operation = new URL(req.url).pathname.split('/api/auth/')[1];
  if (!['sign-in/email', 'sign-up/email', 'get-session', 'sign-out', 'change-password'].includes(operation)) {
    return Response.json({ error: 'This dashboard is invite-only.' }, { status: 404 });
  }
  const headers = new Headers(req.headers);
  // Caddy overwrites this header with the remote address. Missing edge metadata
  // shares one rate bucket; it never disables login limits.
  if (!headers.get('cf-connecting-ip')) headers.set('cf-connecting-ip', '0.0.0.0');
  return dashboardAuth().handler(new Request(req.url, {
    method: req.method,
    headers,
    body: req.body
  }));
}

export const GET = handleAuth;
export const POST = handleAuth;
