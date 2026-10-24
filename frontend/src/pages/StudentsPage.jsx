import { studentApi } from '../api/services.js';
import ListPage from '../components/ListPage.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import { formatDate } from '../utils/format.js';

export default function StudentsPage() {
  return (
    <ListPage
      title="Students"
      fetcher={studentApi.list}
      statuses={['ACTIVE', 'INACTIVE']}
      columns={[
        { header: 'Name', key: 'name' },
        { header: 'Class', key: 'class_name' },
        { header: 'Section', key: 'section_name' },
        { header: 'Date of birth', render: (r) => formatDate(r.date_of_birth) },
        { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
      ]}
    />
  );
}
