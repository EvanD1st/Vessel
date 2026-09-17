import { LocalError, runProcess } from './security';

export type JsonObject = { [key: string]: unknown };
const messages: Record<string, string> = {
    not_enrolled: 'This workspace is not enrolled. Run Set Up VESSEL.',
    review_changed: 'The reviewed inputs changed. Refresh and review again.',
    configuration_conflict: 'Existing settings or hooks conflict with this setup. No conflicting files were overwritten.',
    unsupported_cline: 'Unsupported Cline build. No compatibility files were changed.',
    owner_action_blocked: 'The owner action did not pass VESSEL checks. Inspect capture, ownership, environment and unresolved operations in Status.',
    provider_rejected: 'Orbio did not verify this key and model pair. Check the key, connection and model availability.',
    companion_failed: 'The companion could not start. Inspect status and the selected local port before retrying.',
    invalid_request: 'The local request was invalid. Refresh status and retry.',
    local_operation_failed: 'The local operation failed. Existing recovery data was preserved; inspect status before retrying.'
};

/** Executes only a module in the extension-managed interpreter, never project code. */
export class PythonCli {
    constructor(readonly python: string, readonly storage: string) {}
    async request<T = JsonObject>(action: string, payload: JsonObject = {}, timeout = 40000): Promise<T> {
        const raw = await runProcess(this.python, ['-I', '-m', 'vessel.extension_api'], {
            input: JSON.stringify({ ...payload, schema: 1, action, storage: this.storage }), timeout, cwd: this.storage
        });
        let response: { schema?: number; ok?: boolean; result?: T; code?: string };
        try { response = JSON.parse(raw); } catch { throw new LocalError('invalid_response', 'The local runtime returned an invalid response.'); }
        if (response.schema !== 1 || typeof response.ok !== 'boolean') { throw new LocalError('invalid_response', 'The local runtime protocol is incompatible. Run setup again.'); }
        if (!response.ok) { throw new LocalError(response.code ?? 'local_operation_failed', messages[response.code ?? ''] ?? messages.local_operation_failed); }
        if (!Object.prototype.hasOwnProperty.call(response, 'result')) { throw new LocalError('invalid_response', 'The local runtime returned no result.'); }
        return response.result as T;
    }
}
