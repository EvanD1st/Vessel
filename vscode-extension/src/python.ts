import * as fs from 'fs/promises';
import * as path from 'path';
import { LocalError, runProcess } from './security';

export interface PythonInfo { executable: string; version: string; minor: number; arch: string; }

export async function parsePython(output: string): Promise<PythonInfo> {
    let value: { executable?: unknown; version?: unknown; arch?: unknown };
    try { value = JSON.parse(output); } catch { throw new LocalError('python_invalid', 'Python did not return a valid interpreter identity.'); }
    const version = typeof value.version === 'string' && /^(3)\.(\d+)\.(\d+)$/.exec(value.version);
    if (!version || Number(version[2]) < 11 || typeof value.executable !== 'string' ||
        !path.isAbsolute(value.executable) || /[\\/]WindowsApps[\\/]/i.test(value.executable) ||
        !(await fs.stat(value.executable)).isFile()) {
        throw new LocalError('python_unsupported', 'Python 3.11 or newer is required. Microsoft Store aliases are not interpreters.');
    }
    return { executable: await fs.realpath(value.executable), version: value.version as string,
        minor: Number(version[2]), arch: typeof value.arch === 'string' ? value.arch.toLowerCase() : '' };
}

export async function detectPython(): Promise<PythonInfo> {
    const candidates = process.platform === 'win32' ? [['pyw', '-3.11'], ['pyw', '-3.12'], ['pyw', '-3.13'], ['pyw', '-3.14'], ['pythonw'], ['py', '-3.11'], ['py', '-3.12'], ['py', '-3.13'], ['py', '-3.14'], ['python']] : [['python3']];
    const script = 'import sys,json,platform; print(json.dumps({"executable":sys.executable,"version":".".join(map(str,sys.version_info[:3])),"arch":platform.machine()}))';
    for (const [executable, ...prefix] of candidates) {
        try { return await parsePython(await runProcess(executable, [...prefix, '-I', '-c', script], { timeout: 5000, maxBytes: 65536 })); }
        catch { /* Try the next fixed candidate, never a workspace command. */ }
    }
    throw new LocalError('python_missing', 'Python 3.11 or newer is required to run the VESSEL companion.');
}
