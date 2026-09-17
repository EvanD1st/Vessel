import * as vscode from 'vscode';
import { randomBytes } from 'crypto';
import { escapeHtml } from './security';

export function htmlDocument(title: string, body: string, controls = false): string {
    const nonce = randomBytes(24).toString('base64');
    return `<!doctype html><html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>${escapeHtml(title)}</title>
<style nonce="${nonce}">body{font-family:var(--vscode-font-family);padding:16px;line-height:1.5;color:var(--vscode-foreground)}
h1{font-size:1.5rem}button{background:var(--vscode-button-background);color:var(--vscode-button-foreground);border:1px solid var(--vscode-contrastBorder,transparent);padding:8px 12px;margin:4px;cursor:pointer}
button:focus-visible{outline:2px solid var(--vscode-focusBorder)}pre{white-space:pre-wrap;overflow-wrap:anywhere}li{margin:8px 0}.notice{border-left:3px solid var(--vscode-focusBorder);padding:8px}dt{font-weight:bold}dd{margin:0 0 10px}</style></head>
<body>${body}${controls ? `<script nonce="${nonce}">const api=acquireVsCodeApi();document.querySelectorAll('button[data-action]').forEach(b=>b.addEventListener('click',()=>api.postMessage({action:b.dataset.action})));</script>` : ''}</body></html>`;
}

export function review(title: string, details: unknown, applyLabel = 'Approve reviewed changes'): Promise<boolean> {
    const panel = vscode.window.createWebviewPanel('vesselReview', title, vscode.ViewColumn.One,
        { enableScripts: true, localResourceRoots: [], retainContextWhenHidden: false });
    panel.webview.html = htmlDocument(title, `<h1>${escapeHtml(title)}</h1><p>Review these exact changes. Existing recovery data stays on this computer.</p><pre>${escapeHtml(JSON.stringify(details, null, 2))}</pre><button data-action="approve">${escapeHtml(applyLabel)}</button><button data-action="cancel">Cancel</button>`, true);
    return new Promise(resolve => {
        panel.webview.onDidReceiveMessage((message: unknown) => {
            const action = (message as { action?: unknown })?.action;
            if (action === 'approve' || action === 'cancel') { resolve(action === 'approve'); panel.dispose(); }
        });
        panel.onDidDispose(() => resolve(false));
    });
}

export class OnboardingWebviewProvider implements vscode.WebviewViewProvider {
    static readonly viewType = 'vessel.welcomeView';
    resolveWebviewView(view: vscode.WebviewView): void {
        view.webview.options = { enableScripts: true, localResourceRoots: [] };
        view.webview.html = htmlDocument('Welcome to VESSEL', '<h1>Welcome to VESSEL</h1><p>Protect your Cline tasks from interrupted sessions, provider failures and lost progress.</p><p>Windows x64, Python 3.11–3.14 and the exact verified Cline 4.1.17 build are required for this preview.</p><button data-action="setup">Set up VESSEL</button><button data-action="guide">Learn how it works</button><button data-action="status">Show status</button>', true);
        view.webview.onDidReceiveMessage((message: { action?: string }) => {
            const command = { setup: 'vessel.setup', guide: 'vessel.openGuide', status: 'vessel.showStatus' }[message?.action ?? ''];
            if (command) { void vscode.commands.executeCommand(command); }
        });
    }
}
