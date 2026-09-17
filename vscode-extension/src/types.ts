export type CheckState = 'passed' | 'failed' | 'pending' | 'skipped' | 'unsupported' | 'unknown';
export const STEPS = ['requirements', 'project', 'provider', 'models', 'review', 'configure', 'verify', 'finish'] as const;
export type Step = typeof STEPS[number];
export interface SetupState {
    schema: 1; workspace: string; steps: Record<Step, CheckState>; updated: number;
    credentialVersion?: string; previousCredentialVersion?: string; models?: string[];
    verifiedAt?: number; transaction?: string; review?: string; configured?: boolean; errorCode?: string;
    compatibilityBackup?: string; compatibilityExtension?: string; compatibilityOwned?: boolean;
    binding?: { run: string; epoch: number }; paused?: boolean;
}
export interface Compatibility {
    version: string | null; platform: string; supported: boolean; mode: string; state: string;
    bundle_sha256: string | null; restore_available: boolean; reload_required: boolean;
    evidence: string; verified_date: string;
}
export interface Snapshot {
    enrollment: { workspace: string; id: string };
    policy_revision: number; policy: { mission: string; revision: number; allowed_models: string[] };
    lease: { holder_run_id: string; execution_epoch: number; status: string; policy_revision: number } | null;
    lease_stale: boolean; capture: { state: string; gaps: string[]; last_observation: number | null };
    companion: { running: boolean; status?: string; port?: number };
    bridge: { capture_worker_running: boolean; worker_error: string | null };
    gateway: { running: boolean; status?: string; port?: number; credential_version?: string };
    gateway_config: { port: number; models: string[]; paused: boolean; credential_version: string; verified_at: number } | null;
    configuration: { installed: boolean; server_name?: string; missing_hooks?: string[] };
    sessions: Array<{ id: string; active: boolean; run_id?: string; last_observation?: number }>;
    runs: Array<{ id: string; native_session_id: string; status: string; stop_evidence?: { note: string } }>;
    tasks: Array<{ id: string; run_id: string; description: string; status: string }>;
    operations: Array<{ id: string; uncertain: boolean; successful: boolean }>;
    checkpoints: Array<{ id: string; run_id: string; created_at: number; validation: { eligible: boolean; blockers: string[] } }>;
    recoveries: Recovery[];
}
export interface Recovery {
    id: string; status: string; destination_session: string; destination_run_id?: string; review_token: string;
    continuation?: { operation_id: string }; preflight: { blockers: string[]; context: unknown; context_bytes: number; context_budget: number };
}
export interface Plan {
    id: string; review: string; status: string; changes: string[]; processes: string[]; models: string[]; gateway_port: number;
    plan: { state: string; mission: string; existing_enrollment: boolean; other_enabled_servers: string[];
        profile: { workspace: string; port: number; origin: string; mcp_config: string; python: string } };
}
