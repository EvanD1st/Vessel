import * as vscode from 'vscode';
import { createHash } from 'crypto';
import * as path from 'path';
import * as fs from 'fs/promises';
import * as os from 'os';
import { PythonCli } from './pythonCli';
import { Compatibility } from './types';

/** Minimum Cline version VESSEL supports (inclusive). */
const MIN_CLINE_VERSION: readonly [number, number, number] = [4, 1, 17];

export function detectCline() {
    const extension = vscode.extensions.getExtension('saoudrizwan.claude-dev');
    return extension ? { installed: true, version: String(extension.packageJSON.version), extensionPath: extension.extensionPath }
        : { installed: false, version: undefined, extensionPath: undefined };
}
export function isSupportedClineVersion(version: string | undefined): boolean {
    if (!version) { return false; }
    const parts = version.split('.').map(Number);
    if (parts.some(isNaN)) { return false; }
    const [maj = 0, min = 0, patch = 0] = parts;
    const [rMaj, rMin, rPatch] = MIN_CLINE_VERSION;
    if (maj !== rMaj) { return maj > rMaj; }
    if (min !== rMin) { return min > rMin; }
    return patch >= rPatch;
}
export async function detectClineMcpConfig(): Promise<string | undefined> {
    const homedir = os.homedir();
    const candidates = [
        path.join(homedir, '.cline', 'data', 'settings', 'cline_mcp_settings.json'),
        path.join(process.env.APPDATA || '', 'Code', 'User', 'globalStorage', 'saoudrizwan.claude-dev', 'settings', 'cline_mcp_settings.json'),
        path.join(homedir, '.vscode', 'cline_mcp_settings.json')
    ];
    for (const candidate of candidates) {
        try {
            await fs.access(candidate);
            return candidate;
        } catch {
            // Not found or not accessible
        }
    }
    return undefined;
}
export function backupPath(storage: string, extension: string): string {
    return path.join(storage, 'compatibility', createHash('sha256').update(extension.toLowerCase()).digest('hex').slice(0, 24));
}
export async function inspectCline(cli: PythonCli): Promise<Compatibility | undefined> {
    const cline = detectCline();
    if (!cline.extensionPath) { return undefined; }
    return cli.request<Compatibility>('compatibility', { extension: cline.extensionPath, backup: backupPath(cli.storage, cline.extensionPath) });
}

