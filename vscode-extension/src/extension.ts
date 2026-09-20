import * as vscode from 'vscode';
import * as path from 'path';
import { randomUUID } from 'crypto';
import { detectPython } from './python';
import { PythonCli, JsonObject } from './pythonCli';
import { RuntimeManager } from './runtime';
import { OnboardingWizard, secretId } from './onboarding';
import { backupPath, detectCline, detectClineMcpConfig, inspectCline, isSupportedClineVersion } from './cline';
import { OnboardingWebviewProvider, review } from './webview';
import { diagnostics, protectionState, VesselStatusManager } from './status';
import { Plan, Recovery, SetupState, Snapshot } from './types';
import { LocalError, safeError } from './security';

const id = () => randomUUID().replace(/-/g, '');
let controller: Controller | undefined;

export class Controller implements vscode.Disposable {
    readonly wizard: OnboardingWizard;
    readonly runtime: RuntimeManager;
    readonly status = new VesselStatusManager();
    private timer?: NodeJS.Timeout;
    private busy = false;
    private output = vscode.window.createOutputChannel('VESSEL');
    private lastError?: string;
    constructor(readonly context: vscode.ExtensionContext) {
        this.wizard = new OnboardingWizard(context); this.runtime = new RuntimeManager(context);
    }
    guard(): void {
        if (!vscode.workspace.isTrusted) { throw new LocalError('workspace_untrusted', 'Trust this workspace before configuring or controlling local VESSEL processes.'); }
        if (process.platform !== 'win32' || process.arch !== 'x64' || vscode.env.remoteName) {
            throw new LocalError('platform_unsupported', 'This release supports local Windows x64 VS Code only. Remote and other platforms are not verified.');
        }
    }
    async execute(operation: () => Promise<void>): Promise<void> {
        if (this.busy) { void vscode.window.showInformationMessage('Another VESSEL operation is in progress.'); return; }
        this.busy = true;
        try { this.guard(); await operation(); }
        catch (error) {
            this.lastError = error instanceof LocalError ? error.code : 'local_operation_failed';
            this.output.appendLine(`${new Date().toISOString()} ${this.lastError}`);
            void vscode.window.showErrorMessage(safeError(error));
        } finally { this.busy = false; await this.refresh(false); }
    }
    async client(): Promise<PythonCli> {
        const runtime = await this.runtime.current();
        if (!runtime) { throw new LocalError('setup_required', 'Run Set Up VESSEL to prepare its isolated Python runtime.'); }
        return new PythonCli(runtime.python, this.context.globalStorageUri.fsPath);
    }
    selected(): string {
        const workspace = this.wizard.selected();
        if (!workspace) { throw new LocalError('workspace_missing', 'Run Set Up VESSEL and explicitly select one open project.'); }
        return workspace;
    }
    async snapshot(): Promise<Snapshot> { return (await this.client()).request<Snapshot>('status', { workspace: this.selected() }); }
    async refresh(show: boolean): Promise<void> {
        const workspace = this.wizard.selected();
        if (!workspace || !vscode.workspace.isTrusted) { if (show) { this.status.show(undefined, undefined, undefined); } return; }
        const state = this.wizard.load(workspace);
        try {
            const cli = await this.client();
            const snapshot = await cli.request<Snapshot>('status', { workspace });
            const compatibility = await inspectCline(cli);
            const verified = snapshot.configuration.installed && compatibility?.state === 'patched' && snapshot.companion.running &&
                snapshot.gateway.running && Boolean(snapshot.gateway_config?.verified_at) && snapshot.capture.state === 'healthy' &&
                snapshot.checkpoints.some(cp => cp.validation.eligible);
            if (state.configured) {
                state.steps.verify = verified ? 'passed' : snapshot.capture.state === 'degraded' ? 'failed' : 'pending';
                state.steps.finish = verified ? 'passed' : 'pending'; await this.wizard.save(state);
            }
            this.status.update(protectionState(snapshot, compatibility, state.configured));
            if (show) { this.status.show(snapshot, state, compatibility); }
        } catch { this.status.update('Setup required'); if (show) { this.status.show(undefined, state, undefined); } }
    }
    async owner(name: string, payload: JsonObject, snapshot?: Snapshot): Promise<unknown> {
        const cli = await this.client(), workspace = this.selected(), current = snapshot ?? await this.snapshot();
        const pending = this.context.workspaceState.get<{ id: string; name: string; workspace: string }>('vessel.lastOwnerRequest');
        if (pending) {
            const receipt = await cli.request<{ status: string }>('action-result', { workspace: pending.workspace, request_id: pending.id });
            if (receipt.status === 'started') { throw new LocalError('owner_result_unknown', 'The previous owner action is unresolved. Inspect its result before another action; no automatic replay is allowed.'); }
            if (!await review('Previous owner action result', { ...receipt, workspace: pending.workspace, action: pending.name }, 'Acknowledge result')) { throw new LocalError('owner_result_unknown', 'Previous action review is still pending.'); }
            await this.context.workspaceState.update('vessel.lastOwnerRequest', undefined);
            throw new LocalError('owner_result_reviewed', 'Previous action result reviewed. Refresh Status before choosing the next action.');
        }
        const request = { workspace, name, payload, request_id: id(), revision: current.policy_revision, epoch: current.lease?.execution_epoch ?? null };
        await this.context.workspaceState.update('vessel.lastOwnerRequest', { id: request.request_id, name, workspace });
        const receipt = await cli.request<{ status: string; result: unknown; warning?: string }>('owner-action', request, 60000);
        if (receipt.status !== 'succeeded') { throw new LocalError('owner_action_blocked', 'The owner action was not confirmed. Inspect Status before another action.'); }
        await this.context.workspaceState.update('vessel.lastOwnerRequest', undefined);
        if (receipt.warning) { void vscode.window.showWarningMessage('The owner action completed, but capture did not start. Inspect Status and use Resume Protection after resolving its blockers.'); }
        return receipt.result;
    }
    async setGateway(paused: boolean, extra: JsonObject = {}): Promise<void> {
        const snapshot = await this.snapshot();
        await (await this.client()).request('gateway-mode', { workspace: this.selected(), paused,
            revision: snapshot.policy_revision, epoch: snapshot.lease?.execution_epoch ?? null, ...extra });
    }
    async key(state: SetupState): Promise<string> {
        const cli = await this.client();
        const canonical = await cli.request<{ has_key: boolean; key?: string; credential_version?: string }>('orbio-get-key', { workspace: state.workspace });
        if (canonical.has_key && canonical.key) {
            return canonical.key;
        }
        const legacy = state.credentialVersion && await this.context.secrets.get(secretId(state.workspace, state.credentialVersion));
        if (legacy) {
            try {
                const migration = await cli.request<{ migrated: boolean; credential_version: string }>('orbio-migrate-key', {
                    workspace: state.workspace,
                    key: legacy,
                    credential_version: state.credentialVersion,
                    verified_at: state.verifiedAt,
                });
                if (migration.migrated && state.credentialVersion) {
                    await this.context.secrets.delete(secretId(state.workspace, state.credentialVersion)).then(undefined, () => undefined);
                    return legacy;
                }
            } catch {
                return legacy;
            }
        }
        throw new LocalError('key_missing', 'No Orbio key is stored for this project. Use Replace Orbio Key.');
    }
    async collectKey(state: SetupState, cli: PythonCli): Promise<boolean> {
        while (true) {
            const value = await vscode.window.showInputBox({
                title: 'Connect Inference Provider (Orbio / OpenRouter)',
                prompt: 'Enter your Orbio (sk-orb-...) or OpenRouter (sk-or-v1-...) API key. Leave blank to skip and configure later.',
                password: true,
                ignoreFocusOut: true,
                validateInput: input => input && (input.length > 8192 || /\s/.test(input)) ? 'Paste only the API key, without spaces or Bearer prefix.' : undefined
            });
            if (!value) {
                state.steps.provider = 'pending';
                await this.wizard.save(state);
                return true;
            }
            const approved = await vscode.window.showWarningMessage('Verify this key with two small READY-only inference requests, then store it securely? Provider charges may apply. No project content is sent.', { modal: true }, 'Verify and save');
            if (approved !== 'Verify and save') { return false; }
            const models = ['openai/gpt-4.1-mini', 'openai/gpt-4o-mini'];
            try {
                const result = await cli.request<{ verified_at: number }>('validate-provider', { key: value, models }, 60000);
                const version = id();
                await this.context.secrets.store(secretId(state.workspace, version), value);
                await cli.request('orbio-migrate-key', { workspace: state.workspace, key: value, credential_version: version, verified_at: result.verified_at }).catch(() => undefined);
                if (state.credentialVersion && state.credentialVersion !== version) {
                    await this.context.secrets.delete(secretId(state.workspace, state.credentialVersion)).then(undefined, () => undefined);
                }
                state.previousCredentialVersion = state.credentialVersion;
                state.credentialVersion = version; state.verifiedAt = result.verified_at; state.steps.provider = 'passed';
                await this.wizard.save(state);
                return true;
            } catch (err) {
                const choice = await vscode.window.showErrorMessage(
                    `Provider verification failed: ${safeError(err)}. Check your key and credits, or configure inference later.`,
                    'Try another key',
                    'Skip for now'
                );
                if (choice === 'Skip for now') {
                    state.steps.provider = 'pending';
                    await this.wizard.save(state);
                    return true;
                }
                if (choice !== 'Try another key') {
                    return false;
                }
            }
        }
    }
    async setup(): Promise<void> {
        let python;
        try { python = await detectPython(); } catch (error) {
            const choice = await vscode.window.showErrorMessage('Python 3.11 or newer is required.', 'Open installation guide', 'Check again');
            if (choice === 'Open installation guide') { await vscode.env.openExternal(vscode.Uri.parse('https://www.python.org/downloads/windows/')); return; }
            if (choice === 'Check again') { python = await detectPython(); } else { throw error; }
        }
        const cline = detectCline();
        if (!cline.installed || !isSupportedClineVersion(cline.version)) { throw new LocalError('unsupported_cline', 'Install Cline 4.1.17 or a later verified build. Older builds are not supported; VESSEL will not patch them.'); }
        const workspace = await this.wizard.selectWorkspace(); if (!workspace) { return; }
        const state = this.wizard.load(workspace);
        if (await vscode.window.showInformationMessage('Prepare the pinned offline VESSEL runtime in VS Code private storage? No Python or package downloads will occur.', { modal: true }, 'Prepare runtime') !== 'Prepare runtime') { return; }
        const runtime = await vscode.window.withProgress({ location: vscode.ProgressLocation.Notification, title: 'Preparing isolated VESSEL runtime' }, () => this.runtime.ensure(python));
        const cli = new PythonCli(runtime.python, this.context.globalStorageUri.fsPath);
        const compatibility = await inspectCline(cli);
        if (!compatibility?.supported) { state.steps.requirements = 'unsupported'; await this.wizard.save(state); throw new LocalError('unsupported_cline', 'This Cline bundle does not match the verified build. Open Diagnostic Report for its version and hash.'); }
        state.steps.requirements = 'passed'; state.steps.project = 'passed'; await this.wizard.save(state);
        const found = await cli.request<{ existing: boolean; state: string; mission?: string; profile?: { mcp_config: string; origin: string; port: number } }>('discover', { workspace });
        const mission = found.mission ?? await vscode.window.showInputBox({ title: 'Project mission', prompt: 'What should Cline accomplish? Existing missions are preserved.', ignoreFocusOut: true, validateInput: value => value.trim() ? undefined : 'Enter a mission.' });
        if (!mission) { return; }
        let config = found.profile?.mcp_config;
        if (!config) {
            config = await detectClineMcpConfig();
        }
        if (!config) {
            const choice = await vscode.window.showInformationMessage(
                'In Cline, open MCP Servers → Configure MCP Servers. Select that settings file in the dialog.',
                'Select settings file'
            );
            if (choice === 'Select settings file') {
                config = (await vscode.window.showOpenDialog({
                    title: 'Select cline_mcp_settings.json',
                    canSelectMany: false,
                    filters: { JSON: ['json'] }
                }))?.[0]?.fsPath;
            }
        }
        if (!config) { return; }
        const vesselConfig = vscode.workspace.getConfiguration('vessel');
        const configuredOrigin = vesselConfig.get<string>('dashboardUrl', 'https://vessel-dashboard.cloud-ip.cc');
        const originChoice = await vscode.window.showQuickPick([
            ...(found.profile?.origin ? [{ label: `Keep ${found.profile.origin}`, value: found.profile.origin }] : []),
            { label: 'Configured VESSEL dashboard', detail: configuredOrigin, value: configuredOrigin },
            { label: 'Alternative hosted dashboard', detail: 'https://vessel-cont.duckdns.org', value: 'https://vessel-cont.duckdns.org' },
            { label: 'Local development dashboard', detail: 'http://localhost:3000', value: 'http://localhost:3000' },
            { label: 'Another HTTPS origin', value: 'custom' }
        ], { title: 'Choose the exact dashboard origin allowed to reach this local companion', ignoreFocusOut: true });
        if (!originChoice) { return; }
        const origin = originChoice.value === 'custom'
            ? await vscode.window.showInputBox({ title: 'Dashboard HTTPS origin', placeHolder: 'https://dashboard.example.com', ignoreFocusOut: true })
            : originChoice.value;
        if (!origin) { return; }
        const orbioStatus = await cli.request<{ has_key: boolean }>('orbio-status', { workspace }).catch(() => ({ has_key: false }));
        if (!orbioStatus.has_key) {
            const hasLegacy = state.credentialVersion && await this.context.secrets.get(secretId(workspace, state.credentialVersion));
            if (!hasLegacy) {
                if (!await this.collectKey(state, cli)) { return; }
            }
        }
        const catalog = await cli.request<{ models: string[] }>('models');
        const primary = await vscode.window.showQuickPick(catalog.models.map(model => ({ label: model, description: 'Text verified for your key · tools previously verified · native Cline pending' })), { title: 'Primary model', ignoreFocusOut: true });
        if (!primary) { return; }
        const fallback = await vscode.window.showQuickPick(catalog.models.filter(model => model !== primary.label), { title: 'Fallback model (only before response commitment)', ignoreFocusOut: true });
        if (!fallback) { return; }
        state.models = [primary.label, fallback];
        state.steps.models = 'passed';
        await this.wizard.save(state);
        const configuredCompanionPort = vesselConfig.get<number>('companionPort', 8765);
        const configuredGatewayPort = vesselConfig.get<number>('gatewayPort', 8091);
        const companionPort = await this.port('Companion port', found.profile?.port ?? configuredCompanionPort); if (!companionPort) { return; }
        const gatewayPort = await this.port('Inference gateway port', configuredGatewayPort); if (!gatewayPort) { return; }
        const plan = await cli.request<Plan>('plan', { workspace, mission, mcp_config: config, models: state.models,
            port: companionPort, gateway_port: gatewayPort, origin });
        state.transaction = plan.id; state.review = plan.review;
        state.compatibilityExtension = cline.extensionPath; state.compatibilityBackup = backupPath(cli.storage, cline.extensionPath!);
        await this.wizard.save(state);
        if (!await review('Review VESSEL setup', { project: workspace, mission, privateState: plan.plan.state,
            files: plan.changes, processes: plan.processes, companionPort, gatewayPort, dashboardOrigin: origin, runtime: runtime.python,
            models: state.models, otherMcpServersPreserved: plan.plan.other_enabled_servers,
            compatibility: { ...compatibility, extension: cline.extensionPath, backup: state.compatibilityBackup },
            nativeChecks: 'Pending until owner-selected native Cline observations and an eligible checkpoint are recorded.',
            removal: 'Owned configuration only; encrypted recovery data is preserved.' })) { return; }
        state.steps.review = 'passed'; await this.wizard.save(state);
        let patched = false, startedCompanion = false;
        try {
            if (compatibility.state === 'patch_required') {
                await cli.request('patch', { extension: cline.extensionPath, backup: state.compatibilityBackup, bundle_sha256: compatibility.bundle_sha256 });
                patched = true; state.compatibilityOwned = true;
            }
            await cli.request('apply', { transaction: plan.id, review: plan.review, credential_version: state.credentialVersion, verified_at: state.verifiedAt });
            state.configured = true; state.paused = false; state.steps.configure = 'passed'; await this.wizard.save(state);
            const before = await this.snapshot();
            await cli.request('launch', { workspace, transaction: plan.id }); startedCompanion = !before.companion.running;
            await cli.request('gateway-stop', { workspace });
            await this.setGateway(false);
            let launchKey: string | undefined;
            try { launchKey = await this.key(state); } catch { launchKey = undefined; }
            if (launchKey) {
                await cli.request('gateway-launch', { workspace, transaction: plan.id, key: launchKey });
            }
            state.steps.verify = 'pending'; state.errorCode = undefined; await this.wizard.save(state);
            if (state.previousCredentialVersion) { await this.context.secrets.delete(secretId(workspace, state.previousCredentialVersion)); }
            void vscode.window.showInformationMessage('Local configuration is ready. Enable Cline hooks and reload while Cline is idle, then use Status to bind a real task and verify capture.');
            if (patched && await vscode.window.showInformationMessage('The verified Cline compatibility layer was installed. Reload VS Code while Cline is idle.', 'Reload window') === 'Reload window') {
                await vscode.commands.executeCommand('workbench.action.reloadWindow');
            }
        } catch (error) {
            state.steps.configure = 'failed'; state.errorCode = error instanceof LocalError ? error.code : 'setup_failed';
            await cli.request('gateway-stop', { workspace }).catch(() => undefined);
            if (startedCompanion) { await cli.request('stop-companion', { workspace }).catch(() => undefined); }
            await cli.request('rollback', { transaction: plan.id, review: plan.review }).then(() => { state.configured = false; }).catch(() => undefined);
            if (patched) {
                const current = await inspectCline(cli);
                if (current?.state === 'patched') { await cli.request('restore-patch', { extension: cline.extensionPath, backup: state.compatibilityBackup, bundle_sha256: current.bundle_sha256 }).catch(() => undefined); }
            }
            await this.wizard.save(state); throw error;
        }
        await this.refresh(true);
    }
    async port(title: string, value: number): Promise<number | undefined> {
        const result = await vscode.window.showInputBox({ title, value: String(value), ignoreFocusOut: true,
            validateInput: text => /^\d+$/.test(text) && Number(text) >= 1024 && Number(text) <= 65535 ? undefined : 'Choose a port from 1024 to 65535.' });
        return result ? Number(result) : undefined;
    }
    async bind(): Promise<void> {
        const snapshot = await this.snapshot();
        if (snapshot.lease && snapshot.lease.status !== 'closed') { throw new LocalError('run_exists', 'This enrollment already has an execution owner. Use reviewed recovery to change conversations.'); }
        const choices = snapshot.sessions.filter(session => session.last_observation && !session.run_id);
        if (!choices.length) { throw new LocalError('native_pending', 'No fresh Cline task was observed. Enable hooks, reload, and send a READY-only probe in this exact project.'); }
        const selected = await vscode.window.showQuickPick(choices.map(session => ({ label: session.id })), { title: 'Select the exact observed Cline task' });
        if (!selected || !await review('Bind observed task', { workspace: this.selected(), conversation: selected.label, note: 'Only future events are attributed to this run.' })) { return; }
        const run = await this.owner('start', { session_id: selected.label }, snapshot) as { id: string; execution_epoch: number };
        const state = this.wizard.load(this.selected()); state.binding = { run: run.id, epoch: run.execution_epoch }; await this.wizard.save(state);
        void vscode.window.showInformationMessage('Task bound. Send a second READY-only probe in the SAME Cline task, then refresh Status.');
    }
    async pause(): Promise<void> {
        if (!await review('Pause protection', { workspace: this.selected(), effect: 'Block new gateway admissions and stop VESSEL processes. This does not assert that Cline or its tools have stopped.' })) { return; }
        await this.setGateway(true);
        const cli = await this.client(), workspace = this.selected();
        await cli.request('gateway-stop', { workspace }); await cli.request('stop-companion', { workspace });
        const state = this.wizard.load(workspace); state.paused = true; await this.wizard.save(state);
    }
    async resume(automatic = false): Promise<void> {
        const workspace = this.selected(), state = this.wizard.load(workspace), cli = await this.client();
        if (!state.configured || (automatic && state.paused)) { return; }
        const compatible = await inspectCline(cli);
        if (compatible?.state !== 'patched') { throw new LocalError('unsupported_cline', 'Cline changed or is unsupported. Review compatibility before resuming.'); }
        const current = await this.snapshot();
        if (!automatic && !await review('Resume protection', { workspace, run: current.lease?.holder_run_id, epoch: current.lease?.execution_epoch,
            policyRevision: current.policy_revision, note: 'Only the previously selected active run is renewed. A stopped source requires recovery.' })) { return; }
        await cli.request('launch', { workspace });
        if (!automatic) { await this.setGateway(false); }
        if (current.gateway_config?.paused && automatic) { return; }
        await cli.request('gateway-launch', { workspace, key: await this.key(state) });
        if (state.binding && current.lease?.status === 'active' && current.lease.holder_run_id === state.binding.run && current.lease.execution_epoch === state.binding.epoch) {
            if (current.lease.policy_revision !== current.policy_revision) {
                if (automatic) { return; }
                await this.owner('revalidate-policy', { run_id: state.binding.run });
            }
            await this.owner('keep-capturing', { run_id: state.binding.run });
        }
        state.paused = false; await this.wizard.save(state);
    }
    async checkpoint(): Promise<void> {
        const snapshot = await this.snapshot();
        if (!snapshot.lease) { throw new LocalError('native_pending', 'Bind a real observed Cline task and verify capture first.'); }
        const note = await vscode.window.showInputBox({ title: 'Confirm the native source has stopped', prompt: 'Stop Cline and all foreground/background commands. Describe the shutdown evidence; do not submit while work is running.', ignoreFocusOut: true,
            validateInput: text => text.trim() ? undefined : 'Shutdown evidence is required.' });
        if (!note || !await review('Stop source and capture checkpoint', { run: snapshot.lease.holder_run_id, note, attestation: 'I confirm the Cline source and its tools have stopped.' })) { return; }
        await this.owner('stop', { run_id: snapshot.lease.holder_run_id, attested: true, note }, snapshot);
        const checkpoint = await this.owner('checkpoint', { run_id: snapshot.lease.holder_run_id }) as { id: string };
        const latest = await this.snapshot();
        const saved = latest.checkpoints.find(cp => cp.id === checkpoint.id);
        if (!saved?.validation.eligible) { throw new LocalError('checkpoint_ineligible', 'A checkpoint was recorded but did not pass recovery checks. Inspect its blockers in Status.'); }
        void vscode.window.showInformationMessage('Checkpoint integrity and recovery checks passed. The source remains stopped.');
    }
    async recover(): Promise<void> {
        let snapshot = await this.snapshot();
        const checkpoint = await vscode.window.showQuickPick(snapshot.checkpoints.filter(cp => cp.validation.eligible).map(cp => ({ label: cp.id, description: new Date(cp.created_at * 1000).toLocaleString() })), { title: 'Select an eligible checkpoint' });
        if (!checkpoint) { return; }
        const destination = await vscode.window.showQuickPick(snapshot.sessions.filter(session => session.last_observation && !session.run_id).map(session => ({ label: session.id })), { title: 'Choose a fresh observed destination task (send READY in a new Cline task first)' });
        if (!destination) { return; }
        const model = await vscode.window.showQuickPick(snapshot.policy.allowed_models, { title: 'Confirm the model selected in the destination Cline task' });
        if (!model) { return; }
        const capacity = await vscode.window.showInputBox({ title: 'Verified available handover capacity (bytes)', prompt: 'Reserve space for tools, wrappers, future messages and output. Confirm this against the destination model context capacity.', value: '24000', validateInput: value => /^\d+$/.test(value) && Number(value) >= 1024 && Number(value) <= 1048576 ? undefined : 'Enter 1024–1048576 bytes.' });
        const note = capacity && await vscode.window.showInputBox({ title: 'Environment and model review evidence', prompt: 'Describe how you checked required runtimes/services and the selected model capacity.' });
        if (!note) { return; }
        if (!await review('Review destination environment', { model, availableContextBytes: Number(capacity), note })) { return; }
        await this.owner('review-environment', { model, context_bytes: Number(capacity), note });
        const recovery = await this.owner('prepare-recovery', { checkpoint_id: checkpoint.label, session_id: destination.label, context_bytes: Number(capacity), idempotency_key: id() }) as Recovery;
        if (recovery.preflight.blockers.length) { await review('Recovery blocked — inspect these findings', recovery.preflight, 'Close review'); return; }
        if (!await review('Review handover and transfer ownership', { recovery: recovery.id, destination: destination.label, ...recovery.preflight }, 'Transfer ownership')) { return; }
        await this.owner('handover', { recovery_id: recovery.id, review_token: recovery.review_token });
        snapshot = await this.snapshot();
        const state = this.wizard.load(this.selected());
        if (snapshot.lease) { state.binding = { run: snapshot.lease.holder_run_id, epoch: snapshot.lease.execution_epoch }; await this.wizard.save(state);
            await this.owner('keep-capturing', { run_id: snapshot.lease.holder_run_id }); }
        const prompt = `In this exact destination Cline task, call vessel_get_recovery_context on MCP server ${snapshot.configuration.server_name} with {"recovery_id":"${recovery.id}"}. If it fails, stop. Inspect the saved handover and current files; continue only pending work. Do not replay uncertain operations.`;
        if (await vscode.window.showInformationMessage('Ownership transferred. Have the selected destination retrieve this exact handover.', 'Copy destination prompt') === 'Copy destination prompt') { await vscode.env.clipboard.writeText(prompt); }
    }
    async confirmRecovery(): Promise<void> {
        const snapshot = await this.snapshot();
        const recovery = await vscode.window.showQuickPick(snapshot.recoveries.filter(item => item.destination_run_id === snapshot.lease?.holder_run_id && item.status !== 'succeeded').map(item => ({ label: item.id })), { title: 'Select the recovery to confirm' });
        const operation = recovery && await vscode.window.showQuickPick(snapshot.operations.filter(item => item.successful && !item.uncertain).map(item => ({ label: item.id })), { title: 'Select the actual successful continuation operation' });
        const note = operation && await vscode.window.showInputBox({ title: 'Continuation evidence', prompt: 'Explain how this observed destination operation advances the recovered task.' });
        if (recovery && operation && note && await review('Confirm observed continuation', { recovery: recovery.label, operation: operation.label, note })) {
            await this.owner('confirm', { recovery_id: recovery.label, operation_id: operation.label, note }, snapshot);
            void vscode.window.showInformationMessage('VESSEL accepted the observed continuation evidence.');
        }
    }
    async task(): Promise<void> {
        const snapshot = await this.snapshot(); if (!snapshot.lease) { throw new LocalError('run_missing', 'Bind an observed task first.'); }
        const taskId = await vscode.window.showInputBox({ title: 'Task ID', prompt: 'Use an existing ID to update a task, or a new short ID to add one.' }); if (!taskId) { return; }
        const description = await vscode.window.showInputBox({ title: 'Task description' }); if (!description) { return; }
        const status = await vscode.window.showQuickPick(['pending', 'active', 'blocked', 'done'], { title: 'Task state' }); if (!status) { return; }
        const evidence = status === 'done' ? await vscode.window.showQuickPick(snapshot.operations.filter(op => op.successful && !op.uncertain).map(op => op.id), { title: 'Select observed successful evidence' }) : undefined;
        if (status === 'done' && !evidence) { return; }
        if (await review('Record owner task', { taskId, description, status, evidence })) { await this.owner('task', { run_id: snapshot.lease.holder_run_id, task_id: taskId, description, status, evidence }, snapshot); }
    }
    async replaceKey(): Promise<void> {
        const workspace = this.selected(), state = this.wizard.load(workspace), cli = await this.client();
        if (!await this.collectKey(state, cli)) { return; }
        if (state.configured) {
            await this.setGateway(true, { credential_version: state.credentialVersion, verified_at: state.verifiedAt });
            await cli.request('gateway-stop', { workspace });
            state.paused = true; await this.wizard.save(state);
        }
        if (state.previousCredentialVersion) { await this.context.secrets.delete(secretId(workspace, state.previousCredentialVersion)); }
        void vscode.window.showInformationMessage('Verified key saved. New inference is paused; use Resume Protection after reviewing the current run.');
    }
    async forgetKey(): Promise<void> {
        const workspace = this.selected(), state = this.wizard.load(workspace);
        if (await vscode.window.showWarningMessage('Forget this project’s Orbio key and pause new inference? Checkpoints are preserved.', { modal: true }, 'Forget key') !== 'Forget key') { return; }
        if (state.configured) { await this.setGateway(true, { credential_version: id() }); }
        if (state.credentialVersion) { await this.context.secrets.delete(secretId(workspace, state.credentialVersion)).then(undefined, () => undefined); }
        if (state.previousCredentialVersion) { await this.context.secrets.delete(secretId(workspace, state.previousCredentialVersion)).then(undefined, () => undefined); }
        const cli = await this.client();
        await cli.request('orbio-forget-key', { workspace }).catch(() => undefined);
        state.credentialVersion = undefined; state.previousCredentialVersion = undefined; state.steps.provider = 'pending'; state.paused = true;
        await this.wizard.save(state);
        if (state.configured) { await cli.request('gateway-stop', { workspace }).catch(() => undefined); }
        void vscode.window.showInformationMessage('Key forgotten and new gateway admissions paused. Recovery data is preserved.');
    }
    async configureCline(): Promise<void> {
        const snapshot = await this.snapshot();
        if (!await review('Connect Cline inference to VESSEL', { baseUrl: `http://127.0.0.1:${snapshot.gateway_config?.port}/v1`, model: 'vessel-auto',
            provider: 'OpenAI Compatible', reasoning: 'Disable reasoning; the verified route rejected reasoning_effort.',
            key: 'A new VESSEL client credential will be copied only with your explicit approval. The Orbio key remains private.' }, 'Create and copy client key')) { return; }
        const credential = await (await this.client()).request<{ token: string }>('gateway-key', { workspace: this.selected(), revision: snapshot.policy_revision, epoch: snapshot.lease?.execution_epoch ?? null });
        await vscode.env.clipboard.writeText(credential.token);
        void vscode.window.showInformationMessage(`In Cline API Configuration choose OpenAI Compatible, base URL http://127.0.0.1:${snapshot.gateway_config?.port}/v1, model vessel-auto, and paste the copied VESSEL key. Disable reasoning. The clipboard clears after one minute if unchanged.`);
        setTimeout(() => { void vscode.env.clipboard.readText().then(text => text === credential.token ? vscode.env.clipboard.writeText('') : undefined); }, 60000);
    }
    async compatibility(restore = false): Promise<void> {
        const cli = await this.client(), cline = detectCline(), info = await inspectCline(cli);
        if (!info || !cline.extensionPath) { throw new LocalError('cline_missing', 'Cline is not installed.'); }
        if (!restore) { await review('Cline compatibility', info, 'Close review'); return; }
        if (!info.restore_available) { throw new LocalError('backup_missing', 'This extension has no verified original backup for the installed patch. Use its original owner-managed restore workflow.'); }
        if (await review('Restore original Cline files', { ...info, note: 'Stop Cline first. Protection will be unavailable until compatible capture is restored.' }, 'Restore original files')) {
            await this.setGateway(true);
            await cli.request('restore-patch', { extension: cline.extensionPath, backup: backupPath(cli.storage, cline.extensionPath), bundle_sha256: info.bundle_sha256 });
            void vscode.window.showInformationMessage('Original Cline files restored. Reload VS Code while Cline is idle.');
        }
    }
    async remove(): Promise<void> {
        const workspace = this.selected(), snapshot = await this.snapshot();
        if (!await review('Remove VESSEL workspace integration', { workspace, effects: ['Stop VESSEL processes', 'Remove only unchanged owned hooks and MCP entry', 'Keep enrollment, encrypted checkpoints and recovery history'], note: 'Stop the native task and create a checkpoint first.' }, 'Remove integration')) { return; }
        await this.setGateway(true);
        const cli = await this.client(); await cli.request('gateway-stop', { workspace }); await cli.request('stop-companion', { workspace });
        await cli.request('remove', { workspace, revision: snapshot.policy_revision, epoch: snapshot.lease?.execution_epoch ?? null });
        const state = this.wizard.load(workspace); state.configured = false; state.paused = true; state.steps.configure = 'pending'; await this.wizard.save(state);
        void vscode.window.showInformationMessage('Owned integration removed. Encrypted recovery data remains on this computer.');
    }
    async rollback(): Promise<void> {
        const state = this.wizard.load(this.selected()); if (!state.transaction || !state.review) { return; }
        if (!await review('Roll back setup changes', { transaction: state.transaction, effect: 'Restore only unchanged owned configuration. Keep enrollment and checkpoints.' })) { return; }
        await (await this.client()).request('rollback', { transaction: state.transaction, review: state.review });
        state.configured = false; state.paused = true; state.steps.configure = 'pending'; await this.wizard.save(state);
    }
    async diagnostic(): Promise<void> {
        const workspace = this.wizard.selected(), state = workspace ? this.wizard.load(workspace) : undefined;
        const runtime = await this.runtime.current();
        const cli = runtime && new PythonCli(runtime.python, this.context.globalStorageUri.fsPath);
        const compatibility = cli ? await inspectCline(cli).catch(() => undefined) : undefined;
        const snapshot = cli && workspace ? await cli.request<Snapshot>('status', { workspace }).catch(() => undefined) : undefined;
        const report = { ...diagnostics(state, snapshot, compatibility, runtime?.python_version), errorCode: this.lastError ?? state?.errorCode ?? null };
        const document = await vscode.workspace.openTextDocument({ language: 'json', content: JSON.stringify(report, null, 2) });
        await vscode.window.showTextDocument(document);
    }
    async restart(): Promise<void> {
        if (!await review('Restart VESSEL companion', { workspace: this.selected(), effect: 'Temporarily pause new inference, stop and restart VESSEL processes without replaying Cline work.' })) { return; }
        await this.setGateway(true); const cli = await this.client(), workspace = this.selected();
        await cli.request('gateway-stop', { workspace }); await cli.request('stop-companion', { workspace });
        await this.resume(false);
    }
    async start(): Promise<void> {
        this.timer = setInterval(() => { if (!this.busy) { void this.refresh(false); } }, 15000);
        if (vscode.workspace.getConfiguration('vessel').get<boolean>('startOnOpen', false) && this.wizard.selected()) { await this.execute(() => this.resume(true)); }
        else { await this.refresh(false); }
    }
    async shutdown(): Promise<void> {
        if (!vscode.workspace.getConfiguration('vessel').get<boolean>('stopOnClose', true) || !this.wizard.selected()) { return; }
        const state = this.wizard.load(this.selected()); if (!state.configured) { return; }
        const cli = await this.client(), workspace = this.selected();
        await cli.request('gateway-stop', { workspace }); await cli.request('stop-companion', { workspace });
    }
    openLogs(): void { this.output.show(); }
    dispose(): void { if (this.timer) { clearInterval(this.timer); } this.status.dispose(); this.output.dispose(); }
}

