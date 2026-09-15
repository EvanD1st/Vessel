import { connectionDb } from '@/db';
import { accountSession } from '@/app/auth';
export const accountJson = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });
export async function activeAccount(request: Request, owner = false) {
  const session = await accountSession(request.headers);
  if (!session || session.user.banned) return null;
  if (
    owner &&
    (session.user.mustChangePassword ||
      session.user.role !== 'admin' ||
      Date.now() - session.session.createdAt.getTime() > 15 * 60 * 1000)
  )
    return null;
  return session;
}
// Single UPSERT: concurrent attempts cannot reuse a stale counter.
export async function allowAccountMutation(id: string) {
  const key = 'account-mutation:' + id;
  const now = Date.now();
  const result = await connectionDb()
    .prepare(`INSERT INTO rate_limit (id, key, count, last_request) VALUES (?, ?, 1, ?)
    ON CONFLICT(key) DO UPDATE SET count = CASE WHEN last_request <= ? THEN 1 ELSE count + 1 END,
    last_request = CASE WHEN last_request <= ? THEN excluded.last_request ELSE last_request END
    RETURNING count`)
    .bind(key, key, now, now - 60000, now - 60000)
    .first<{ count: number }>();
  return !!result && result.count <= 10;
}
