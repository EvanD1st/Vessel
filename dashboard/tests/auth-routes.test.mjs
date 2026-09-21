import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import ts from 'typescript';

const source = readFileSync(
  new URL('../app/api/auth/[...all]/route.ts', import.meta.url),
  'utf8',
).replace(
  "import { dashboardAuth } from '@/app/auth';",
  'const dashboardAuth = () => ({ handler: async (request) => Response.json({ body: await request.text() }) });',
);
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { handleAuth } = await import(
  'data:text/javascript;base64,' + Buffer.from(compiled).toString('base64')
);

void test('direct auth POST forwards a streamed body on Node', async () => {
  const request = new Request('https://vessel.test.invalid/api/auth/sign-out', {
    method: 'POST',
    body: JSON.stringify({ example: true }),
  });
  const response = await handleAuth(request);
  assert.equal(response.status, 200);
  assert.equal((await response.json()).body, '{"example":true}');
});
