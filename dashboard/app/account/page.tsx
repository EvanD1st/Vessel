import { getDashboardAuth } from '../auth';
import LoginForm from '../login-form';
import AccountPanel from '../account-panel';
import AccountBoundary from '../account-boundary';
export const dynamic = 'force-dynamic';
export default async function AccountPage() {
  const { user } = await getDashboardAuth();
  if (!user) return <LoginForm />;
  return (
    <AccountBoundary user={user}>
      <AccountPanel user={user} />
    </AccountBoundary>
  );
}
