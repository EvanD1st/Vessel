'use client';

import Link from 'next/link';
import { useParams, useSearchParams } from 'next/navigation';
import { Suspense, useState } from 'react';
import { ShieldCheck, Lock, KeyRound, ArrowRight, ArrowLeft, Terminal, AlertCircle, CheckCircle2, Eye, EyeOff } from 'lucide-react';
import { CyberCanvas } from '@/components/cyber-canvas';

function ResetPasswordForm() {
  const searchParams = useSearchParams();
  const params = useParams();
  const pathToken = typeof params?.token === 'string' ? params.token : '';
  const urlToken = searchParams.get('token') || pathToken || '';

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  return (
    <div className="web3-card-container">
      {/* Futuristic HUD Tech Corner Brackets */}
      <div className="hud-corner hud-tl" aria-hidden="true" />
      <div className="hud-corner hud-tr" aria-hidden="true" />
      <div className="hud-corner hud-bl" aria-hidden="true" />
      <div className="hud-corner hud-br" aria-hidden="true" />

      <section className="login-card web3-card" aria-labelledby="reset-title">
        {/* Web3 Protocol Status Bar */}
        <div className="web3-status-bar">
          <div className="web3-status-pill">
            <span className="pulse-dot" />
            <span className="mono-status">RESET_CIPHER // PROTOCOL</span>
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
          <h1 id="reset-title">UPDATE MASTER CIPHER</h1>
          <p>Establish a new master authentication password for your workspace identity.</p>
        </div>

        {success ? (
          <div className="web3-recovery-success">
            <output className="web3-success-banner">
              <CheckCircle2 size={18} className="success-icon" />
              <div>
                <strong>Cipher Updated Successfully</strong>
                <p>Your master password has been refreshed. You can now authenticate with your new credentials.</p>
              </div>
            </output>
            <Link href="/" className="primary-action web3-submit-btn text-center block mt-4">
              <span className="btn-state">
                <ArrowLeft size={15} /> Authenticate Now
              </span>
            </Link>
          </div>
        ) : (
          <form
            className="owner-form web3-form"
            onSubmit={async (event) => {
              event.preventDefault();
              const fields = new FormData(event.currentTarget);
              const token = (fields.get('token') as string || urlToken).trim();
              const password = fields.get('password') as string;
              const confirmPassword = fields.get('confirmPassword') as string;

              if (!token) {
                setError('A reset token is required. Please check your reset link.');
                return;
              }
              if (password.length < 8) {
                setError('Password must be at least 8 characters long.');
                return;
              }
              if (password !== confirmPassword) {
                setError('Passwords do not match. Please re-enter.');
                return;
              }

              setBusy(true);
              setError('');
              try {
                const response = await fetch('/api/reset-password', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ token, password }),
                });
                const result = (await response.json()) as { error?: string; success?: boolean };
                if (!response.ok) {
                  throw new Error(result.error || 'Could not reset password. Token may have expired.');
                }
                setSuccess(true);
              } catch (failure) {
                setError(
                  failure instanceof Error
                    ? failure.message
                    : 'Could not reset password.',
                );
                setBusy(false);
              }
            }}
          >
            {!urlToken && (
              <div className="form-field web3-field">
                <label htmlFor="reset-token" className="web3-label">
                  <span className="label-tag">[TOKEN]</span> Reset Authorization Token
                </label>
                <div className="web3-input-wrapper">
                  <KeyRound className="field-icon" size={16} />
                  <input
                    id="reset-token"
                    name="token"
                    type="text"
                    required
                    placeholder="Enter token from email link"
                    className="web3-input"
                  />
                </div>
              </div>
            )}

            <div className="form-field web3-field">
              <label htmlFor="reset-password" className="web3-label">
                <span className="label-tag">[NEW_CIPHER]</span> New Password
              </label>
              <div className="web3-input-wrapper">
                <Lock className="field-icon" size={16} />
                <input
                  id="reset-password"
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

            <div className="form-field web3-field">
              <label htmlFor="reset-confirm" className="web3-label">
                <span className="label-tag">[CONFIRM_CIPHER]</span> Confirm Password
              </label>
              <div className="web3-input-wrapper">
                <Lock className="field-icon" size={16} />
                <input
                  id="reset-confirm"
                  name="confirmPassword"
                  type={showConfirm ? 'text' : 'password'}
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
                  onClick={() => setShowConfirm(!showConfirm)}
                  aria-label={showConfirm ? 'Hide password' : 'Show password'}
                  tabIndex={0}
                >
                  {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
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
                  <span className="cyber-spinner" /> UPDATING CIPHER...
                </span>
              ) : (
                <span className="btn-state">
                  SAVE NEW CIPHER <ArrowRight size={15} className="btn-arrow" />
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
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="login-page web3-login-page">
      <CyberCanvas />
      <div className="web3-ambient-glow" aria-hidden="true" />
      <Suspense fallback={<div className="text-white text-center">Loading recovery interface...</div>}>
        <ResetPasswordForm />
      </Suspense>
    </main>
  );
}
