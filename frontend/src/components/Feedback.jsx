export const Loading = () => <p className="muted" role="status">Loading…</p>;

export function ErrorMessage({ error }) {
  if (!error) return null;
  return (
    <div className="alert alert-error" role="alert">
      <strong>{error.message}</strong>
      {error.details && <pre>{JSON.stringify(error.details, null, 2)}</pre>}
      {error.requestId && <div className="muted">Reference: {error.requestId}</div>}
    </div>
  );
}

export const Success = ({ children }) =>
  children ? <div className="alert alert-ok" role="status">{children}</div> : null;
