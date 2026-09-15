'use client';
import { useEffect, useState, type ReactNode } from 'react';
export type AccountUser = {
  userId: string;
  email: string;
  displayName: string;
  role: string;
  mustChangePassword: boolean;
};
export function notifyAccountChange() {
  try {
    localStorage.setItem('vessel_account_changed', crypto.randomUUID());
  } catch {
    /* Polling still revalidates other tabs. */
  }
}
export default function AccountBoundary({
  user,
  children,
}: {
  user: AccountUser;
  children: ReactNode;
}) {
  const [available, setAvailable] = useState(true);
  useEffect(() => {
    let stopped = false;
    let pending = false;
    async function check() {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch('/api/session', { cache: 'no-store' });
        if (!response.ok) throw new Error('unavailable');
        const data = (await response.json()) as { user: AccountUser | null };
        if (stopped) return;
        if (
          data.user?.userId !== user.userId ||
          data.user.mustChangePassword !== user.mustChangePassword
        ) {
          setAvailable(false);
          window.location.replace('/');
        } else setAvailable(true);
      } catch {
        if (!stopped) setAvailable(false);
      } finally {
        pending = false;
      }
    }
    void check();
    const timer = setInterval(() => void check(), 30000);
    const onStorage = (event: StorageEvent) => {
      if (event.key === 'vessel_account_changed') void check();
    };
    const onFocus = () => void check();
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', onFocus);
    return () => {
      stopped = true;
      clearInterval(timer);
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', onFocus);
    };
  }, [user.userId, user.mustChangePassword]);
  return available ? (
    children
  ) : (
    <main className="login-page">
      <section className="login-card">
        <h1>Checking your account</h1>
        <p>
          Your workspace is paused until your sign-in can be verified.
          Reconnecting automatically…
        </p>
      </section>
    </main>
  );
}
