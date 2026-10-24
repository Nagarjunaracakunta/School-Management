import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';
import { useForm } from '../hooks/useForm.js';
import { ErrorMessage } from '../components/Feedback.jsx';
import Field from '../components/Field.jsx';

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname ?? '/';
  const form = useForm({ email: '', password: '' }, async ({ email, password }) => {
    await login(email, password);
    navigate(from, { replace: true });
  });

  if (user) return <Navigate to="/" replace />;
  return (
    <div className="login">
      <form className="card" onSubmit={form.submit}>
        <h1>School Portal</h1>
        <p className="muted">Sign in with your school account.</p>
        <Field label="Email"><input type="email" autoComplete="username" required {...form.bind('email')} /></Field>
        <Field label="Password">
          <input type="password" autoComplete="current-password" required {...form.bind('password')} />
        </Field>
        <ErrorMessage error={form.error} />
        <button className="primary" disabled={form.submitting}>{form.submitting ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  );
}
