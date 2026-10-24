import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';

// Which roles see which menu entries. Cosmetic only; the backend enforces access.
const NAV = [
  { to: '/', label: 'Dashboard', roles: ['admin', 'teacher', 'parent'], end: true },
  { to: '/admissions', label: 'Admissions', roles: ['admin', 'parent'] },
  { to: '/students', label: 'Students', roles: ['admin', 'teacher', 'parent'] },
  { to: '/fees', label: 'Fees', roles: ['admin', 'parent'] },
  { to: '/payments', label: 'Payments', roles: ['admin', 'parent'] },
  { to: '/attendance', label: 'Attendance', roles: ['admin', 'teacher', 'parent'] },
  { to: '/notifications', label: 'Notifications', roles: ['admin', 'teacher', 'parent'] },
  { to: '/admin', label: 'Admin', roles: ['admin'] },
];

export default function Layout() {
  const { user, logout } = useAuth();
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">School Portal</div>
        <nav>
          {NAV.filter((n) => n.roles.includes(user.role)).map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}>{n.label}</NavLink>
          ))}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <span>{user.name} <span className="badge badge-info">{user.role}</span></span>
          <button onClick={logout}>Sign out</button>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
