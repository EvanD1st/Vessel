/**
 * The Node target is bound to loopback and reached only through Caddy. Caddy
 * replaces forwarding headers, allowing the original HTTPS origin to be used
 * for same-origin checks without trusting arbitrary internet headers.
 */
export function requestOrigin(request: Request): string {
  const direct = new URL(request.url).origin;
  if (typeof process === 'undefined' || process.env.VESSEL_TARGET !== 'node')
    return direct;
  const configured = process.env.VESSEL_AUTH_URL;
  if (!configured) return direct;
  const expected = new URL(configured);
  const proto = request.headers.get('x-forwarded-proto');
  const host = request.headers.get('x-forwarded-host');
  return proto === expected.protocol.slice(0, -1) && host === expected.host
    ? expected.origin
    : direct;
}

/** Small same-origin JSON mutations, with streaming body bounds. */
export async function readBody(
  request: Request,
): Promise<Record<string, unknown>> {
  if (request.headers.get('origin') !== requestOrigin(request))
    throw new Error('origin');
  if (request.headers.get('content-type')?.split(';')[0] !== 'application/json')
    throw new Error('json');
  const reader = request.body?.getReader();
  if (!reader) throw new Error('body');
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > 4096) {
        await reader.cancel();
        throw new Error('size');
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  const data: unknown = JSON.parse(new TextDecoder().decode(bytes));
  if (!data || typeof data !== 'object' || Array.isArray(data))
    throw new Error('shape');
  return data as Record<string, unknown>;
}
