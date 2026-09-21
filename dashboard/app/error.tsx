'use client';

import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { RefreshCw, RotateCcw } from 'lucide-react';

export default function ErrorBoundaryPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Attempt automatic recovery once per session if a transient render/hydration conflict occurs
    try {
      const recovered = sessionStorage.getItem('vessel_client_recovered');
      if (!recovered) {
        sessionStorage.setItem('vessel_client_recovered', Date.now().toString());
        window.location.reload();
      } else {
        // Clear recovery marker after 10 seconds so future genuine refreshes can still self-heal
        const last = Number(recovered);
        if (Date.now() - last > 10000) {
          sessionStorage.removeItem('vessel_client_recovered');
        }
      }
    } catch {
      /* ignore */
    }
  }, [error]);

  return (
    <main className="login-page">
      <section className="login-card" style={{ maxWidth: 440, textAlign: 'center' }}>
        <h1 style={{ fontSize: 20, marginBottom: 8 }}>Workspace Reconnecting</h1>
        <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 20 }}>
          A transient connection or rendering refresh occurred. Re-establishing secure companion bridge...
        </p>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
          <Button onClick={() => reset()} className="primary-action">
            <RefreshCw size={14} style={{ marginRight: 6 }} />
            Try again
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              window.location.href = '/';
            }}
          >
            <RotateCcw size={14} style={{ marginRight: 6 }} />
            Return to Dashboard
          </Button>
        </div>
      </section>
    </main>
  );
}
