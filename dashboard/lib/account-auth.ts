import { betterAuth } from 'better-auth/minimal';
import { admin } from 'better-auth/plugins/admin';
import { drizzleAdapter } from '@better-auth/drizzle-adapter';
import { drizzle } from 'drizzle-orm/d1';
import * as schema from '../db/schema';

export function createAccountAuth(
  db: D1Database,
  secret: string,
  baseURL: string,
) {
  const origin = new URL(baseURL);
  if (
    origin.origin !== baseURL ||
    (origin.protocol !== 'https:' &&
      !/^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(baseURL))
  )
    throw new Error(
      'Set VESSEL_AUTH_URL to the exact HTTPS origin (HTTP is loopback-only).',
    );
  if (!secret || secret.length < 32)
    throw new Error(
      'Set a private VESSEL_AUTH_SECRET of at least 32 characters.',
    );
  return betterAuth({
    appName: 'VESSEL',
    baseURL,
    secret,
    database: drizzleAdapter(drizzle(db, { schema }), {
      provider: 'sqlite',
      schema,
      transaction: false,
    }),
    trustedOrigins: [baseURL],
    emailAndPassword: {
      enabled: true,
      disableSignUp: true,
      minPasswordLength: 12,
      maxPasswordLength: 128,
    },
    session: {
      expiresIn: 60 * 60 * 24 * 7,
      updateAge: 60 * 60 * 24,
      cookieCache: { enabled: false },
    },
    user: {
      additionalFields: {
        mustChangePassword: {
          type: 'boolean',
          defaultValue: true,
          input: false,
        },
      },
    },
    advanced: {
      cookiePrefix: 'vessel',
      useSecureCookies: origin.protocol === 'https:',
      defaultCookieAttributes: {
        httpOnly: true,
        sameSite: 'strict',
        path: '/',
      },
      // Only the hosting edge may supply this header. Local requests use a fixed
      // address in our route wrapper, ignoring client-supplied forwarding headers.
      ipAddress: { ipAddressHeaders: ['cf-connecting-ip'] },
    },
    rateLimit: {
      enabled: true,
      storage: 'database',
      window: 60,
      max: 100,
      customRules: { '/sign-in/email': { window: 60, max: 5 } },
    },
    plugins: [admin({ defaultRole: 'user', adminRoles: ['admin'] })],
  });
}
