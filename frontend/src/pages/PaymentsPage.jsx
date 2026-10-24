import { useRef, useState } from 'react';
import { feeApi, paymentApi } from '../api/services.js';
import { useApi } from '../hooks/useApi.js';
import { useForm } from '../hooks/useForm.js';
import ListPage from '../components/ListPage.jsx';
import StatusBadge from '../components/StatusBadge.jsx';
import Field from '../components/Field.jsx';
import { ErrorMessage, Success } from '../components/Feedback.jsx';
import { formatDateTime, formatMoney } from '../utils/format.js';

function PaymentForm({ onPaid, refreshKey }) {
  // One key per payment attempt: a retry or double-click reuses it, so the backend
  // creates a single payment. A new key is generated only after a success.
  const keyRef = useRef(crypto.randomUUID());
  // Only fees that still have a balance can be paid, so offer exactly those instead of asking for an ID.
  const fees = useApi(() => feeApi.listFees({ outstanding: true, page_size: 100 }), [refreshKey]);
  const form = useForm({ fee_id: '', amount: '', method: 'CARD' }, async (v) => {
    const payment = await paymentApi.create(
      { fee_id: v.fee_id, amount: Number(v.amount), method: v.method },
      keyRef.current,
    );
    keyRef.current = crypto.randomUUID();
    onPaid();
    return payment;
  });
  return (
    <form className="card form-grid" onSubmit={form.submit}>
      <h2>Pay a fee</h2>
      <Field label="Fee">
        <select required {...form.bind('fee_id')}>
          <option value="">Select a fee…</option>
          {fees.data?.items.map((f) => (
            <option key={f.id} value={f.id}>{f.student_name}: {f.name} (due {formatMoney(f.outstanding)})</option>
          ))}
        </select>
      </Field>
      <Field label="Amount"><input type="number" min="0.01" step="0.01" required {...form.bind('amount')} /></Field>
      <Field label="Method">
        <select {...form.bind('method')}><option>CARD</option><option>UPI</option><option>CASH</option></select>
      </Field>
      <ErrorMessage error={form.error} />
      <Success>{form.done && `Payment accepted. Receipt: ${form.done.receipt_no ?? 'pending'}`}</Success>
      <button className="primary" disabled={form.submitting}>{form.submitting ? 'Processing…' : 'Pay'}</button>
    </form>
  );
}

export default function PaymentsPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  return (
    <ListPage
      title="Payments"
      fetcher={paymentApi.list}
      statuses={['COMPLETED', 'FAILED', 'PENDING']}
      refreshKey={refreshKey}
      columns={[
        { header: 'Receipt', key: 'receipt_no' },
        { header: 'Fee', key: 'fee_id' },
        { header: 'Amount', render: (r) => formatMoney(r.amount) },
        { header: 'Method', key: 'method' },
        { header: 'Paid at', render: (r) => formatDateTime(r.created_at) },
        { header: 'Status', render: (r) => <StatusBadge value={r.status} /> },
      ]}
    >
      <PaymentForm refreshKey={refreshKey} onPaid={() => setRefreshKey((k) => k + 1)} />
    </ListPage>
  );
}
