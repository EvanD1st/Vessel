import * as vscode from 'vscode';
import { Compatibility, SetupState, Snapshot } from './types';
import { escapeHtml } from './security';
import { htmlDocument } from './webview';

export function protectionState(snapshot?: Snapshot, compatibility?: Compatibility, configured = false): string {
    if (!configured || !snapshot) { return 'Setup required'; }
    if (!compatibility?.supported || compatibility.state !== 'patched') { return 'Unsupported Cline'; }
    if (snapshot.gateway_config?.paused || snapshot.lease?.status === 'paused') { return 'Paused'; }
    if (!snapshot.companion.running || snapshot.companion.status !== 'ready') { return 'Companion offline'; }
    if (snapshot.capture.state === 'degraded' || snapshot.capture.gaps.length || !snapshot.configuration.installed || snapshot.bridge?.worker_error) { return 'Capture degraded'; }
    if (snapshot.capture.state !== 'healthy' || snapshot.lease_stale || !snapshot.gateway.running ||
        snapshot.gateway.status !== 'ready' || !snapshot.bridge?.capture_worker_running || !snapshot.gateway_config?.verified_at ||
        !snapshot.lease || snapshot.lease.status !== 'active' || snapshot.gateway.credential_version !== snapshot.gateway_config.credential_version ||
        !snapshot.checkpoints.some(cp => cp.validation.eligible)) { return 'Setup required'; }
    return 'Protected';
}

export function diagnostics(state: SetupState | undefined, snapshot: Snapshot | undefined, compatibility: Compatibility | undefined,
    pythonVersion?: string) {
    return { schema: 1, extensionVersion: '0.3.2', packageVersion: '0.5.0', vscodeVersion: vscode.version,
        platform: process.platform, architecture: process.arch, pythonVersion: pythonVersion ?? 'unknown', pythonLocation: 'extension-managed',
        clineVersion: compatibility?.version ?? 'missing', clineMode: compatibility?.mode ?? 'unknown',
        clineBundleHash: compatibility?.bundle_sha256 ?? null, steps: state?.steps ?? {},
        companion: snapshot?.companion.status ?? 'stopped', capture: snapshot?.capture.state ?? 'unknown',
        gateway: snapshot?.gateway.status ?? 'stopped', errorCode: state?.errorCode ?? null };
}

const actions: Record<string, string> = {
    'Set up / retry': 'vessel.setup', 'Bind observed Cline task': 'vessel.bindSession',
    'Configure Cline inference': 'vessel.configureCline', 'Create checkpoint': 'vessel.createCheckpoint',
    'Recover task': 'vessel.recoverTask', 'Confirm continuation': 'vessel.confirmRecovery',
    'Record task': 'vessel.manageTasks', 'Pause protection': 'vessel.pauseProtection',
    'Resume protection': 'vessel.resumeProtection', 'Refresh': 'vessel.showStatus',
    'Diagnostics': 'vessel.openDiagnostic'
};

export class VesselStatusManager implements vscode.Disposable {
    private bar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    private panel?: vscode.WebviewPanel;
    constructor() { this.bar.command = 'vessel.showStatus'; this.update('Setup required'); }
    update(state: string): void { this.bar.text = `${state === 'Protected' ? '$(shield)' : '$(info)'} VESSEL: ${state}`; this.bar.show(); }
    show(snapshot: Snapshot | undefined, state: SetupState | undefined, compatibility: Compatibility | undefined): void {
        if (!this.panel) {
            this.panel = vscode.window.createWebviewPanel('vesselStatus', 'VESSEL Status & Recovery', vscode.ViewColumn.One,
                { enableScripts: true, localResourceRoots: [] });
            this.panel.onDidDispose(() => { this.panel = undefined; });
            this.panel.webview.onDidReceiveMessage((message: { action?: string }) => {
                if (Object.values(actions).includes(message?.action ?? '')) { void vscode.commands.executeCommand(message.action!); }
            });
        }
        this.panel.reveal();
        const status = protectionState(snapshot, compatibility, state?.configured);
        const list = (values: string[]) => `<ul>${values.map(value => `<li>${escapeHtml(value)}</li>`).join('')}</ul>`;
        const tasks = snapshot?.tasks.filter(task => task.run_id === snapshot.lease?.holder_run_id) ?? [];
        const currentRun = snapshot?.runs.find(run => run.id === snapshot.lease?.holder_run_id);
        const body = `<h1>VESSEL: ${escapeHtml(status)}</h1><p>${escapeHtml(state?.workspace ?? 'Select a workspace to begin.')}</p>
<p class="notice">Configuration checks and native recovery evidence are separate. A recovery succeeds only after reviewed destination activity. VESSEL never replays uncertain tools.</p>
<h2>Current mission</h2><p>${escapeHtml(snapshot?.policy.mission ?? 'Not enrolled')}</p>
<dl><dt>Cline conversation</dt><dd>${escapeHtml(currentRun?.native_session_id ?? 'No observed task bound')}</dd><dt>Capture</dt><dd>${escapeHtml(snapshot?.capture.state ?? 'pending')}</dd><dt>Companion</dt><dd>${escapeHtml(snapshot?.companion.status ?? 'stopped')}</dd><dt>Gateway</dt><dd>${escapeHtml(snapshot?.gateway_config?.paused ? 'paused' : snapshot?.gateway.status ?? 'stopped')}</dd></dl>
<h2>Setup checks</h2>${list(Object.entries(state?.steps ?? {}).map(([step, value]) => `${step}: ${value}`))}
<h2>Completed work</h2>${list(tasks.filter(task => task.status === 'done').map(task => task.description))}
<h2>Unfinished work</h2>${list(tasks.filter(task => task.status !== 'done').map(task => `${task.status}: ${task.description}`))}
<h2>Capture blockers</h2>${list(snapshot?.capture.gaps ?? [])}
<h2>Checkpoints</h2>${list((snapshot?.checkpoints ?? []).map(cp => `${cp.id}: ${cp.validation.eligible ? 'integrity checks passed' : cp.validation.blockers.join(', ')}`))}
<h2>Recoveries</h2>${list((snapshot?.recoveries ?? []).map(recovery => `${recovery.id} → ${recovery.destination_session}: ${recovery.status}${recovery.continuation ? ' · observed operation ' + recovery.continuation.operation_id : ''}${recovery.preflight.blockers.length ? ' · ' + recovery.preflight.blockers.join(', ') : ''}`))}
<p>For first capture, enable Cline hooks, reload VS Code while Cline is idle, send a READY-only probe, bind its observed task here, then send a second probe in the same task.</p>
${Object.entries(actions).map(([label, action]) => `<button data-action="${action}">${escapeHtml(label)}</button>`).join('')}`;
        this.panel.webview.html = htmlDocument('VESSEL Status & Recovery', body, true);
        this.update(status);
    }
    dispose(): void { this.bar.dispose(); this.panel?.dispose(); }
}
