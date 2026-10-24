import { useState } from 'react';
import { admissionApi } from '../api/services.js';
import { useForm } from '../hooks/useForm.js';
import { useAuth } from '../auth/AuthContext.jsx';
import ListPage from '../components/ListPage.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import Field from '../components/Field.jsx';
import { ErrorMessage, Success } from '../components/Feedback.jsx';
import { formatDate } from '../utils/format.js';

const STATUSES = ['SUBMITTED', 'UNDER_REVIEW', 'APPROVED', 'REJECTED', 'ENROLLED'];
const EMPTY = { applicant_name: '', date_of_birth: '', class_applied: '', parent_name: '', parent_email: '', parent_phone: '' };

function AdmissionForm({ onCreated }) {
  const form = useForm(EMPTY, async (v) => {
    const created = await admissionApi.create({
      applicant_name: v.applicant_name,
      date_of_birth: v.date_of_birth,
      class_applied: v.class_applied,
      parents: [{ name: v.parent_name, email: v.parent_email, phone: v.parent_phone }],
    });
    onCreated();
    return created;
  });
  return (
    <form className="card form-grid" onSubmit={form.submit}>
      <h2>New admission application</h2>
      <Field label="Student name"><input required {...form.bind('applicant_name')} /></Field>
      <Field label="Date of birth"><input type="date" required {...form.bind('date_of_birth')} /></Field>
      <Field label="Class applied for"><input required {...form.bind('class_applied')} /></Field>
      <Field label="Parent name"><input required {...form.bind('parent_name')} /></Field>
      <Field label="Parent email"><input type="email" required {...form.bind('parent_email')} /></Field>
      <Field label="Parent phone"><input required {...form.bind('parent_phone')} /></Field>
      <ErrorMessage error={form.error} />
      <Success>{form.done && `Application submitted (status: ${form.done.status ?? 'SUBMITTED'}). The parent will be notified.`}</Success>
      <button className="primary" disabled={form.submitting}>{form.submitting ? 'Submitting…' : 'Submit application'}</button>
    </form>
  );
}

export default function AdmissionsPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const { user } = useAuth();
  const canReview = user.role === 'admin';

  const [actionError, setActionError] = useState(null);
  const run = async (action) => {
    setActionError(null);
    try {
      await action();
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setActionError(err);
    }
  };
  const setStatus = (id, status) => run(() => admissionApi.update(id, { status }));
  const enroll = (id) => run(() => admissionApi.enroll(id));

  return (
    <ListPage
      title="Admissions"
      fetcher={admissionApi.list}
      statuses={STATUSES}
      refreshKey={refreshKey}
      columns={[
        { header: 'Applicant', key: 'applicant_name' },
        { header: 'Class', key: 'class_applied' },
        { header: 'Submitted', render: (r) => formatDate(r.submitted_at) },
        { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
        ...(canReview ? [{ header: 'Actions', render: (r) => (
          <>
            {r.status === 'SUBMITTED' && (
              <>
                <button onClick={() => setStatus(r.id, 'APPROVED')}>Approve</button>{' '}
                <button onClick={() => setStatus(r.id, 'REJECTED')}>Reject</button>
              </>
            )}
            {r.status === 'APPROVED' && <button onClick={() => enroll(r.id)}>Enroll student</button>}
          </>
        ) }] : []),
      ]}
    >
      <ErrorMessage error={actionError} />
      <AdmissionForm onCreated={() => setRefreshKey((k) => k + 1)} />
    </ListPage>
  );
}
