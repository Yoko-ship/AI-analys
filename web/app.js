const API_BASE = window.location.origin;
const STORAGE_KEY = "uz_stock_analyzer_token";

const state = {
  token: localStorage.getItem(STORAGE_KEY) || "",
  user: null,
  companies: [],
  lastResult: null,
  oauthMessage: "",
};

const els = {
  navButtons: Array.from(document.querySelectorAll(".nav-btn")),
  views: Array.from(document.querySelectorAll(".page-view")),
  authStatus: document.getElementById("authStatus"),
  apiState: document.getElementById("apiState"),
  loginForm: document.getElementById("loginForm"),
  registerForm: document.getElementById("registerForm"),
  authMessage: document.getElementById("authMessage"),
  googleLoginBtn: document.getElementById("googleLoginBtn"),
  userCard: document.getElementById("userCard"),
  userName: document.getElementById("userName"),
  userEmail: document.getElementById("userEmail"),
  logoutBtn: document.getElementById("logoutBtn"),
  analysisForm: document.getElementById("analysisForm"),
  companyInput: document.getElementById("companyInput"),
  companiesList: document.getElementById("companiesList"),
  quickCompanies: document.getElementById("quickCompanies"),
  companyCount: document.getElementById("companyCount"),
  includeHtml: document.getElementById("includeHtml"),
  resultCompany: document.getElementById("resultCompany"),
  resultCache: document.getElementById("resultCache"),
  scoreValue: document.getElementById("scoreValue"),
  gradeValue: document.getElementById("gradeValue"),
  verdictValue: document.getElementById("verdictValue"),
  summaryValue: document.getElementById("summaryValue"),
  annualPeriod: document.getElementById("annualPeriod"),
  quarterlyPeriod: document.getElementById("quarterlyPeriod"),
  modelName: document.getElementById("modelName"),
  costValue: document.getElementById("costValue"),
  metricsGrid: document.getElementById("metricsGrid"),
  sectionsWrap: document.getElementById("sectionsWrap"),
  debugJson: document.getElementById("debugJson"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setMessage(text, tone = "muted") {
  els.authMessage.textContent = text;
  els.authMessage.style.color = tone === "error" ? "var(--danger)" : "var(--muted)";
}

function clearHash() {
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
}

function consumeOAuthHash() {
  const hash = new URLSearchParams(window.location.hash.replace(/^#/, ""));
  const token = hash.get("token");
  const provider = hash.get("provider") || hash.get("oauth");
  const error = hash.get("oauth_error") || hash.get("error");

  if (error) {
    state.oauthMessage = decodeURIComponent(error.replace(/\+/g, " "));
    setMessage(state.oauthMessage, "error");
    clearHash();
    return false;
  }

  if (!token) {
    return false;
  }

  state.token = token;
  localStorage.setItem(STORAGE_KEY, token);
  state.oauthMessage = provider ? `Signed in with ${provider}` : "OAuth login complete";
  clearHash();
  return true;
}

function setAuthState(user) {
  state.user = user;
  const signedIn = Boolean(user);

  els.userCard.classList.toggle("hidden", !signedIn);
  els.authStatus.textContent = signedIn ? "Signed in" : "Not signed in";
  els.authStatus.className = signedIn ? "status-badge" : "status-badge muted";

  if (signedIn) {
    els.userName.textContent = user.full_name || user.email;
    els.userEmail.textContent = user.email;
    setMessage(`Signed in as ${user.email}`);
  } else {
    els.userName.textContent = "-";
    els.userEmail.textContent = "-";
  }
}

function setView(viewName) {
  els.navButtons.forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === viewName);
  });
  els.views.forEach((view) => {
    view.classList.toggle("active", view.id === `view-${viewName}`);
  });
}

function apiFetch(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }
  if (!(options.body instanceof FormData) && !headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${API_BASE}${path}`, { ...options, headers });
}

async function handleAuthResponse(res) {
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "Request failed");
  }
  if (data.token) {
    state.token = data.token;
    localStorage.setItem(STORAGE_KEY, data.token);
  }
  if (data.user) {
    setAuthState(data.user);
  }
  return data;
}

function clearResults() {
  els.metricsGrid.classList.add("empty-state");
  els.metricsGrid.innerHTML = '<p class="empty-copy">Metrics will appear here after the first request.</p>';
  els.sectionsWrap.classList.add("empty-state");
  els.sectionsWrap.innerHTML = '<p class="empty-copy">The report sections will render here after analysis.</p>';
  els.debugJson.textContent = "{}";
}

function renderMetrics(metrics = {}) {
  const cards = [];
  const toneClass = (tone) => {
    if (tone === "good") return "metric-good";
    if (tone === "danger") return "metric-danger";
    return "metric-warning";
  };
  const pushCard = ({ label, value, sub = "", tone = "warning" }) => {
    if (value === undefined || value === null || value === "") return;
    cards.push(`
      <article class="metric-card fade-in">
        <div class="metric-label">${escapeHtml(label)}</div>
        <div class="metric-value ${toneClass(tone)}">${escapeHtml(value)}</div>
        <div class="metric-sub">${escapeHtml(sub)}</div>
      </article>
    `);
  };

  const total = metrics.total_score || {};
  pushCard({
    label: "Total score",
    value: total.score ?? "—",
    sub: total.summary || total.grade || "",
    tone: total.score >= 70 ? "good" : total.score >= 45 ? "warning" : "danger",
  });

  const piotroski = metrics.piotroski_f_score || {};
  pushCard({
    label: "Piotroski",
    value: `${piotroski.score ?? "—"}/9`,
    sub: piotroski.verdict || "",
    tone: piotroski.score >= 7 ? "good" : piotroski.score >= 4 ? "warning" : "danger",
  });

  const altman = metrics.altman_z_score || {};
  pushCard({
    label: "Altman Z",
    value: altman.score ?? "—",
    sub: altman.verdict || "",
    tone: altman.score > 2.99 ? "good" : altman.score > 1.81 ? "warning" : "danger",
  });

  const buffett = metrics.buffett_criteria || {};
  pushCard({
    label: "Buffett",
    value: `${buffett.passed ?? "—"}/${buffett.total ?? "—"}`,
    sub: buffett.verdict || "",
    tone: buffett.passed >= 4 ? "good" : buffett.passed >= 2 ? "warning" : "danger",
  });

  const graham = metrics.graham_number || {};
  pushCard({
    label: "Graham",
    value: graham.graham_number ?? graham.value ?? "—",
    sub: [graham.verdict, graham.upside_pct != null ? `${graham.upside_pct}% upside` : ""]
      .filter(Boolean)
      .join(" · "),
    tone: graham.upside_pct > 0 ? "good" : "warning",
  });

  const dcf = metrics.dcf || {};
  pushCard({
    label: "DCF",
    value: dcf.intrinsic_value_bn ?? "—",
    sub: dcf.verdict || dcf.signal || "",
    tone: dcf.signal === "bullish" ? "good" : dcf.signal === "bearish" ? "danger" : "warning",
  });

  const industry = metrics.industry || {};
  pushCard({
    label: "Industry",
    value: industry.sector_name ?? "—",
    sub: [industry.verdict || "", `${industry.good_count ?? 0} good / ${industry.weak_count ?? 0} weak`]
      .filter(Boolean)
      .join(" · "),
    tone: industry.good_count > industry.weak_count ? "good" : "warning",
  });

  const liquidity = metrics.market_liquidity || {};
  pushCard({
    label: "Liquidity",
    value: liquidity.liquidity_label ?? "—",
    sub: [
      `Trades: ${liquidity.trade_days ?? "—"}/30`,
      liquidity.avg_trade_value ? `Avg trade: ${Number(liquidity.avg_trade_value).toLocaleString()}` : "",
    ]
      .filter(Boolean)
      .join(" · "),
    tone: liquidity.liquidity_label === "high" ? "good" : "warning",
  });

  const momentum = metrics.momentum || {};
  pushCard({
    label: "Momentum",
    value: momentum.overall || "—",
    sub: momentum.acceleration || "",
    tone: momentum.css === "bullish" ? "good" : momentum.css === "bearish" ? "danger" : "warning",
  });

  if (!cards.length) {
    els.metricsGrid.classList.add("empty-state");
    els.metricsGrid.innerHTML = '<p class="empty-copy">Metrics will appear here after the first request.</p>';
    return;
  }

  els.metricsGrid.classList.remove("empty-state");
  els.metricsGrid.innerHTML = cards.join("");
}

function renderSections(sections = {}) {
  const entries = Object.entries(sections);
  if (!entries.length) {
    els.sectionsWrap.classList.add("empty-state");
    els.sectionsWrap.innerHTML = '<p class="empty-copy">The report sections will render here after analysis.</p>';
    return;
  }

  els.sectionsWrap.classList.remove("empty-state");
  els.sectionsWrap.innerHTML = entries
    .map(
      ([key, value], index) => `
        <details class="section-card fade-in" ${index === 0 ? "open" : ""}>
          <summary>
            <span>${escapeHtml(key.replaceAll("_", " "))}</span>
            <span class="muted">#${String(index + 1).padStart(2, "0")}</span>
          </summary>
          <div class="section-content">${escapeHtml(value || "No content")}</div>
        </details>
      `
    )
    .join("");
}

function renderResult(data) {
  state.lastResult = data;
  els.resultCompany.textContent = data.company_name || data.input || "Analysis result";
  els.resultCache.textContent = data.from_cache ? "Cached" : "Fresh";

  const score = data.summary?.score ?? data.metrics?.total_score?.score ?? null;
  const grade = data.summary?.grade ?? data.metrics?.total_score?.grade ?? "-";
  const verdict = data.summary?.verdict ?? "";
  const itog = data.summary?.itog ?? data.summary?.score_summary ?? "";

  els.scoreValue.textContent = score ?? "--";
  els.scoreValue.className = `score-value ${score != null ? renderScoreTone(score) : ""}`;
  els.gradeValue.textContent = grade || "-";
  els.verdictValue.textContent = verdict || "No verdict returned";
  els.summaryValue.textContent = itog || "";
  els.annualPeriod.textContent = data.annual_period || "-";
  els.quarterlyPeriod.textContent = data.quarterly_period || "-";
  els.modelName.textContent = data.model || "-";
  els.costValue.textContent = data.cost != null ? `$${Number(data.cost).toFixed(4)}` : "-";

  renderMetrics(data.metrics || {});
  renderSections(data.sections || {});
  els.debugJson.textContent = JSON.stringify(
    {
      input: data.input,
      company_name: data.company_name,
      summary: data.summary,
      metrics: data.metrics,
      liquidity: data.liquidity,
      from_cache: data.from_cache,
      source: data.source,
    },
    null,
    2
  );
}

function renderScoreTone(score) {
  if (score >= 70) return "metric-good";
  if (score >= 45) return "metric-warning";
  return "metric-danger";
}

async function loadCompanies() {
  const res = await apiFetch("/api/companies");
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Failed to load companies");

  state.companies = data.companies || [];
  els.companyCount.textContent = `${data.count || state.companies.length} companies`;

  els.companiesList.innerHTML = state.companies
    .map((company) => `<option value="${company.ticker}">${company.company_name}</option>`)
    .join("");

  els.quickCompanies.innerHTML = state.companies
    .slice(0, 16)
    .map(
      (company) => `
        <button class="quick-chip" type="button" data-company="${company.ticker}">
          ${company.ticker}
        </button>
      `
    )
    .join("");

  document.querySelectorAll("[data-company]").forEach((btn) => {
    btn.addEventListener("click", () => {
      els.companyInput.value = btn.dataset.company;
      els.companyInput.focus();
    });
  });
}

async function refreshSession() {
  if (!state.token) {
    setAuthState(null);
    return;
  }

  try {
    const res = await apiFetch("/api/auth/me");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Session invalid");
    setAuthState(data.user);
  } catch {
    localStorage.removeItem(STORAGE_KEY);
    state.token = "";
    setAuthState(null);
  }
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((el) => el.classList.remove("active"));
    document.querySelectorAll(".auth-form").forEach((el) => el.classList.remove("active"));
    btn.classList.add("active");
    const target = btn.dataset.tab;
    document.getElementById(`${target}Form`).classList.add("active");
  });
});

els.navButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    setView(btn.dataset.view);
  });
});

els.googleLoginBtn.addEventListener("click", () => {
  window.location.href = `${API_BASE}/api/auth/oauth/google/start`;
});

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Signing in...");
  const form = new FormData(els.loginForm);
  try {
    const res = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
      }),
    });
    const data = await handleAuthResponse(res);
    setMessage(`Welcome back, ${data.user.full_name || data.user.email}`);
    setView("analysis");
  } catch (error) {
    setMessage(error.message, "error");
  }
});

els.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Creating account...");
  const form = new FormData(els.registerForm);
  try {
    const res = await fetch(`${API_BASE}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: form.get("email"),
        password: form.get("password"),
        full_name: form.get("full_name"),
      }),
    });
    const data = await handleAuthResponse(res);
    setMessage(`Account created for ${data.user.email}`);
    document.querySelector('.tab-btn[data-tab="login"]').click();
    setView("auth");
  } catch (error) {
    setMessage(error.message, "error");
  }
});

