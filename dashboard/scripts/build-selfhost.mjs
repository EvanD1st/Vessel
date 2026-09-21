import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { copyFile, cp, mkdir, rm, writeFile } from 'node:fs/promises';

// Vinext records public paths at build time. CI replaces this marker with the
// tested VSIX after the parallel extension job completes.
const download = resolve('public/downloads/vessel.vsix');
const createdMarker = !existsSync(download);
if (createdMarker) {
  await mkdir(resolve('public/downloads'), { recursive: true });
  await writeFile(download, 'VSIX is staged with the tested release.');
}
let result;
try {
  result = spawnSync(process.execPath, [resolve('node_modules/vinext/dist/cli.js'), 'build'], {
    stdio: 'inherit', env: { ...process.env, VESSEL_TARGET: 'node' }, timeout: 240000,
  });
} finally {
  if (createdMarker) await rm(download, { force: true });
}
if (result.error) throw result.error;
if (result.status !== 0) process.exit(result.status ?? 1);
const releaseScripts = resolve('dist/standalone/scripts');
await mkdir(releaseScripts, { recursive: true });
for (const name of ['migrate-selfhost.py', 'bootstrap-selfhost.mjs']) {
  await copyFile(resolve('scripts', name), resolve(releaseScripts, name));
}
await cp(resolve('drizzle'), resolve('dist/standalone/drizzle'), { recursive: true });
