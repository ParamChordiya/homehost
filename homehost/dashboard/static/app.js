/* ============================================================
   HomeHost Dashboard — app.js
   Single-page application logic. Requires index.html structure.
   ============================================================ */

"use strict";

class HomehostDashboard {
  constructor() {
    /** @type {WebSocket|null} */
    this._ws = null;
    this._wsRetryDelay = 1000;
    this._wsRetryMax = 30000;
    this._wsRetryTimer = null;
    this._wsManualClose = false;

    /** @type {Array<{name:string, type:string, status:string, port:number, public_url:string, local_url:string, uptime_seconds:number, request_count_today:number, request_count_total:number, error_count_today:number, auto_start:boolean}>} */
    this._projects = [];

    /** @type {string|null} Current detail page project name */
    this._detailProject = null;

    /** @type {string} Current page id (without "page-" prefix) */
    this._currentPage = "overview";

    this._systemInfo = null;

    // Bind theme from localStorage on construction
    const saved = localStorage.getItem("homehost-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.setAttribute("data-theme", saved);
    }
    this._syncThemeToggle();
  }

  // ─── Init ───────────────────────────────────────────────────────────────────

  async init() {
    this.connectWebSocket();
    await this.fetchProjects();
    this._fetchSystemInfo();
  }

  // ─── WebSocket ──────────────────────────────────────────────────────────────

  connectWebSocket() {
    if (this._ws && (this._ws.readyState === WebSocket.OPEN || this._ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this._setWsStatus("connecting");

    const wsUrl = `ws://${location.host}/ws`;
    let ws;
    try {
      ws = new WebSocket(wsUrl);
    } catch (err) {
      console.warn("WebSocket constructor failed:", err);
      this._scheduleWsReconnect();
      return;
    }

    this._ws = ws;

    ws.addEventListener("open", () => {
      this._wsRetryDelay = 1000;
      clearTimeout(this._wsRetryTimer);
      this._setWsStatus("connected");
    });

    ws.addEventListener("message", (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "projects_update" && Array.isArray(msg.projects)) {
          this._handleProjectsUpdate(msg.projects);
        }
      } catch (e) {
        console.warn("WS message parse error:", e);
      }
    });

    ws.addEventListener("close", () => {
      this._setWsStatus("error");
      if (!this._wsManualClose) {
        this._scheduleWsReconnect();
      }
    });

    ws.addEventListener("error", () => {
      this._setWsStatus("error");
    });
  }

  _scheduleWsReconnect() {
    clearTimeout(this._wsRetryTimer);
    const delay = this._wsRetryDelay;
    this._wsRetryDelay = Math.min(this._wsRetryDelay * 2, this._wsRetryMax);
    this._wsRetryTimer = setTimeout(() => {
      this.connectWebSocket();
    }, delay);
  }

  _setWsStatus(state /* "connected" | "connecting" | "error" */) {
    const indicator = document.getElementById("ws-indicator");
    const label = document.getElementById("ws-status-text");
    const settingsWs = document.getElementById("settings-ws-status");
    if (!indicator || !label) return;

    indicator.className = `ws-indicator ${state}`;
    const labels = { connected: "Live", connecting: "Connecting…", error: "Disconnected" };
    label.textContent = labels[state] || state;
    if (settingsWs) {
      settingsWs.textContent = labels[state] || state;
      settingsWs.style.color = state === "connected" ? "var(--success)" :
                               state === "connecting" ? "var(--warning)" : "var(--error)";
    }
  }

  // ─── Data fetching ──────────────────────────────────────────────────────────

  async fetchProjects() {
    try {
      const resp = await fetch("/api/projects");
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const projects = await resp.json();
      this._projects = projects;
      this._renderOverview();
      this._renderProjectNav();
      if (this._currentPage === "project" && this._detailProject) {
        this._renderDetailPage(this._detailProject);
      }
    } catch (err) {
      console.error("fetchProjects error:", err);
      this._renderOverviewError();
    }
  }

