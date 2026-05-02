import {
  clearSession, getCmsDashboard, getJobStatus, getGraph, getRecommendations,
  getSummary, getUser, listDocuments, loginEmail, register,
  requestDocumentProcessing, requestQa, requestSummary,
  searchAllDocuments, searchInDocument, uploadDocument, deleteDocument,
} from "./api.js";
import { getPlatformConfig, listPlatforms, setPlatformConfig } from "./platforms.js";

// ── STATE ──────────────────────────────────────────────
const state = {
  config: getPlatformConfig(),
  docs: [],
  selectedDocId: null,
  currentView: "dashboard",
};

// ── HELPERS ────────────────────────────────────────────
const $ = (id) => document.getElementById(id);
const show = (el) => el?.classList.remove("hidden");
const hide = (el) => el?.classList.add("hidden");

function toast(msg, type = "info") {
  const container = $("toastContainer");
  const t = document.createElement("div");
  t.className = `toast toast-${type}`;
  t.innerHTML = `<div class="toast-dot"></div><span>${msg}</span>`;
  container.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

function setLoading(btn, loading) {
  if (!btn) return;
  if (loading) {
    btn.dataset.orig = btn.innerHTML;
    btn.innerHTML = `<span class="spinner"></span>`;
    btn.disabled = true;
  } else {
    btn.innerHTML = btn.dataset.orig || btn.innerHTML;
    btn.disabled = false;
  }
}

function statusClass(s) {
  const map = { uploaded:"uploaded", processing:"processing", processed:"processed",
    failed:"failed", extracting:"extracting", chunking:"chunking", embedding:"embedding" };
  return `status-${map[s] || "uploaded"}`;
}

function docColor(type) {
  if (type === "pdf") return "var(--red)";
  if (type === "docx") return "var(--accent)";
  return "var(--green)";
}

function timeAgo(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  const s = Math.floor((Date.now() - d) / 1000);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s/60)}m ago`;
  if (s < 86400) return `${Math.floor(s/3600)}h ago`;
  return `${Math.floor(s/86400)}d ago`;
}

function showFeatureResult(id, data, isError = false) {
  const el = $(id);
  if (!el) return;
  show(el);
  el.style.color = isError ? "var(--red)" : "var(--text2)";
  el.textContent = typeof data === "string" ? data : JSON.stringify(data, null, 2);
}

// ── AUTH ───────────────────────────────────────────────
function initAuth() {
  const overlay = $("authOverlay");
  const appShell = $("appShell");

  // Tab switching
  document.querySelectorAll(".auth-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".auth-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".auth-form").forEach(f => f.classList.remove("active"));
      tab.classList.add("active");
      $(`${tab.dataset.tab}Form`)?.classList.add("active");
    });
  });

  $("loginBtn").addEventListener("click", async () => {
    const btn = $("loginBtn");
    setLoading(btn, true);
    try {
      await loginEmail(state.config.apiBaseUrl, {
        email: $("loginEmail").value.trim(),
        password: $("loginPassword").value,
      });
      hide(overlay);
      show(appShell);
      renderUser();
      loadDashboard();
      toast("Welcome back!", "success");
    } catch (e) {
      toast(e.message, "error");
    } finally { setLoading(btn, false); }
  });

  $("registerBtn").addEventListener("click", async () => {
    const btn = $("registerBtn");
    setLoading(btn, true);
    try {
      await register(state.config.apiBaseUrl, {
        email: $("regEmail").value.trim(),
        password: $("regPassword").value,
      });
      toast("Account created! Please sign in.", "success");
      document.querySelector('.auth-tab[data-tab="login"]').click();
    } catch (e) {
      toast(e.message, "error");
    } finally { setLoading(btn, false); }
  });

  // Enter key support
  [$("loginEmail"), $("loginPassword")].forEach(el => {
    el?.addEventListener("keydown", e => { if (e.key === "Enter") $("loginBtn").click(); });
  });

  $("logoutBtn").addEventListener("click", () => {
    clearSession();
    hide(appShell);
    show(overlay);
    toast("Signed out", "info");
  });

  // Check existing session
  if (getUser()) {
    hide(overlay);
    show(appShell);
    renderUser();
    loadDashboard();
  }
}

function renderUser() {
  const user = getUser();
  if (!user) return;
  $("userEmail").textContent = user.email || "—";
  $("userRole").textContent = user.role || "user";
  $("userAvatar").textContent = (user.email || "?")[0].toUpperCase();
}

// ── PLATFORM SWITCHER ──────────────────────────────────
function initPlatform() {
  const container = $("platformCards");
  container.innerHTML = "";

  listPlatforms().forEach(p => {
    const card = document.createElement("div");
    card.className = `platform-card ${p.key === state.config.platform ? "active" : ""}`;
    card.style.setProperty("--card-color", p.color);
    card.dataset.key = p.key;
    card.innerHTML = `
      <span class="platform-card-badge" style="color:${p.color}">${p.badge}</span>
      <span class="platform-card-label">${p.label}</span>
    `;
    card.addEventListener("click", () => {
      state.config = setPlatformConfig(p.key, p.apiBaseUrl);
      $("apiBaseUrl").value = p.apiBaseUrl;
      document.querySelectorAll(".platform-card").forEach(c => c.classList.remove("active"));
      card.classList.add("active");
      toast(`Switched to ${p.label}`, "success");
    });
    container.appendChild(card);
  });

  $("apiBaseUrl").value = state.config.apiBaseUrl;

  $("applyPlatformBtn").addEventListener("click", () => {
    const url = $("apiBaseUrl").value.trim();
    if (url) {
      state.config = setPlatformConfig(state.config.platform, url);
      toast("Custom URL applied", "success");
    }
  });
}

// ── NAVIGATION ─────────────────────────────────────────
function initNav() {
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view;
      switchView(view);
    });
  });
}

function switchView(view) {
  state.currentView = view;
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
  document.querySelector(`.nav-item[data-view="${view}"]`)?.classList.add("active");
  document.querySelectorAll(".view").forEach(v => v.classList.remove("active"));
  $(`view-${view}`)?.classList.add("active");
  if (view === "dashboard") loadDashboard();
  if (view === "documents") loadDocuments();
  if (view === "ai") loadAiDocPicker();
  if (view === "search") loadSearchDocSelect();
}

// ── DASHBOARD ──────────────────────────────────────────
async function loadDashboard() {
  try {
    const [dash, docs] = await Promise.all([
      getCmsDashboard(state.config.apiBaseUrl),
      listDocuments(state.config.apiBaseUrl),
    ]);
    state.docs = docs.items || [];

    const counts = { total: 0, processed: 0, processing: 0, failed: 0 };
    const statusMap = {};
    state.docs.forEach(d => {
      counts.total++;
      const s = d.status || "uploaded";
      statusMap[s] = (statusMap[s] || 0) + 1;
      if (s === "processed") counts.processed++;
      else if (["processing","extracting","chunking","embedding"].includes(s)) counts.processing++;
      else if (s === "failed") counts.failed++;
    });

    $("kpiTotal").textContent = dash.total_documents ?? counts.total;
    $("kpiProcessed").textContent = dash.processed ?? counts.processed;
    $("kpiProcessing").textContent = counts.processing;
    $("kpiFailed").textContent = dash.failed ?? counts.failed;

    // Recent docs
    const recentList = $("dashRecentList");
    recentList.innerHTML = "";
    state.docs.slice(0, 8).forEach(d => {
      const row = document.createElement("div");
      row.className = "recent-item";
      row.innerHTML = `
        <svg class="recent-item-icon" width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M3 2h7l3 3v9a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5"/></svg>
        <span class="recent-item-name" title="${d.filename}">${d.filename}</span>
        <span class="status-chip ${statusClass(d.status)}">${d.status}</span>
        <span class="recent-item-date">${timeAgo(d.created_at)}</span>
      `;
      recentList.appendChild(row);
    });
    if (!state.docs.length) {
      recentList.innerHTML = `<div class="empty-state"><p>No documents yet</p></div>`;
    }

    // Status chart
    const chart = $("dashStatusChart");
    chart.innerHTML = "";
    const colors = { uploaded:"var(--text3)", processing:"var(--yellow)", processed:"var(--green)", failed:"var(--red)", extracting:"var(--purple)", chunking:"var(--accent)", embedding:"var(--accent2)" };
    const total = counts.total || 1;
    Object.entries(statusMap).forEach(([s, n]) => {
      const pct = Math.round((n / total) * 100);
      const row = document.createElement("div");
      row.className = "status-bar-row";
      row.innerHTML = `
        <div class="status-bar-label"><span>${s}</span><span>${n} (${pct}%)</span></div>
        <div class="status-bar-track"><div class="status-bar-fill" style="width:${pct}%;background:${colors[s]||'var(--text3)'}"></div></div>
      `;
      chart.appendChild(row);
    });
    if (!Object.keys(statusMap).length) {
      chart.innerHTML = `<div style="color:var(--text3);font-size:0.82rem;padding:8px 0">No data</div>`;
    }
  } catch (e) {
    toast("Failed to load dashboard: " + e.message, "error");
  }
}

$("refreshDashBtn")?.addEventListener("click", loadDashboard);

// ── DOCUMENTS ──────────────────────────────────────────
async function loadDocuments() {
  const grid = $("docGrid");
  grid.innerHTML = `<div class="empty-state"><span class="spinner"></span><p>Loading...</p></div>`;
  try {
    const data = await listDocuments(state.config.apiBaseUrl);
    state.docs = data.items || [];
    renderDocGrid();
  } catch (e) {
    toast("Failed to load: " + e.message, "error");
    grid.innerHTML = `<div class="empty-state"><p>Failed to load documents</p></div>`;
  }
}

function renderDocGrid() {
  const grid = $("docGrid");
  const filter = $("docFilter")?.value?.toLowerCase() || "";
  const sort = $("docSort")?.value || "newest";

  let docs = state.docs.filter(d => d.filename?.toLowerCase().includes(filter));
  if (sort === "newest") docs = [...docs].sort((a,b) => new Date(b.created_at) - new Date(a.created_at));
  if (sort === "oldest") docs = [...docs].sort((a,b) => new Date(a.created_at) - new Date(b.created_at));
  if (sort === "name") docs = [...docs].sort((a,b) => a.filename?.localeCompare(b.filename));
  if (sort === "status") docs = [...docs].sort((a,b) => (a.status||"").localeCompare(b.status||""));

  grid.innerHTML = "";
  if (!docs.length) {
    grid.innerHTML = `<div class="empty-state" style="grid-column:1/-1"><svg width="40" height="40" viewBox="0 0 40 40" fill="none"><rect width="40" height="40" rx="10" fill="var(--bg3)"/><path d="M12 10h11l7 7v13a2 2 0 01-2 2H12a2 2 0 01-2-2V12a2 2 0 012-2z" stroke="var(--text3)" stroke-width="1.5"/></svg><p>No documents found</p></div>`;
    return;
  }

  docs.forEach(d => {
    const card = document.createElement("div");
    card.className = `doc-card ${d.id === state.selectedDocId ? "selected" : ""}`;
    card.style.setProperty("--doc-color", docColor(d.file_type));

    card.innerHTML = `
      <div class="doc-card-head">
        <div class="doc-card-icon">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M3 2h7l3 3v9a1 1 0 01-1 1H3a1 1 0 01-1-1V3a1 1 0 011-1z" stroke="currentColor" stroke-width="1.5"/><path d="M10 2v3h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
        </div>
        <div class="doc-card-actions">
          <button class="doc-card-btn process-btn" title="Process" data-id="${d.id}">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M8 1v3M8 12v3M1 8h3M12 8h3" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><circle cx="8" cy="8" r="3" stroke="currentColor" stroke-width="1.5"/></svg>
          </button>
          <button class="doc-card-btn danger del-btn" title="Delete" data-id="${d.id}">
            <svg width="12" height="12" viewBox="0 0 16 16" fill="none"><path d="M3 4h10M5 4V3h6v1M6 7v5M10 7v5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
          </button>
        </div>
      </div>
      <div class="doc-card-name" title="${d.filename}">${d.filename}</div>
      <div class="doc-card-meta">
        <span class="doc-card-type">${d.file_type || "—"}</span>
        <span class="status-chip ${statusClass(d.status)}">${d.status || "unknown"}</span>
      </div>
    `;

    card.addEventListener("click", (e) => {
      if (e.target.closest(".doc-card-btn")) return;
      state.selectedDocId = d.id;
      renderDocGrid();
      toast(`Selected: ${d.filename}`, "info");
    });

    card.querySelector(".process-btn").addEventListener("click", async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      setLoading(btn, true);
      try {
        const res = await requestDocumentProcessing(state.config.apiBaseUrl, d.id);
        toast(`Processing queued (Job #${res.job_id})`, "success");
        loadDocuments();
      } catch (err) {
        toast(err.message, "error");
      } finally { setLoading(btn, false); }
    });

    card.querySelector(".del-btn").addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`Delete "${d.filename}"?`)) return;
      const btn = e.currentTarget;
      setLoading(btn, true);
      try {
        await deleteDocument(state.config.apiBaseUrl, d.id);
        toast("Deleted", "success");
        if (state.selectedDocId === d.id) state.selectedDocId = null;
        loadDocuments();
      } catch (err) {
        toast(err.message, "error");
      } finally { setLoading(btn, false); }
    });

    grid.appendChild(card);
  });
}

