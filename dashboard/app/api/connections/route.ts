import { getDashboardUser } from '@/app/auth';
import { readBody } from '@/lib/request-body';
import { connectionDb } from '@/db';

export const dynamic = 'force-dynamic';
const json = (data: unknown, status = 200) =>
  Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });

export async function GET() {
  const user = await getDashboardUser();
  if (!user) return json({ error: 'Sign in to view saved connections.' }, 401);
  try {
    const result = await connectionDb()
      .prepare(
        'SELECT enrollment_id AS enrollmentId, label, port, updated_at AS updatedAt FROM connections WHERE owner_id = ? ORDER BY updated_at DESC LIMIT 20',
      )
      .bind(user.userId)
      .all();
    return json({ connections: result.results });
  } catch {
    return json(
      {
        error:
          'Saved connections are unavailable. Your local companion can still connect.',
      },
      503,
    );
  }
}

export async function POST(request: Request) {
  const user = await getDashboardUser();
  if (!user) return json({ error: 'Sign in to save a connection.' }, 401);
  let body: Record<string, unknown>;
  try {
    body = await readBody(request);
    if (
      Object.keys(body).some(
        (k) => !['enrollmentId', 'label', 'port'].includes(k),
      ) ||
      typeof body.enrollmentId !== 'string' ||
      !/^[a-zA-Z0-9_-]{8,128}$/.test(body.enrollmentId) ||
      typeof body.label !== 'string' ||
      !body.label.trim() ||
      body.label.length > 80 ||
      !Number.isInteger(body.port) ||
      Number(body.port) < 1024 ||
      Number(body.port) > 65535
    )
      throw new Error('fields');
  } catch {
    return json(
      {
        error:
          'Use a connection label, enrollment ID and valid local port from this workspace.',
      },
      400,
    );
  }
  try {
    const result = await connectionDb()
      .prepare(
        'INSERT INTO connections (owner_id, enrollment_id, label, port, updated_at) SELECT ?, ?, ?, ?, ? WHERE (SELECT COUNT(*) FROM connections WHERE owner_id = ?) < 20 OR EXISTS (SELECT 1 FROM connections WHERE owner_id = ? AND enrollment_id = ?) ON CONFLICT(owner_id, enrollment_id) DO UPDATE SET label = excluded.label, port = excluded.port, updated_at = excluded.updated_at',
      )
      .bind(
        user.userId,
        body.enrollmentId,
        (body.label as string).trim(),
        body.port,
        Date.now(),
        user.userId,
        user.userId,
        body.enrollmentId,
      )
      .run();
    if (!result.meta.changes)
      return json(
        {
          error:
            'This workspace supports 20 saved connection labels. Remove one to add another.',
        },
        409,
      );
    return json({ saved: true });
  } catch {
    return json(
      { error: 'Could not save this label. Local capture is unaffected.' },
      503,
    );
  }
}

export async function DELETE(request: Request) {
  const user = await getDashboardUser();
  if (!user)
    return json({ error: 'Sign in to remove a saved connection.' }, 401);
  let body: Record<string, unknown>;
  try {
    body = await readBody(request);
    if (
      Object.keys(body).length !== 1 ||
      typeof body.enrollmentId !== 'string' ||
      !/^[a-zA-Z0-9_-]{8,128}$/.test(body.enrollmentId)
    )
      throw new Error('id');
  } catch {
    return json({ error: 'Choose a saved connection in this workspace.' }, 400);
  }
  try {
    await connectionDb()
      .prepare(
        'DELETE FROM connections WHERE owner_id = ? AND enrollment_id = ?',
      )
      .bind(user.userId, body.enrollmentId)
      .run();
    return json({ removed: true });
  } catch {
    return json({ error: 'Could not remove the saved label.' }, 503);
  }
}
