import { betterAuth } from 'better-auth/minimal';
import { env } from 'cloudflare:workers';
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
      minPasswordLength: 8,
      maxPasswordLength: 128,
      requireEmailVerification: false,
      async sendResetPassword({ user, url }) {
        if (env.RESEND_API_KEY) {
          try {
            await fetch('https://api.resend.com/emails', {
              method: 'POST',
              headers: {
                'Authorization': `Bearer ${env.RESEND_API_KEY}`,
                'Content-Type': 'application/json'
              },
              body: JSON.stringify({
                from: 'VESSEL <noreply@vessel-dashboard.cloud-ip.cc>',
                to: user.email,
                subject: 'Reset your VESSEL password',
                html: `<p>Click the link below to reset your password:</p><p><a href="${url}">${url}</a></p>`
              })
            });
          } catch (err) {
            console.error('[VESSEL AUTH] Failed to send reset email via Resend:', err);
          }
        }
        console.log(`[VESSEL AUTH] Password reset link for ${user.email}: ${url}`);
      },
    },
    emailVerification: {
      sendOnSignUp: false,
      async sendVerificationEmail({ user, url }) {
        await fetch('https://api.resend.com/emails', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${env.RESEND_API_KEY}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            from: 'VESSEL <noreply@vessel-dashboard.cloud-ip.cc>',
            to: user.email,
            subject: 'Verify your VESSEL account',
            html: `<p>Welcome to VESSEL! Click the link below to verify your email:</p><p><a href="${url}">${url}</a></p>`
          })
        });
      },
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
          defaultValue: false,
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