// Filter & sort listeners
$("docFilter")?.addEventListener("input", renderDocGrid);
$("docSort")?.addEventListener("change", renderDocGrid);

// Upload
function initUpload() {
  const fileInput = $("fileInput");
  const zone = $("uploadZone");

  const doUpload = async (file) => {
    const label = $("uploadLabel");
    setLoading(label, true);
    try {
      const res = await uploadDocument(state.config.apiBaseUrl, file);
      toast(`Uploaded: ${res.filename || file.name}`, "success");
      loadDocuments();
    } catch (e) {
      toast("Upload failed: " + e.message, "error");
    } finally { setLoading(label, false); }
  };

  fileInput?.addEventListener("change", () => {
    if (fileInput.files[0]) doUpload(fileInput.files[0]);
  });

  zone?.addEventListener("click", () => fileInput?.click());
  zone?.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("dragover"); });
  zone?.addEventListener("dragleave", () => zone.classList.remove("dragover"));
  zone?.addEventListener("drop", e => {
    e.preventDefault(); zone.classList.remove("dragover");
    if (e.dataTransfer.files[0]) doUpload(e.dataTransfer.files[0]);
  });
}

// ── AI FEATURES ────────────────────────────────────────
async function loadAiDocPicker() {
  const list = $("aiDocList");
  list.innerHTML = `<div style="padding:16px;color:var(--text3);font-size:0.82rem"><span class="spinner"></span></div>`;
  try {
    const data = await listDocuments(state.config.apiBaseUrl);
    state.docs = data.items || [];
    list.innerHTML = "";
    state.docs.forEach(d => {
      const item = document.createElement("div");
      item.className = `ai-doc-item ${d.id === state.selectedDocId ? "active" : ""}`;
      item.innerHTML = `
        <span class="ai-doc-item-name">${d.filename}</span>
        <span class="ai-doc-item-meta">${d.file_type?.toUpperCase() || "—"} · <span class="status-chip ${statusClass(d.status)}" style="font-size:0.6rem;padding:1px 5px">${d.status}</span></span>
      `;
      item.addEventListener("click", () => {
        state.selectedDocId = d.id;
        document.querySelectorAll(".ai-doc-item").forEach(i => i.classList.remove("active"));
        item.classList.add("active");
        showAiPanel(d);
      });
      list.appendChild(item);
    });
    if (!state.docs.length) {
      list.innerHTML = `<div class="empty-state" style="padding:24px"><p>No documents</p></div>`;
    }
    if (state.selectedDocId) {
      const selected = state.docs.find(d => d.id === state.selectedDocId);
      if (selected) showAiPanel(selected);
    }
  } catch (e) { toast(e.message, "error"); }
}

