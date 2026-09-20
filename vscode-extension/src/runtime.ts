import * as fs from 'fs/promises';
import * as path from 'path';
import * as vscode from 'vscode';
import { PythonInfo } from './python';
import { LocalError, runProcess } from './security';

export interface RuntimeRecord { schema: 1; python: string; generation: string; python_version: string; version: string; healthy: boolean; }

export class RuntimeManager {
    constructor(private readonly context: vscode.ExtensionContext) {}
    async current(): Promise<RuntimeRecord | undefined> {
        try {
            const value = JSON.parse(await fs.readFile(path.join(this.context.globalStorageUri.fsPath, 'runtime.json'), 'utf8')) as RuntimeRecord;
            const relative = path.relative(path.join(this.context.globalStorageUri.fsPath, 'runtimes'), value.python);
            if (value.schema !== 1 || !value.healthy || relative.startsWith('..') || path.isAbsolute(relative) || !(await fs.stat(value.python)).isFile()) { return undefined; }
            if (process.platform === 'win32' && value.python.toLowerCase().endsWith('python.exe')) {
                const w = value.python.slice(0, -4) + 'w.exe';
                try {
                    if ((await fs.stat(w)).isFile()) {
                        value.python = w;
                    }
                } catch {
                    /* keep original if pythonw.exe is not found */
                }
            }
            return value;
        } catch { return undefined; }
    }
    async ensure(python: PythonInfo): Promise<RuntimeRecord> {
        const bootstrap = path.join(this.context.extensionUri.fsPath, 'scripts', 'bootstrap.py');
        const result = JSON.parse(await runProcess(python.executable, ['-I', bootstrap, this.context.globalStorageUri.fsPath], { timeout: 420000 })) as { ok: boolean; code?: string; runtime?: RuntimeRecord };
        if (!result.ok || !result.runtime) {
            throw new LocalError(result.code ?? 'runtime_install_failed', result.code === 'runtime_platform_unsupported'
                ? 'This VSIX contains offline runtimes for Windows x64 and the Python versions listed in its README. Install a supported Python version and check again.'
                : 'The isolated runtime could not be verified. The previous runtime was preserved. Retry setup or reinstall the VSIX.');
        }
        return result.runtime;
    }
}
