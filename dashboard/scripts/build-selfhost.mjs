import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { copyFile, mkdir } from 'node:fs/promises';

const result = spawnSync(process.execPath, [resolve('node_modules/vinext/dist/cli.js'), 'build'], {
  stdio: 'inherit', env: { ...process.env, VESSEL_TARGET: 'node' }, timeout: 240000,
});
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
const releaseScripts = resolve('dist/standalone/scripts');
await mkdir(releaseScripts, { recursive: true });
for (const name of ['migrate-selfhost.py', 'bootstrap-selfhost.mjs']) {
  await copyFile(resolve('scripts', name), resolve(releaseScripts, name));
}
