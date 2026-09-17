'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ShieldCheck, Mail, ArrowRight, ArrowLeft, Terminal, AlertCircle, CheckCircle2 } from 'lucide-react';
import { CyberCanvas } from '@/components/cyber-canvas';

export default function ForgotPasswordPage() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);

  return (
    <main className="login-page web3-login-page">
      <CyberCanvas />

      {/* Ambient glowing vignette behind the card */}
      <div className="web3-ambient-glow" aria-hidden="true" />

      <div className="web3-card-container">
        {/* Futuristic HUD Tech Corner Brackets */}
        <div className="hud-corner hud-tl" aria-hidden="true" />
        <div className="hud-corner hud-tr" aria-hidden="true" />
        <div className="hud-corner hud-bl" aria-hidden="true" />
        <div className="hud-corner hud-br" aria-hidden="true" />

        <section className="login-card web3-card" aria-labelledby="forgot-title">
          {/* Web3 Protocol Status Bar */}
          <div className="web3-status-bar">
            <div className="web3-status-pill">
              <span className="pulse-dot" />
              <span className="mono-status">CIPHER_RECOVERY // PROTOCOL</span>
            </div>
            <div className="web3-network-badge">
              <Terminal size={11} className="badge-icon" />
              <span>0xVESSEL_v0.3</span>
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
            <h1 id="forgot-title">RECOVER CIPHER</h1>
            <p>Enter your operator email address. If an account is registered, a password reset link will be dispatched.</p>
          </div>

          {submitted ? (
            <div className="web3-recovery-success">
              <output className="web3-success-banner">
                <CheckCircle2 size={18} className="success-icon" />
                <div>
                  <strong>Reset Link Dispatched</strong>
                  <p>If an account exists with this email, instructions to reset your master cipher have been generated.</p>
                </div>
              </output>
              <Link href="/" className="primary-action web3-submit-btn text-center block mt-4">
                <span className="btn-state">
                  <ArrowLeft size={15} /> Return to Sign In
                </span>
              </Link>
            </div>
          ) : (
            <form
              className="owner-form web3-form"
              onSubmit={async (event) => {
                event.preventDefault();
                const fields = new FormData(event.currentTarget);
                setBusy(true);
                setError('');
                try {
                  const response = await fetch('/api/forgot-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      email: fields.get('email'),
                    }),
                  });
                  const result = (await response.json()) as { error?: string };
                  if (!response.ok) {
                    throw new Error(result.error || 'Could not process password reset request.');
                  }
                  setSubmitted(true);
                } catch (failure) {
                  setError(
                    failure instanceof Error
                      ? failure.message
                      : 'Could not process password reset request.',
                  );
                  setBusy(false);
                }
              }}
            >
              <div className="form-field web3-field">
                <label htmlFor="recovery-email" className="web3-label">
                  <span className="label-tag">[IDENTITY]</span> Email
                </label>
                <div className="web3-input-wrapper">
                  <Mail className="field-icon" size={16} />
                  <input
                    id="recovery-email"
                    name="email"
                    type="email"
                    autoComplete="username"
                    required
                    maxLength={254}
                    placeholder="operator@domain.com"
                    className="web3-input"
                  />
                </div>
              </div>

              {error && (
                <div className="web3-error-banner" role="alert">
                  <AlertCircle size={15} />
                  <span>{error}</span>
                </div>
              )}

              <button className="primary-action web3-submit-btn" type="submit" disabled={busy}>
                {busy ? (
                  <span className="btn-state loading">
                    <span className="cyber-spinner" /> DISPATCHING CIPHER LINK...
                  </span>
                ) : (
                  <span className="btn-state">
                    REQUEST RESET LINK <ArrowRight size={15} className="btn-arrow" />
                  </span>
                )}
              </button>
            </form>
          )}

          {/* Web3 Card Footer */}
          <div className="web3-card-footer">
            <div className="web3-aux-links">
              <Link href="/" className="web3-secondary-link">
                <ArrowLeft size={13} /> Back to <span className="highlight">Sign in</span>
              </Link>
            </div>

            <div className="web3-security-strip">
              <span className="strip-item">CUSTODY: LOCAL_MACHINE</span>
              <span className="strip-dot">•</span>
              <span className="strip-item">CIPHER: AES_256_GCM</span>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}
