import { useState } from 'react';
import { authApi } from '../api/services.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useForm } from '../hooks/useForm.js';
import ListPage from '../components/ListPage.jsx';
import Field from '../components/Field.jsx';
import { ErrorMessage, Success } from '../components/Feedback.jsx';
import StatusBadge from '../components/StatusBadge.jsx';

function CreateUserForm({ onCreated }) {
  const form = useForm({ email: '', full_name: '', role: 'teacher', password: '' }, async (v) => {
    await authApi.createUser(v);
    onCreated();
    return true;
  });
  return (
    <form className="card form-grid" onSubmit={form.submit}>
      <h2>Create user</h2>
      <Field label="Full name"><input required {...form.bind('full_name')} /></Field>
      <Field label="Email"><input type="email" required {...form.bind('email')} /></Field>
      <Field label="Role">
        <select {...form.bind('role')}><option value="teacher">teacher</option><option value="parent">parent</option><option value="admin">admin</option></select>
      </Field>
      <Field label="Temporary password (12+ characters)">
        <input type="password" minLength={12} autoComplete="new-password" required {...form.bind('password')} />
      </Field>
      <ErrorMessage error={form.error} />
      <Success>{form.done && 'User created.'}</Success>
      <button className="primary" disabled={form.submitting}>Create</button>
    </form>
  );
}

export default function AdminPage() {
  const { user: me } = useAuth();
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionError, setActionError] = useState(null);

  // Disabling an account stops new logins at once. A token already issued still works until it expires
  // (30 minutes), because services check tokens without asking this service.
  const setActive = async (id, is_active) => {
    setActionError(null);
    try {
      await authApi.updateUser(id, { is_active });
    } catch (err) {
      setActionError(err);
    }
    setRefreshKey((k) => k + 1);
  };

  return (
    <ListPage
      title="Admin: users"
      fetcher={authApi.listUsers}
      refreshKey={refreshKey}
      columns={[
        { header: 'Name', key: 'full_name' },
        { header: 'Email', key: 'email' },
        { header: 'Role', key: 'role' },
        { header: 'Status', render: (r) => <StatusBadge value={r.is_active ? 'ACTIVE' : 'FAILED'} /> },
        {
          header: 'Actions',
          render: (r) => r.id !== me.id && (
            <button onClick={() => setActive(r.id, !r.is_active)}>{r.is_active ? 'Disable' : 'Enable'}</button>
          ),
        },
      ]}
    >
      <ErrorMessage error={actionError} />
      <CreateUserForm onCreated={() => setRefreshKey((k) => k + 1)} />
    </ListPage>
  );
}
