/** Small same-origin JSON mutations, with streaming body bounds. */
export async function readBody(
  request: Request,
): Promise<Record<string, unknown>> {
  if (request.headers.get('origin') !== new URL(request.url).origin)
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
