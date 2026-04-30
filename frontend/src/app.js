import {
  clearSession,
  getCmsDashboard,
  getJobStatus,
  getGraph,
  getRecommendations,
  getSummary,
  getUser,
  listDocuments,
  loginEmail,
  register,
  requestDocumentProcessing,
  requestQa,
  requestSummary,
  searchAllDocuments,
  searchInDocument,
  uploadDocument,
} from "./api.js";
import { getPlatformConfig, listPlatforms, setPlatformConfig } from "./platforms.js";

const state = {
  config: getPlatformConfig(),
  selectedDocumentId: null,
};

function byId(id) {
  return document.getElementById(id);
}

function renderUser() {
  const user = getUser();
  byId("userInfo").textContent = user
    ? `${user.email} (${user.role})`
    : "Not logged in";
}

function setStatus(text) {
  byId("statusBadge").textContent = text;
}

function renderPlatforms() {
  const select = byId("platformSelect");
  select.innerHTML = "";
  for (const p of listPlatforms()) {
    const option = document.createElement("option");
    option.value = p.key;
    option.textContent = p.label;
    if (p.key === state.config.platform) option.selected = true;
    select.appendChild(option);
  }
  byId("apiBaseUrl").value = state.config.apiBaseUrl;
}

function setOutput(id, data) {
  byId(id).textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

function selectDocument(id) {
  state.selectedDocumentId = id;
  byId("selectedDocumentIdInput").value = String(id);
}

async function loadDocuments() {
  const data = await listDocuments(state.config.apiBaseUrl);
  const root = byId("documentsList");
  root.innerHTML = "";
  for (const item of data.items || []) {
    const row = document.createElement("tr");
    const statusClass = `status-${item.status || "uploaded"}`;
    row.innerHTML = `
      <td>#${item.id}</td>
      <td>${item.filename || ""}</td>
      <td><span class="status-chip ${statusClass}">${item.status || "unknown"}</span></td>
      <td>${item.file_type || "-"}</td>
      <td>${item.created_at ? new Date(item.created_at).toLocaleString() : "-"}</td>
      <td></td>
    `;
    const btn = document.createElement("button");
    btn.className = "btn";
    btn.textContent = "Select";
    btn.onclick = () => selectDocument(item.id);
    row.children[5].appendChild(btn);
    root.appendChild(row);
  }
}

function renderKpi(data) {
  byId("kpiTotal").textContent = String(data.total_documents || 0);
  byId("kpiUploaded").textContent = String(data.uploaded || 0);
  byId("kpiProcessing").textContent = String(data.processing || 0);
  byId("kpiProcessed").textContent = String(data.processed || 0);
  byId("kpiFailed").textContent = String(data.failed || 0);
}

function readSelectedId() {
  const value = byId("selectedDocumentIdInput").value;
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) throw new Error("Invalid document id");
  return n;
}

function bindEvents() {
  byId("applyPlatformBtn").onclick = () => {
    const platform = byId("platformSelect").value;
    const apiBaseUrl = byId("apiBaseUrl").value.trim();
    state.config = setPlatformConfig(platform, apiBaseUrl);
    setStatus(`Platform: ${state.config.label}`);
    setOutput("aiOutput", { platform: state.config });
  };

  byId("registerBtn").onclick = async () => {
    try {
      setStatus("Registering");
      const data = await register(state.config.apiBaseUrl, {
        email: byId("emailInput").value.trim(),
        password: byId("passwordInput").value,
        full_name: byId("fullNameInput").value.trim() || null,
      });
      setOutput("authOutput", data);
      setStatus("Register success");
    } catch (e) {
      setOutput("authOutput", e.message);
      setStatus("Register failed");
    }
  };

  byId("loginBtn").onclick = async () => {
    try {
      setStatus("Logging in");
      const data = await loginEmail(state.config.apiBaseUrl, {
        email: byId("emailInput").value.trim(),
        password: byId("passwordInput").value,
        device_id: byId("deviceIdInput").value.trim() || "web-cms",
      });
      renderUser();
      setOutput("authOutput", data.user);
      setStatus("Login success");
    } catch (e) {
      setOutput("authOutput", e.message);
      setStatus("Login failed");
    }
  };

  byId("logoutBtn").onclick = () => {
    clearSession();
    renderUser();
    setOutput("authOutput", "Logged out");
    setStatus("Logged out");
  };

  byId("refreshDashboardBtn").onclick = async () => {
    try {
      setStatus("Loading dashboard");
      const data = await getCmsDashboard(state.config.apiBaseUrl);
      renderKpi(data);
      setOutput("dashboardOutput", data);
      setStatus("Dashboard updated");
    } catch (e) {
      setOutput("dashboardOutput", e.message);
      setStatus("Dashboard failed");
    }
  };

  byId("uploadBtn").onclick = async () => {
    try {
      setStatus("Uploading document");
      const file = byId("fileInput").files[0];
      if (!file) throw new Error("Please choose a file");
      const data = await uploadDocument(state.config.apiBaseUrl, file);
      setOutput("aiOutput", data);
      await loadDocuments();
      setStatus("Upload success");
    } catch (e) {
      setOutput("aiOutput", e.message);
      setStatus("Upload failed");
    }
  };

  byId("loadDocsBtn").onclick = async () => {
    try {
      setStatus("Loading documents");
      await loadDocuments();
      setStatus("Documents loaded");
    } catch (e) {
      setOutput("aiOutput", e.message);
      setStatus("Load documents failed");
    }
  };

  byId("requestSummaryBtn").onclick = async () => {
    try {
      const data = await requestSummary(
        state.config.apiBaseUrl,
        readSelectedId(),
        byId("summaryLevelInput").value,
      );
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("requestProcessBtn").onclick = async () => {
    try {
      const data = await requestDocumentProcessing(
        state.config.apiBaseUrl,
        readSelectedId(),
      );
      byId("jobIdInput").value = String(data.job_id);
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("getJobStatusBtn").onclick = async () => {
    try {
      const jobId = Number(byId("jobIdInput").value);
      if (!Number.isFinite(jobId) || jobId <= 0) throw new Error("Invalid job id");
      const data = await getJobStatus(state.config.apiBaseUrl, jobId);
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("getSummaryBtn").onclick = async () => {
    try {
      const data = await getSummary(state.config.apiBaseUrl, readSelectedId());
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("askQuestionBtn").onclick = async () => {
    try {
      const data = await requestQa(
        state.config.apiBaseUrl,
        readSelectedId(),
        byId("questionInput").value.trim(),
      );
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("searchDocBtn").onclick = async () => {
    try {
      const data = await searchInDocument(
        state.config.apiBaseUrl,
        readSelectedId(),
        byId("searchQueryInput").value.trim(),
      );
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("searchAllBtn").onclick = async () => {
    try {
      const data = await searchAllDocuments(
        state.config.apiBaseUrl,
        byId("searchQueryInput").value.trim(),
      );
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("getGraphBtn").onclick = async () => {
    try {
      const data = await getGraph(state.config.apiBaseUrl, readSelectedId());
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };

  byId("getRecommendationsBtn").onclick = async () => {
    try {
      const data = await getRecommendations(state.config.apiBaseUrl, readSelectedId());
      setOutput("aiOutput", data);
    } catch (e) {
      setOutput("aiOutput", e.message);
    }
  };
}

function init() {
  renderPlatforms();
  renderUser();
  setStatus("Idle");
  bindEvents();
}

init();
