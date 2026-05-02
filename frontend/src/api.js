const TOKEN_KEY = "ai-paper-token";
const REFRESH_TOKEN_KEY = "ai-paper-refresh-token";
const USER_KEY = "ai-paper-user";

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setSession(data) {
  localStorage.setItem(TOKEN_KEY, data.access_token);
  localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh_token);
  localStorage.setItem(USER_KEY, JSON.stringify(data.user));
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

export function getUser() {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

async function request(baseUrl, path, options = {}) {
  const token = getToken();
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${baseUrl}${path}`, { ...options, headers });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!res.ok) throw new Error(data?.detail || `HTTP ${res.status}`);
  return data;
}

export async function register(baseUrl, payload) {
  return request(baseUrl, "/auth/register", { method: "POST", body: JSON.stringify(payload) });
}

export async function loginEmail(baseUrl, payload) {
  const data = await request(baseUrl, "/auth/login/email", { method: "POST", body: JSON.stringify(payload) });
  setSession(data);
  return data;
}

export async function getCmsDashboard(baseUrl) {
  return request(baseUrl, "/cms/dashboard/overview");
}

export async function uploadDocument(baseUrl, file) {
  const form = new FormData();
  form.append("file", file);
  return request(baseUrl, "/documents/upload", { method: "POST", body: form });
}

export async function listDocuments(baseUrl) {
  return request(baseUrl, "/documents?page=1&page_size=50");
}

export async function deleteDocument(baseUrl, documentId) {
  return request(baseUrl, `/documents/${documentId}`, { method: "DELETE" });
}

export async function requestDocumentProcessing(baseUrl, documentId) {
  return request(baseUrl, `/cms/documents/${documentId}/process/request`, { method: "POST" });
}

export async function requestSummary(baseUrl, documentId, level) {
  return request(baseUrl, `/cms/documents/${documentId}/summary/request`, {
    method: "POST",
    body: JSON.stringify({ level }),
  });
}

export async function getJobStatus(baseUrl, jobId) {
  return request(baseUrl, `/cms/jobs/${jobId}`);
}

export async function getSummary(baseUrl, documentId) {
  return request(baseUrl, `/cms/documents/${documentId}/summary`);
}

export async function requestQa(baseUrl, documentId, question) {
  return request(baseUrl, `/cms/documents/${documentId}/qa/request`, {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export async function searchInDocument(baseUrl, documentId, query) {
  return request(baseUrl, `/cms/documents/${documentId}/search`, {
    method: "POST",
    body: JSON.stringify({ query, limit: 10 }),
  });
}

export async function searchAllDocuments(baseUrl, query) {
  return request(baseUrl, "/cms/search", {
    method: "POST",
    body: JSON.stringify({ query, limit: 10 }),
  });
}

export async function getGraph(baseUrl, documentId) {
  return request(baseUrl, `/cms/documents/${documentId}/graph`);
}

export async function getRecommendations(baseUrl, documentId) {
  return request(baseUrl, `/cms/documents/${documentId}/recommendations`);
}
