'use client';

import Link from 'next/link';
import { useState } from 'react';
import { ShieldCheck, Lock, Mail, User, ArrowRight, Fingerprint, Terminal, AlertCircle, Eye, EyeOff } from 'lucide-react';
import { CyberCanvas } from '@/components/cyber-canvas';

export default function RegisterPage() {
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

        <section className="login-card web3-card" aria-labelledby="register-title">
          {/* Web3 Protocol Status Bar */}
          <div className="web3-status-bar">
            <div className="web3-status-pill">
              <span className="pulse-dot" />
              <span className="mono-status">NODE_REGISTRATION // MAINNET</span>
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
            <h1 id="register-title">INITIALIZE IDENTITY</h1>
            <p>Register node credentials to participate in autonomous agent continuity.</p>
          </div>

          <form
            className="owner-form web3-form"
            onSubmit={async (event) => {
              event.preventDefault();
              const fields = new FormData(event.currentTarget);
              setBusy(true);
              setError('');
              try {
                const response = await fetch('/api/register', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    name: fields.get('name'),
                    email: fields.get('email'),
                    password: fields.get('password'),
                  }),
                });
                const result = (await response.json()) as { error?: string; success?: boolean };
                if (!response.ok) {
                  throw new Error(result.error || 'Could not complete registration.');
                }
                // Registration sets the session cookie; enter the workspace
                window.location.assign('/');
              } catch (failure) {
                setError(
                  failure instanceof Error
                    ? failure.message
                    : 'Could not complete registration.',
                );
                setBusy(false);
              }
            }}
          >
            <div className="form-field web3-field">
              <label htmlFor="register-name" className="web3-label">
                <span className="label-tag">[OPERATOR_ALIAS]</span> Full Name
              </label>
              <div className="web3-input-wrapper">
                <User className="field-icon" size={16} />
                <input
                  id="register-name"
                  name="name"
                  type="text"
                  autoComplete="name"
                  required
                  maxLength={80}
                  placeholder="Operator Alice"
                  className="web3-input"
                />
              </div>
            </div>

            <div className="form-field web3-field">
              <label htmlFor="register-email" className="web3-label">
                <span className="label-tag">[IDENTITY]</span> Email
              </label>
              <div className="web3-input-wrapper">
                <Mail className="field-icon" size={16} />
                <input
                  id="register-email"
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
              <label htmlFor="register-password" className="web3-label">
                <span className="label-tag">[PASS_CIPHER]</span> Master Password
              </label>
              <div className="web3-input-wrapper">
                <Lock className="field-icon" size={16} />
                <input
                  id="register-password"
                  name="password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="new-password"
                  required
                  minLength={8}
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
                  <span className="cyber-spinner" /> INITIALIZING NODE IDENTITY...
                </span>
              ) : (
                <span className="btn-state">
                  INITIALIZE NODE IDENTITY <ArrowRight size={15} className="btn-arrow" />
                </span>
              )}
            </button>
          </form>

          {/* Web3 Card Footer */}
          <div className="web3-card-footer">
            <div className="web3-aux-links">
              <Link href="/" className="web3-secondary-link">
                Already registered? <span className="highlight">Sign in</span> →
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
