'use client';
import { useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export default function LoginForm() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <main className="login-page">
      <section className="login-card" aria-labelledby="login-title">
        <div className="login-brand">
          <ShieldCheck aria-hidden="true" size={30} />
          <span>VESSEL</span>
        </div>
        <h1 id="login-title">Sign in to your workspace</h1>
        <p>Use the account provided by your workspace owner.</p>
        <form
          className="owner-form"
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
          <div className="form-field">
            <label htmlFor="login-email">Email</label>
            <Input
              id="login-email"
              name="email"
              type="email"
              autoComplete="username"
              required
              maxLength={254}
            />
          </div>
          <div className="form-field">
            <label htmlFor="login-password">Password</label>
            <Input
              id="login-password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
            />
          </div>
          {error && (
            <p className="notice error" role="alert">
              {error}
            </p>
          )}
          <Button className="primary-action" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>
        <small>
          Invite-only access. Need an account or a password reset? Contact your
          workspace owner.
        </small>
      </section>
    </main>
  );
}
