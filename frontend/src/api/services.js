// One small module per backend service. Pages never build URLs themselves, so when a
// service's contract changes there is exactly one place to update.
// List endpoints return: { items: [...], total, page, page_size }
import { api } from './client.js';

export const authApi = {
  login: (email, password) => api.post('/auth/login', { email, password }),
  listUsers: (params) => api.get('/users', params),
  createUser: (user) => api.post('/users', user),
  updateUser: (id, changes) => api.put(`/users/${id}`, changes),
  me: () => api.get('/auth/me'),
  changePassword: (current_password, new_password) => api.post('/auth/change-password', { current_password, new_password }),
};

export const admissionApi = {
  list: (params) => api.get('/admissions', params),
  get: (id) => api.get(`/admissions/${id}`),
  create: (data) => api.post('/admissions', data),
  update: (id, data) => api.put(`/admissions/${id}`, data),
  enroll: (id) => api.post(`/admissions/${id}/enroll`),
};

export const studentApi = {
  list: (params) => api.get('/students', params),
  get: (id) => api.get(`/students/${id}`),
  create: (data) => api.post('/students', data),
  update: (id, data) => api.put(`/students/${id}`, data),
  classes: (params) => api.get('/classes', params),
  sections: (params) => api.get('/sections', params),
};

export const feeApi = {
  listFees: (params) => api.get('/fees', params),
  studentFees: (studentId, params) => api.get(`/students/${studentId}/fees`, params),
};

export const paymentApi = {
  list: (params) => api.get('/payments', params),
  get: (id) => api.get(`/payments/${id}`),
  // Idempotency-Key makes a retried/double-clicked request create only one payment.
  create: (data, idempotencyKey) =>
    api.post('/payments', data, { headers: { 'Idempotency-Key': idempotencyKey } }),
};

export const attendanceApi = {
  mark: (data) => api.post('/attendance', data),
  markSection: (data) => api.post('/attendance/bulk', data),
  list: (params) => api.get('/attendance', params),
  summary: (date) => api.get('/attendance/summary', { date }),
  forStudent: (studentId, params) => api.get(`/students/${studentId}/attendance`, params),
};

export const notificationApi = {
  list: (params) => api.get('/notifications', params),
  get: (id) => api.get(`/notifications/${id}`),
  retry: (id) => api.post(`/notifications/${id}/retry`),
};
