'use client';

import Link from 'next/link';
import { ShieldCheck, Terminal, ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { CyberCanvas } from '@/components/cyber-canvas';

const STEPS = [
  ['Install VESSEL', 'Install the local preview VSIX in VS Code. Installation alone does not configure your project.'],
  ['Check requirements', 'VESSEL checks Python 3.11 or newer and the exact supported Cline build before making changes.'],
  ['Choose a project', 'Choose one open folder. Review its mission and the private recovery storage outside your repository.'],
  ['Connect Orbio', 'Approve small verification requests and save your key in VS Code SecretStorage. Project content is not part of this check.'],
  ['Choose two models', 'Choose verified primary and fallback routes. Native Cline compatibility remains a separate check.'],
  ['Configure locally', 'Review hooks, MCP settings, local ports and any compatibility change before applying them.'],
  ['Verify protection', 'Check the companion and gateway, bind an observed Cline task, then verify real capture and a checkpoint. Pending checks stay pending.'],
  ['Recover when needed', 'Stop the source, review a handover for a fresh task, retrieve its context, and confirm observed continuation.'],
];

export default function SetupGuide() {
  return (
    <main className="login-page web3-login-page setup-guide-page">
      <CyberCanvas />

      {/* Ambient glowing vignette behind the card */}
      <div className="web3-ambient-glow" aria-hidden="true" />

      <div className="web3-setup-container">
        {/* Futuristic HUD Tech Corner Brackets */}
        <div className="hud-corner hud-tl" aria-hidden="true" />
        <div className="hud-corner hud-tr" aria-hidden="true" />
        <div className="hud-corner hud-bl" aria-hidden="true" />
        <div className="hud-corner hud-br" aria-hidden="true" />

        <section className="login-card setup-guide-card web3-card web3-setup-card" aria-labelledby="setup-title">
          {/* Web3 Protocol Status Bar */}
          <div className="web3-status-bar">
            <div className="web3-status-pill">
              <span className="pulse-dot" />
              <span className="mono-status">PROTOCOL_SPEC // v0.3</span>
            </div>
            <div className="web3-network-badge">
              <Terminal size={11} className="badge-icon" />
              <span>SETUP_GUIDE</span>
            </div>
          </div>

          {/* Brand Header */}
          <div className="login-brand web3-brand">
            <div className="brand-shield-wrapper">
              <ShieldCheck className="brand-shield-icon" size={26} />
              <div className="shield-glow" />
            </div>
            <div className="brand-meta">
              <span className="brand-name">VESSEL</span>
              <span className="brand-tagline">AGENT CONTINUITY PROTOCOL</span>
            </div>
          </div>

          <div className="web3-header-text">
            <p className="setup-guide-kicker">[LOCAL PREVIEW · SETUP SPECIFICATION]</p>
            <h1 id="setup-title">Keep your work within reach.</h1>
            <p>This is an educational preview. Installation and setup happen in VS Code; viewing this page changes nothing on your computer.</p>
            <p className="setup-guide-subtext">
              Install the local VESSEL VSIX, then choose <strong>Set up VESSEL</strong>. The current preview supports Windows x64, Python 3.11–3.14, and the verified Cline 4.1.17 bundle.
            </p>
          </div>

          <ol className="setup-guide-steps web3-steps-list" aria-label="VESSEL setup steps">
            {STEPS.map(([title, description], index) => (
              <li key={title} className="web3-step-item">
                <span className="setup-guide-number web3-step-number" aria-hidden="true">
                  {String(index + 1).padStart(2, '0')}
                </span>
                <div className="web3-step-content">
                  <h2>{title}</h2>
                  <p>{description}</p>
                </div>
              </li>
            ))}
          </ol>

          <p className="setup-guide-notice">The complete guide is shown above. Configuration executes locally within your IDE environment.</p>

          <div className="setup-guide-footer web3-guide-footer">
            <Button disabled aria-describedby="marketplace-note" className="web3-vscode-btn">
              Open in VS Code — preview only
            </Button>
            <p id="marketplace-note">A Marketplace listing is not available. Use the locally packaged VSIX.</p>
            <Link href="/" className="web3-back-link">
              <ArrowLeft size={14} /> Back to sign in
            </Link>
          </div>
        </section>
      </div>
    </main>
  );
}
