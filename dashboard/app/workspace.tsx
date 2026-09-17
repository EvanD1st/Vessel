'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import {
  Activity,
  ArrowRight,
  CheckCheck,
  Database,
  History,
  Layers3,
  Link2,
  LockKeyhole,
  Plus,
  Radio,
  RefreshCw,
  ShieldCheck,
  Trash2,
  Unplug,
  Wallet,
  TriangleAlert,
  Settings,
  LogOut,
} from 'lucide-react';
import {
  Sidebar,
  SidebarProvider,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarMenu,
  SidebarMenuItem,
  SidebarMenuButton,
  SidebarTrigger,
} from '@/components/ui/sidebar';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  NativeSelect,
  NativeSelectOption,
} from '@/components/ui/native-select';
import { accountStorage } from '@/lib/account-storage';
import { notifyAccountChange } from './account-boundary';
import OwnerAction, { makeAction, type ActionSpec } from './owner-action';
import {
  companion,
  CompanionError,
  connectionLink,
  when,
  short,
  type Connection,
  type Session,
  type Snapshot,
  type Task,
} from '@/lib/vessel';
import {
  readPairing,
  savePairing,
  pairCompanion,
  resumePairing,
  removePairing,
  startReconnection,
  type Pairing,
  type Connected,
} from '@/lib/pairing';
const navigation = [
  { name: 'Overview', icon: Activity },
  { name: 'Tasks', icon: CheckCheck },
  { name: 'Checkpoints', icon: Database },
  { name: 'Recovery', icon: History },
  { name: 'Funding', icon: Wallet },
];

