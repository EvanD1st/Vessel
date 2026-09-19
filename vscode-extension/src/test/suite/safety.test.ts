import * as assert from 'assert';
import * as fs from 'fs/promises';
import * as os from 'os';
import * as path from 'path';
import * as vscode from 'vscode';
import { parsePython } from '../../python';
import { initialState, secretId, validateState } from '../../onboarding';
import { protectionState, diagnostics } from '../../status';
import { escapeHtml, runProcess, safeError } from '../../security';
import { htmlDocument } from '../../webview';
import { Snapshot, Compatibility } from '../../types';
import { Controller } from '../../extension';
import { PythonCli } from '../../pythonCli';

suite('Safety boundaries', () => {
    const compatibility = { supported: true, state: 'patched' } as Compatibility;
    const healthy = (): Snapshot => ({
        policy: { mission: 'private mission', revision: 2, allowed_models: [] }, policy_revision: 2,
        lease: { status: 'active', holder_run_id: 'native-run', execution_epoch: 1, policy_revision: 2 }, lease_stale: false,
        capture: { state: 'healthy', gaps: [], last_observation: 1 }, configuration: { installed: true },
        companion: { running: true, status: 'ready' }, bridge: { capture_worker_running: true, worker_error: null },
        gateway: { running: true, status: 'ready', credential_version: 'v1' },
        gateway_config: { paused: false, verified_at: 1, credential_version: 'v1', port: 8091, models: [] },
        checkpoints: [{ id: 'checkpoint', run_id: 'old-run', created_at: 1, validation: { eligible: true, blockers: [] } }],
        sessions: [], runs: [], tasks: [], recoveries: [], operations: [], enrollment: { id: 'id', workspace: 'private-path' }
    });
    test('Protection requires current processes, compatibility and native evidence', () => {
        assert.equal(protectionState(healthy(), compatibility, true), 'Protected');
        for (const mutate of [
            (s: Snapshot) => { s.bridge.capture_worker_running = false; },
            (s: Snapshot) => { s.lease_stale = true; },
            (s: Snapshot) => { s.capture.state = 'unknown'; },
            (s: Snapshot) => { s.checkpoints = []; },
            (s: Snapshot) => { s.gateway.credential_version = 'old'; },
            (s: Snapshot) => { s.lease = null; },
        ]) { const state = healthy(); mutate(state); assert.notEqual(protectionState(state, compatibility, true), 'Protected'); }
        assert.equal(protectionState(healthy(), { ...compatibility, supported: false }, true), 'Unsupported Cline');
        const paused = healthy(); paused.gateway_config!.paused = true;
        assert.equal(protectionState(paused, compatibility, true), 'Paused');
    });
    test('Diagnostics exclude paths, task contents, keys and owner request bodies', () => {
        const state = initialState('private-path'); state.credentialVersion = 'a'.repeat(32);
        const output = JSON.stringify(diagnostics(state, healthy(), compatibility));
        for (const secret of ['private-path', 'private mission', 'native-run', 'a'.repeat(32)]) assert.ok(!output.includes(secret));
    });
    test('Persisted setup is scoped and invalid state does not resume', () => {
        const state = initialState('project-a'); state.steps.requirements = 'passed';
        assert.deepEqual(validateState(state, 'project-a'), state);
        assert.equal(validateState(state, 'project-b'), undefined);
        assert.equal(validateState({ ...state, schema: 2 }, 'project-a'), undefined);
        assert.equal(validateState({ ...state, credentialVersion: 'plaintext-key' }, 'project-a'), undefined);
        assert.notEqual(secretId('project-a', '1'), secretId('project-b', '1'));
    });
    test('Interpreter identity rejects old versions, aliases and malformed results', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'vessel-python-'));
        const exe = path.join(dir, 'python.exe'); await fs.writeFile(exe, 'fixture');
        try {
            assert.equal((await parsePython(JSON.stringify({ executable: exe, version: '3.11.9', arch: 'AMD64' }))).minor, 11);
            for (const value of ['not JSON', JSON.stringify({ executable: exe, version: '3.10.9' }), JSON.stringify({ executable: exe, version: '4.0.0' }), JSON.stringify({ executable: 'python', version: '3.11.1' })]) {
                await assert.rejects(parsePython(value));
            }
        } finally { await fs.rm(dir, { recursive: true, force: true }); }
    });
    test('Webview content is escaped and scripts require a nonce', () => {
        const injection = '<img src=x onerror="steal()">';
        const html = htmlDocument('Review', escapeHtml(injection), true);
        assert.ok(!html.includes(injection)); assert.ok(html.includes('&lt;img'));
        assert.ok(html.includes("default-src 'none'")); assert.ok(html.includes('script-src'));
        assert.ok(!html.includes('unsafe-inline')); assert.ok(!html.includes('http-equiv="refresh"'));
        assert.ok(!safeError(new Error('private-key')).includes('private-key'));
    });
    test('Subprocess timeout and output limits never expose stderr', async function () {
        this.timeout(15000);
        // Electron's executable exposes a Node runtime only for this disposable test.
        const env = { ELECTRON_RUN_AS_NODE: '1' };
        await assert.rejects(runProcess(process.execPath, ['-e', 'process.stderr.write("private-key");process.exit(1)'], { env }), error => !String(error).includes('private-key'));
        await assert.rejects(runProcess(process.execPath, ['-e', 'process.stdout.write("x".repeat(5000))'], { env, maxBytes: 100 }), /exceeded/);
        await assert.rejects(runProcess(process.execPath, ['-e', 'setInterval(()=>{},100)'], { env, timeout: 100 }), /timed out/);
    });
    test('Every contributed command registers in the real extension host', async () => {
        const extension = vscode.extensions.getExtension('n3ythrax.vessel-companion')!; await extension.activate();
        const commands = await vscode.commands.getCommands(true);
        for (const command of extension.packageJSON.contributes.commands) assert.ok(commands.includes(command.command), command.command);
    });
    test('Key verification failure cannot persist a credential', async () => {
        const saved: unknown[] = [], secrets: string[] = [];
        const context = { globalState: { get: () => undefined, update: async (_key: string, value: unknown) => { saved.push(value); } },
            secrets: { store: async (_key: string, value: string) => { secrets.push(value); } } } as unknown as vscode.ExtensionContext;
        const app = new Controller(context);
        const input = vscode.window.showInputBox, warning = vscode.window.showWarningMessage;
        try {
            Object.assign(vscode.window, { showInputBox: async () => 'test-only-private-key', showWarningMessage: async () => 'Verify and save' });
            const state = initialState('workspace');
            const cli = { request: async () => { throw new Error('provider failed'); } } as unknown as PythonCli;
            await assert.rejects(app.collectKey(state, cli));
            assert.equal(secrets.length, 0); assert.equal(saved.length, 0); assert.equal(state.credentialVersion, undefined);
            const requests: Array<{ method: string; params: any }> = [];
            const valid = { request: async (method: string, params: any) => { requests.push({ method, params }); return { verified_at: 1 }; } } as unknown as PythonCli;
            assert.equal(await app.collectKey(state, valid), true);
            assert.ok(requests.some(r => r.method === 'orbio-migrate-key' && r.params.key === 'test-only-private-key'));
            assert.ok(!JSON.stringify(saved).includes('test-only-private-key'));
            assert.equal(state.credentialVersion !== undefined, true);
            Object.assign(vscode.window, { showWarningMessage: async () => undefined });
            assert.equal(await app.collectKey(state, valid), false);
        } finally { Object.assign(vscode.window, { showInputBox: input, showWarningMessage: warning }); app.dispose(); }
    });
});