function showAiPanel(doc) {
  hide($("aiNoSelection"));
  show($("aiPanel"));
  $("aiSelectedName").textContent = doc.filename;
  const sc = $("aiSelectedStatus");
  sc.textContent = doc.status;
  sc.className = `status-chip ${statusClass(doc.status)}`;
  // Clear previous results
  ["processResult","summaryResult","qaResult","graphResult","recResult","jobResult"].forEach(id => {
    const el = $(id); if (el) { el.textContent=""; hide(el); }
  });
}

function initAiFeatures() {
  $("processBtn")?.addEventListener("click", async () => {
    if (!state.selectedDocId) return toast("Select a document first", "error");
    const btn = $("processBtn");
    setLoading(btn, true);
    try {
      const res = await requestDocumentProcessing(state.config.apiBaseUrl, state.selectedDocId);
      showFeatureResult("processResult", res);
      toast(`Job #${res.job_id} queued`, "success");
    } catch(e) { showFeatureResult("processResult", e.message, true); }
    finally { setLoading(btn, false); }
  });

  $("summaryBtn")?.addEventListener("click", async () => {
    if (!state.selectedDocId) return toast("Select a document first", "error");
    const btn = $("summaryBtn");
    setLoading(btn, true);
    try {
      const level = $("summaryLevel")?.value || "medium";
      const res = await requestSummary(state.config.apiBaseUrl, state.selectedDocId, level);
      showFeatureResult("summaryResult", res);
      toast(`Summary job #${res.job_id} queued`, "success");
    } catch(e) { showFeatureResult("summaryResult", e.message, true); }
    finally { setLoading(btn, false); }
  });

  $("getSummaryBtn")?.addEventListener("click", async () => {
    if (!state.selectedDocId) return toast("Select a document first", "error");
    const btn = $("getSummaryBtn");
    setLoading(btn, true);
    try {
      const res = await getSummary(state.config.apiBaseUrl, state.selectedDocId);
      const text = res.summary_short || res.summary_medium || res.summary_long || JSON.stringify(res, null, 2);
      showFeatureResult("summaryResult", text);
    } catch(e) { showFeatureResult("summaryResult", e.message, true); }
    finally { setLoading(btn, false); }
  });

  $("qaBtn")?.addEventListener("click", async () => {
    if (!state.selectedDocId) return toast("Select a document first", "error");
    const question = $("qaQuestion")?.value?.trim();
    if (!question) return toast("Enter a question", "error");
    const btn = $("qaBtn");
    setLoading(btn, true);
    try {
      const res = await requestQa(state.config.apiBaseUrl, state.selectedDocId, question);
      showFeatureResult("qaResult", res);
      toast(`QA job #${res.job_id} queued`, "success");
    } catch(e) { showFeatureResult("qaResult", e.message, true); }
    finally { setLoading(btn, false); }
  });

  $("graphBtn")?.addEventListener("click", async () => {
    if (!state.selectedDocId) return toast("Select a document first", "error");
    const btn = $("graphBtn");
    setLoading(btn, true);
    try {
      const res = await getGraph(state.config.apiBaseUrl, state.selectedDocId);
      const summary = `Nodes: ${res.nodes?.length || 0}, Edges: ${res.edges?.length || 0}\n\n` + JSON.stringify(res, null, 2);
      showFeatureResult("graphResult", summary);
    } catch(e) { showFeatureResult("graphResult", e.message, true); }
    finally { setLoading(btn, false); }
  });

  $("recBtn")?.addEventListener("click", async () => {
    if (!state.selectedDocId) return toast("Select a document first", "error");
    const btn = $("recBtn");
    setLoading(btn, true);
    try {
      const res = await getRecommendations(state.config.apiBaseUrl, state.selectedDocId);
      showFeatureResult("recResult", res);
    } catch(e) { showFeatureResult("recResult", e.message, true); }
    finally { setLoading(btn, false); }
  });

  $("jobPollBtn")?.addEventListener("click", async () => {
    const jobId = parseInt($("jobIdInput")?.value);
    if (!jobId) return toast("Enter a job ID", "error");
    const btn = $("jobPollBtn");
    setLoading(btn, true);
    try {
      const res = await getJobStatus(state.config.apiBaseUrl, jobId);
      showFeatureResult("jobResult", res);
    } catch(e) { showFeatureResult("jobResult", e.message, true); }
    finally { setLoading(btn, false); }
  });
}