  async refreshProjects() {
    await this.fetchProjects();
    this.showToast("Projects refreshed", "info");
  }

  _handleProjectsUpdate(projects) {
    this._projects = projects;
    this._renderOverview();
    this._renderProjectNav();
    if (this._currentPage === "project" && this._detailProject) {
      const p = this._projects.find(p => p.name === this._detailProject);
      if (p) this._updateDetailHeader(p);
    }
  }

  async _fetchSystemInfo() {
    try {
      const resp = await fetch("/api/system");
      if (!resp.ok) return;
      this._systemInfo = await resp.json();
      this._renderSystemBar();
      this._renderSettingsSystemInfo();
    } catch (e) {
      console.warn("system info fetch failed:", e);
    }
  }

  async _fetchLogs(projectName) {
    const el = document.getElementById("log-output");
    if (!el) return;
    el.textContent = "Loading…";
    try {
      const resp = await fetch(`/api/projects/${encodeURIComponent(projectName)}/logs`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      const lines = data.lines || [];
      if (lines.length === 0) {
        el.textContent = "No log output yet.";
        return;
      }
      el.innerHTML = lines.map(l => this._colorizeLogLine(l)).join("\n");
      el.scrollTop = el.scrollHeight;
    } catch (e) {
      el.textContent = `Error loading logs: ${e.message}`;
    }
  }

  async refreshDetailLogs() {
    if (this._detailProject) await this._fetchLogs(this._detailProject);
  }

  async _fetchMetrics(projectName) {
    try {
      const resp = await fetch(`/api/projects/${encodeURIComponent(projectName)}/metrics`);
      if (!resp.ok) return null;
      return await resp.json();
    } catch (e) {
      return null;
    }
  }

  _colorizeLogLine(line) {
    const l = line.toLowerCase();
    const esc = this._escapeHtml(line);
    if (/error|exception|traceback|fatal|critical/.test(l)) {
      return `<span class="log-line-error">${esc}</span>`;
    }
    if (/warn/.test(l)) {
      return `<span class="log-line-warn">${esc}</span>`;
    }
    if (/info|started|running|ready/.test(l)) {
      return `<span class="log-line-info">${esc}</span>`;
    }
    if (/success|ok|200/.test(l)) {
      return `<span class="log-line-success">${esc}</span>`;
    }
    return esc;
  }

  // ─── Rendering: Overview ────────────────────────────────────────────────────

  _renderOverview() {
    this._renderStats();
    this._renderProjectsGrid();
  }

  _renderStats() {
    const total    = this._projects.length;
    const running  = this._projects.filter(p => p.status === "running").length;
    const stopped  = this._projects.filter(p => p.status === "stopped").length;
    const errors   = this._projects.filter(p => p.status === "error").length;
    const reqToday = this._projects.reduce((s, p) => s + (p.request_count_today || 0), 0);

    this._setText("stat-total",    total);
    this._setText("stat-running",  running);
    this._setText("stat-stopped",  stopped);
    this._setText("stat-errors",   errors);
    this._setText("stat-requests", reqToday.toLocaleString());
  }

  _renderProjectsGrid() {
    const grid = document.getElementById("projects-grid");
    if (!grid) return;

    if (this._projects.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <div class="empty-icon">📂</div>
          <h3>No projects yet</h3>
          <p>Add your first project to get started. HomeHost will detect the type automatically.</p>
          <code>homehost add ./my-project</code>
        </div>`;
      return;
    }

    grid.innerHTML = this._projects.map(p => this.renderProjectCard(p)).join("");
  }

  _renderOverviewError() {
    const grid = document.getElementById("projects-grid");
    if (!grid) return;
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <div class="empty-icon">⚠</div>
        <h3>Could not load projects</h3>
        <p>Make sure the HomeHost daemon is running.</p>
        <code>homehost start</code>
      </div>`;
  }

  renderProjectCard(project) {
    const statusClass = project.status; // running | stopped | error
    const typeBadge   = this._typeBadgeLabel(project.type);
    const localUrl    = project.local_url  || `http://localhost:${project.port}`;
    const publicUrl   = project.public_url || "";
    const uptime      = project.status === "running" ? this.formatUptime(project.uptime_seconds) : "—";

    const startDisabled   = project.status === "running"  ? "disabled" : "";
    const stopDisabled    = project.status === "stopped"  ? "disabled" : "";
    const restartDisabled = "";

    return `
    <div class="project-card" data-project="${this._escapeAttr(project.name)}">
      <div class="card-header">
        <div class="card-status-icon ${statusClass}"></div>
        <div class="card-title-group">
          <div class="card-title">${this._escapeHtml(project.name)}</div>
          <div class="card-status-label ${statusClass}">${statusClass}</div>
        </div>
        <div class="type-badge">${this._escapeHtml(typeBadge)}</div>
      </div>

      <div class="card-urls">
        <div class="card-url-row">
          <span class="card-url-label">Local</span>
          <a href="${this._escapeAttr(localUrl)}" target="_blank" rel="noopener" class="card-url-link">
            ${this._escapeHtml(localUrl)}
          </a>
        </div>
        ${publicUrl ? `
        <div class="card-url-row">
          <span class="card-url-label">Public</span>
          <a href="${this._escapeAttr(publicUrl)}" target="_blank" rel="noopener" class="card-url-link">
            ${this._escapeHtml(publicUrl)}
          </a>
        </div>` : ""}
      </div>

      <div class="card-metrics">
        <div class="metric-item">
          <div class="metric-label">Requests Today</div>
          <div class="metric-value">${(project.request_count_today || 0).toLocaleString()}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Total</div>
          <div class="metric-value">${(project.request_count_total || 0).toLocaleString()}</div>
        </div>
        <div class="metric-item">
          <div class="metric-label">Uptime</div>
          <div class="metric-value small">${uptime}</div>
        </div>
      </div>

      <div class="card-actions">
        <button class="btn btn-primary" ${startDisabled}
          onclick="dashboard.performAction('${this._escapeAttr(project.name)}', 'start', this)">
          ▶ Start
        </button>
        <button class="btn btn-danger" ${stopDisabled}
          onclick="dashboard.performAction('${this._escapeAttr(project.name)}', 'stop', this)">
          ■ Stop
        </button>
        <button class="btn btn-ghost"
          onclick="dashboard.performAction('${this._escapeAttr(project.name)}', 'restart', this)">
          ↺
        </button>
        <button class="btn btn-icon" title="View details"
          onclick="dashboard.navigate('project', '${this._escapeAttr(project.name)}')">
          ↗
        </button>
      </div>
    </div>`;
  }

  // ─── Rendering: Project Nav ─────────────────────────────────────────────────

  _renderProjectNav() {
    const container = document.getElementById("project-nav-items");
    if (!container) return;

    if (this._projects.length === 0) {
      container.innerHTML = `<div style="padding: 8px 18px; color: var(--text-muted); font-size: 12px;">No projects</div>`;
      return;
    }

    container.innerHTML = this._projects.map(p => `
      <button class="nav-item ${this._currentPage === "project" && this._detailProject === p.name ? "active" : ""}"
        data-page="project" data-project="${this._escapeAttr(p.name)}"
        onclick="dashboard.navigate('project', '${this._escapeAttr(p.name)}')">
        <span class="nav-icon" style="font-size:13px;">◈</span>
        <span style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
          ${this._escapeHtml(p.name)}
        </span>
        <span class="status-dot ${p.status}"></span>
      </button>`).join("");
  }

  // ─── Rendering: Detail page ─────────────────────────────────────────────────

  async _renderDetailPage(name) {
    const project = this._projects.find(p => p.name === name);
    if (!project) return;

    this._updateDetailHeader(project);

    // Info rows
    const infoBody = document.getElementById("detail-info-body");
    if (infoBody) {
      const localUrl   = project.local_url  || `http://localhost:${project.port}`;
      const publicUrl  = project.public_url || "—";
      infoBody.innerHTML = [
        ["Type",         this._typeBadgeLabel(project.type)],
        ["Port",         project.port],
        ["Local URL",    `<a href="${this._escapeAttr(localUrl)}" target="_blank">${this._escapeHtml(localUrl)}</a>`],
        ["Public URL",   publicUrl !== "—" ? `<a href="${this._escapeAttr(publicUrl)}" target="_blank">${this._escapeHtml(publicUrl)}</a>` : "—"],
        ["Auto-start",   project.auto_start ? "Yes" : "No"],
        ["Uptime",       project.status === "running" ? this.formatUptime(project.uptime_seconds) : "—"],
        ["Req. Today",   (project.request_count_today || 0).toLocaleString()],
        ["Req. Total",   (project.request_count_total || 0).toLocaleString()],
        ["Errors Today", project.error_count_today || 0],
      ].map(([k, v]) => `
        <div class="info-row">
          <span class="info-key">${k}</span>
          <span class="info-val">${v}</span>
        </div>`).join("");
    }

    // Metrics chart
    const metrics = await this._fetchMetrics(name);
    this._renderMetricsChart(metrics);

    // Logs
    await this._fetchLogs(name);
  }

  _updateDetailHeader(project) {
    this._setText("detail-project-name", project.name);
    const statusEl = document.getElementById("detail-project-status");
    if (statusEl) {
      statusEl.innerHTML = `<span class="status-badge ${project.status}">${project.status}</span>
        <span style="color:var(--text-muted); margin-left:8px; font-size:11px;">
          Port ${project.port}
        </span>`;
    }

    // Update action buttons
    const startBtn   = document.getElementById("detail-start-btn");
    const stopBtn    = document.getElementById("detail-stop-btn");
    const restartBtn = document.getElementById("detail-restart-btn");
    if (startBtn)   startBtn.disabled   = project.status === "running";
    if (stopBtn)    stopBtn.disabled    = project.status === "stopped";
    if (restartBtn) restartBtn.disabled = false;
  }

  _renderMetricsChart(metrics) {
    const container = document.getElementById("detail-metrics-chart");
    if (!container) return;

    if (!metrics || !metrics.requests_per_hour || metrics.requests_per_hour.every(v => v === 0)) {
      container.innerHTML = `<div class="chart-empty">No request data yet</div>`;
      return;
    }

    const values = metrics.requests_per_hour;
    const maxVal = Math.max(...values, 1);

    // Generate hour labels for the last 24h
    const now = new Date();
    const labels = values.map((_, i) => {
      const h = new Date(now);
      h.setHours(now.getHours() - 23 + i, 0, 0, 0);
      return `${String(h.getHours()).padStart(2, "0")}:00`;
    });

    const bars = values.map((v, i) => {
      const pct = Math.round((v / maxVal) * 100);
      return `<div class="bar-chart-bar" style="height:${Math.max(pct, 2)}%;">
        <div class="bar-tooltip">${labels[i]}: ${v} req</div>
      </div>`;
    }).join("");

    // Show every 4th label
    const labelHtml = labels.map((l, i) => `
      <div class="bar-chart-label">${i % 4 === 0 ? l.replace(":00","h") : ""}</div>`).join("");

    container.innerHTML = `
      <div class="bar-chart">${bars}</div>
      <div class="bar-chart-labels">${labelHtml}</div>`;

    // Sparkline for response times
    if (metrics.response_times && metrics.response_times.length > 0) {
      const rts = metrics.response_times.slice(-50);
      const rtMax = Math.max(...rts, 1);
      const sparkBars = rts.map(v => {
        const pct = Math.round((v / rtMax) * 100);
        return `<div class="sparkline-bar" style="height:${Math.max(pct, 4)}%" title="${Math.round(v)}ms"></div>`;
      }).join("");
      const avg = rts.reduce((a, b) => a + b, 0) / rts.length;
      container.innerHTML += `
        <div class="sparkline-container">
          <div class="sparkline-label">Response Times (ms) · avg ${Math.round(avg)}ms</div>
          <div class="sparkline">${sparkBars}</div>
        </div>`;
    }
  }

  // ─── Rendering: System bar / Settings ───────────────────────────────────────

  _renderSystemBar() {
    if (!this._systemInfo) return;
    this._setText("sys-os",      this._systemInfo.os || "—");
    this._setText("sys-caddy",   this._systemInfo.caddy_version || "—");
    this._setText("sys-uptime",  this.formatUptime(this._systemInfo.uptime || 0));
    this._setText("sys-version", this._systemInfo.version || "—");
  }

  _renderSettingsSystemInfo() {
    const body = document.getElementById("settings-system-body");
    if (!body || !this._systemInfo) return;
    body.innerHTML = [
      ["OS",              this._systemInfo.os],
      ["Caddy Version",   this._systemInfo.caddy_version],
      ["System Uptime",   this.formatUptime(this._systemInfo.uptime || 0)],
      ["HomeHost Version",this._systemInfo.version],
    ].map(([k, v]) => `
      <div class="settings-row">
        <div class="settings-row-info"><label>${k}</label></div>
        <span style="font-size:13px; color: var(--text-secondary);">${this._escapeHtml(String(v || "—"))}</span>
      </div>`).join("");
  }

  // ─── Actions ────────────────────────────────────────────────────────────────

  async performAction(projectName, action, btnEl) {
    const allBtns = document.querySelectorAll(`.project-card[data-project="${CSS.escape(projectName)}"] button`);
    allBtns.forEach(b => { b.disabled = true; });
    if (btnEl) btnEl.classList.add("loading");

    try {
      const resp = await fetch(`/api/projects/${encodeURIComponent(projectName)}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = await resp.json();

      if (data.success) {
        this.showToast(data.message || `${action} successful`, "success");
      } else {
        this.showToast(data.message || "Action failed", "error");
      }

      // Refresh project data after a brief moment
      setTimeout(() => this.fetchProjects(), 600);
    } catch (err) {
      this.showToast(`Network error: ${err.message}`, "error");
    } finally {
      if (btnEl) btnEl.classList.remove("loading");
      // Re-enable via next fetchProjects render cycle
    }
  }

  async detailAction(action) {
    if (!this._detailProject) return;
    const nameStr = this._detailProject;

    const btns = ["detail-start-btn", "detail-stop-btn", "detail-restart-btn"].map(
      id => document.getElementById(id)
    ).filter(Boolean);
    btns.forEach(b => { b.disabled = true; b.classList.add("loading"); });

    try {
      const resp = await fetch(`/api/projects/${encodeURIComponent(nameStr)}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = await resp.json();
      this.showToast(data.message || (data.success ? "Done" : "Failed"),
                     data.success ? "success" : "error");
      setTimeout(() => this.fetchProjects(), 600);
    } catch (err) {
      this.showToast(`Network error: ${err.message}`, "error");
    } finally {
      btns.forEach(b => b.classList.remove("loading"));
    }
  }

  // ─── Navigation ─────────────────────────────────────────────────────────────

  navigate(page, projectName) {
    this._currentPage = page;
    this._detailProject = projectName || null;

    // Hide all pages
    document.querySelectorAll(".page").forEach(el => el.classList.remove("active"));

    // Update sidebar active state
    document.querySelectorAll(".nav-item").forEach(el => el.classList.remove("active"));

    if (page === "overview") {
      this._showPage("overview");
      this._setText("page-title", "Overview");
      document.querySelector(".nav-item[data-page='overview']")?.classList.add("active");
    } else if (page === "settings") {
      this._showPage("settings");
      this._setText("page-title", "Settings");
      document.querySelector(".nav-item[data-page='settings']")?.classList.add("active");
      this._renderSettingsSystemInfo();
    } else if (page === "project" && projectName) {
      this._showPage("project");
      this._setText("page-title", projectName);
      document.querySelector(`.nav-item[data-project="${CSS.escape(projectName)}"]`)?.classList.add("active");
      this._renderDetailPage(projectName);
    }

    this._renderProjectNav();

    // Close mobile sidebar
    document.getElementById("sidebar")?.classList.remove("open");
    document.getElementById("sidebar-overlay")?.classList.remove("open");
  }

  _showPage(name) {
    document.getElementById(`page-${name}`)?.classList.add("active");
  }

  // ─── Toast notifications ─────────────────────────────────────────────────────

  showToast(message, type = "success") {
    const container = document.getElementById("toast-container");
    if (!container) return;

    const icons = { success: "✓", error: "✕", info: "ℹ", warning: "⚠" };
    const icon  = icons[type] || "ℹ";

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.setAttribute("role", "alert");
    toast.innerHTML = `
      <span class="toast-icon">${icon}</span>
      <span class="toast-message">${this._escapeHtml(message)}</span>`;

    container.appendChild(toast);

    const remove = () => {
      toast.classList.add("removing");
      toast.addEventListener("transitionend", () => toast.remove(), { once: true });
      // Fallback
      setTimeout(() => toast.remove(), 400);
    };

    setTimeout(remove, 3500);
  }

  // ─── Theme ──────────────────────────────────────────────────────────────────

  toggleTheme() {
    const html    = document.documentElement;
    const current = html.getAttribute("data-theme");
    const next    = current === "dark" ? "light" : "dark";
    html.setAttribute("data-theme", next);
    localStorage.setItem("homehost-theme", next);
    this._syncThemeToggle();
  }

  _syncThemeToggle() {
    const theme    = document.documentElement.getAttribute("data-theme") || "dark";
    const iconEl   = document.getElementById("theme-icon");
    const labelEl  = document.getElementById("theme-label");
    if (iconEl)  iconEl.textContent  = theme === "dark" ? "☀" : "☾";
    if (labelEl) labelEl.textContent = theme === "dark" ? "Light" : "Dark";
  }

  // ─── Sidebar toggle (mobile) ─────────────────────────────────────────────────

  toggleSidebar() {
    const sidebar  = document.getElementById("sidebar");
    const overlay  = document.getElementById("sidebar-overlay");
    const isOpen   = sidebar?.classList.toggle("open");
    overlay?.classList.toggle("open", isOpen);
  }

  openDocs() {
    window.open("https://github.com/homehost-dev/homehost/blob/main/docs/quickstart.md", "_blank");
  }

  // ─── Formatting helpers ──────────────────────────────────────────────────────

  formatUptime(seconds) {
    if (!seconds || seconds < 0) return "—";
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return `${d}d ${h}h`;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m`;
    return `${seconds}s`;
  }

  formatUrl(url) {
    if (!url) return "—";
    const a = document.createElement("a");
    a.href   = url;
    a.target = "_blank";
    a.rel    = "noopener noreferrer";
    a.textContent = url;
    a.className = "card-url-link";
    return a.outerHTML;
  }

  _typeBadgeLabel(type) {
    const map = {
      static:  "Static",
      flask:   "Flask",
      fastapi: "FastAPI",
      django:  "Django",
      nextjs:  "Next.js",
      react:   "React",
      node:    "Node.js",
      docker:  "Docker",
      custom:  "Custom",
    };
    return map[type] || type || "Unknown";
  }

  // ─── DOM helpers ─────────────────────────────────────────────────────────────

  _setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = String(text);
  }

  _escapeHtml(str) {
    return String(str)
      .replace(/&/g,  "&amp;")
      .replace(/</g,  "&lt;")
      .replace(/>/g,  "&gt;")
      .replace(/"/g,  "&quot;")
      .replace(/'/g,  "&#39;");
  }

  _escapeAttr(str) {
    return String(str).replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────

const dashboard = new HomehostDashboard();

// Close mobile sidebar when overlay is clicked
document.getElementById("sidebar-overlay")?.addEventListener("click", () => {
  dashboard.toggleSidebar();
});

// Keyboard shortcut: Escape to go back to overview
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && dashboard._currentPage !== "overview") {
    dashboard.navigate("overview");
  }
});

// Init after DOM is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => dashboard.init());
} else {
  dashboard.init();
}