els.logoutBtn.addEventListener("click", async () => {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch {
    // ignore
  }
  localStorage.removeItem(STORAGE_KEY);
  state.token = "";
  setAuthState(null);
  setMessage("Signed out");
  setView("auth");
});

els.analysisForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!state.token) {
    setMessage("Please sign in first to run an analysis.", "error");
    return;
  }

  const form = new FormData(els.analysisForm);
  const company = String(form.get("company") || "").trim();
  if (!company) {
    setMessage("Choose a company first.", "error");
    return;
  }

  els.apiState.textContent = "Analyzing...";
  setMessage("Running analysis...");
  clearResults();

  try {
    const res = await apiFetch("/api/analyze", {
      method: "POST",
      body: JSON.stringify({
        company,
        include_html: els.includeHtml.checked,
        include_raw: false,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Analysis failed");
    renderResult(data);
    els.apiState.textContent = "Ready";
    setMessage(`Analysis complete for ${data.company_name || company}`);
  } catch (error) {
    els.apiState.textContent = "API ready";
    setMessage(error.message, "error");
  }
});

window.addEventListener("DOMContentLoaded", async () => {
  const oauthReturned = consumeOAuthHash();
  setView("main");
  try {
    await loadCompanies();
  } catch (error) {
    els.companyCount.textContent = "Unavailable";
    setMessage(error.message, "error");
  }

  await refreshSession();
  if (oauthReturned) {
    setMessage(state.oauthMessage || "OAuth login complete");
    setView("analysis");
  }
  state.oauthMessage = "";
  clearResults();
});