export default function Workspace({
  signedIn,
  accountId,
}: {
  signedIn: boolean;
  accountId: string;
}) {
  const storedPairing = useCallback(
    (enrollmentId: string): Pairing | null => {
      try {
        return readPairing(
          accountStorage(localStorage, accountId),
          enrollmentId,
        );
      } catch {
        return null;
      }
    },
    [accountId],
  );
  const [view, setView] = useState('Overview'),
    [connecting, setConnecting] = useState(false),
    [origin, setOrigin] = useState('');
  const [link, setLink] = useState(''),
    [label, setLabel] = useState('My agent'),
    [connectBusy, setConnectBusy] = useState(false),
    [connectError, setConnectError] = useState('');
  const [session, setSession] = useState<Session | null>(null),
    [snapshot, setSnapshot] = useState<Snapshot | null>(null),
    [live, setLive] = useState(false);
  const [saved, setSaved] = useState<Connection[]>([]),
    [savedLoading, setSavedLoading] = useState(true),
    [savedError, setSavedError] = useState('');
  const [message, setMessage] = useState(''),
    [connectionError, setConnectionError] = useState(''),
    [action, setAction] = useState<ActionSpec | null>(null);
  const [taskRun, setTaskRun] = useState(''),
    [taskState, setTaskState] = useState('all'),
    [taskSearch, setTaskSearch] = useState('');
  const sessionRef = useRef<Session | null>(null),
    polling = useRef(false),
    snapshotRef = useRef<Snapshot | null>(null),
    liveRef = useRef(false);
  const pairingRef = useRef<Pairing | null>(null),
    connectionGeneration = useRef(0),
    reconnectAllowed = useRef(true);
  const acceptConnection = useCallback((connected: Connected) => {
    sessionRef.current = connected.session;
    pairingRef.current = connected.pairing;
    snapshotRef.current = connected.snapshot;
    liveRef.current = true;
    setSession(connected.session);
    setSnapshot(connected.snapshot);
    setLive(true);
    setConnectionError('');
  }, []);
  useEffect(() => {
    snapshotRef.current = snapshot;
    liveRef.current = live;
  }, [snapshot, live]);
  useEffect(() => {
    let cancelled = false;
    const origin = window.location.origin;
    let connection = '';
    if (window.location.hash.startsWith('#connect=')) {
      connection = window.location.hash.slice(1);
      window.history.replaceState(
        null,
        '',
        window.location.pathname + window.location.search,
      );
    }
    // Import browser-only connection state after hydration, and immediately
    // remove its private fragment from the current history entry.
    queueMicrotask(() => {
      if (cancelled) return;
      setOrigin(origin);
      if (connection) {
        setLink(connection);
        setConnecting(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);
  const loadSaved = useCallback(async () => {
    await Promise.resolve();
    if (!signedIn) {
      setSavedLoading(false);
      return;
    }
    setSavedError('');
    setSavedLoading(true);
    try {
      const response = await fetch('/api/connections', { cache: 'no-store' });
      const data = (await response.json()) as {
        error?: string;
        connections: Connection[];
      };
      if (!response.ok) throw new Error(data.error);
      setSaved(data.connections);
    } catch (error) {
      setSavedError(
        error instanceof Error
          ? error.message
          : 'Saved connections are unavailable.',
      );
    } finally {
      setSavedLoading(false);
    }
  }, [signedIn]);
  useEffect(() => {
    const timer = setTimeout(() => {
      void loadSaved();
    }, 0);
    return () => clearTimeout(timer);
  }, [loadSaved]);
  useEffect(() => {
    if (!signedIn || !saved.length) return;
    return startReconnection(
      async () => {
        if (sessionRef.current || !reconnectAllowed.current || connecting)
          return null;
        const generation = connectionGeneration.current;
        let failure: unknown;
        for (const item of saved) {
          const pairing = storedPairing(item.enrollmentId);
          if (!pairing) continue;
          try {
            const connected = await resumePairing({
              ...pairing,
              port: item.port,
            });
            if (
              generation !== connectionGeneration.current ||
              !reconnectAllowed.current
            )
              return null;
            return connected;
          } catch (error) {
            failure = error;
          }
        }
        if (failure) throw failure;
        return null;
      },
      (connected) => {
        if (sessionRef.current || !reconnectAllowed.current) return;
        acceptConnection(connected);
      },
      (error) => {
        if (!reconnectAllowed.current) return;
        setConnectionError(
          error instanceof Error
            ? error.message
            : 'Waiting for the local companion to start.',
        );
      },
    );
  }, [saved, signedIn, connecting, acceptConnection, storedPairing]);
  const refresh = useCallback(async () => {
    const current = sessionRef.current;
    if (!current || polling.current) return;
    polling.current = true;
    try {
      const pairing = pairingRef.current;
      let state: Snapshot;
      try {
        state = await companion<Snapshot>(current, '/v1/snapshot');
      } catch (error) {
        if (
          !(error instanceof CompanionError) ||
          error.status !== 401 ||
          !pairing
        )
          throw error;
        const connected = await resumePairing(pairing);
        if (sessionRef.current === current) acceptConnection(connected);
        return;
      }
      if (sessionRef.current !== current) return;
      if (pairing && state.bridge.renew_after <= Date.now() / 1000) {
        const connected = await resumePairing(pairing);
        if (sessionRef.current === current) acceptConnection(connected);
        return;
      }
      setSnapshot(state);
      setLive(true);
      setConnectionError('');
    } catch (error) {
      if (sessionRef.current === current) {
        setLive(false);
        setConnectionError(
          error instanceof Error
            ? error.message
            : 'Companion is unreachable. Keep the local terminal running and allow this site to reach your local network.',
        );
      }
    } finally {
      polling.current = false;
    }
  }, [acceptConnection]);
  useEffect(() => {
    if (!session) return;
    const timer = setInterval(() => {
      void refresh();
    }, 5000);
    return () => clearInterval(timer);
  }, [session, refresh]);
  useEffect(
    () => () => {
      sessionRef.current = null;
      connectionGeneration.current += 1;
    },
    [],
  );
  async function connect(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!signedIn) return;
    setConnectBusy(true);
    setConnectError('');
    reconnectAllowed.current = false;
    const generation = ++connectionGeneration.current;
    try {
      const connected = await pairCompanion(connectionLink(link), label.trim());
      if (generation !== connectionGeneration.current) return;
      const { session: next, snapshot: state } = connected;
      acceptConnection(connected);
      setConnecting(false);
      setLink('');
      setTaskRun('');
      setMessage(
        'Companion connected. Review the current run before starting background capture.',
      );
      try {
        savePairing(accountStorage(localStorage, accountId), connected.pairing);
      } catch {
        setMessage(
          'Connected for this visit, but this browser could not save its device pairing.',
        );
      }

      try {
        const response = await fetch('/api/connections', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            enrollmentId: state.enrollment.id,
            label: label.trim(),
            port: next.port,
          }),
        });
        const data = (await response.json()) as {
          error?: string;
          connections: Connection[];
        };
        if (!response.ok) throw new Error(data.error);
        await loadSaved();
      } catch (error) {
        setSavedError(
          error instanceof Error
            ? error.message
            : 'Connected locally, but the label could not be saved.',
        );
      }
    } catch (error) {
      setConnectError(
        error instanceof Error
          ? error.message
          : 'Connection failed. Keep the companion running, use its fresh connection link, and allow local network access when your browser asks.',
      );
    } finally {
      setConnectBusy(false);
    }
  }
  function disconnect() {
    connectionGeneration.current += 1;
    reconnectAllowed.current = false;
    sessionRef.current = null;
    pairingRef.current = null;
    setSession(null);
    setSnapshot(null);
    setLive(false);
    setAction(null);
    setConnectionError('');
    setMessage(
      'Dashboard disconnected. Background capture continues in the local companion until that process stops.',
    );
  }
  async function removeSaved(enrollmentId: string, port?: number) {
    connectionGeneration.current += 1;
    reconnectAllowed.current = false;
    try {
      const pairing =
        pairingRef.current?.enrollmentId === enrollmentId
          ? pairingRef.current
          : storedPairing(enrollmentId);
      if (pairing) {
        // Keep the credential and label on network failure so revocation can be retried.
        await removePairing(accountStorage(localStorage, accountId), {
          ...pairing,
          port: port ?? pairing.port,
        });
        if (snapshotRef.current?.enrollment.id === enrollmentId) disconnect();
      }
      const response = await fetch('/api/connections', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enrollmentId }),
      });
      const data = (await response.json()) as {
        error?: string;
        connections: Connection[];
      };
      if (!response.ok) throw new Error(data.error);
      await loadSaved();
    } catch (error) {
      setSavedError(
        error instanceof Error
          ? error.message
          : 'Could not remove the saved label.',
      );
    }
  }
  async function connectSaved(item: Connection) {
    reconnectAllowed.current = false;
    const generation = ++connectionGeneration.current;
    const pairing = storedPairing(item.enrollmentId);
    if (!pairing) {
      setLabel(item.label);
      setConnecting(true);
      return;
    }
    setConnectBusy(true);
    setConnectError('');
    try {
      const connected = await resumePairing({ ...pairing, port: item.port });
      if (generation !== connectionGeneration.current) return;
      acceptConnection(connected);
      setTaskRun('');
      setAction(null);
    } catch (error) {
      setConnectionError(
        error instanceof Error
          ? error.message
          : 'Could not reconnect the companion.',
      );
      setLabel(item.label);
      setConnecting(true);
    } finally {
      setConnectBusy(false);
    }
  }
  function openAction(name: string, payload: Record<string, unknown> = {}) {
    if (snapshot && live && session)
      setAction(makeAction(name, snapshot, payload));
  }
  // WebMCP exposes only a read and navigation. It cannot invoke owner mutations.
  useEffect(() => {
    type Tool = {
      name: string;
      title: string;
      description: string;
      inputSchema: object;
      annotations: { readOnlyHint: boolean; untrustedContentHint: boolean };
      execute: (input: unknown) => unknown;
    };
    const context = (
      document as Document & {
        modelContext?: {
          registerTool: (
            tool: Tool,
            options: { signal: AbortSignal },
          ) => void | Promise<void>;
        };
      }
    ).modelContext;
    if (!context?.registerTool) return;
    const lifecycle = new AbortController();
    const tools: Tool[] = [
      {
        name: 'read_vessel_status',
        title: 'Read VESSEL status',
        description:
          'Read the connected companion’s reported mission, capture state and counts. Does not read files or change policy, execution or funding.',
        inputSchema: {
          type: 'object',
          properties: {},
          additionalProperties: false,
        },
        annotations: { readOnlyHint: true, untrustedContentHint: true },
        execute(input) {
          if (
            !input ||
            typeof input !== 'object' ||
            Array.isArray(input) ||
            Object.keys(input).length
          )
            throw new Error('Use an empty object.');
          const state = snapshotRef.current;
          return state
            ? {
                connected: liveRef.current,
                mission: state.policy.mission,
                policyRevision: state.policy.revision,
                execution: state.lease?.execution_epoch,
                capture: state.capture,
                taskCount: state.tasks.length,
                checkpointCount: state.checkpoints.length,
              }
            : { connected: false };
        },
      },
      {
        name: 'navigate_vessel',
        title: 'Open VESSEL section',
        description:
          'Open Overview, Tasks, Checkpoints, Recovery or Funding. Navigation only; no owner action is performed.',
        inputSchema: {
          type: 'object',
          properties: {
            section: { type: 'string', enum: navigation.map((n) => n.name) },
          },
          required: ['section'],
          additionalProperties: false,
        },
        annotations: { readOnlyHint: false, untrustedContentHint: false },
        async execute(input) {
          if (
            !input ||
            typeof input !== 'object' ||
            Array.isArray(input) ||
            Object.keys(input).length !== 1 ||
            !('section' in input) ||
            typeof input.section !== 'string' ||
            !navigation.some((n) => n.name === input.section)
          )
            throw new Error('Choose a valid section.');
          setView(input.section);
          await new Promise<void>((resolve) =>
            requestAnimationFrame(() => resolve()),
          );
          return { opened: input.section, ownerActionPerformed: false };
        },
      },
    ];
    for (const tool of tools)
      try {
        void Promise.resolve(
          context.registerTool(tool, { signal: lifecycle.signal }),
        ).catch(() => {});
      } catch {
        /* Unsupported registry leaves the ordinary UI available. */
      }
    return () => lifecycle.abort();
  }, []);
  const currentRun = snapshot?.runs.find(
    (run) => run.id === snapshot.lease?.holder_run_id,
  );
  const selectedRun = taskRun || snapshot?.lease?.holder_run_id || '';
  const tasks = (snapshot?.tasks ?? []).filter(
    (task) =>
      task.run_id === selectedRun &&
      (taskState === 'all' || task.status === taskState) &&
      `${task.id} ${task.description}`
        .toLowerCase()
        .includes(taskSearch.toLowerCase()),
  );
  const currentTasks = (snapshot?.tasks ?? []).filter(
    (task) => task.run_id === snapshot?.lease?.holder_run_id,
  );
  const proposals =
    snapshot?.proposals.filter((proposal) => !proposal.decision) ?? [];
  const mutate = !!snapshot && live,
    active = mutate && snapshot?.lease?.status === 'active',
    paused = mutate && snapshot?.lease?.status === 'paused';
  function editTask(task: Task) {
    openAction('task', {
      run_id: task.run_id,
      task_id: task.id,
      description: task.description,
      status: task.status,
      dependencies: task.dependencies.join(', '),
      evidence: task.evidence ?? '',
    });
  }
  function connectButton(text = 'Connect a companion') {
    return (
      <Button className="primary-action" onClick={() => setConnecting(true)}>
        <Plus size={17} />
        {text}
      </Button>
    );
  }
  return (
    <SidebarProvider>
      <Sidebar>
        <SidebarHeader className="brand">
          <Layers3 size={26} />
          <span>VESSEL</span>
          <small>WORKSPACE</small>
        </SidebarHeader>
        <SidebarContent className="nav-content">
          <p className="nav-label">YOUR AGENTS</p>
          <SidebarMenu>
            {navigation.map(({ name, icon: Icon }) => (
              <SidebarMenuItem key={name}>
                <SidebarMenuButton
                  isActive={view === name}
                  onClick={() => setView(name)}
                  className="nav-item"
                >
                  <Icon />
                  <span>{name}</span>
                  {name === 'Tasks' && proposals.length > 0 && (
                    <small>{proposals.length}</small>
                  )}
                </SidebarMenuButton>
              </SidebarMenuItem>
            ))}
          </SidebarMenu>
        </SidebarContent>
        <SidebarFooter className="sidebar-bottom">
          <div className="custody-note">
            <LockKeyhole size={17} />
            <div>
              Local custody<p>Project files stay on your machine.</p>
            </div>
          </div>
          <span className="preview-label">
            PRIVATE PREVIEW <span>0.3</span>
          </span>
        </SidebarFooter>
      </Sidebar>
      <main className="workspace">
        <header className="topbar">
          <div>
            <SidebarTrigger />
            <span>Your workspace</span>
            <span className="slash">/</span>
            <strong>{view}</strong>
          </div>
          <span className={`status ${live ? 'online' : ''}`}>
            <i />
            {live
              ? 'Companion connected'
              : snapshot
                ? 'Connection interrupted'
                : 'No companion connected'}
          </span>
        </header>
        <div className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">CONTINUITY CONTROL</p>
              <h1>
                {view === 'Overview' ? 'Keep your work within reach.' : view}
              </h1>
              <p className="subheading">
                {view === 'Funding'
                  ? 'Inference access and funding availability.'
                  : 'Your agent’s progress, checkpoints and next steps.'}
              </p>
            </div>
            <div className="button-row">
              {session ? (
                <>
                  <Button
                    variant="outline"
                    onClick={() => void refresh()}
                    aria-label="Refresh companion status"
                  >
                    <RefreshCw size={16} />
                    Refresh
                  </Button>
                  <Button variant="outline" onClick={disconnect}>
                    <Unplug size={16} />
                    Disconnect
                  </Button>
                </>
              ) : (
                connectButton()
              )}
            </div>
          </div>
          {message && (
            <output className="notice info">
              {message}
              <button
                onClick={() => setMessage('')}
                aria-label="Dismiss update"
              >
                ×
              </button>
            </output>
          )}
          {connectionError && (
            <div role="alert" className="notice error">
              <TriangleAlert size={18} />
              <div>
                {connectionError}
                <p>
                  Displayed records may be stale. Owner actions are disabled
                  until the connection returns.
                </p>
              </div>
              <Button variant="outline" onClick={() => setConnecting(true)}>
                Reconnect
              </Button>
            </div>
          )}
          {view === 'Overview' && (
            <>
              <section className="metrics" aria-label="Workspace status">
                <div>
                  <span>CONNECTED COMPANIONS</span>
                  <strong>
                    {live ? '1' : '0'} <Radio size={22} />
                  </strong>
                  <p>
                    {live
                      ? 'Live state from this computer'
                      : 'Waiting for a local connection'}
                  </p>
                </div>
                <div>
                  <span>SAVED CHECKPOINTS</span>
                  <strong>
                    {snapshot?.checkpoints.length ?? '—'} <Database size={22} />
                  </strong>
                  <p>
                    {snapshot
                      ? `Latest: ${when(snapshot.recovery_window.last_checkpoint_at)}`
                      : 'No capture history received'}
                  </p>
                </div>
                <div>
                  <span>LAST VERIFIED BACKUP</span>
                  <strong className="metric-date">
                    {when(
                      snapshot?.recovery_window.last_verified_backup
                        ?.created_at,
                    )}{' '}
                    <ShieldCheck size={22} />
                  </strong>
                  <p>Same-user local backup</p>
                </div>
              </section>
              {snapshot ? (
                <div className="overview-grid">
                  <section className="panel">
                    <div className="section-heading">
                      <h2>
                        {saved.find(
                          (item) =>
                            item.enrollmentId === snapshot.enrollment.id,
                        )?.label ?? 'Connected agent'}
                      </h2>
                      <span className="pill">
                        Capture {snapshot.capture.state}
                      </span>
                    </div>
                    <div className="panel-body">
                      <p className="eyebrow">CURRENT MISSION</p>
                      <h2 className="mission">{snapshot.policy.mission}</h2>
                      <p className="path-text">
                        {snapshot.enrollment.workspace}
                      </p>
                      <dl className="facts">
                        <div>
                          <dt>Current conversation</dt>
                          <dd>
                            {currentRun?.native_session_id ?? 'Not bound'}
                          </dd>
                        </div>
                        <div>
                          <dt>Execution</dt>
                          <dd>
                            {snapshot.lease
                              ? `${snapshot.lease.execution_epoch} · ${snapshot.lease.status}${snapshot.lease_stale && snapshot.lease.status === 'active' ? ' · heartbeat expired' : ''}`
                              : 'No run started'}
                          </dd>
                        </div>
                        <div>
                          <dt>Background capture</dt>
                          <dd>
                            {snapshot.bridge.capture_worker_running
                              ? 'Running in companion'
                              : 'Not running'}
                          </dd>
                        </div>
                        <div>
                          <dt>Observed activity</dt>
                          <dd>{when(snapshot.capture.last_observation)}</dd>
                        </div>
                        <div>
                          <dt>Tasks completed</dt>
                          <dd>
                            {
                              currentTasks.filter(
                                (task) => task.status === 'done',
                              ).length
                            }{' '}
                            of {currentTasks.length}
                          </dd>
                        </div>
                        <div>
                          <dt>Connection expires</dt>
                          <dd>{when(snapshot.bridge.expires_at)}</dd>
                        </div>
                      </dl>
                      {snapshot.bridge.worker_error && (
                        <div className="notice error">
                          Capture worker stopped: {snapshot.bridge.worker_error}
                          . Inspect the local companion before restarting.
                        </div>
                      )}
                      {!!snapshot.capture.gaps.length && (
                        <div className="notice error">
                          <div>
                            <strong>Capture requires attention</strong>
                            <ul>
                              {snapshot.capture.gaps.map((gap) => (
                                <li key={gap}>{gap}</li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      )}
                      <div className="button-row wrap">
                        {!snapshot.lease ||
                        snapshot.lease.status === 'closed' ? (
                          <Button
                            disabled={!mutate}
                            onClick={() => openAction('start')}
                          >
                            Bind new conversation
                          </Button>
                        ) : (
                          <>
                            <Button
                              disabled={
                                !active ||
                                snapshot.bridge.capture_worker_running
                              }
                              onClick={() => openAction('keep-capturing')}
                            >
                              Start capture
                            </Button>
                            <Button
                              variant="outline"
                              disabled={!active}
                              onClick={() => openAction('stop')}
                            >
                              Record stopped writer
                            </Button>
                            <Button
                              variant="outline"
                              disabled={!paused}
                              onClick={() => openAction('checkpoint')}
                            >
                              Capture checkpoint
                            </Button>
                            <Button
                              variant="outline"
                              disabled={!paused}
                              onClick={() => openAction('finish-run')}
                            >
                              Close run
                            </Button>
                          </>
                        )}
                      </div>
                    </div>
                  </section>
                  <aside className="panel policy-panel">
                    <p className="eyebrow">
                      OWNER POLICY · {snapshot.policy.revision}
                    </p>
                    <h2>Your approved boundaries</h2>
                    <ul>
                      {snapshot.policy.restrictions.map((r, i) => (
                        <li key={i}>{r}</li>
                      ))}
                    </ul>
                    <p>
                      Recovery{' '}
                      {snapshot.policy.recovery_allowed
                        ? 'allowed after review'
                        : 'disabled'}
                    </p>
                    <p>
                      Models:{' '}
                      {snapshot.policy.allowed_models.join(', ') ||
                        'None approved'}
                    </p>
                    <div className="stack">
                      <Button
                        variant="outline"
                        disabled={!active}
                        onClick={() => openAction('revalidate-policy')}
                      >
                        Review policy for current run
                      </Button>
                      <Button
                        variant="outline"
                        disabled={!mutate}
                        onClick={() => openAction('review-environment')}
                      >
                        Review environment
                      </Button>
                      <Button
                        variant="outline"
                        disabled={!mutate || !snapshot.capture.gaps.length}
                        onClick={() => openAction('repair-capture')}
                      >
                        Record capture repair
                      </Button>
                    </div>
                  </aside>
                </div>
              ) : (
                <div className="overview-grid">
                  <section className="panel connect-panel">
                    <div className="section-heading">
                      <h2>Your agents</h2>
                      <span className="pill">Ready to connect</span>
                    </div>
                    <div className="empty-agent">
                      <div className="empty-icon">
                        <Link2 size={34} />
                      </div>
                      <h2>Give your agent a place to return.</h2>
                      <p>
                        Connect the VESSEL companion to an approved project.
                        Checkpoints and observed progress will appear here.
                      </p>
                      {connectButton('Connect your first companion')}
                    </div>
                    <div className="capture-note">
                      <ShieldCheck size={20} />
                      <p>
                        A saved checkpoint preserves recorded work. Recovery
                        still checks the project and asks you to review the
                        handover.
                      </p>
                    </div>
                  </section>
                  <aside className="panel setup-panel">
                    <p className="eyebrow">GET CONNECTED</p>
                    <h2>
                      A small setup.
                      <br />A durable history.
                    </h2>
                    <ol>
                      {[
                        [
                          '01',
                          'Choose your project',
                          'Enroll one folder with the local companion.',
                        ],
                        [
                          '02',
                          'Link this workspace',
                          'Approve the connection on your machine.',
                        ],
                        [
                          '03',
                          'Keep working in Cline',
                          'Inspect what was captured before recovering.',
                        ],
                      ].map(([n, title, detail]) => (
                        <li key={n}>
                          <span>{n}</span>
                          <div>
                            <strong>{title}</strong>
                            <p>{detail}</p>
                          </div>
                        </li>
                      ))}
                    </ol>
                    <div className="setup-foot">
                      Your computer must be running for local capture.
                    </div>
                  </aside>
                </div>
              )}
              <section className="panel saved-panel">
                <div className="section-heading">
                  <h2>Saved connections</h2>
                  <span className="muted">Labels only · up to 20</span>
                </div>
                {savedLoading ? (
                  <output className="panel-body">Loading saved labels…</output>
                ) : saved.length ? (
                  <div className="saved-list">
                    {saved.map((item) => (
                      <div key={item.enrollmentId}>
                        <div>
                          <strong>{item.label}</strong>
                          <p>
                            {snapshot?.enrollment.id === item.enrollmentId &&
                            live
                              ? 'Connected now'
                              : 'Offline · reconnect with this paired browser'}
                          </p>
                        </div>
                        <div className="button-row">
                          <Button
                            variant="outline"
                            onClick={() => void connectSaved(item)}
                            disabled={connectBusy}
                          >
                            Connect
                          </Button>
                          <Button
                            variant="ghost"
                            aria-label={`Forget ${item.label}`}
                            onClick={() =>
                              void removeSaved(item.enrollmentId, item.port)
                            }
                          >
                            <Trash2 size={16} />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="panel-body muted">
                    {signedIn
                      ? 'Connection labels appear here after you connect.'
                      : 'Sign in to save connection labels across visits.'}
                  </p>
                )}
                {savedError && (
                  <div role="alert" className="notice error">
                    {savedError}
                    <Button variant="outline" onClick={() => void loadSaved()}>
                      Retry
                    </Button>
                  </div>
                )}
              </section>
            </>
          )}
          {view === 'Tasks' &&
            (snapshot ? (
              <>
                <section className="panel">
                  <div className="section-heading">
                    <h2>Task ledger</h2>
                    <Button
                      disabled={!active}
                      onClick={() => openAction('task')}
                    >
                      Add task
                    </Button>
                  </div>
                  <div className="filter-row">
                    <label htmlFor="task-run">
                      Run
                      <NativeSelect
                        id="task-run"
                        value={selectedRun}
                        onChange={(event) => setTaskRun(event.target.value)}
                      >
                        {snapshot.runs.map((run) => (
                          <NativeSelectOption key={run.id} value={run.id}>
                            Execution {run.execution_epoch} · {run.status}
                          </NativeSelectOption>
                        ))}
                      </NativeSelect>
                    </label>
                    <label htmlFor="task-state">
                      State
                      <NativeSelect
                        id="task-state"
                        value={taskState}
                        onChange={(event) => setTaskState(event.target.value)}
                      >
                        {['all', 'pending', 'active', 'blocked', 'done'].map(
                          (state) => (
                            <NativeSelectOption key={state} value={state}>
                              {state}
                            </NativeSelectOption>
                          ),
                        )}
                      </NativeSelect>
                    </label>
                    <label className="search-field" htmlFor="task-search">
                      Search
                      <Input
                        id="task-search"
                        value={taskSearch}
                        onChange={(event) => setTaskSearch(event.target.value)}
                        placeholder="Task name or ID"
                      />
                    </label>
                  </div>
                  {tasks.length ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Task</TableHead>
                          <TableHead>State</TableHead>
                          <TableHead>Evidence & dependencies</TableHead>
                          <TableHead>
                            <span className="sr-only">Actions</span>
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {tasks.map((task) => (
                          <TableRow key={task.id}>
                            <TableCell>
                              <strong>{task.description}</strong>
                              <small>{task.id}</small>
                            </TableCell>
                            <TableCell>
                              <span className="pill">{task.status}</span>
                            </TableCell>
                            <TableCell>
                              <small>
                                {task.evidence
                                  ? short(task.evidence)
                                  : 'Not independently verified'}
                              </small>
                              <small>
                                {task.dependencies.length
                                  ? `Requires: ${task.dependencies.join(', ')}`
                                  : 'No dependencies'}
                              </small>
                            </TableCell>
                            <TableCell>
                              <Button
                                variant="outline"
                                disabled={
                                  !active ||
                                  task.run_id !== snapshot.lease?.holder_run_id
                                }
                                onClick={() => editTask(task)}
                              >
                                Review
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <Empty
                      title="No tasks match this view."
                      text="Choose a different run or filter, or assign the first task to the active run."
                    />
                  )}
                </section>
                <section className="panel saved-panel">
                  <div className="section-heading">
                    <h2>Agent proposals</h2>
                    <span className="pill">
                      {proposals.length} awaiting review
                    </span>
                  </div>
                  {proposals.length ? (
                    <div className="card-list">
                      {proposals.map((proposal) => (
                        <article key={proposal.id}>
                          <div className="button-row spread">
                            <span className="eyebrow">
                              {proposal.kind} · agent claim
                            </span>
                            <small>{short(proposal.id)}</small>
                          </div>
                          <h3>
                            {proposal.payload.mission ??
                              proposal.payload.description}
                          </h3>
                          {proposal.payload.constraints?.length ? (
                            <p>
                              Proposed constraints:{' '}
                              {proposal.payload.constraints.join('; ')}
                            </p>
                          ) : null}
                          {proposal.payload.claimed_status && (
                            <p>
                              Claimed state: {proposal.payload.claimed_status}
                            </p>
                          )}
                          <div className="button-row">
                            <Button
                              disabled={
                                !mutate ||
                                (['task', 'task_update'].includes(
                                  proposal.kind,
                                ) &&
                                  !active)
                              }
                              onClick={() =>
                                openAction('review-proposal', {
                                  proposal_id: proposal.id,
                                  decision: 'accept',
                                  proposal_kind: proposal.kind,
                                })
                              }
                            >
                              Review acceptance
                            </Button>
                            <Button
                              variant="outline"
                              disabled={!mutate}
                              onClick={() =>
                                openAction('review-proposal', {
                                  proposal_id: proposal.id,
                                  decision: 'reject',
                                })
                              }
                            >
                              Review rejection
                            </Button>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <Empty
                      title="No proposals awaiting review."
                      text="Mission and task proposals remain unverified until you review them."
                    />
                  )}
                </section>
                <section className="panel saved-panel">
                  <div className="section-heading">
                    <h2>Observed operations</h2>
                    <span className="muted">Selected run</span>
                  </div>
                  {snapshot.operations.filter((op) => op.run_id === selectedRun)
                    .length ? (
                    <div className="card-list">
                      {snapshot.operations
                        .filter((op) => op.run_id === selectedRun)
                        .map((op) => (
                          <article key={op.id}>
                            <h3>
                              {op.native_id}{' '}
                              <span className="pill">
                                {op.uncertain
                                  ? 'Uncertain'
                                  : op.resolution
                                    ? 'Owner reconciled'
                                    : 'Observed result'}
                              </span>
                            </h3>
                            <code>{op.id}</code>
                            <details>
                              <summary>Inspect recorded receipts</summary>
                              <pre>
                                {JSON.stringify(
                                  {
                                    intent: op.intent,
                                    result: op.result,
                                    resolution: op.resolution,
                                  },
                                  null,
                                  2,
                                )}
                              </pre>
                            </details>
                            {op.uncertain && (
                              <Button
                                variant="outline"
                                disabled={!mutate}
                                onClick={() =>
                                  openAction('resolve-operation', {
                                    operation_id: op.id,
                                  })
                                }
                              >
                                Reconcile result
                              </Button>
                            )}
                          </article>
                        ))}
                    </div>
                  ) : (
                    <Empty
                      title="No operations recorded in this run."
                      text="Observed Cline tool receipts will appear here. A model’s completion claim is not an observed result."
                    />
                  )}
                </section>
              </>
            ) : (
              <Disconnected
                section="tasks"
                onConnect={() => setConnecting(true)}
              />
            ))}
          {view === 'Checkpoints' &&
            (snapshot ? (
              <section className="panel">
                <div className="section-heading">
                  <div>
                    <h2>Checkpoint history</h2>
                    <p className="muted">
                      Select a specific saved point before preparing recovery.
                    </p>
                  </div>
                  <Button
                    disabled={!paused}
                    onClick={() => openAction('checkpoint')}
                  >
                    Capture checkpoint
                  </Button>
                </div>
                {snapshot.checkpoints.length ? (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Captured</TableHead>
                        <TableHead>Source</TableHead>
                        <TableHead>Recorded capture checks</TableHead>
                        <TableHead>
                          <span className="sr-only">Recovery</span>
                        </TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {[...snapshot.checkpoints]
                        .sort((a, b) => b.created_at - a.created_at)
                        .map((cp) => (
                          <TableRow key={cp.id}>
                            <TableCell>
                              <strong>{when(cp.created_at)}</strong>
                              <small>{cp.id}</small>
                            </TableCell>
                            <TableCell>
                              {short(cp.run_id)}
                              <small>
                                {cp.capture_seconds.toFixed(2)}s capture
                              </small>
                            </TableCell>
                            <TableCell>
                              <span className="pill">
                                {cp.capture.blockers.length
                                  ? 'Inspection only'
                                  : 'No recorded capture blockers'}
                              </span>
                              {cp.capture.blockers.map((blocker) => (
                                <small key={blocker}>{blocker}</small>
                              ))}
                            </TableCell>
                            <TableCell>
                              <Button
                                variant="outline"
                                disabled={!mutate}
                                onClick={() =>
                                  openAction('prepare-recovery', {
                                    checkpoint_id: cp.id,
                                  })
                                }
                              >
                                Prepare recovery
                              </Button>
                            </TableCell>
                          </TableRow>
                        ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Empty
                    title="No checkpoints recorded yet."
                    text="Start background capture for inspection snapshots. Stop the writer and record that evidence before taking a checkpoint for recovery."
                  />
                )}
                <div className="capture-note">
                  <ShieldCheck size={20} />
                  <p>
                    Recorded checks describe capture time. Recovery rechecks the
                    current files, environment, policy and execution ownership.
                  </p>
                </div>
              </section>
            ) : (
              <Disconnected
                section="checkpoint history"
                onConnect={() => setConnecting(true)}
              />
            ))}
          {view === 'Recovery' &&
            (snapshot ? (
              <section className="panel">
                <div className="section-heading">
                  <h2>Reviewed recovery</h2>
                  <Button
                    variant="outline"
                    onClick={() => setView('Checkpoints')}
                  >
                    Select checkpoint
                    <ArrowRight size={16} />
                  </Button>
                </div>
                {snapshot.recoveries.length ? (
                  <div className="card-list">
                    {snapshot.recoveries.map((recovery) => (
                      <article key={recovery.id}>
                        <div className="button-row spread">
                          <h3>Destination: {recovery.destination_session}</h3>
                          <span className="pill">
                            {recovery.status.replaceAll('_', ' ')}
                          </span>
                        </div>
                        <p>
                          Checkpoint {short(recovery.checkpoint_id)} · Policy{' '}
                          {recovery.preflight.policy_revision} · Execution{' '}
                          {recovery.preflight.expected_epoch}
                        </p>
                        {recovery.preflight.blockers.length > 0 && (
                          <div className="notice error">
                            <ul>
                              {recovery.preflight.blockers.map((blocker) => (
                                <li key={blocker}>{blocker}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                        <details>
                          <summary>
                            Inspect the prepared context and checks
                          </summary>
                          <pre>
                            {JSON.stringify(recovery.preflight, null, 2)}
                          </pre>
                        </details>
                        <div className="button-row wrap">
                          <Button
                            disabled={
                              !mutate || recovery.status !== 'awaiting_owner'
                            }
                            onClick={() =>
                              openAction('handover', {
                                recovery_id: recovery.id,
                                review_token: recovery.review_token,
                              })
                            }
                          >
                            Review handover
                          </Button>
                          <Button
                            variant="outline"
                            disabled={
                              !mutate ||
                              !recovery.destination_run_id ||
                              recovery.status === 'succeeded'
                            }
                            onClick={() =>
                              openAction('confirm', {
                                recovery_id: recovery.id,
                              })
                            }
                          >
                            Confirm observed continuation
                          </Button>
                          <Button
                            variant="outline"
                            disabled={
                              !mutate ||
                              !!recovery.destination_run_id ||
                              recovery.status === 'cancelled'
                            }
                            onClick={() =>
                              openAction('cancel-recovery', {
                                recovery_id: recovery.id,
                              })
                            }
                          >
                            Cancel pending recovery
                          </Button>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="Every recovery starts with a deliberate choice."
                    text="Choose a source checkpoint, specify a destination conversation, and inspect the prepared plan before transferring execution."
                  />
                )}
                <div className="capture-note">
                  <ShieldCheck size={20} />
                  <p>
                    After handover, use VESSEL’s context tool in the exact
                    destination Cline conversation and start capture for its new
                    execution. A succeeded status means the recorded
                    continuation evidence was verified for that recovery.
                  </p>
                </div>
              </section>
            ) : (
              <Disconnected
                section="recovery plans"
                onConnect={() => setConnecting(true)}
              />
            ))}
          {view === 'Funding' && (
            <section className="panel">
              <div className="section-heading">
                <h2>Inference access</h2>
                <span className="pill">Setup required</span>
              </div>
              <div className="panel-body funding-content">
                <div className="empty-icon">
                  <Wallet size={32} />
                </div>
                <h2>Funding is not connected.</h2>
                <p>
                  VESSEL currently provides local continuity and a configurable
                  inference gateway. Live Orbio account management, wallet
                  ownership, balance reporting and funded model recovery are
                  still pending.
                </p>
                <dl className="facts">
                  <div>
                    <dt>Wallet ownership</dt>
                    <dd>Not implemented</dd>
                  </div>
                  <div>
                    <dt>Orbio funding & key rotation</dt>
                    <dd>Unavailable</dd>
                  </div>
                  <div>
                    <dt>Live gateway inference</dt>
                    <dd>Not verified</dd>
                  </div>
                  <div>
                    <dt>Balance</dt>
                    <dd>Not available</dd>
                  </div>
                </dl>
                <p>
                  Continue using your existing Cline inference configuration.
                  Funding setup requires a supported provider and owner-approved
                  model access.
                </p>
              </div>
            </section>
          )}
          <footer className="page-footer">
            <span>
              <LockKeyhole size={14} />
              Private workspace ·{' '}
              {signedIn
                ? 'Account authenticated'
                : 'Sign-in required for saved connections'}
            </span>
            <div className="footer-actions">
              <Link href="/account" className="account-settings-btn">
                <Settings size={14} /> Account settings
              </Link>
              {signedIn && (
                <Button
                  variant="outline"
                  className="sign-out-btn"
                  onClick={async () => {
                    try {
                      const response = await fetch('/api/session', {
                        method: 'DELETE',
                      });
                      if (!response.ok) throw new Error('Could not sign out.');
                      disconnect();
                      notifyAccountChange();
                      window.location.assign('/');
                    } catch {
                      setMessage('Could not sign out. Please try again.');
                    }
                  }}
                >
                  <LogOut size={14} /> Sign out
                </Button>
              )}
            </div>
          </footer>
        </div>
      </main>
      <Dialog
        open={connecting}
        onOpenChange={(open) => {
          if (!connectBusy) {
            setConnecting(open);
            if (!open) {
              setLink('');
              setConnectError('');
            }
          }
        }}
      >
        <DialogContent className="connect-dialog">
          <DialogHeader>
            <DialogTitle>Connect your companion</DialogTitle>
            <DialogDescription>
              Connect one enrolled local project. Files and encryption keys stay
              on this computer.
            </DialogDescription>
          </DialogHeader>
          {!signedIn ? (
            // oxlint-disable-next-line next/no-html-link-for-pages
            <a className="signin-link" href="/" target="_top">
              Sign in <ArrowRight size={16} />
            </a>
          ) : (
            <form className="owner-form" onSubmit={connect}>
              <ol className="connection-steps">
                <li>
                  Enroll your project using the VESSEL companion, then run this
                  in its terminal:
                  <pre>{`.\\vessel.cmd dashboard --origin '${origin}'`}</pre>
                </li>
                <li>
                  Paste the private connection link printed by that command.
                  Keep the terminal running and allow local network access when
                  your browser asks.
                </li>
              </ol>
              <div className="form-field">
                <label htmlFor="connection-label">Connection label</label>
                <Input
                  id="connection-label"
                  value={label}
                  onChange={(event) => setLabel(event.target.value)}
                  maxLength={80}
                  required
                  placeholder="My agent"
                />
                <small>
                  Only this label, enrollment ID and local port are saved to
                  your private workspace.
                </small>
              </div>
              <div className="form-field">
                <label htmlFor="connection-link">Private connection link</label>
                <Input
                  id="connection-link"
                  type="password"
                  autoComplete="off"
                  value={link}
                  onChange={(event) => setLink(event.target.value)}
                  required
                  spellCheck={false}
                  placeholder="Paste from your local terminal"
                />
                <small>
                  This browser saves a device credential for automatic
                  reconnection. Forget the connection to revoke this browser’s
                  access. Never share the link.
                </small>
              </div>
              {connectError && (
                <div role="alert" className="notice error">
                  {connectError}
                  <p>
                    Check that the link is fresh, the terminal is running, and
                    this site has local network permission.
                  </p>
                </div>
              )}
              <Button
                className="primary-action"
                type="submit"
                disabled={connectBusy || !label.trim()}
              >
                {connectBusy ? 'Connecting…' : 'Connect companion'}
                <Link2 size={16} />
              </Button>
            </form>
          )}
          <small>
            One active local connection per tab. Signed in with your VESSEL
            account. Wallet ownership is pending.
          </small>
        </DialogContent>
      </Dialog>
      {action && session && (
        <OwnerAction
          key={action.id}
          spec={action}
          session={session}
          onClose={() => setAction(null)}
          onResult={(text) => {
            setMessage(text);
            void refresh();
          }}
        />
      )}
    </SidebarProvider>
  );
}
function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="empty-inline">
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
function Disconnected({
  section,
  onConnect,
}: {
  section: string;
  onConnect: () => void;
}) {
  return (
    <section className="panel">
      <div className="empty-agent">
        <div className="empty-icon">
          <Link2 size={32} />
        </div>
        <h2>Connect to inspect {section}.</h2>
        <p>
          Live project records are read directly from your enrolled companion.
          Keep it running on this computer.
        </p>
        <Button onClick={onConnect}>
          Connect companion
          <ArrowRight size={16} />
        </Button>
      </div>
    </section>
  );
}