export function activate(context: vscode.ExtensionContext): void {
    const app = new Controller(context); controller = app; context.subscriptions.push(app);
    context.subscriptions.push(vscode.window.registerWebviewViewProvider(OnboardingWebviewProvider.viewType, new OnboardingWebviewProvider()));
    const commands: Record<string, () => Promise<void>> = {
        setup: () => app.setup(), protectWorkspace: () => app.setup(), showStatus: () => app.refresh(true),
        createCheckpoint: () => app.checkpoint(), recoverTask: () => app.recover(), pauseProtection: () => app.pause(),
        resumeProtection: () => app.resume(), restartCompanion: () => app.restart(), replaceOrbioKey: () => app.replaceKey(),
        forgetOrbioKey: () => app.forgetKey(), reviewCompatibility: () => app.compatibility(), restoreOriginal: () => app.compatibility(true),
        removeWorkspace: () => app.remove(), openDiagnostic: () => app.diagnostic(), bindSession: () => app.bind(),
        confirmRecovery: () => app.confirmRecovery(), manageTasks: () => app.task(), configureCline: () => app.configureCline(),
        rollbackSetup: () => app.rollback(), openLogs: async () => app.openLogs(),
        openGuide: async () => { await vscode.commands.executeCommand('markdown.showPreview', vscode.Uri.file(path.join(context.extensionUri.fsPath, 'README.md'))); },
        openDashboard: async () => {
            try {
                let conn = await (await app.client()).request<{ connect_url: string }>('connection', { workspace: app.selected() }).catch(() => null);
                if (!conn?.connect_url) {
                    conn = await (await app.client()).request<{ connect_url: string }>('launch', { workspace: app.selected() }).catch(() => null);
                }
                if (conn?.connect_url) {
                    await vscode.env.clipboard.writeText(conn.connect_url);
                    await vscode.env.openExternal(vscode.Uri.parse(conn.connect_url));
                    void vscode.window.showInformationMessage('Dashboard opened with private companion pairing. Link copied to clipboard.');
                    return;
                }
            } catch { /* Fallback to default dashboard URL if companion not yet running */ }
            const url = vscode.workspace.getConfiguration('vessel').get<string>('dashboardUrl', 'https://vessel-dashboard.cloud-ip.cc');
            await vscode.env.openExternal(vscode.Uri.parse(url));
        }
    };
    for (const [name, callback] of Object.entries(commands)) { context.subscriptions.push(vscode.commands.registerCommand('vessel.' + name, () => app.execute(callback))); }
    context.subscriptions.push(vscode.extensions.onDidChange(() => { void app.refresh(false); }));
    void app.start();
}
export async function deactivate(): Promise<void> { await controller?.shutdown().catch(() => undefined); }
