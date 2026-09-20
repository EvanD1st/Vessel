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
  RefreshCw,
  ShieldCheck,
  Trash2,
  Unplug,
  Wallet,
  TriangleAlert,
  Settings,
  LogOut,
  Cpu,
  Key,
  ExternalLink,
  Sparkles,
  Search,
  Zap,
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
  type OrbioStatus,
  type OrbioModel,
  type OrbioUsageAnalytics,
  type OperatorIdentityCard,
  getOrbioStatus,
  getOrbioUsage,
  linkOrbioWallet,
  connectOrbioKey,
  replaceOrbioKey,
  forgetOrbioKey,
  refreshOrbioStatus,
  claimOrbioKey,
  getOrbioModels,
  updateOrbioRouting,
} from '@/lib/vessel';
import {
  readPairing,
  savePairing,
  pairCompanion,
  resumePairing,
  removePairing,
  startReconnection,
  importPairingFromIdentity,
  type Pairing,
  type Connected,
} from '@/lib/pairing';
import { IdentityCard } from '@/components/identity-card';
import type { AccountUser } from './account-boundary';

const navigation = [
  { name: 'Overview', icon: Activity },
  { name: 'Identity', icon: ShieldCheck },
  { name: 'Tasks', icon: CheckCheck },
  { name: 'Checkpoints', icon: Database },
  { name: 'Recovery', icon: History },
  { name: 'Orbio', icon: Wallet },
];

