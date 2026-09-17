import * as vscode from 'vscode';
import { createHash } from 'crypto';
import * as path from 'path';
import { PythonCli } from './pythonCli';
import { Compatibility } from './types';

export function detectCline() {
    const extension = vscode.extensions.getExtension('saoudrizwan.claude-dev');
    return extension ? { installed: true, version: String(extension.packageJSON.version), extensionPath: extension.extensionPath }
        : { installed: false, version: undefined, extensionPath: undefined };
}
export function backupPath(storage: string, extension: string): string {
    return path.join(storage, 'compatibility', createHash('sha256').update(extension.toLowerCase()).digest('hex').slice(0, 24));
}
export async function inspectCline(cli: PythonCli): Promise<Compatibility | undefined> {
    const cline = detectCline();
    if (!cline.extensionPath) { return undefined; }
    return cli.request<Compatibility>('compatibility', { extension: cline.extensionPath, backup: backupPath(cli.storage, cline.extensionPath) });
}
