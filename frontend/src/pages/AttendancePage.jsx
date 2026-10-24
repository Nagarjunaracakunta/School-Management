import { useState } from 'react';
import { attendanceApi, studentApi } from '../api/services.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { useApi } from '../hooks/useApi.js';
import ListPage from '../components/ListPage.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import Field from '../components/Field.jsx';
import { ErrorMessage, Loading, Success } from '../components/Feedback.jsx';
import { formatDate, today } from '../utils/format.js';

const OPTIONS = ['PRESENT', 'ABSENT', 'LATE'];

// A teacher marks a whole class at once: pick a section, everyone starts as PRESENT, change the exceptions.
// The Student Service only returns the students this user may mark, so other sections come back empty.
function RosterForm({ onSaved }) {
  const sections = useApi(() => studentApi.sections({ page_size: 100 }), []);
  const [sectionId, setSectionId] = useState('');
  const [date, setDate] = useState(today());
  const [marks, setMarks] = useState({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const roster = useApi(
    () => (sectionId ? studentApi.list({ section_id: sectionId, status: 'ACTIVE', page_size: 100 }) : Promise.resolve(null)),
    [sectionId],
  );

  const pickSection = (id) => { setSectionId(id); setMarks({}); setResult(null); setError(null); };

  const save = async (e) => {
    e.preventDefault();
    if (saving) return;
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const records = roster.data.items.map((s) => ({ student_id: s.id, status: marks[s.id] ?? 'PRESENT' }));
      setResult(await attendanceApi.markSection({ section_id: sectionId, date, records }));
      onSaved();
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  const students = roster.data?.items ?? [];
  return (
    <form className="card" onSubmit={save}>
      <h2>Mark a class</h2>
      <div className="form-grid">
        <Field label="Section">
          <select required value={sectionId} onChange={(e) => pickSection(e.target.value)}>
            <option value="">Select a section…</option>
            {sections.data?.items.map((s) => <option key={s.id} value={s.id}>{s.class_name} - {s.name}</option>)}
          </select>
        </Field>
        <Field label="Date"><input type="date" max={today()} required value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      </div>
      {sectionId && roster.loading && <Loading />}
      <ErrorMessage error={roster.error} />
      {sectionId && !roster.loading && !students.length && !roster.error && (
        <p className="muted">No students you can mark in this section.</p>
      )}
      {students.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Student</th>{OPTIONS.map((o) => <th key={o}>{o}</th>)}</tr></thead>
            <tbody>
              {students.map((s) => (
                <tr key={s.id}>
                  <td>{s.name}</td>
                  {OPTIONS.map((o) => (
                    <td key={o}>
                      <input type="radio" name={`mark-${s.id}`} aria-label={`${s.name} ${o}`}
                             checked={(marks[s.id] ?? 'PRESENT') === o}
                             onChange={() => setMarks((m) => ({ ...m, [s.id]: o }))} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ErrorMessage error={error} />
      <Success>{result && `Saved: ${result.created} new, ${result.updated} corrected. ${result.absent_notifications} parent(s) will be notified.`}</Success>
      <button className="primary" disabled={saving || !students.length}>{saving ? 'Saving…' : 'Save attendance'}</button>
    </form>
  );
}

export default function AttendancePage() {
  const { user } = useAuth();
  const [refreshKey, setRefreshKey] = useState(0);
  const canMark = user.role === 'admin' || user.role === 'teacher';
  return (
    <ListPage
      title="Attendance"
      fetcher={attendanceApi.list}
      statuses={OPTIONS}
      refreshKey={refreshKey}
      columns={[
        { header: 'Date', render: (r) => formatDate(r.date) },
        { header: 'Type', key: 'subject_type' },
        { header: 'Name', key: 'subject_name' },
        { header: 'Class', render: (r) => (r.class_name ? `${r.class_name} - ${r.section_name}` : '-') },
        { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
      ]}
    >
      {canMark && <RosterForm onSaved={() => setRefreshKey((k) => k + 1)} />}
    </ListPage>
  );
}
