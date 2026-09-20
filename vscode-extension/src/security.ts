import { spawn } from 'child_process';
import * as fs from 'fs';

export class LocalError extends Error {
    constructor(public readonly code: string, message: string) { super(message); }
}

export function escapeHtml(value: unknown): string {
    return String(value ?? '').replace(/[&<>"']/g, character => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[character]!));
}

/** Subprocess stderr can contain secrets and must never become UI or log text. */
export function runProcess(executable: string, args: string[], options: {
    input?: string; timeout?: number; cwd?: string; env?: NodeJS.ProcessEnv; maxBytes?: number;
} = {}): Promise<string> {
    let resolvedExe = executable;
    if (process.platform === 'win32' && resolvedExe.toLowerCase().endsWith('python.exe')) {
        const w = resolvedExe.slice(0, -4) + 'w.exe';
        try {
            if (fs.existsSync(w)) {
                resolvedExe = w;
            }
        } catch {
            /* Keep original executable if check fails */
        }
    }
    return new Promise((resolve, reject) => {
        const child = spawn(resolvedExe, args, {
            shell: false, windowsHide: true, cwd: options.cwd,
            env: { ...process.env, PYTHONUTF8: '1', PYTHONNOUSERSITE: '1', ...options.env },
            stdio: ['pipe', 'pipe', 'pipe']
        });
        let output = '', bytes = 0, settled = false;
        const finish = (error?: LocalError) => {
            if (settled) { return; }
            settled = true; clearTimeout(timer);
            if (error) { child.kill(); reject(error); } else { resolve(output); }
        };
        const timer = setTimeout(() => finish(new LocalError('process_timeout', 'The local operation timed out. Inspect status before retrying.')), options.timeout ?? 30000);
        child.stdout.on('data', (chunk: Buffer) => {
            bytes += chunk.length;
            if (bytes > (options.maxBytes ?? 2 * 1024 * 1024)) {
                finish(new LocalError('output_limit', 'The local response exceeded its limit.'));
            } else { output += chunk.toString('utf8'); }
        });
        child.stderr.on('data', (chunk: Buffer) => {
            bytes += chunk.length;
            if (bytes > (options.maxBytes ?? 2 * 1024 * 1024)) {
                finish(new LocalError('output_limit', 'The local response exceeded its limit.'));
            }
        });
        child.on('error', () => finish(new LocalError('process_unavailable', 'The selected Python runtime could not start. Run setup again.')));
        child.on('close', code => finish(code === 0 ? undefined : new LocalError('process_failed', 'The local operation failed. Open the redacted diagnostic report.')));
        child.stdin.on('error', () => { /* close/error supplies the bounded result */ });
        child.stdin.end(options.input ?? '');
    });
}

export function safeError(error: unknown): string {
    return error instanceof LocalError ? error.message : 'The operation could not complete. Inspect VESSEL status and retry after resolving its blockers.';
}
