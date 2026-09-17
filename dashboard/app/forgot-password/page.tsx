import Link from 'next/link';

export default function ForgotPasswordPage() {
  return <main className="login-page"><section className="login-card"><h1>Password help</h1>
    <p>Ask your workspace owner to reset your password. They can issue a temporary password from Account settings.</p>
    <Link href="/">Back to sign in</Link></section></main>;
}
