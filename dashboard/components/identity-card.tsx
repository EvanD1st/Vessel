'use client';

import React, { useState } from 'react';
import {
  ShieldCheck,
  Download,
  Copy,
  Check,
  Upload,
  Laptop,
  Fingerprint,
  Cpu,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';
import {
  type OperatorIdentityCard,
  createIdentityCard,
  serializeIdentityPass,
  parseIdentityPass,
} from '@/lib/vessel';

export interface IdentityCardProps {
  operator: {
    id: string;
    name: string;
    email: string;
    role?: string;
  };
  origin: string;
  pairing?: {
    enrollmentId: string;
    deviceId: string;
    port: number;
    credential: string;
  } | null;
  onImportIdentity?: (card: OperatorIdentityCard) => void;
}

export function IdentityCard({
  operator,
  origin,
  pairing,
  onImportIdentity,
}: IdentityCardProps) {
  const [copied, setCopied] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [importInput, setImportInput] = useState('');
  const [importError, setImportError] = useState('');
  const [importSuccess, setImportSuccess] = useState('');

  const card = createIdentityCard({
    operator,
    origin: origin || 'https://vessel-dashboard.cloud-ip.cc',
    pairing,
  });

  const passString = serializeIdentityPass(card);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(passString);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback
    }
  };

  const handleDownload = () => {
    const jsonStr = JSON.stringify(card, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `vessel-identity-${operator.id.slice(0, 8)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target?.result as string;
      setImportInput(content);
    };
    reader.readAsText(file);
  };

  const handleProcessImport = () => {
    setImportError('');
    setImportSuccess('');
    try {
      const parsedCard = parseIdentityPass(importInput);
      if (onImportIdentity) {
        onImportIdentity(parsedCard);
        setImportSuccess(
          `Identity imported for ${parsedCard.operator.name || parsedCard.operator.email}! Rehydrating connection...`,
        );
        setTimeout(() => {
          setImportOpen(false);
          setImportInput('');
          setImportSuccess('');
        }, 1500);
      }
    } catch (err) {
      setImportError(
        err instanceof Error
          ? err.message
          : 'Failed to parse identity pass. Ensure it is valid JSON or a vessel-pass token.',
      );
    }
  };

  return (
    <div className="vessel-identity-container w-full">
      {/* Visual Cybernetic Identity Card */}
      <div className="relative overflow-hidden rounded-2xl border border-emerald-500/40 bg-gradient-to-br from-slate-950 via-[#0a1118] to-slate-900 p-6 shadow-2xl transition-all duration-300 hover:border-emerald-400/60">
        {/* Holographic Watermark & Circuit Accents */}
        <div className="pointer-events-none absolute -right-12 -top-12 h-56 w-56 rounded-full bg-emerald-500/5 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-10 -left-10 h-48 w-48 rounded-full bg-cyan-500/5 blur-2xl" />

        {/* Card Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-emerald-500/40 bg-emerald-950/40 text-emerald-400 shadow-[0_0_15px_rgba(16,185,129,0.2)]">
              <ShieldCheck className="h-6 w-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold tracking-wider text-white">
                  OPERATOR IDENTITY CARD
                </span>
                <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-bold text-emerald-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  AUTHENTICATED
                </span>
              </div>
              <p className="text-xs font-mono text-slate-400">
                VESSEL Cryptographic Passport &bull; Cross-System Continuity
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setGuideOpen(true)}
              className="border-slate-700 bg-slate-900/80 text-xs text-slate-300 hover:border-cyan-500/50 hover:bg-slate-800 hover:text-cyan-300"
            >
              <Laptop className="mr-1.5 h-3.5 w-3.5 text-cyan-400" />
              Moving to New PC?
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setImportOpen(true)}
              className="border-slate-700 bg-slate-900/80 text-xs text-slate-300 hover:border-emerald-500/50 hover:bg-slate-800 hover:text-emerald-300"
            >
              <Upload className="mr-1.5 h-3.5 w-3.5 text-emerald-400" />
              Import Pass
            </Button>
          </div>
        </div>

        {/* Card Body - Grid Layout */}
        <div className="mt-5 grid grid-cols-1 gap-6 md:grid-cols-12">
          {/* Left Column: Operator Bio & Chip */}
          <div className="space-y-4 md:col-span-7">
            <div className="flex items-center gap-4">
              <div className="flex h-14 w-14 flex-col items-center justify-center rounded-lg border border-amber-500/30 bg-amber-500/10 text-amber-400">
                <Cpu className="h-7 w-7" />
                <span className="text-[8px] font-mono font-bold tracking-widest text-amber-500/80">
                  VAULT
                </span>
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-base font-bold text-white truncate">
                  {operator.name || 'VESSEL Operator'}
                </div>
                <div className="text-xs font-mono text-emerald-400/90 truncate">
                  {operator.email}
                </div>
                <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
                  <span>ID: <code className="text-slate-300">{operator.id}</code></span>
                  {operator.role && (
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-slate-300">
                      {operator.role}
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Origin & Enrollment Status */}
            <div className="grid grid-cols-2 gap-3 pt-2">
              <div className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-2.5">
                <div className="text-[10px] font-mono text-slate-500">AUTHORITY ORIGIN</div>
                <div className="mt-0.5 truncate text-xs font-mono font-semibold text-slate-200">
                  {card.origin}
                </div>
              </div>

              <div className="rounded-lg border border-slate-800/80 bg-slate-950/60 p-2.5">
                <div className="text-[10px] font-mono text-slate-500">PAIRING STATUS</div>
                <div className="mt-0.5 truncate text-xs font-mono font-semibold">
                  {card.enrollmentId ? (
                    <span className="text-emerald-400">
                      PORT :{card.port} &bull; BOUND
                    </span>
                  ) : (
                    <span className="text-amber-400">AWAITING LOCAL HOST</span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Right Column: Cryptographic Fingerprint & Security Spec */}
          <div className="flex flex-col justify-between space-y-4 md:col-span-5 md:border-l md:border-slate-800/80 md:pl-6">
            <div>
              <div className="flex items-center justify-between text-[10px] font-mono text-slate-400">
                <span className="flex items-center gap-1">
                  <Fingerprint className="h-3.5 w-3.5 text-cyan-400" />
                  PASSPORT FINGERPRINT
                </span>
                <span className="text-slate-500">{new Date(card.issuedAt).toLocaleDateString()}</span>
              </div>
              <div className="mt-1.5 rounded-lg border border-slate-800 bg-black/50 p-2 font-mono text-[11px] text-cyan-300 tracking-wider break-all select-all">
                {card.fingerprint}
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5 pt-1">
              <span className="rounded border border-slate-800 bg-slate-900/60 px-2 py-0.5 text-[10px] font-mono text-slate-400">
                DPAPI ZERO-KNOWLEDGE
              </span>
              <span className="rounded border border-slate-800 bg-slate-900/60 px-2 py-0.5 text-[10px] font-mono text-slate-400">
                FAIL-CLOSED GATEWAY
              </span>
              <span className="rounded border border-slate-800 bg-slate-900/60 px-2 py-0.5 text-[10px] font-mono text-slate-400">
                CROSS-OS PORTABLE
              </span>
            </div>
          </div>
        </div>

        {/* Card Footer Actions */}
        <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-800/80 pt-4">
          <div className="text-xs text-slate-400">
            Use this Identity Card to restore your session or pair a new computer.
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={handleCopy}
              className="border-slate-700 bg-slate-900 text-xs text-slate-200 hover:border-slate-600 hover:bg-slate-800"
            >
              {copied ? (
                <>
                  <Check className="mr-1.5 h-3.5 w-3.5 text-emerald-400" />
                  Copied Token!
                </>
              ) : (
                <>
                  <Copy className="mr-1.5 h-3.5 w-3.5" />
                  Copy Pass Token
                </>
              )}
            </Button>

            <Button
              size="sm"
              onClick={handleDownload}
              className="bg-emerald-500 font-semibold text-black hover:bg-emerald-400 text-xs shadow-[0_0_12px_rgba(16,185,129,0.3)]"
            >
              <Download className="mr-1.5 h-3.5 w-3.5" />
              Download Identity Card (.json)
            </Button>
          </div>
        </div>
      </div>

      {/* IMPORT DIALOG */}
      <Dialog open={importOpen} onOpenChange={setImportOpen}>
        <DialogContent className="border-slate-800 bg-slate-950 text-slate-100 sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-white flex items-center gap-2">
              <Upload className="h-5 w-5 text-emerald-400" />
              Import Operator Identity Pass
            </DialogTitle>
            <DialogDescription className="text-xs text-slate-400">
              Restore your pairing credentials and project custody on this computer.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-3">
            {/* File Upload Option */}
            <div className="rounded-lg border border-dashed border-slate-700 bg-slate-900/50 p-4 text-center hover:border-emerald-500/50 transition">
              <input
                type="file"
                id="identity-file-upload"
                accept=".json"
                className="hidden"
                onChange={handleFileUpload}
              />
              <label
                htmlFor="identity-file-upload"
                className="cursor-pointer block space-y-1"
              >
                <Download className="mx-auto h-6 w-6 text-slate-400" />
                <span className="text-xs font-semibold text-emerald-400 hover:underline block">
                  Click to select vessel-identity.json
                </span>
                <span className="text-[10px] text-slate-500 block">
                  or paste the pass token below
                </span>
              </label>
            </div>

            {/* Textarea for token or JSON */}
            <div>
              <label
                htmlFor="pass-token-input"
                className="block text-[11px] font-mono text-slate-400 mb-1"
              >
                IDENTITY TOKEN OR JSON
              </label>
              <textarea
                id="pass-token-input"
                rows={4}
                value={importInput}
                onChange={(e) => setImportInput(e.target.value)}
                placeholder="vessel-pass:eyJmb3JtYXQiOiJ2ZXNzZWwt..."
                className="w-full rounded-lg border border-slate-800 bg-slate-900 p-2.5 font-mono text-xs text-slate-200 placeholder-slate-600 focus:border-emerald-500 focus:outline-none"
              />
            </div>

            {importError && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-950/30 p-2.5 text-xs text-rose-300">
                {importError}
              </div>
            )}

            {importSuccess && (
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-950/30 p-2.5 text-xs text-emerald-300">
                {importSuccess}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 border-t border-slate-800 pt-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setImportOpen(false);
                setImportInput('');
                setImportError('');
              }}
              className="border-slate-700 bg-slate-900 text-xs text-slate-300"
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleProcessImport}
              disabled={!importInput.trim()}
              className="bg-emerald-500 font-semibold text-black hover:bg-emerald-400 text-xs"
            >
              Import &amp; Restore Pairing
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      {/* MOVING TO NEW PC GUIDE DIALOG */}
      <Dialog open={guideOpen} onOpenChange={setGuideOpen}>
        <DialogContent className="border-slate-800 bg-slate-950 text-slate-100 sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-lg font-bold text-white flex items-center gap-2">
              <Laptop className="h-5 w-5 text-cyan-400" />
              Migrating to a Different PC or System
            </DialogTitle>
            <DialogDescription className="text-xs text-slate-400">
              How to move your VESSEL setup and agent continuity to another computer in 3 steps:
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-3 text-xs">
            {/* Step 1 */}
            <div className="flex items-start gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 font-mono font-bold text-emerald-400">
                1
              </div>
              <div className="space-y-1">
                <div className="font-bold text-white">Export Your Identity Card</div>
                <p className="text-slate-400">
                  Click <strong>&quot;Download Identity Card&quot;</strong> above to save{' '}
                  <code className="text-emerald-300 font-mono">vessel-identity.json</code> onto a USB drive or your secure cloud folder.
                </p>
              </div>
            </div>

            {/* Step 2 */}
            <div className="flex items-start gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 font-mono font-bold text-emerald-400">
                2
              </div>
              <div className="space-y-1">
                <div className="font-bold text-white">Install on the New Computer</div>
                <p className="text-slate-400">
                  On the new PC, open VS Code and install the <strong>VESSEL - Agent Continuity</strong> extension (or run the companion daemon with Python).
                </p>
              </div>
            </div>

            {/* Step 3 */}
            <div className="flex items-start gap-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 font-mono font-bold text-emerald-400">
                3
              </div>
              <div className="space-y-1">
                <div className="font-bold text-white">Import on the New System</div>
                <p className="text-slate-400">
                  Open <strong>https://vessel-dashboard.cloud-ip.cc</strong> in your browser on the new PC, sign in, and click <strong>&quot;Import Pass&quot;</strong> to restore pairing instantly.
                </p>
                <div className="mt-2 rounded bg-slate-950 p-2 font-mono text-[11px] text-slate-300">
                  CLI alternative: <span className="text-emerald-400">vessel identity import vessel-identity.json</span>
                </div>
              </div>
            </div>
          </div>

          <div className="flex justify-end border-t border-slate-800 pt-3">
            <Button
              size="sm"
              onClick={() => setGuideOpen(false)}
              className="bg-emerald-500 font-semibold text-black hover:bg-emerald-400 text-xs"
            >
              Got it, Close
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
