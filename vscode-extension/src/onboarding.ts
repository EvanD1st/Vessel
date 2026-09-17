import * as vscode from 'vscode';
import { createHash } from 'crypto';
import { SetupState, STEPS, Step, CheckState } from './types';
import { LocalError } from './security';

export function workspaceId(workspace: string): string {
    return createHash('sha256').update(process.platform === 'win32' ? workspace.toLowerCase() : workspace).digest('hex');
}
export function secretId(workspace: string, version: string): string { return `vessel.orbio.${workspaceId(workspace)}.${version}`; }
export function initialState(workspace: string): SetupState {
    return { schema: 1, workspace, steps: Object.fromEntries(STEPS.map(step => [step, 'pending'])) as Record<Step, CheckState>, updated: Date.now() };
}
export function validateState(value: unknown, workspace: string): SetupState | undefined {
    if (!value || typeof value !== 'object') { return undefined; }
    const state = value as SetupState;
    if (state.schema !== 1 || state.workspace !== workspace || !state.steps || !STEPS.every(step => ['passed', 'failed', 'pending', 'skipped', 'unsupported', 'unknown'].includes(state.steps[step]))) { return undefined; }
    if (state.credentialVersion && !/^[a-f0-9]{32}$/.test(state.credentialVersion)) { return undefined; }
    return state;
}
export class OnboardingWizard {
    constructor(private readonly context: vscode.ExtensionContext) {}
    load(workspace: string): SetupState { return validateState(this.context.globalState.get(`setup.${workspaceId(workspace)}`), workspace) ?? initialState(workspace); }
    async save(state: SetupState): Promise<void> { state.updated = Date.now(); await this.context.globalState.update(`setup.${workspaceId(state.workspace)}`, state); }
    async selectWorkspace(): Promise<string | undefined> {
        const folders = vscode.workspace.workspaceFolders ?? [];
        if (!folders.length) { throw new LocalError('workspace_missing', 'Open the project folder in VS Code, then run setup.'); }
        const selected = await vscode.window.showQuickPick(folders.map(folder => ({ label: folder.name, description: folder.uri.fsPath, folder })), {
            title: 'Choose the one project VESSEL will protect', ignoreFocusOut: true
        });
        if (!selected) { return undefined; }
        await this.context.workspaceState.update('vessel.selectedWorkspace', selected.folder.uri.toString());
        return selected.folder.uri.fsPath;
    }
    selected(): string | undefined {
        const uri = this.context.workspaceState.get<string>('vessel.selectedWorkspace');
        return vscode.workspace.workspaceFolders?.find(folder => folder.uri.toString() === uri)?.uri.fsPath;
    }
}