// ── SEARCH ─────────────────────────────────────────────
async function loadSearchDocSelect() {
  const sel = $("searchDocSelect");
  if (!sel) return;
  sel.innerHTML = `<option value="">Loading...</option>`;
  try {
    const data = await listDocuments(state.config.apiBaseUrl);
    state.docs = data.items || [];
    sel.innerHTML = `<option value="">All documents</option>` +
      state.docs.map(d => `<option value="${d.id}">${d.filename}</option>`).join("");
  } catch(e) {}
}

function initSearch() {
  const scopeInputs = document.querySelectorAll('input[name="searchScope"]');
  scopeInputs.forEach(inp => {
    inp.addEventListener("change", () => {
      const docSel = $("searchDocSelect");
      if (inp.value === "doc") { docSel.style.display = ""; }
      else { docSel.style.display = "none"; }
    });
  });

  const doSearch = async () => {
    const query = $("globalSearch")?.value?.trim();
    if (!query) return;
    const scope = document.querySelector('input[name="searchScope"]:checked')?.value || "all";
    const docId = scope === "doc" ? parseInt($("searchDocSelect")?.value) : null;

    const btn = $("globalSearchBtn");
    setLoading(btn, true);
    const results = $("searchResults");
    results.innerHTML = `<div class="search-empty"><span class="spinner"></span></div>`;

    try {
      let res;
      if (docId) {
        res = await searchInDocument(state.config.apiBaseUrl, docId, query);
      } else {
        res = await searchAllDocuments(state.config.apiBaseUrl, query);
      }
      renderSearchResults(res.items || [], query);
    } catch(e) {
      results.innerHTML = `<div class="search-empty"><p>Error: ${e.message}</p></div>`;
    } finally { setLoading(btn, false); }
  };

  $("globalSearchBtn")?.addEventListener("click", doSearch);
  $("globalSearch")?.addEventListener("keydown", e => { if (e.key === "Enter") doSearch(); });
}

