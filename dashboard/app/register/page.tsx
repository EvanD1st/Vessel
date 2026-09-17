import Link from 'next/link';

export default function RegisterPage() {
  return <main className="login-page"><section className="login-card"><h1>Invitation required</h1>
    <p>The workspace owner creates accounts and shares temporary credentials directly with invited users.</p>
    <Link href="/">Back to sign in</Link></section></main>;
}
