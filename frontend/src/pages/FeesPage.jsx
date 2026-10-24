import { feeApi } from '../api/services.js';
import ListPage from '../components/ListPage.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import { formatDate, formatMoney } from '../utils/format.js';

export default function FeesPage() {
  return (
    <ListPage
      title="Fees"
      fetcher={feeApi.listFees}
      statuses={['PENDING', 'PARTIAL', 'PAID', 'OVERDUE']}
      columns={[
        { header: 'Student', key: 'student_name' },
        { header: 'Fee', key: 'name' },
        { header: 'Amount due', render: (r) => formatMoney(r.amount_due) },
        { header: 'Outstanding', render: (r) => formatMoney(r.outstanding) },
        { header: 'Due date', render: (r) => formatDate(r.due_date) },
        { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
      ]}
    />
  );
}