function renderSearchResults(items, query) {
  const results = $("searchResults");
  results.innerHTML = "";
  if (!items.length) {
    results.innerHTML = `<div class="search-empty"><svg width="40" height="40" viewBox="0 0 40 40" fill="none"><circle cx="18" cy="18" r="12" stroke="var(--border2)" stroke-width="2"/><path d="M28 28L36 36" stroke="var(--border2)" stroke-width="2" stroke-linecap="round"/></svg><p>No results for "<strong>${query}</strong>"</p></div>`;
    return;
  }

  const docMap = {};
  state.docs.forEach(d => { docMap[d.id] = d.filename; });

  items.forEach(item => {
    const card = document.createElement("div");
    card.className = "search-result-card";
    const highlighted = item.content?.replace(
      new RegExp(query, "gi"),
      m => `<mark style="background:var(--accent-20);color:var(--accent2);border-radius:2px;padding:0 2px">${m}</mark>`
    );
    card.innerHTML = `
      <div class="search-result-meta">
        <span class="search-result-doc">${docMap[item.document_id] || `Doc #${item.document_id}`}</span>
        <span class="search-result-chunk">Chunk ${item.chunk_index ?? "—"}</span>
        ${item.score != null ? `<span style="color:var(--text3)">score: ${item.score.toFixed(3)}</span>` : ""}
      </div>
      <div class="search-result-content">${highlighted || item.content}</div>
    `;
    results.appendChild(card);
  });
}

// ── BOOT ───────────────────────────────────────────────
function init() {
  initAuth();
  initPlatform();
  initNav();
  initUpload();
  initAiFeatures();
  initSearch();
}

init();
