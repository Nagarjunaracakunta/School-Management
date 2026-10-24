export const formatDate = (iso) => (iso ? new Date(iso).toLocaleDateString() : '-');
export const formatDateTime = (iso) => (iso ? new Date(iso).toLocaleString() : '-');
export const formatMoney = (amount) =>
  amount == null ? '-' : new Intl.NumberFormat(undefined, { style: 'currency', currency: 'INR' }).format(amount);
export const today = () => new Date().toISOString().slice(0, 10);
