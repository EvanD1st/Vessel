'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ShieldCheck, Lock, Mail, ArrowRight, Fingerprint, Terminal, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { CyberCanvas } from '@/components/cyber-canvas';

export default function LoginForm() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);

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

        <section className="login-card web3-card" aria-labelledby="login-title">
          {/* Web3 Protocol Status Bar */}
          <div className="web3-status-bar">
            <div className="web3-status-pill">
              <span className="pulse-dot" />
              <span className="mono-status">NODE_ONLINE // MAINNET</span>
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
            <h1 id="login-title">ACCESS WORKSPACE</h1>
            <p>Cryptographic identity gateway. Authenticate node to resume autonomous continuity.</p>
          </div>

          <form
            className="owner-form web3-form"
            onSubmit={async (event) => {
              event.preventDefault();
              const fields = new FormData(event.currentTarget);
              setBusy(true);
              setError('');
              try {
                const response = await fetch('/api/session', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    email: fields.get('email'),
                    password: fields.get('password'),
                  }),
                });
                const result = (await response.json()) as { error?: string };
                if (!response.ok)
                  throw new Error(result.error || 'Could not sign in.');
                window.location.assign('/');
              } catch (failure) {
                setError(
                  failure instanceof Error
                    ? failure.message
                    : 'Could not sign in.',
                );
                setBusy(false);
              }
            }}
          >
            <div className="form-field web3-field">
              <label htmlFor="login-email" className="web3-label">
                <span className="label-tag">[IDENTITY]</span> Email
              </label>
              <div className="web3-input-wrapper">
                <Mail className="field-icon" size={16} />
                <input
                  id="login-email"
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

            <div className="form-field web3-field">
              <div className="label-split">
                <label htmlFor="login-password" className="web3-label">
                  <span className="label-tag">[PASS_CIPHER]</span> Password
                </label>
                <Link href="/forgot-password" className="web3-forgot-link">
                  Forgot key?
                </Link>
              </div>
              <div className="web3-input-wrapper">
                <Lock className="field-icon" size={16} />
                <input
                  id="login-password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  required
                  maxLength={128}
                  placeholder="••••••••••••••••"
                  className="web3-input web3-input-has-action"
                />
                <button
                  type="button"
                  className="password-toggle-btn"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  tabIndex={0}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
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
                  <span className="cyber-spinner" /> VERIFYING CIPHER...
                </span>
              ) : (
                <span className="btn-state">
                  AUTHENTICATE NODE <ArrowRight size={15} className="btn-arrow" />
                </span>
              )}
            </button>
          </form>

          {/* Web3 Card Footer */}
          <div className="web3-card-footer">
            <div className="web3-aux-links">
              <Link href="/register" className="web3-secondary-link">
                Need an account? <span className="highlight">Register identity</span> →
              </Link>
              <Link href="/setup-guide" className="web3-secondary-link setup">
                <Fingerprint size={13} /> Protocol Setup Guide ↗
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
