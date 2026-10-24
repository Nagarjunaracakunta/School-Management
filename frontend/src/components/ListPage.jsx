import { useState } from 'react';
import { useApi } from '../hooks/useApi.js';
import DataTable from './DataTable.jsx';
import Pagination from './Pagination.jsx';
import { ErrorMessage, Loading } from './Feedback.jsx';

const PAGE_SIZE = 10;

// Reusable "title + optional status filter + paged table" used by most pages.
// `fetcher(params)` must return { items, total }.
export default function ListPage({ title, fetcher, columns, statuses, children, refreshKey = 0 }) {
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState('');
  const { data, error, loading } = useApi(
    () => fetcher({ page, page_size: PAGE_SIZE, status }),
    [page, status, refreshKey],
  );

  return (
    <section>
      <header className="page-header">
        <h1>{title}</h1>
        {statuses && (
          <select aria-label="Filter by status" value={status}
                  onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
      </header>
      {children}
      <ErrorMessage error={error} />
      {loading ? <Loading /> : (
        <>
          <DataTable columns={columns} rows={data?.items} />
          {data && <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onChange={setPage} />}
        </>
      )}
    </section>
  );
}
