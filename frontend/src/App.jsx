import { Navigate, Route, Routes } from 'react-router-dom';
import ProtectedRoute from './auth/ProtectedRoute.jsx';
import Layout from './components/Layout.jsx';
import LoginPage from './pages/LoginPage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import AdmissionsPage from './pages/AdmissionsPage.jsx';
import StudentsPage from './pages/StudentsPage.jsx';
import FeesPage from './pages/FeesPage.jsx';
import PaymentsPage from './pages/PaymentsPage.jsx';
import AttendancePage from './pages/AttendancePage.jsx';
import NotificationsPage from './pages/NotificationsPage.jsx';
import AdminPage from './pages/AdminPage.jsx';

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
        <Route index element={<DashboardPage />} />
        <Route path="admissions" element={<ProtectedRoute roles={['admin', 'parent']}><AdmissionsPage /></ProtectedRoute>} />
        <Route path="students" element={<StudentsPage />} />
        <Route path="fees" element={<ProtectedRoute roles={['admin', 'parent']}><FeesPage /></ProtectedRoute>} />
        <Route path="payments" element={<ProtectedRoute roles={['admin', 'parent']}><PaymentsPage /></ProtectedRoute>} />
        <Route path="attendance" element={<AttendancePage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="admin" element={<ProtectedRoute roles={['admin']}><AdminPage /></ProtectedRoute>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
