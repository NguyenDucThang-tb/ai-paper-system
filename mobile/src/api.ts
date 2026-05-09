import { Platform } from 'react-native';

import { clearSession, getSessionState, setSession, type SessionUser } from './session';

const API_BASE_URL =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  (Platform.OS === 'android' ? 'http://10.0.2.2:8000/api/v1' : 'http://127.0.0.1:8000/api/v1');

function queryString(params: Record<string, string | number | undefined | null>) {
  const entries = Object.entries(params).filter(([, value]) => value !== undefined && value !== null && value !== '');
  if (!entries.length) return '';
  return `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString()}`;
}

async function request(path: string, options: RequestInit = {}) {
  const session = getSessionState();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(session.accessToken ? { Authorization: `Bearer ${session.accessToken}` } : {}),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const contentType = response.headers.get('content-type') || '';
    if (response.status === 401) {
      await clearSession();
    }
    if (contentType.includes('application/json')) {
      const error = await response.json().catch(() => ({}));
      const detail = error?.detail;
      if (typeof detail === 'string' && detail) throw new Error(detail);
      if (Array.isArray(detail) && detail[0]?.msg) throw new Error(detail[0].msg);
      throw new Error(error?.message || 'Request failed');
    }
    const raw = await response.text().catch(() => '');
    throw new Error(raw || 'Request failed');
  }

  if (response.status === 204) return null;
  return response.json();
}

export type DocumentItem = {
  id: string | number;
  filename?: string;
  status?: string;
  metadata?: {
    title?: string;
    publication_year?: string | number;
    authors?: string[];
    abstract?: string;
    topics?: string[];
    keywords?: string[];
  };
};

export const api = {
  apiBaseUrl: API_BASE_URL,
  login: async (email: string, password: string) => {
    const data = await request('/auth/login/email', {
      method: 'POST',
      body: JSON.stringify({ email, password, device_id: 'mobile' }),
    });
    await setSession(data);
    return data;
  },
  loginWithGoogle: async (idToken: string) => {
    const data = await request('/auth/login/google', {
      method: 'POST',
      body: JSON.stringify({ id_token: idToken, device_id: 'mobile-google' }),
    });
    await setSession(data);
    return data;
  },
  register: (payload: { email: string; password: string; full_name: string }) =>
    request('/auth/register', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  sendForgotPasswordCode: (email: string) =>
    request('/auth/forgot-password/send-code', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),
  verifyForgotPasswordCode: (email: string, code: string) =>
    request('/auth/forgot-password/verify-code', {
      method: 'POST',
      body: JSON.stringify({ email, code }),
    }),
  resetPasswordWithCode: (email: string, code: string, newPassword: string) =>
    request('/auth/forgot-password/reset-password', {
      method: 'POST',
      body: JSON.stringify({ email, code, new_password: newPassword }),
    }),
  me: () => request('/users/me') as Promise<SessionUser>,
  updateProfile: (payload: { full_name?: string }) =>
    request('/users/me', {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  changePassword: (payload: { old_password: string; new_password: string }) =>
    request('/users/me/change-password', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  userDashboard: () => request('/users/me/dashboard'),
  dashboard: () => request('/cms/dashboard/overview'),
  adminUsers: () => request('/admin/users'),
  updateAdminUser: (userId: string, payload: Record<string, any>) =>
    request(`/admin/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  listWorkspaces: (params: Record<string, string | number | undefined> = {}) =>
    request(`/workspaces/${queryString(params)}`),
  createWorkspace: (title = 'Untitled notebook') =>
    request('/workspaces/', {
      method: 'POST',
      body: JSON.stringify({ title }),
    }),
  getWorkspace: (workspaceId: string) => request(`/workspaces/${workspaceId}`),
  updateWorkspace: (workspaceId: string, payload: Record<string, any>) =>
    request(`/workspaces/${workspaceId}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  deleteWorkspace: (workspaceId: string) =>
    request(`/workspaces/${workspaceId}`, {
      method: 'DELETE',
    }),
  listDocuments: (params: Record<string, string | number | undefined> = {}) =>
    request(`/documents/${queryString(params)}`),
  getDocument: (documentId: string) => request(`/documents/${documentId}`),
  getDocumentTimeline: (documentId: string) => request(`/documents/${documentId}/timeline`),
  getQaHistory: (documentId: string) => request(`/documents/${documentId}/qa`),
  deleteDocument: (documentId: string) =>
    request(`/documents/${documentId}`, {
      method: 'DELETE',
    }),
  search: (query: string, limit = 10) =>
    request('/cms/search', {
      method: 'POST',
      body: JSON.stringify({ query, limit }),
    }),
  documentSearch: (documentId: string, query: string, limit = 10) =>
    request(`/cms/documents/${documentId}/search`, {
      method: 'POST',
      body: JSON.stringify({ query, limit }),
    }),
  requestQuestion: (documentId: string, question: string) =>
    request(`/cms/documents/${documentId}/qa/request`, {
      method: 'POST',
      body: JSON.stringify({ question }),
    }),
  requestSummary: (documentId: string, level: 'short' | 'medium' | 'long' = 'medium') =>
    request(`/cms/documents/${documentId}/summary/request`, {
      method: 'POST',
      body: JSON.stringify({ level }),
    }),
  getSummary: (documentId: string) => request(`/cms/documents/${documentId}/summary`),
  getRecommendations: (documentId: string) => request(`/cms/documents/${documentId}/recommendations`),
  getGraph: (documentId: string) => request(`/cms/documents/${documentId}/graph`),
  getJobStatus: (jobId: string) => request(`/cms/jobs/${jobId}`),
  analytics: (groupBy = 'year') => request(`/cms/analytics/overview?group_by=${groupBy}`),
  uploadDocument: (file: { uri: string; name: string; type?: string }, workspaceId?: string) => {
    const formData = new FormData();
    formData.append('file', {
      uri: file.uri,
      name: file.name,
      type: file.type || 'application/pdf',
    } as any);
    if (workspaceId) formData.append('workspace_id', workspaceId);
    return request('/documents/upload', {
      method: 'POST',
      body: formData,
    });
  },
};