export default function Workspace({
  signedIn,
  accountId,
  user,
}: {
  signedIn: boolean;
  accountId: string;
  user?: AccountUser;
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
  const [orbio, setOrbio] = useState<OrbioStatus | null>(null),
    [orbioLoading, setOrbioLoading] = useState(false),
    [orbioError, setOrbioError] = useState(''),
    [orbioKeyInput, setOrbioKeyInput] = useState(''),
    [orbioConnecting, setOrbioConnecting] = useState(false),
    [replacingOrbio, setReplacingOrbio] = useState(false),
    [replaceKeyInput, setReplaceKeyInput] = useState(''),
    [replaceModalOpen, setReplaceModalOpen] = useState(false),
    [forgetModalOpen, setForgetModalOpen] = useState(false),
    [forgettingOrbio, setForgettingOrbio] = useState(false),
    [refreshingOrbio, setRefreshingOrbio] = useState(false);
  const [orbioUsage, setOrbioUsage] = useState<OrbioUsageAnalytics | null>(null),
    [orbioUsageLoading, setOrbioUsageLoading] = useState(false),
    [walletModalOpen, setWalletModalOpen] = useState(false),
    [walletInput, setWalletInput] = useState(''),
    [walletSaving, setWalletSaving] = useState(false);
  const [modelsCatalog, setModelsCatalog] = useState<OrbioModel[]>([]),
    [activeGatewayModel, setActiveGatewayModel] = useState('openrouter/auto'),
    [isSmartRouting, setIsSmartRouting] = useState(false),
    [modelsLoading, setModelsLoading] = useState(false),
    [modelSearch, setModelSearch] = useState(''),
    [selectedProviderFilter, setSelectedProviderFilter] = useState('all'),
    [updatingRouting, setUpdatingRouting] = useState(false),
    [claimingKey, setClaimingKey] = useState(false),
    [claimNoticeModalOpen, setClaimNoticeModalOpen] = useState(false),
    [claimNotice, setClaimNotice] = useState<{ status: string; message: string; url?: string } | null>(null);
  const [currentPairing, setCurrentPairing] = useState<Pairing | null>(null);
  const sessionRef = useRef<Session | null>(null),
    polling = useRef(false),
    snapshotRef = useRef<Snapshot | null>(null),
    liveRef = useRef(false);
  const pairingRef = useRef<Pairing | null>(null),
    connectionGeneration = useRef(0),
    reconnectAllowed = useRef(true);
  const loadOrbioModels = useCallback(async (targetSession?: Session | null) => {
    const activeSession = targetSession ?? sessionRef.current;
    if (!activeSession) return;
    setModelsLoading(true);
    try {
      const data = await getOrbioModels(activeSession);
      setModelsCatalog(data.models);
      setActiveGatewayModel(data.active_model);
      setIsSmartRouting(data.smart_routing);
    } catch {
      // Fallback gracefully
    } finally {
      setModelsLoading(false);
    }
  }, []);
  const loadOrbioUsage = useCallback(async (targetSession?: Session | null) => {
    const activeSession = targetSession ?? sessionRef.current;
    if (!activeSession) {
      setOrbioUsage(null);
      return;
    }
    setOrbioUsageLoading(true);
    try {
      const data = await getOrbioUsage(activeSession);
      setOrbioUsage(data);
    } catch {
      // Fallback gracefully
    } finally {
      setOrbioUsageLoading(false);
    }
  }, []);
  const loadOrbio = useCallback(async (targetSession?: Session | null) => {
    const activeSession = targetSession ?? sessionRef.current;
    if (!activeSession) {
      setOrbio(null);
      setOrbioUsage(null);
      return;
    }
    setOrbioLoading(true);
    try {
      const status = await getOrbioStatus(activeSession);
      setOrbio(status);
      if (status.connected) {
        void loadOrbioModels(activeSession);
        void loadOrbioUsage(activeSession);
      }
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Orbio status is unavailable.',
      );
    } finally {
      setOrbioLoading(false);
    }
  }, [loadOrbioModels, loadOrbioUsage]);
  const acceptConnection = useCallback((connected: Connected) => {
    sessionRef.current = connected.session;
    pairingRef.current = connected.pairing;
    snapshotRef.current = connected.snapshot;
    liveRef.current = true;
    setSession(connected.session);
    setSnapshot(connected.snapshot);
    setCurrentPairing(connected.pairing);
    setLive(true);
    setConnectionError('');
    void loadOrbio(connected.session);
  }, [loadOrbio]);
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

  const operatorProfile = {
    id: user?.userId || accountId || 'usr_operator',
    name: user?.displayName || (user?.email ? user.email.split('@')[0] : 'VESSEL Operator'),
    email: user?.email || 'operator@vessel-dashboard.cloud-ip.cc',
    role: user?.role,
  };

  const activePairing =
    currentPairing ||
    (saved[0] ? storedPairing(saved[0].enrollmentId) : null);

  const handleImportIdentity = useCallback(
    (importedCard: OperatorIdentityCard) => {
      try {
        const storage = accountStorage(localStorage, accountId);
        const pairing = importPairingFromIdentity(storage, importedCard);
        if (pairing) {
          pairingRef.current = pairing;
          if (signedIn) {
            void fetch('/api/connections', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                enrollmentId: pairing.enrollmentId,
                label: importedCard.operator.name
                  ? `${importedCard.operator.name} Companion`
                  : 'Imported Companion',
                port: pairing.port,
              }),
            }).then(() => void loadSaved());
          }
          void resumePairing(pairing)
            .then(acceptConnection)
            .catch((err) => {
              setConnectionError(
                err instanceof Error
                  ? err.message
                  : 'Companion awaiting startup on this system (port ' +
                      pairing.port +
                      ').',
              );
            });
        }
      } catch (err) {
        setConnectionError(
          err instanceof Error ? err.message : 'Could not import identity.',
        );
      }
    },
    [accountId, signedIn, loadSaved, acceptConnection],
  );

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
      void loadOrbio(current);
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
  }, [acceptConnection, loadOrbio]);
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
      const paired = await pairCompanion(connectionLink(link), label.trim());
      if (generation !== connectionGeneration.current) return;
      savePairing(accountStorage(localStorage, accountId), paired.pairing);
      setConnecting(false);
      setLink('');
      acceptConnection(paired);
      setMessage(
        `Paired with companion on port ${paired.session.port}. This browser can reconnect automatically.`,
      );
      const response = await fetch('/api/connections', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enrollmentId: paired.snapshot.enrollment.id,
          label: label.trim(),
          port: paired.session.port,
        }),
      });
      const data = (await response.json()) as {
        error?: string;
        connections: Connection[];
      };
      if (!response.ok) throw new Error(data.error);
      setSaved(data.connections);
    } catch (error) {
      if (generation !== connectionGeneration.current) return;
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
    setCurrentPairing(null);
    setSession(null);
    setSnapshot(null);
    setLive(false);
    setOrbio(null);
    setOrbioError('');
    setAction(null);
    setConnectionError('');
    setMessage(
      'Dashboard disconnected. Background capture continues in the local companion until that process stops.',
    );
  }
  async function handleConnectOrbio(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const current = sessionRef.current;
    if (!current || !orbioKeyInput.trim()) return;
    setOrbioConnecting(true);
    setOrbioError('');
    const rawKey = orbioKeyInput.trim();
    setOrbioKeyInput('');
    try {
      const result = await connectOrbioKey(current, rawKey);
      setMessage(`Orbio key connected and verified (${result.masked_key}).`);
      await loadOrbio(current);
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to connect Orbio key.',
      );
    } finally {
      setOrbioConnecting(false);
    }
  }
  async function handleReplaceOrbio(event: React.SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    const current = sessionRef.current;
    if (!current || !replaceKeyInput.trim()) return;
    setReplacingOrbio(true);
    setOrbioError('');
    const rawKey = replaceKeyInput.trim();
    setReplaceKeyInput('');
    try {
      const result = await replaceOrbioKey(current, rawKey);
      setMessage(`Orbio key replaced and verified (${result.masked_key}).`);
      setReplaceModalOpen(false);
      await loadOrbio(current);
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to replace Orbio key.',
      );
    } finally {
      setReplacingOrbio(false);
    }
  }
  async function handleForgetOrbio() {
    const current = sessionRef.current;
    if (!current) return;
    setForgettingOrbio(true);
    setOrbioError('');
    try {
      await forgetOrbioKey(current);
      setMessage(
        'Orbio credential removed. Gateway paused. Recovery history preserved.',
      );
      setForgetModalOpen(false);
      await loadOrbio(current);
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to forget Orbio key.',
      );
    } finally {
      setForgettingOrbio(false);
    }
  }
  async function handleRefreshOrbio() {
    const current = sessionRef.current;
    if (!current) return;
    setRefreshingOrbio(true);
    setOrbioError('');
    try {
      const status = await refreshOrbioStatus(current);
      setOrbio(status);
      void loadOrbioUsage(current);
      setMessage('Orbio gateway status and usage analytics refreshed.');
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to refresh Orbio status.',
      );
    } finally {
      setRefreshingOrbio(false);
    }
  }
  async function handleLinkWallet(address?: string, action: 'connect' | 'disconnect' = 'connect') {
    const current = sessionRef.current;
    if (!current) return;
    setWalletSaving(true);
    setOrbioError('');
    try {
      const res = await linkOrbioWallet(current, address, action);
      if (res.wallet) {
        setOrbioUsage((prev) => prev ? { ...prev, wallet: res.wallet } : null);
        setMessage(
          action === 'disconnect'
            ? 'Solana wallet unlinked. Tier reset to Community.'
            : `Solana wallet linked! Tier: ${res.wallet.tier_name} (${res.wallet.holdings.toLocaleString()} $ORBIO)`
        );
      }
      setWalletModalOpen(false);
      setWalletInput('');
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to update wallet link.',
      );
    } finally {
      setWalletSaving(false);
    }
  }
  async function handleClaimOrbio() {
    const current = sessionRef.current;
    if (!current) return;
    setClaimingKey(true);
    setOrbioError('');
    try {
      const res = await claimOrbioKey(current);
      if (res.status === 'claimed') {
        setMessage('Orbio API key successfully claimed and registered.');
        await loadOrbio(current);
      } else {
        setClaimNotice({
          status: res.status,
          message:
            res.message ||
            'Orbio Remote MCP is not configured on this machine.',
          url: res.url || 'https://orbio.so',
        });
        setClaimNoticeModalOpen(true);
      }
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to claim key via Orbio MCP.',
      );
    } finally {
      setClaimingKey(false);
    }
  }
  async function handleSelectModel(modelId: string) {
    const current = sessionRef.current;
    if (!current) return;
    setUpdatingRouting(true);
    setOrbioError('');
    try {
      const res = await updateOrbioRouting(current, {
        activeModel: modelId,
        smartRouting: modelId === 'openrouter/auto',
      });
      setActiveGatewayModel(res.active_model);
      setIsSmartRouting(res.smart_routing);
      setMessage(`Inference route updated: default model set to ${res.active_model}.`);
      await loadOrbio(current);
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to update model routing.',
      );
    } finally {
      setUpdatingRouting(false);
    }
  }
  async function handleToggleSmartRouting(enable: boolean) {
    const current = sessionRef.current;
    if (!current) return;
    setUpdatingRouting(true);
    setOrbioError('');
    try {
      const targetModel = enable
        ? 'openrouter/auto'
        : modelsCatalog.find((m) => m.id !== 'openrouter/auto')?.id ||
          'anthropic/claude-sonnet-4.5';
      const res = await updateOrbioRouting(current, {
        activeModel: targetModel,
        smartRouting: enable,
      });
      setActiveGatewayModel(res.active_model);
      setIsSmartRouting(res.smart_routing);
      setMessage(
        enable
          ? 'Smart Dynamic Routing (openrouter/auto) activated.'
          : `Smart routing disabled. Default set to ${res.active_model}.`,
      );
      await loadOrbio(current);
    } catch (err) {
      setOrbioError(
        err instanceof Error ? err.message : 'Failed to toggle smart routing.',
      );
    } finally {
      setUpdatingRouting(false);
    }
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
            <LockKeyhole size={14} />
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
                {view === 'Overview' ? 'Keep your work within reach.' : view === 'Funding' ? 'Orbio' : view}
              </h1>
              <p className="subheading">
                {view === 'Orbio' || view === 'Funding'
                  ? 'First-class inference compute, credential security and gateway status.'
                  : view === 'Overview'
                    ? 'Your agent’s progress, checkpoints and next steps.'
                    : 'Continuity controls and workspace state.'}
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
              <div className="overview-hero">
                <div className="hero-status-row">
                  <div>
                    <span className="hero-eyebrow">AGENT CONTINUITY SYSTEM</span>
                    <h2>
                      {snapshot
                        ? (saved.find(
                            (item) =>
                              item.enrollmentId === snapshot.enrollment.id,
                          )?.label ?? 'Active Agent')
                        : 'No Agent Connected'}
                    </h2>
                  </div>
                  <div
                    className={`product-badge ${
                      !session && !snapshot
                        ? 'pill-offline'
                        : !live && snapshot
                          ? 'pill-offline'
                          : snapshot?.bridge.capture_worker_running &&
                              (!snapshot.capture.gaps ||
                                snapshot.capture.gaps.length === 0) &&
                              snapshot.lease?.status === 'active'
                            ? 'pill-protected'
                            : 'pill-warning'
                    }`}
                  >
                    <span className="badge-dot" />
                    <span>
                      {!session && !snapshot
                        ? 'NOT CONNECTED'
                        : !live && snapshot
                          ? 'COMPANION OFFLINE'
                          : snapshot?.bridge.capture_worker_running &&
                              (!snapshot.capture.gaps ||
                                snapshot.capture.gaps.length === 0) &&
                              snapshot.lease?.status === 'active'
                            ? 'PROTECTED'
                            : 'SETUP REQUIRED'}
                    </span>
                  </div>
                </div>

                {snapshot && (
                  <div className="mission-card">
                    <div className="mission-header">
                      <span className="mission-label">CURRENT MISSION</span>
                      <span className="agent-badge">
                        {saved.find(
                          (item) =>
                            item.enrollmentId === snapshot.enrollment.id,
                        )?.label ?? 'Workspace'}
                      </span>
                    </div>
                    <h3 className="mission-title">{snapshot.policy.mission}</h3>
                    <p className="mission-path">
                      {snapshot.enrollment.workspace}
                    </p>
                    <div className="mission-meta-grid">
                      <div className="meta-item">
                        <span className="meta-label">CURRENT SESSION</span>
                        <span className="meta-value">
                          {currentRun?.native_session_id
                            ? short(currentRun.native_session_id)
                            : 'Unbound'}
                        </span>
                      </div>
                      <div className="meta-item">
                        <span className="meta-label">EXECUTION LEASE</span>
                        <span className="meta-value">
                          {snapshot.lease
                            ? `${snapshot.lease.execution_epoch} · ${snapshot.lease.status}`
                            : 'No lease'}
                        </span>
                      </div>
                      <div className="meta-item">
                        <span className="meta-label">CAPTURE WORKER</span>
                        <span className="meta-value">
                          {snapshot.bridge.capture_worker_running
                            ? 'Watching'
                            : 'Stopped'}
                        </span>
                      </div>
                      <div className="meta-item">
                        <span className="meta-label">INFERENCE PROVIDER</span>
                        <span
                          className="meta-value"
                          style={{
                            color: orbio?.connected ? '#2e7d32' : undefined,
                          }}
                        >
                          {orbio?.connected
                            ? 'Orbio (Connected)'
                            : 'Local Gateway'}
                        </span>
                      </div>
                    </div>
                  </div>
                )}

                <div className="protection-matrix">
                  <div className="matrix-card">
                    <div className="matrix-head">
                      <Database size={16} />
                      <span>CHECKPOINT PROTECTION</span>
                    </div>
                    <div className="matrix-val">
                      {snapshot
                        ? `${snapshot.checkpoints.length} Checkpoints`
                        : '0 Checkpoints'}
                    </div>
                    <p className="matrix-sub">
                      {snapshot
                        ? `Latest: ${when(snapshot.recovery_window.last_checkpoint_at)}`
                        : 'No capture history received'}
                    </p>
                  </div>

                  <div className="matrix-card">
                    <div className="matrix-head">
                      <History size={16} />
                      <span>RECOVERY READINESS</span>
                    </div>
                    <div className="matrix-val">
                      {snapshot?.policy.recovery_allowed
                        ? 'Standby Ready'
                        : 'Review Required'}
                    </div>
                    <p className="matrix-sub">
                      Verified backup:{' '}
                      {when(
                        snapshot?.recovery_window.last_verified_backup
                          ?.created_at,
                      ) || 'None'}
                    </p>
                  </div>

                  <div className="matrix-card">
                    <div className="matrix-head">
                      <Activity size={16} />
                      <span>EXECUTION CONTINUITY</span>
                    </div>
                    <div className="matrix-val">
                      {live ? 'Live Stream' : 'Disconnected'}
                    </div>
                    <p className="matrix-sub">
                      {snapshot?.lease
                        ? `Epoch ${snapshot.lease.execution_epoch} · ${snapshot.lease.status}`
                        : 'Waiting for conversation lease'}
                    </p>
                  </div>

                  <div className="matrix-card">
                    <div className="matrix-head">
                      <Cpu size={16} />
                      <span>INFERENCE GATEWAY</span>
                    </div>
                    <div className="matrix-val">
                      {orbio?.connected
                        ? orbio.probe_status === 'ok'
                          ? 'Orbio Active'
                          : 'Probe Degraded'
                        : 'Not Connected'}
                    </div>
                    <p className="matrix-sub">
                      {orbio?.connected
                        ? orbio.balance?.available &&
                          orbio.balance.amount !== null
                          ? `Balance: ${orbio.balance.amount} ${orbio.balance.currency}`
                          : 'Credential encrypted & active'
                        : 'Connect Orbio for remote inference'}
                    </p>
                  </div>
                </div>
              </div>
              <div className="my-6">
                <IdentityCard
                  operator={operatorProfile}
                  origin={origin}
                  pairing={activePairing}
                  onImportIdentity={handleImportIdentity}
                />
              </div>
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
          {view === 'Identity' && (
            <div className="space-y-6">
              <div className="overview-hero">
                <div className="hero-status-row">
                  <div>
                    <span className="hero-eyebrow">PORTABLE IDENTITY & REPUTATION</span>
                    <h2>Operator Identity Vault</h2>
                  </div>
                  <div className="product-badge pill-protected">
                    <span className="badge-dot" />
                    <span>ZERO-KNOWLEDGE AUTH</span>
                  </div>
                </div>
                <p className="mt-2 text-xs text-slate-400 font-mono">
                  Your identity card allows you to move seamlessly to a different PC or operating system without losing your dashboard pairing or starting from scratch.
                </p>
              </div>

              <div className="my-6">
                <IdentityCard
                  operator={operatorProfile}
                  origin={origin}
                  pairing={activePairing}
                  onImportIdentity={handleImportIdentity}
                />
              </div>

              <section className="panel">
                <div className="section-heading">
                  <h2>Cross-System Portability Guarantees</h2>
                  <span className="pill">Fail-Closed Security</span>
                </div>
                <div className="panel-body">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 space-y-2 transition-all hover:bg-white hover:border-emerald-300/80 hover:shadow-sm">
                      <strong className="text-slate-900 flex items-center gap-2 font-semibold text-sm">
                        <span className="p-1 rounded-md bg-emerald-100/70 text-emerald-700">
                          <LockKeyhole size={14} />
                        </span>
                        Zero Secret Exposure
                      </strong>
                      <p className="text-slate-600 text-xs leading-relaxed">
                        Raw provider API keys (like Orbio keys) never leave your local OS keychain. Identity passes export pairing references, not raw secrets.
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 space-y-2 transition-all hover:bg-white hover:border-cyan-300/80 hover:shadow-sm">
                      <strong className="text-slate-900 flex items-center gap-2 font-semibold text-sm">
                        <span className="p-1 rounded-md bg-cyan-100/70 text-cyan-700">
                          <ShieldCheck size={14} />
                        </span>
                        Origin Lock &amp; Integrity
                      </strong>
                      <p className="text-slate-600 text-xs leading-relaxed">
                        Identity passes are bound to this verified dashboard HTTPS origin. Tampered passes fail validation automatically.
                      </p>
                    </div>
                    <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-4 space-y-2 transition-all hover:bg-white hover:border-amber-300/80 hover:shadow-sm">
                      <strong className="text-slate-900 flex items-center gap-2 font-semibold text-sm">
                        <span className="p-1 rounded-md bg-amber-100/70 text-amber-700">
                          <History size={14} />
                        </span>
                        Portable State Transfer
                      </strong>
                      <p className="text-slate-600 text-xs leading-relaxed">
                        Pairing on a new computer immediately links the new system to your hosted account. Checkpoint archives can be migrated via standard local backup.
                      </p>
                    </div>
                  </div>
                </div>
              </section>
            </div>
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
          {(view === 'Orbio' || view === 'Funding') && (
            <div className="orbio-container">
              {!session ? (
                <Disconnected
                  section="Orbio inference & credentials"
                  onConnect={() => setConnecting(true)}
                />
              ) : orbioLoading && !orbio ? (
                <div className="empty-inline" style={{ padding: 48, textAlign: 'center' }}>
                  <RefreshCw className="animate-spin" size={24} style={{ margin: '0 auto 12px' }} />
                  <p>Loading Orbio status from companion…</p>
                </div>
              ) : !orbio?.connected ? (
                <div className="orbio-onboarding">
                  <div className="orbio-card">
                    <div className="orbio-card-header">
                      <span className="orbio-brand-badge">ORBIO INTEGRATION</span>
                      <h3>Connect Orbio to VESSEL</h3>
                      <p>
                        Route agent model inference through Orbio’s compute network. VESSEL validates credentials locally, stores them in encrypted OS storage, and manages model routing via local companion gateway.
                      </p>
                    </div>

                    <div className="security-guarantee-box">
                      <ShieldCheck className="guarantee-icon" size={24} />
                      <div className="guarantee-text">
                        <strong>Local Security Guarantee</strong>
                        <p>
                          Your raw Orbio API key never leaves this machine unencrypted. It is stored exclusively in DPAPI local storage on 127.0.0.1 and never sent to cloud servers, hosted databases, or web browsers.
                        </p>
                      </div>
                    </div>

                    <form className="orbio-form" onSubmit={handleConnectOrbio}>
                      <div className="form-field">
                        <label htmlFor="orbio-api-key">Orbio API Key</label>
                        <Input
                          id="orbio-api-key"
                          type="password"
                          autoComplete="off"
                          value={orbioKeyInput}
                          onChange={(e) => setOrbioKeyInput(e.target.value)}
                          placeholder="sk-orbio-..."
                          required
                          spellCheck={false}
                        />
                        <small>Key format: sk-orbio-... (validated locally via probe before saving)</small>
                      </div>

                      {orbioError && (
                        <div role="alert" className="notice error">
                          <TriangleAlert size={16} />
                          <span>{orbioError}</span>
                        </div>
                      )}

                      <div className="button-row" style={{ marginTop: 6 }}>
                        <Button
                          type="submit"
                          disabled={orbioConnecting || !orbioKeyInput.trim()}
                          className="primary-action"
                        >
                          {orbioConnecting ? 'Validating & Connecting…' : 'Connect Orbio Key'}
                          <Key size={16} />
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          disabled={claimingKey}
                          onClick={() => void handleClaimOrbio()}
                        >
                          <Sparkles size={16} style={{ color: '#00d2ff' }} />
                          {claimingKey ? 'Checking Orbio MCP…' : 'Claim via Orbio MCP'}
                        </Button>
                      </div>
                    </form>

                    <div className="orbio-info-grid">
                      <div className="info-item">
                        <strong>Claim via Orbio MCP</strong>
                        <p>
                          Hold $ORBIO at{' '}
                          <a
                            href="https://orbio.so"
                            target="_blank"
                            rel="noreferrer"
                            className="external-link-btn"
                            style={{ padding: '2px 0' }}
                          >
                            orbio.so <ExternalLink size={12} />
                          </a>{' '}
                          to auto-claim streaming inference credits.
                        </p>
                      </div>
                      <div className="info-item">
                        <strong>Need an API key?</strong>
                        <p>
                          <a
                            href="https://orbio.so"
                            target="_blank"
                            rel="noreferrer"
                            className="external-link-btn"
                            style={{ padding: '4px 0' }}
                          >
                            Get key on orbio.so <ExternalLink size={12} />
                          </a>
                        </p>
                      </div>
                      <div className="info-item">
                        <strong>Documentation</strong>
                        <p>
                          <a
                            href="https://orbio.net/docs"
                            target="_blank"
                            rel="noreferrer"
                            className="external-link-btn"
                            style={{ padding: '4px 0' }}
                          >
                            Explore docs <ExternalLink size={12} />
                          </a>
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <>
                  <div className="hero-status-row">
                    <div>
                      <span className="hero-eyebrow">INFERENCE ENGINE</span>
                      <h2>Orbio Compute Network</h2>
                    </div>
                    <div className={`product-badge ${orbio.probe_status === 'ok' ? 'pill-protected' : 'pill-degraded'}`}>
                      <span className="badge-dot" />
                      <span>{orbio.probe_status === 'ok' ? 'Connected' : 'Probe Degraded'}</span>
                    </div>
                  </div>

                  {orbioError && (
                    <div role="alert" className="notice error">
                      <TriangleAlert size={16} />
                      <span>{orbioError}</span>
                    </div>
                  )}

                  {/* Quota & Token Gating Analytics */}
                  <div className="orbio-analytics-grid">
                    {/* Usage & Quota Meter Card */}
                    <div className="orbio-analytics-card">
                      <div className="quota-meter-header">
                        <div>
                          <span className="card-tag">QUOTA &amp; COMPUTE USAGE</span>
                          <h4 style={{ margin: '4px 0 0', fontSize: 18, fontWeight: 700 }}>
                            Real-Time Spend &amp; Credits
                          </h4>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={orbioUsageLoading}
                          onClick={() => sessionRef.current && void loadOrbioUsage(sessionRef.current)}
                          title="Refresh usage analytics"
                        >
                          <RefreshCw className={orbioUsageLoading ? 'animate-spin' : ''} size={15} />
                        </Button>
                      </div>

                      <div className="quota-stats-row">
                        <div className="quota-stat-main">
                          <span className="quota-sub">Remaining Credits</span>
                          <span className="quota-number" style={{ color: '#00f0b5' }}>
                            ${typeof orbioUsage?.usage?.remaining_credits === 'number'
                              ? orbioUsage.usage.remaining_credits.toFixed(4)
                              : '0.0000'}
                          </span>
                        </div>
                        <div className="quota-stat-main" style={{ textAlign: 'right' }}>
                          <span className="quota-sub">Period Usage</span>
                          <span className="quota-number" style={{ fontSize: 20 }}>
                            ${typeof orbioUsage?.usage?.usage === 'number'
                              ? orbioUsage.usage.usage.toFixed(4)
                              : '0.0000'}
                          </span>
                        </div>
                      </div>

                      {/* Quota Progress Bar */}
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, marginBottom: 6, color: 'var(--muted)' }}>
                          <span>Quota Utilization</span>
                          <span>
                            {typeof orbioUsage?.usage?.percent_used === 'number'
                              ? `${orbioUsage.usage.percent_used.toFixed(1)}%`
                              : '0.0%'}
                            {typeof orbioUsage?.usage?.total_credits === 'number' && orbioUsage.usage.total_credits > 0 ? ` of $${orbioUsage.usage.total_credits.toFixed(2)}` : ''}
                          </span>
                        </div>
                        <div className="quota-progress-track">
                          <div
                            className={`quota-progress-fill ${(orbioUsage?.usage?.percent_used ?? 0) > 85 ? 'warning' : ''}`}
                            style={{
                              width: `${Math.min(Math.max(orbioUsage?.usage?.percent_used ?? 0, 2), 100)}%`,
                            }}
                          />
                        </div>
                      </div>

                      {/* Rate limits & Key label */}
                      <div className="rate-limits-row">
                        <span className="rate-limit-badge" title="Requests per minute rate limit">
                          <Zap size={13} style={{ color: '#00d2ff' }} />
                          {orbioUsage?.usage?.rate_limits?.requests_per_minute ?? 200} req/min
                        </span>
                        <span className="rate-limit-badge" title="Tokens per minute rate limit">
                          <Cpu size={13} style={{ color: '#a855f7' }} />
                          {orbioUsage?.usage?.rate_limits?.tokens_per_minute?.toLocaleString() ?? '40,000'} tok/min
                        </span>
                        {orbioUsage?.usage?.label && (
                          <span className="rate-limit-badge" title="Key label">
                            <Key size={13} />
                            {orbioUsage.usage.label}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* $ORBIO Token-Gated Tier Card */}
                    <div className="orbio-analytics-card">
                      <div className="quota-meter-header">
                        <div>
                          <span className="card-tag">$ORBIO TOKEN HOLDINGS</span>
                          <h4 style={{ margin: '4px 0 0', fontSize: 18, fontWeight: 700 }}>
                            Wallet-Gated Access Tier
                          </h4>
                        </div>
                        <span className={`tier-badge tier-${(orbioUsage?.wallet?.tier_name ?? 'community').toLowerCase()}`}>
                          <Sparkles size={12} />
                          {`${orbioUsage?.wallet?.tier_name ?? 'Community'} // TIER ${orbioUsage?.wallet?.tier ?? 0}`}
                        </span>
                      </div>

                      <div className="quota-stats-row">
                        <div className="quota-stat-main">
                          <span className="quota-sub">Verified Holdings</span>
                          <span className="quota-number" style={{ color: '#a855f7' }}>
                            {orbioUsage?.wallet?.holdings ? orbioUsage.wallet.holdings.toLocaleString() : '0'}{' '}
                            <span style={{ fontSize: 16, color: 'var(--primary)' }}>$ORBIO</span>
                          </span>
                        </div>
                        <div className="quota-stat-main" style={{ textAlign: 'right' }}>
                          <span className="quota-sub">Compute Multiplier</span>
                          <span className="quota-number" style={{ fontSize: 20, color: '#00d2ff' }}>
                            {orbioUsage?.wallet?.tier_perks?.multiplier ?? 0.5}x
                          </span>
                        </div>
                      </div>

                      <div style={{ fontSize: 12.5, color: 'var(--muted)', background: 'var(--secondary)', padding: '8px 12px', borderRadius: 8 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                          <strong style={{ color: 'var(--foreground)' }}>Routing:</strong>
                          <span>{orbioUsage?.wallet?.tier_perks?.routing_priority ?? 'Standard'}</span>
                        </div>
                        <div>{orbioUsage?.wallet?.tier_perks?.description ?? 'Base inference routing'}</div>
                      </div>

                      {/* Linked Wallet Address */}
                      <div className="wallet-badge-row">
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, overflow: 'hidden' }}>
                          <Wallet size={15} style={{ color: '#00d2ff', flexShrink: 0 }} />
                          {orbioUsage?.wallet?.wallet_address ? (
                            <span title={orbioUsage.wallet.wallet_address} style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {orbioUsage.wallet.wallet_address.slice(0, 6)}...{orbioUsage.wallet.wallet_address.slice(-6)}
                            </span>
                          ) : (
                            <span style={{ color: 'var(--muted)' }}>No Solana wallet linked</span>
                          )}
                        </div>
                        {orbioUsage?.wallet?.wallet_address ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            style={{ height: 26, fontSize: 11, padding: '0 8px' }}
                            onClick={() => void handleLinkWallet(undefined, 'disconnect')}
                            title="Unlink Solana wallet"
                          >
                            <Unplug size={12} style={{ marginRight: 4 }} />
                            Unlink
                          </Button>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            style={{ height: 26, fontSize: 11, padding: '0 8px' }}
                            onClick={() => {
                              setWalletInput('');
                              setWalletModalOpen(true);
                            }}
                          >
                            <Link2 size={12} style={{ marginRight: 4 }} />
                            Link Solana Wallet
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="orbio-connected-grid">
                    <div className="card-panel">
                      <div className="card-panel-header">
                        <span className="card-tag">AUTHENTICATION</span>
                        <h4>Encrypted Credential</h4>
                      </div>
                      <div className="credential-display">
                        <span className="key-code">{orbio.masked_key}</span>
                        <span className="status-indicator">
                          <span className={`dot ${orbio.probe_status === 'ok' ? 'dot-green' : 'pill-degraded'}`} />
                          {orbio.probe_status === 'ok' ? 'Active' : 'Unhealthy'}
                        </span>
                      </div>
                      <dl className="facts-mini">
                        <div>
                          <dt>Storage Type</dt>
                          <dd>DPAPI Local (127.0.0.1)</dd>
                        </div>
                        <div>
                          <dt>Probe Health</dt>
                          <dd>{orbio.probe_status}</dd>
                        </div>
                        <div>
                          <dt>Remote MCP</dt>
                          <dd>{orbio.mcp.configured ? 'Configured' : 'Fail-Closed / Unavailable'}</dd>
                        </div>
                      </dl>
                      <div className="button-row" style={{ marginTop: 'auto' }}>
                        <Button
                          variant="outline"
                          onClick={() => {
                            setOrbioError('');
                            setReplaceModalOpen(true);
                          }}
                        >
                          <Key size={14} />
                          Replace Key
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => {
                            setOrbioError('');
                            setForgetModalOpen(true);
                          }}
                        >
                          <Trash2 size={14} />
                          Forget Key
                        </Button>
                      </div>
                    </div>

                    <div className="card-panel">
                      <div className="card-panel-header">
                        <span className="card-tag">ACCOUNT HEALTH</span>
                        <h4>Inference & Balance</h4>
                      </div>
                      <div className="balance-display">
                        {orbio.balance.available && orbio.balance.amount !== null ? (
                          <>
                            <span className="balance-amount">{orbio.balance.amount}</span>
                            <span className="balance-currency">{orbio.balance.currency}</span>
                          </>
                        ) : (
                          <div>
                            <span className="balance-amount">—</span>{' '}
                            <span className="balance-currency">CREDIT</span>
                            <p className="balance-reason">
                              {orbio.balance.reason || 'Remote balance unavailable over direct gateway. Inference active.'}
                            </p>
                          </div>
                        )}
                      </div>
                      <dl className="facts-mini">
                        <div>
                          <dt>Usage Reported</dt>
                          <dd>
                            {orbio.usage.available && orbio.usage.amount !== null
                              ? `${orbio.usage.amount} ${orbio.usage.currency}`
                              : 'Via Orbio Console'}
                          </dd>
                        </div>
                        <div>
                          <dt>Management Mode</dt>
                          <dd>{orbio.mcp.configured ? 'Remote MCP' : 'Gateway-Only'}</dd>
                        </div>
                      </dl>
                    </div>

                    <div className="card-panel">
                      <div className="card-panel-header">
                        <span className="card-tag">LOCAL RUNTIME</span>
                        <h4>Inference Gateway</h4>
                      </div>
                      <div className="gateway-status-row">
                        <span className={`status-pill ${orbio.gateway.running ? 'pill-green' : 'pill-yellow'}`}>
                          {orbio.gateway.running ? 'Active Proxy' : 'Standby'}
                        </span>
                        <span className="port-badge">Port {orbio.gateway.port}</span>
                      </div>
                      <p className="path-text" style={{ fontSize: 12 }}>
                        {orbio.gateway.base_url}
                      </p>
                      <div className="models-list">
                        <span className="models-title">ACTIVE DEFAULT ROUTE</span>
                        <div className="model-tags">
                          <span className="model-chip highlight">
                            {isSmartRouting
                              ? 'openrouter/auto (Smart Dynamic)'
                              : activeGatewayModel || (orbio.gateway.models && orbio.gateway.models[0]) || 'claude-sonnet-4.5'}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="orbio-models-panel">
                    <div className="models-panel-header">
                      <div>
                        <span className="card-tag">MODEL INTELLIGENCE</span>
                        <h4>Model Routing & Catalog</h4>
                        <p>
                          Select which frontier model powers your local gateway (`http://127.0.0.1:{orbio.gateway.port}/v1`), or activate OpenRouter’s dynamic auto-router.
                        </p>
                      </div>
                      <div className="smart-routing-card">
                        <div className="smart-routing-info">
                          <strong>
                            <Zap size={16} style={{ color: isSmartRouting ? '#00d2ff' : 'var(--muted)' }} />
                            Smart Dynamic Routing (`openrouter/auto`)
                          </strong>
                          <p>
                            {isSmartRouting
                              ? 'Active: OpenRouter automatically picks the best price & speed per prompt.'
                              : 'Disabled: Fixed routing to your selected default model below.'}
                          </p>
                        </div>
                        <Button
                          variant={isSmartRouting ? 'default' : 'outline'}
                          size="sm"
                          disabled={updatingRouting}
                          onClick={() => void handleToggleSmartRouting(!isSmartRouting)}
                        >
                          {updatingRouting ? 'Updating…' : isSmartRouting ? 'Active (Auto)' : 'Enable Auto'}
                        </Button>
                      </div>
                    </div>

                    <div className="models-search-row">
                      <div className="models-search-input" style={{ position: 'relative' }}>
                        <Search
                          size={15}
                          style={{
                            position: 'absolute',
                            left: 12,
                            top: '50%',
                            transform: 'translateY(-50%)',
                            color: 'var(--muted)',
                            pointerEvents: 'none',
                          }}
                        />
                        <Input
                          style={{ paddingLeft: 36 }}
                          placeholder="Search models (e.g. claude, deepseek, gpt-4o, llama)..."
                          value={modelSearch}
                          onChange={(e) => setModelSearch(e.target.value)}
                        />
                      </div>
                      <div className="filter-chips">
                        {['all', 'recommended', 'anthropic', 'deepseek', 'openai'].map((filter) => (
                          <button
                            key={filter}
                            type="button"
                            className={`filter-chip ${selectedProviderFilter === filter ? 'active' : ''}`}
                            onClick={() => setSelectedProviderFilter(filter)}
                          >
                            {filter.charAt(0).toUpperCase() + filter.slice(1)}
                          </button>
                        ))}
                      </div>
                    </div>

                    {modelsLoading && modelsCatalog.length === 0 ? (
                      <div className="empty-inline" style={{ padding: 24, textAlign: 'center' }}>
                        <RefreshCw className="animate-spin" size={20} style={{ margin: '0 auto 8px' }} />
                        <p>Loading model catalog from OpenRouter…</p>
                      </div>
                    ) : (
                      <div className="models-grid">
                        {modelsCatalog
                          .filter((model) => {
                            if (modelSearch.trim()) {
                              const q = modelSearch.toLowerCase();
                              if (
                                !model.name.toLowerCase().includes(q) &&
                                !model.id.toLowerCase().includes(q) &&
                                !(model.description || '').toLowerCase().includes(q)
                              ) {
                                return false;
                              }
                            }
                            if (selectedProviderFilter === 'recommended') return !!model.recommended;
                            if (selectedProviderFilter === 'anthropic') return model.id.startsWith('anthropic/');
                            if (selectedProviderFilter === 'deepseek') return model.id.startsWith('deepseek/');
                            if (selectedProviderFilter === 'openai') return model.id.startsWith('openai/');
                            return true;
                          })
                          .slice(0, 18)
                          .map((model) => {
                            const isActive =
                              (isSmartRouting && model.id === 'openrouter/auto') ||
                              (!isSmartRouting && activeGatewayModel === model.id);
                            return (
                              <div key={model.id} className={`model-card ${isActive ? 'is-active' : ''}`}>
                                <div className="model-card-header">
                                  <div>
                                    <div className="model-name">{model.name}</div>
                                    <div className="model-slug">{model.id}</div>
                                  </div>
                                  {model.recommended && (
                                    <span className="meta-pill recommended">Recommended</span>
                                  )}
                                </div>
                                <div className="model-card-meta">
                                  <span className="meta-pill">
                                    {(model.context_length / 1000).toFixed(0)}k context
                                  </span>
                                  <span className="pricing-text">
                                    {model.pricing.prompt === 'Variable'
                                      ? 'Auto Pricing'
                                      : `$${(Number(model.pricing.prompt) * 1000000).toFixed(2)}/1M in`}
                                  </span>
                                </div>
                                {model.description && (
                                  <p className="model-description">{model.description}</p>
                                )}
                                <div className="model-card-footer">
                                  {isActive ? (
                                    <span className="status-indicator">
                                      <span className="dot dot-green" />
                                      Active Gateway Default
                                    </span>
                                  ) : (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      disabled={updatingRouting}
                                      onClick={() => void handleSelectModel(model.id)}
                                    >
                                      Set as Default
                                    </Button>
                                  )}
                                </div>
                              </div>
                            );
                          })}
                      </div>
                    )}
                  </div>

                  <div className="orbio-actions-bar">
                    <div className="left-actions">
                      <Button
                        variant="outline"
                        onClick={() => void handleRefreshOrbio()}
                        disabled={refreshingOrbio}
                      >
                        <RefreshCw size={14} className={refreshingOrbio ? 'animate-spin' : ''} />
                        {refreshingOrbio ? 'Refreshing…' : 'Refresh Status'}
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => void handleClaimOrbio()}
                        disabled={claimingKey}
                      >
                        <Sparkles size={14} style={{ color: '#00d2ff' }} />
                        {claimingKey ? 'Checking MCP…' : 'Claim via Orbio MCP'}
                      </Button>
                      <a
                        href="https://orbio.so"
                        target="_blank"
                        rel="noreferrer"
                        className="external-link-btn"
                      >
                        Manage Account on Orbio <ExternalLink size={14} />
                      </a>
                    </div>
                    <div className="right-actions">
                      <Button
                        variant="outline"
                        onClick={() => {
                          setOrbioError('');
                          setReplaceModalOpen(true);
                        }}
                      >
                        Replace Key
                      </Button>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setOrbioError('');
                          setForgetModalOpen(true);
                        }}
                      >
                        Forget Key
                      </Button>
                    </div>
                  </div>
                </>
              )}
            </div>
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
            account. Encrypted local persistence & zero-knowledge security.
          </small>
        </DialogContent>
      </Dialog>
      <Dialog
        open={replaceModalOpen}
        onOpenChange={(open) => {
          if (!replacingOrbio) {
            setReplaceModalOpen(open);
            if (!open) {
              setReplaceKeyInput('');
              setOrbioError('');
            }
          }
        }}
      >
        <DialogContent className="owner-dialog">
          <DialogHeader>
            <DialogTitle>Replace Orbio API Key</DialogTitle>
            <DialogDescription>
              Enter a new Orbio key. VESSEL will validate the key locally via gateway probe before updating your local encrypted store.
            </DialogDescription>
          </DialogHeader>
          <form className="owner-form" onSubmit={handleReplaceOrbio}>
            <div className="form-field">
              <label htmlFor="replace-orbio-key">New Orbio API Key</label>
              <Input
                id="replace-orbio-key"
                type="password"
                autoComplete="off"
                value={replaceKeyInput}
                onChange={(e) => setReplaceKeyInput(e.target.value)}
                required
                spellCheck={false}
                placeholder="sk-orbio-..."
              />
              <small>
                Transmitted directly to 127.0.0.1 and validated before saving. Previous key remains active if validation fails.
              </small>
            </div>
            {orbioError && (
              <div role="alert" className="notice error">
                <TriangleAlert size={16} />
                <span>{orbioError}</span>
              </div>
            )}
            <div className="button-row" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
              <Button
                type="button"
                variant="outline"
                onClick={() => setReplaceModalOpen(false)}
                disabled={replacingOrbio}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={replacingOrbio || !replaceKeyInput.trim()}
              >
                {replacingOrbio ? 'Validating & Replacing…' : 'Replace Key'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog
        open={forgetModalOpen}
        onOpenChange={(open) => {
          if (!forgettingOrbio) {
            setForgetModalOpen(open);
            if (!open) setOrbioError('');
          }
        }}
      >
        <DialogContent className="owner-dialog">
          <DialogHeader>
            <DialogTitle>Forget Orbio API Key</DialogTitle>
            <DialogDescription>
              Are you sure you want to forget your Orbio API key? This permanently deletes the encrypted credential from local storage.
            </DialogDescription>
          </DialogHeader>
          <div className="review-context">
            <p>
              Inference through the local gateway will pause until a new credential is provided.
            </p>
            <p>
              <strong>Continuity guarantee:</strong> All previous checkpoints, session recovery state, and task history are fully preserved.
            </p>
          </div>
          {orbioError && (
            <div role="alert" className="notice error">
              <TriangleAlert size={16} />
              <span>{orbioError}</span>
            </div>
          )}
          <div className="button-row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
            <Button
              type="button"
              variant="outline"
              onClick={() => setForgetModalOpen(false)}
              disabled={forgettingOrbio}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant="destructive"
              onClick={() => void handleForgetOrbio()}
              disabled={forgettingOrbio}
            >
              {forgettingOrbio ? 'Forgetting…' : 'Forget Key'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog
        open={walletModalOpen}
        onOpenChange={(open) => {
          if (!walletSaving) {
            setWalletModalOpen(open);
            if (!open) {
              setWalletInput('');
              setOrbioError('');
            }
          }
        }}
      >
        <DialogContent className="owner-dialog">
          <DialogHeader>
            <DialogTitle>Link Solana Public Wallet</DialogTitle>
            <DialogDescription>
              Link your public Solana wallet address (Base58) to verify your $ORBIO holdings and unlock tier perks.
            </DialogDescription>
          </DialogHeader>
          <div className="security-guarantee-box" style={{ margin: '8px 0' }}>
            <ShieldCheck className="guarantee-icon" size={20} />
            <div className="guarantee-text">
              <strong>Zero-Knowledge Wallet Security</strong>
              <p style={{ fontSize: 12, margin: 0 }}>
                Only your public Solana address is requested and stored for balance lookups. VESSEL will NEVER ask for your private key, seed phrase, or wallet signature.
              </p>
            </div>
          </div>
          <form
            className="owner-form"
            onSubmit={(e) => {
              e.preventDefault();
              void handleLinkWallet(walletInput.trim(), 'connect');
            }}
          >
            <div className="form-field">
              <label htmlFor="solana-wallet-input">Solana Public Address</label>
              <Input
                id="solana-wallet-input"
                autoComplete="off"
                value={walletInput}
                onChange={(e) => setWalletInput(e.target.value)}
                required
                spellCheck={false}
                placeholder="e.g. 7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
              />
              <small>
                32–44 character base58 Solana public address. Validated locally before checking on-chain holdings.
              </small>
            </div>
            {orbioError && (
              <div role="alert" className="notice error">
                <TriangleAlert size={16} />
                <span>{orbioError}</span>
              </div>
            )}
            <div className="button-row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
              <Button
                type="button"
                variant="outline"
                onClick={() => setWalletModalOpen(false)}
                disabled={walletSaving}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={walletSaving || !walletInput.trim()}
                className="primary-action"
              >
                {walletSaving ? 'Verifying & Linking…' : 'Link Public Address'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <Dialog open={claimNoticeModalOpen} onOpenChange={setClaimNoticeModalOpen}>
        <DialogContent className="modal-content">
          <DialogHeader>
            <DialogTitle>Claim Key via Orbio MCP</DialogTitle>
            <DialogDescription>
              Orbio keys are self-sovereign OpenRouter keys funded by $ORBIO staking.
            </DialogDescription>
          </DialogHeader>
          <div className="claim-modal-body">
            <div className="claim-step-item">
              <span className="claim-step-num">1</span>
              <div>
                <strong>Hold $ORBIO & Connect Wallet</strong>
                <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>
                  Connect your wallet on{' '}
                  <a
                    href="https://orbio.so"
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: 'var(--primary)', textDecoration: 'underline' }}
                  >
                    orbio.so
                  </a>
                  . The protocol streams inference credits directly to your holding address.
                </p>
              </div>
            </div>
            <div className="claim-step-item">
              <span className="claim-step-num">2</span>
              <div>
                <strong>Auto-Claim via Orbio MCP Tool</strong>
                <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>
                  When the Orbio Remote MCP is registered in your environment, VESSEL invokes{' '}
                  <code>orbio_claim_key</code> to automatically mint and rotate your key without copying secrets.
                </p>
              </div>
            </div>
            <div className="claim-step-item">
              <span className="claim-step-num">3</span>
              <div>
                <strong>Manual Key Entry Option</strong>
                <p style={{ margin: 0, fontSize: 13, color: 'var(--muted)' }}>
                  You can also claim your key directly on the Orbio dashboard and connect it above using the standard{' '}
                  <code>sk-or-v1-...</code> or <code>sk-orbio-...</code> key input.
                </p>
              </div>
            </div>
            {claimNotice?.message && (
              <div className="notice" style={{ marginTop: 8 }}>
                <span>{claimNotice.message}</span>
              </div>
            )}
            <div className="button-row" style={{ marginTop: 12, justifyContent: 'flex-end' }}>
              <a
                href={claimNotice?.url || 'https://orbio.so'}
                target="_blank"
                rel="noreferrer"
                className="button primary-action"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
              >
                Open Orbio.so <ExternalLink size={14} />
              </a>
              <Button variant="outline" onClick={() => setClaimNoticeModalOpen(false)}>
                Close
              </Button>
            </div>
          </div>
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
