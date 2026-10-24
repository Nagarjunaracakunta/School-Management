import { useState } from 'react';
import { notificationApi } from '../api/services.js';
import { useAuth } from '../auth/AuthContext.jsx';
import ListPage from '../components/ListPage.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import { ErrorMessage } from '../components/Feedback.jsx';
import { formatDateTime } from '../utils/format.js';

export default function NotificationsPage() {
  const { user } = useAuth();
  const [refreshKey, setRefreshKey] = useState(0);
  const [actionError, setActionError] = useState(null);

  const retry = async (id) => {
    setActionError(null);
    try {
      await notificationApi.retry(id);
    } catch (err) {
      setActionError(err);
    }
    setRefreshKey((k) => k + 1);
  };

  return (
    <ListPage
      title="Notifications"
      fetcher={notificationApi.list}
      statuses={['PENDING', 'SENT', 'FAILED']}
      refreshKey={refreshKey}
      columns={[
        { header: 'Subject', render: (r) => r.subject || r.message.slice(0, 50) },
        { header: 'Event', key: 'event_type' },
        { header: 'Recipient', key: 'recipient' },
        { header: 'Channel', key: 'channel' },
        { header: 'Attempts', key: 'attempts' },
        { header: 'Created', render: (r) => formatDateTime(r.created_at) },
        { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
        ...(user.role === 'admin'
          ? [{ header: 'Actions', render: (r) => r.status !== 'SENT' && <button onClick={() => retry(r.id)}>Retry</button> }]
          : []),
      ]}
    >
      <ErrorMessage error={actionError} />
    </ListPage>
  );
}
