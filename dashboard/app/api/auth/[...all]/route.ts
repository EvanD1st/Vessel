import { dashboardAuth } from '@/app/auth';

export function handleAuth(req: Request) {
  const operation = new URL(req.url).pathname.split('/api/auth/')[1] || '';
  const allowed = [
    'sign-in/email',
    'sign-up/email',
    'get-session',
    'sign-out',
    'change-password',
    'forget-password',
    'reset-password',
  ];
  if (!allowed.includes(operation) && !operation.startsWith('reset-password/')) {
    return Response.json({ error: 'This dashboard is invite-only.' }, { status: 404 });
  }
  const headers = new Headers(req.headers);
  // Caddy overwrites this header with the remote address. Missing edge metadata
  // shares one rate bucket; it never disables login limits.
  if (!headers.get('cf-connecting-ip')) headers.set('cf-connecting-ip', '0.0.0.0');
  const init: RequestInit & { duplex?: 'half' } = {
    method: req.method,
    headers,
  };
  if (req.body && req.method !== 'GET' && req.method !== 'HEAD') {
    init.body = req.body;
    init.duplex = 'half';
  }
  return dashboardAuth().handler(new Request(req.url, init));
}

export const GET = handleAuth;
export const POST = handleAuth;
