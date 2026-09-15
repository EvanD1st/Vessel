import { headers } from 'next/headers';
import { env } from 'cloudflare:workers';
import { createAccountAuth } from '@/lib/account-auth';

export function dashboardAuth() {
  return createAccountAuth(env.DB, env.VESSEL_AUTH_SECRET, env.VESSEL_AUTH_URL);
}

export async function accountSession(requestHeaders: Headers) {
  return dashboardAuth().api.getSession({
    headers: requestHeaders,
    query: { disableCookieCache: true, disableRefresh: true },
  });
}

export async function getDashboardAuth() {
  const requestHeaders = await headers();
  const session = await accountSession(requestHeaders);
  const user =
    session && !session.user.banned
      ? {
          userId: session.user.id,
          email: session.user.email,
          displayName: session.user.name,
          role: session.user.role ?? 'user',
          mustChangePassword: session.user.mustChangePassword,
        }
      : null;
  return { user };
}

export async function getDashboardUser() {
  const { user } = await getDashboardAuth();
  return user?.mustChangePassword ? null : user;
}
