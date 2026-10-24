export default function Pagination({ page, pageSize, total, onChange }) {
  const pages = Math.max(1, Math.ceil((total ?? 0) / pageSize));
  return (
    <div className="pagination">
      <button disabled={page <= 1} onClick={() => onChange(page - 1)}>Previous</button>
      <span>Page {page} of {pages} ({total ?? 0} records)</span>
      <button disabled={page >= pages} onClick={() => onChange(page + 1)}>Next</button>
    </div>
  );
}
