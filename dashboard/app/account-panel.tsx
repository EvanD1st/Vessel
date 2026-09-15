'use client';
import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { notifyAccountChange, type AccountUser } from './account-boundary';
type Member = {
  id: string;
  name: string;
  email: string;
  role: string;
  banned: boolean;
  mustChangePassword: boolean;
};
async function api(path: string, body?: unknown) {
  const response = await fetch(
    path,
    body
      ? {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }
      : { cache: 'no-store' },
  );
  const result = (await response.json()) as {
    error?: string;
    users: Member[];
    total: number;
    email: string;
    temporaryPassword?: string;
  };
  if (!response.ok)
    throw new Error(result.error || 'Could not complete this request.');
  return result;
}
export default function AccountPanel({ user }: { user: AccountUser }) {
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [members, setMembers] = useState<Member[]>([]);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [credential, setCredential] = useState<{
    email: string;
    temporaryPassword: string;
  } | null>(null);
  const owner = user.role === 'admin' && !user.mustChangePassword;
  const reload = useCallback(async () => {
    const data = await api('/api/account/users?offset=' + offset);
    setMembers(data.users);
    setTotal(data.total);
  }, [offset]);
  useEffect(() => {
    if (!owner) return;
    const timer = setTimeout(
      () => void reload().catch((e) => setError(e.message)),
      0,
    );
    return () => clearTimeout(timer);
  }, [owner, reload]);
  async function changeMember(body: unknown) {
    setBusy(true);
    setError('');
    setMessage('');
    setCredential(null);
    try {
      const result = await api('/api/account/users', body);
      if (result.temporaryPassword)
        setCredential({
          email: result.email,
          temporaryPassword: result.temporaryPassword,
        });
      else setMessage('Account updated.');
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update account.');
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="account-page">
      <header className="account-heading">
        <div>
          <p className="eyebrow">VESSEL · ACCOUNT</p>
          <h1>
            {user.mustChangePassword ? 'Choose your password' : 'Your account'}
          </h1>
          <p>{user.email}</p>
        </div>
        <div className="account-actions">
          {!user.mustChangePassword && <Link href="/">Back to workspace</Link>}
          <Button
            variant="outline"
            onClick={async () => {
              setError('');
              try {
                const r = await fetch('/api/session', { method: 'DELETE' });
                if (!r.ok) throw new Error();
                notifyAccountChange();
                window.location.assign('/');
              } catch {
                setError('Could not sign out. Try again.');
              }
            }}
          >
            Sign out
          </Button>
        </div>
      </header>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {message && <output className="notice">{message}</output>}
      <section className="panel">
        <div className="panel-heading">
          <h2>
            {user.mustChangePassword
              ? 'Replace your temporary password'
              : 'Change password'}
          </h2>
        </div>
        <div className="panel-body">
          <p>
            Use 12–128 characters. Changing your password signs you out on every
            device.
          </p>
          <form
            className="owner-form"
            onSubmit={async (e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const fields = new FormData(form);
              if (fields.get('newPassword') !== fields.get('confirmPassword')) {
                setError('The new passwords do not match.');
                return;
              }
              setBusy(true);
              setError('');
              try {
                await api('/api/account/password', {
                  currentPassword: fields.get('currentPassword'),
                  newPassword: fields.get('newPassword'),
                });
                form.reset();
                notifyAccountChange();
                window.location.assign('/');
              } catch (failure) {
                setError(
                  failure instanceof Error
                    ? failure.message
                    : 'Could not change password.',
                );
                setBusy(false);
              }
            }}
          >
            <label className="form-field" htmlFor="account-currentPassword">
              {user.mustChangePassword
                ? 'Temporary password'
                : 'Current password'}
              <Input
                id="account-currentPassword"
                name="currentPassword"
                type="password"
                required
                maxLength={128}
                autoComplete="current-password"
              />
            </label>
            <label className="form-field" htmlFor="account-newPassword">
              New password
              <Input
                id="account-newPassword"
                name="newPassword"
                type="password"
                required
                minLength={12}
                maxLength={128}
                autoComplete="new-password"
              />
            </label>
            <label className="form-field" htmlFor="account-confirmPassword">
              Confirm new password
              <Input
                id="account-confirmPassword"
                name="confirmPassword"
                type="password"
                required
                minLength={12}
                maxLength={128}
                autoComplete="new-password"
              />
            </label>
            <Button type="submit" disabled={busy}>
              Save password and sign out
            </Button>
          </form>
        </div>
      </section>
      {owner && (
        <section className="panel">
          <div className="panel-heading">
            <h2>Invite-only accounts</h2>
          </div>
          <div className="panel-body">
            <p>
              Create an account, then give its temporary password directly to
              that person. They must replace it before opening the workspace.
              VESSEL does not send invitation emails.
            </p>
            <form
              className="owner-form"
              onSubmit={async (e) => {
                e.preventDefault();
                const form = e.currentTarget;
                const f = new FormData(form);
                await changeMember({
                  action: 'create',
                  name: f.get('name'),
                  email: f.get('email'),
                });
              }}
            >
              <label className="form-field" htmlFor="account-name">
                Name
                <Input
                  id="account-name"
                  name="name"
                  required
                  maxLength={80}
                  autoComplete="off"
                />
              </label>
              <label className="form-field" htmlFor="account-email">
                Email
                <Input
                  id="account-email"
                  name="email"
                  type="email"
                  required
                  maxLength={254}
                  autoComplete="off"
                />
              </label>
              <Button type="submit" disabled={busy}>
                Create account
              </Button>
            </form>
            {credential && (
              <div className="notice" aria-live="polite">
                <strong>Temporary password for {credential.email}</strong>
                <p>
                  Copy it now and share it privately. It will not be shown
                  again.
                </p>
                <Input
                  aria-label="Temporary password"
                  readOnly
                  value={credential.temporaryPassword}
                  autoComplete="off"
                />
                <Button variant="outline" onClick={() => setCredential(null)}>
                  Dismiss password
                </Button>
              </div>
            )}
            <p>
              Owner changes require a sign-in within the last 15 minutes.
              Disabling an account ends its dashboard sessions. Companion device
              access is managed separately using “Forget connection” or the
              owner CLI.
            </p>
            <div className="account-members">
              {members.map((m) => (
                <article key={m.id} className="account-member">
                  <div>
                    <strong>{m.name}</strong>
                    <p>{m.email}</p>
                    <small>
                      {m.role === 'admin'
                        ? 'Owner'
                        : m.banned
                          ? 'Disabled'
                          : m.mustChangePassword
                            ? 'Temporary password pending'
                            : 'Active'}
                    </small>
                  </div>
                  {m.role === 'user' && (
                    <div className="account-actions">
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void changeMember({
                            action: m.banned ? 'enable' : 'disable',
                            userId: m.id,
                          })
                        }
                      >
                        {m.banned ? 'Enable' : 'Disable'}
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              'Reset the password for ' +
                                m.email +
                                '? Their current password and sessions will stop working.',
                            )
                          )
                            void changeMember({
                              action: 'reset',
                              userId: m.id,
                            });
                        }}
                      >
                        Reset password
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          void changeMember({ action: 'revoke', userId: m.id })
                        }
                      >
                        End sessions
                      </Button>
                    </div>
                  )}
                </article>
              ))}
            </div>
            <div className="account-actions">
              <Button
                variant="outline"
                disabled={busy || offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous
              </Button>
              <span>{total} accounts</span>
              <Button
                variant="outline"
                disabled={busy || offset + 50 >= total}
                onClick={() => setOffset(offset + 50)}
              >
                Next
              </Button>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
