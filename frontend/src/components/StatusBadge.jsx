const TONE = {
  APPROVED: 'good', ENROLLED: 'good', PAID: 'good', PRESENT: 'good', SENT: 'good', COMPLETED: 'good', ACTIVE: 'good',
  SUBMITTED: 'info', UNDER_REVIEW: 'info', PENDING: 'warn', PARTIAL: 'warn', LATE: 'warn',
  REJECTED: 'bad', FAILED: 'bad', OVERDUE: 'bad', ABSENT: 'bad',
};

export default function StatusBadge({ value }) {
  if (!value) return '-';
  return <span className={`badge badge-${TONE[value] ?? 'info'}`}>{value.replace('_', ' ')}</span>;
}
