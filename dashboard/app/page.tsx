import { getDashboardAuth } from './auth';
import LoginForm from './login-form';
import Workspace from './workspace';
import AccountPanel from './account-panel';
import AccountBoundary from './account-boundary';
export const dynamic = 'force-dynamic';
export default async function Home() {
  const auth = await getDashboardAuth().catch(() => null);
  if (!auth) {
    return (
      <main className="login-page">
        <section className="login-card">
          <h1>Sign-in is unavailable</h1>
          <p>
            Account setup or storage needs attention. Try again shortly, or
            contact the owner.
          </p>
        </section>
      </main>
    );
  }
  const { user } = auth;
  if (!user) return <LoginForm />;
  return (
    <AccountBoundary user={user}>
      {user.mustChangePassword ? (
        <AccountPanel user={user} />
      ) : (
        <Workspace signedIn accountId={user.userId} user={user} />
      )}
    </AccountBoundary>
  );
}
