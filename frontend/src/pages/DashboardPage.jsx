import { admissionApi, attendanceApi, feeApi, notificationApi, paymentApi, studentApi } from '../api/services.js';
import { useApi } from '../hooks/useApi.js';
import { formatDateTime, formatMoney, today } from '../utils/format.js';
import DataTable from '../components/DataTable.jsx';
import StatusBadge from '../components/StatusBadge.jsx';

// Each card loads independently: one failing service must not blank the whole dashboard.
// There is no fake data. A card whose API is down shows "Unavailable".
function StatCard({ label, load, render = (d) => d }) {
  const { data, error, loading } = useApi(load, []);
  return (
    <div className="card stat">
      <div className="muted">{label}</div>
      <div className="stat-value" title={error ? `${error.message} (ref ${error.requestId ?? 'n/a'})` : undefined}>
        {loading ? '…' : error ? 'Unavailable' : render(data)}
      </div>
    </div>
  );
}

function RecentList({ title, load, columns }) {
  const { data, error, loading } = useApi(load, []);
  return (
    <div className="card">
      <h2>{title}</h2>
      {loading ? <p className="muted">Loading…</p>
        : error ? <p className="muted">Unavailable ({error.message})</p>
        : <DataTable columns={columns} rows={data?.items} />}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <section>
      <h1>Dashboard</h1>
      <div className="grid">
        <StatCard label="Total students" load={() => studentApi.list({ page_size: 1 })} render={(d) => d.total} />
        <StatCard label="New admissions" load={() => admissionApi.list({ status: 'SUBMITTED', page_size: 1 })}
                  render={(d) => d.total} />
        <StatCard label="Unpaid fees" load={() => feeApi.listFees({ outstanding: true, page_size: 1 })}
                  render={(d) => d.total} />
        <StatCard label="Today's attendance" load={() => attendanceApi.summary(today())}
                  render={(d) => (d.total ? `${d.present} / ${d.total} present` : 'Not marked yet')} />
      </div>
      <div className="grid two">
        <RecentList title="Recent payments" load={() => paymentApi.list({ page_size: 5 })} columns={[
          { header: 'Receipt', key: 'receipt_no' },
          { header: 'Amount', render: (r) => formatMoney(r.amount) },
          { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
        ]} />
        <RecentList title="Recent notifications" load={() => notificationApi.list({ page_size: 5 })} columns={[
          { header: 'Type', key: 'event_type' },
          { header: 'Channel', key: 'channel' },
          { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
          { header: 'When', render: (r) => formatDateTime(r.created_at) },
        ]} />
      </div>
    </section>
  );
}
