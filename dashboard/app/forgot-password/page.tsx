'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ShieldCheck, Mail, ArrowRight, ArrowLeft, AlertCircle, CheckCircle2 } from 'lucide-react';
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

        <div className="cyber-accent-line" aria-hidden="true" />

        <section className="login-card web3-card" aria-labelledby="forgot-title">
          <div className="web3-logo-badge">
            <div className="web3-logo-inner">
              <ShieldCheck size={26} className="text-[#8bc6ad]" />
            </div>
            <div className="web3-badge-status">
              <span className="live-dot pulse" />
              <span className="live-text">VESSEL RECOVERY NODE</span>
            </div>
          </div>

          <div className="web3-header-text">
            <h1 id="forgot-title">RECOVER CIPHER</h1>
            <p>Enter your operator email address. A secure recovery authorization link will be dispatched to your inbox.</p>
          </div>

          {submitted ? (
            <div className="web3-recovery-success">
              <output className="web3-success-banner">
                <CheckCircle2 size={18} className="success-icon" />
                <div>
                  <strong>Recovery Link Dispatched</strong>
                  <p>If an account is associated with this email, a secure authorization link has been sent to your inbox. Please check your email to complete password recovery.</p>
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
                } finally {
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
                    <span className="cyber-spinner" /> GENERATING RESET AUTHORIZATION...
                  </span>
                ) : (
                  <span className="btn-state">
                    INITIALIZE PASSWORD RESET <ArrowRight size={15} className="btn-arrow" />
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
