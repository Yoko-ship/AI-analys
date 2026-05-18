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
  toastStack: document.getElementById("toastStack"),
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
  resultHero: document.getElementById("resultHero"),
  scoreValue: document.getElementById("scoreValue"),
  gradeValue: document.getElementById("gradeValue"),
  verdictValue: document.getElementById("verdictValue"),
  summaryValue: document.getElementById("summaryValue"),
  metricsGrid: document.getElementById("metricsGrid"),
  sectionsWrap: document.getElementById("sectionsWrap"),
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

function showToast(message, tone = "info", timeoutMs = 3800) {
  if (!els.toastStack) return;

  const toast = document.createElement("div");
  toast.className = `toast toast-${tone}`;

  const label = tone === "error" ? "РћС€РёР±РєР°" : tone === "success" ? "Р“РѕС‚РѕРІРѕ" : "РРЅС„Рѕ";
  toast.innerHTML = `
    <div class="toast-label">${label}</div>
    <div class="toast-message">${escapeHtml(message)}</div>
  `;

  els.toastStack.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));

  window.setTimeout(() => {
    toast.classList.remove("show");
    window.setTimeout(() => toast.remove(), 220);
  }, timeoutMs);
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
    showToast(state.oauthMessage, "error");
    clearHash();
    return false;
  }

  if (!token) {
    return false;
  }

  state.token = token;
  localStorage.setItem(STORAGE_KEY, token);
  const providerLabel = provider ? (provider === "google" ? "Google" : provider) : "";
  state.oauthMessage = providerLabel ? `Р’С…РѕРґ С‡РµСЂРµР· ${providerLabel} РІС‹РїРѕР»РЅРµРЅ` : "OAuth-РІС…РѕРґ РІС‹РїРѕР»РЅРµРЅ";
  showToast(state.oauthMessage, "success");
  clearHash();
  return true;
}

function setAuthState(user) {
  state.user = user;
  const signedIn = Boolean(user);

  els.userCard.classList.toggle("hidden", !signedIn);
  els.authStatus.textContent = signedIn ? "Р’С…РѕРґ РІС‹РїРѕР»РЅРµРЅ" : "Р’С…РѕРґ РЅРµ РІС‹РїРѕР»РЅРµРЅ";
  els.authStatus.className = signedIn ? "status-badge" : "status-badge muted";

  if (signedIn) {
    els.userName.textContent = user.full_name || user.email;
    els.userEmail.textContent = user.email;
    setMessage(`Р’ СЃРёСЃС‚РµРјРµ: ${user.email}`);
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
    throw new Error(data.detail || "Р—Р°РїСЂРѕСЃ РЅРµ РІС‹РїРѕР»РЅРµРЅ");
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
  if (els.resultHero) {
    els.resultHero.classList.remove("is-loading");
  }
  if (els.metricsGrid) {
    els.metricsGrid.classList.add("empty-state");
    els.metricsGrid.innerHTML = '<p class="empty-copy">После первого запроса здесь появятся метрики.</p>';
  }
  if (els.sectionsWrap) {
    els.sectionsWrap.classList.add("empty-state");
    els.sectionsWrap.innerHTML = '<p class="empty-copy">После анализа здесь появятся разделы отчета.</p>';
  }
}

function setLoadingSkeleton(company) {
  if (els.resultHero) {
    els.resultHero.classList.add("is-loading");
  }
  if (els.resultCompany) {
    els.resultCompany.textContent = company ? `Анализ: ${company}` : "Анализ выполняется...";
  }
  if (els.resultCache) {
    els.resultCache.textContent = "Загрузка";
  }
  if (els.scoreValue) {
    els.scoreValue.textContent = "--";
  }
  if (els.gradeValue) {
    els.gradeValue.textContent = "—";
  }
  if (els.verdictValue) {
    els.verdictValue.textContent = "Расчет выполняется. Пожалуйста, подождите.";
  }
  if (els.summaryValue) {
    els.summaryValue.textContent = "";
  }

  if (els.metricsGrid) {
    els.metricsGrid.classList.remove("empty-state");
    els.metricsGrid.innerHTML = `
      <div class="skeleton-grid">
        ${Array.from({ length: 8 })
          .map(
            () => `
              <article class="metric-card skeleton-card">
                <div class="skeleton-line skeleton-line-sm"></div>
                <div class="skeleton-line skeleton-line-lg"></div>
                <div class="skeleton-line skeleton-line-md"></div>
              </article>
            `
          )
          .join("")}
      </div>
    `;
  }

  if (els.sectionsWrap) {
    els.sectionsWrap.classList.remove("empty-state");
    els.sectionsWrap.innerHTML = `
      <div class="skeleton-sections">
        ${Array.from({ length: 3 })
          .map(
            () => `
              <article class="section-card skeleton-card">
                <div class="skeleton-line skeleton-line-lg"></div>
                <div class="skeleton-line skeleton-line-md"></div>
                <div class="skeleton-line skeleton-line-sm"></div>
              </article>
            `
          )
          .join("")}
      </div>
    `;
  }
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
    label: "РС‚РѕРіРѕРІР°СЏ РѕС†РµРЅРєР°",
    value: total.score ?? "вЂ”",
    sub: total.summary || total.grade || "",
    tone: total.score >= 70 ? "good" : total.score >= 45 ? "warning" : "danger",
  });

  const piotroski = metrics.piotroski_f_score || {};
  pushCard({
    label: "Piotroski",
    value: `${piotroski.score ?? "вЂ”"}/9`,
    sub: piotroski.verdict || "",
    tone: piotroski.score >= 7 ? "good" : piotroski.score >= 4 ? "warning" : "danger",
  });

  const altman = metrics.altman_z_score || {};
  pushCard({
    label: "Altman Z",
    value: altman.score ?? "вЂ”",
    sub: altman.verdict || "",
    tone: altman.score > 2.99 ? "good" : altman.score > 1.81 ? "warning" : "danger",
  });

  const buffett = metrics.buffett_criteria || {};
  pushCard({
    label: "РљСЂРёС‚РµСЂРёРё Р‘Р°С„С„РµС‚Р°",
    value: `${buffett.passed ?? "вЂ”"}/${buffett.total ?? "вЂ”"}`,
    sub: buffett.verdict || "",
    tone: buffett.passed >= 4 ? "good" : buffett.passed >= 2 ? "warning" : "danger",
  });

  const graham = metrics.graham_number || {};
  pushCard({
    label: "Р§РёСЃР»Рѕ Р“СЂСЌРјР°",
    value: graham.graham_number ?? graham.value ?? "вЂ”",
    sub: [graham.verdict, graham.upside_pct != null ? `${graham.upside_pct}% РїРѕС‚РµРЅС†РёР°Р»` : ""]
      .filter(Boolean)
      .join(" В· "),
    tone: graham.upside_pct > 0 ? "good" : "warning",
  });

  const dcf = metrics.dcf || {};
  pushCard({
    label: "DCF-РѕС†РµРЅРєР°",
    value: dcf.intrinsic_value_bn ?? "вЂ”",
    sub: dcf.verdict || dcf.signal || "",
    tone: dcf.signal === "bullish" ? "good" : dcf.signal === "bearish" ? "danger" : "warning",
  });

  const industry = metrics.industry || {};
  pushCard({
    label: "РћС‚СЂР°СЃР»СЊ",
    value: industry.sector_name ?? "вЂ”",
    sub: [industry.verdict || "", `${industry.good_count ?? 0} СЃРёР»СЊРЅС‹С… / ${industry.weak_count ?? 0} СЃР»Р°Р±С‹С…`]
      .filter(Boolean)
      .join(" В· "),
    tone: industry.good_count > industry.weak_count ? "good" : "warning",
  });

  const liquidity = metrics.market_liquidity || {};
  pushCard({
    label: "Р›РёРєРІРёРґРЅРѕСЃС‚СЊ",
    value: liquidity.liquidity_label ?? "вЂ”",
    sub: [
      `РЎРґРµР»РєРё: ${liquidity.trade_days ?? "вЂ”"}/30`,
      liquidity.avg_trade_value ? `РЎСЂРµРґРЅРёР№ РѕР±РѕСЂРѕС‚: ${Number(liquidity.avg_trade_value).toLocaleString()}` : "",
    ]
      .filter(Boolean)
      .join(" В· "),
    tone: liquidity.liquidity_label === "high" ? "good" : "warning",
  });

  const momentum = metrics.momentum || {};
  pushCard({
    label: "РРјРїСѓР»СЊСЃ",
    value: momentum.overall || "вЂ”",
    sub: momentum.acceleration || "",
    tone: momentum.css === "bullish" ? "good" : momentum.css === "bearish" ? "danger" : "warning",
  });

  if (!cards.length) {
    els.metricsGrid.classList.add("empty-state");
    els.metricsGrid.innerHTML = '<p class="empty-copy">РџРѕСЃР»Рµ РїРµСЂРІРѕРіРѕ Р·Р°РїСЂРѕСЃР° Р·РґРµСЃСЊ РїРѕСЏРІСЏС‚СЃСЏ РјРµС‚СЂРёРєРё.</p>';
    return;
  }

  els.metricsGrid.classList.remove("empty-state");
  els.metricsGrid.innerHTML = cards.join("");
}

function renderSections(sections = {}) {
  const entries = Object.entries(sections);
  if (!entries.length) {
    els.sectionsWrap.classList.add("empty-state");
    els.sectionsWrap.innerHTML = '<p class="empty-copy">РџРѕСЃР»Рµ Р°РЅР°Р»РёР·Р° Р·РґРµСЃСЊ РїРѕСЏРІСЏС‚СЃСЏ СЂР°Р·РґРµР»С‹ РѕС‚С‡РµС‚Р°.</p>';
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
          <div class="section-content">${escapeHtml(value || "РќРµС‚ СЃРѕРґРµСЂР¶РёРјРѕРіРѕ")}</div>
        </details>
      `
    )
    .join("");
}

function renderResult(data) {
  state.lastResult = data;
  els.resultCompany.textContent = data.company_name || data.input || "Р РµР·СѓР»СЊС‚Р°С‚ Р°РЅР°Р»РёР·Р°";
  els.resultCache.textContent = data.from_cache ? "РР· РєСЌС€Р°" : "РЎРІРµР¶РёР№ СЂР°СЃС‡РµС‚";

  const score = data.summary?.score ?? data.metrics?.total_score?.score ?? null;
  const grade = data.summary?.grade ?? data.metrics?.total_score?.grade ?? "-";
  const verdict = data.summary?.verdict ?? "";
  const itog = data.summary?.itog ?? data.summary?.score_summary ?? "";

  els.scoreValue.textContent = score ?? "--";
  els.scoreValue.className = `score-value ${score != null ? renderScoreTone(score) : ""}`;
  els.gradeValue.textContent = grade || "-";
  els.verdictValue.textContent = verdict || "РС‚РѕРіРѕРІРѕРµ Р·Р°РєР»СЋС‡РµРЅРёРµ РЅРµ СЃС„РѕСЂРјРёСЂРѕРІР°РЅРѕ";
  els.summaryValue.textContent = itog || "";

  renderMetrics(data.metrics || {});
  renderSections(data.sections || {});
}

function renderScoreTone(score) {
  if (score >= 70) return "metric-good";
  if (score >= 45) return "metric-warning";
  return "metric-danger";
}

async function loadCompanies() {
  const res = await apiFetch("/api/companies");
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ СЃРїРёСЃРѕРє РєРѕРјРїР°РЅРёР№");

  state.companies = data.companies || [];
  els.companyCount.textContent = `${data.count || state.companies.length} РєРѕРјРїР°РЅРёР№`;

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
    if (!res.ok) throw new Error(data.detail || "РЎРµСЃСЃРёСЏ РЅРµРґРµР№СЃС‚РІРёС‚РµР»СЊРЅР°");
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
  setMessage("Р’С‹РїРѕР»РЅСЏРµС‚СЃСЏ РІС…РѕРґ...");
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
    setMessage(`Р”РѕР±СЂРѕ РїРѕР¶Р°Р»РѕРІР°С‚СЊ, ${data.user.full_name || data.user.email}`);
    showToast(`Р’С…РѕРґ РІС‹РїРѕР»РЅРµРЅ: ${data.user.email}`, "success");
    setView("analysis");
  } catch (error) {
    setMessage(error.message, "error");
    showToast(error.message, "error");
  }
});

els.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("РЎРѕР·РґР°РЅРёРµ СѓС‡РµС‚РЅРѕР№ Р·Р°РїРёСЃРё...");
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
    setMessage(`РЈС‡РµС‚РЅР°СЏ Р·Р°РїРёСЃСЊ СЃРѕР·РґР°РЅР°: ${data.user.email}`);
    showToast(`РЈС‡РµС‚РЅР°СЏ Р·Р°РїРёСЃСЊ СЃРѕР·РґР°РЅР°: ${data.user.email}`, "success");
    document.querySelector('.tab-btn[data-tab="login"]').click();
    setView("auth");
  } catch (error) {
    setMessage(error.message, "error");
    showToast(error.message, "error");
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
  setMessage("Р’С‹С…РѕРґ РІС‹РїРѕР»РЅРµРЅ");
  showToast("Р’С‹С…РѕРґ РІС‹РїРѕР»РЅРµРЅ", "info");
  setView("auth");
});

els.analysisForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!state.token) {
    setMessage("Р§С‚РѕР±С‹ Р·Р°РїСѓСЃС‚РёС‚СЊ Р°РЅР°Р»РёР·, СЃРЅР°С‡Р°Р»Р° РІС‹РїРѕР»РЅРёС‚Рµ РІС…РѕРґ.", "error");
    showToast("РЎРЅР°С‡Р°Р»Р° РІС‹РїРѕР»РЅРёС‚Рµ РІС…РѕРґ", "error");
    return;
  }

  const form = new FormData(els.analysisForm);
  const company = String(form.get("company") || "").trim();
  if (!company) {
    setMessage("РЎРЅР°С‡Р°Р»Р° РІС‹Р±РµСЂРёС‚Рµ РєРѕРјРїР°РЅРёСЋ.", "error");
    showToast("РЎРЅР°С‡Р°Р»Р° РІС‹Р±РµСЂРёС‚Рµ РєРѕРјРїР°РЅРёСЋ", "error");
    return;
  }

  els.apiState.textContent = "Р’С‹РїРѕР»РЅСЏРµС‚СЃСЏ Р°РЅР°Р»РёР·...";
  setMessage("РђРЅР°Р»РёР· РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ...");
  setLoadingSkeleton(company);

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
    if (!res.ok) throw new Error(data.detail || "РќРµ СѓРґР°Р»РѕСЃСЊ РІС‹РїРѕР»РЅРёС‚СЊ Р°РЅР°Р»РёР·");
    renderResult(data);
    els.apiState.textContent = "Р“РѕС‚РѕРІРѕ";
    setMessage(`РђРЅР°Р»РёР· Р·Р°РІРµСЂС€РµРЅ: ${data.company_name || company}`);
    showToast(`РђРЅР°Р»РёР· Р·Р°РІРµСЂС€РµРЅ: ${data.company_name || company}`, "success");
  } catch (error) {
    els.apiState.textContent = "API РіРѕС‚РѕРІ";
    setMessage(error.message, "error");
    showToast(error.message, "error");
    clearResults();
  }
});

window.addEventListener("DOMContentLoaded", async () => {
  const oauthReturned = consumeOAuthHash();
  setView("main");
  try {
    await loadCompanies();
  } catch (error) {
    els.companyCount.textContent = "РќРµРґРѕСЃС‚СѓРїРЅРѕ";
    setMessage(error.message, "error");
  }

  await refreshSession();
  if (oauthReturned) {
    setMessage(state.oauthMessage || "Р’С…РѕРґ С‡РµСЂРµР· OAuth РІС‹РїРѕР»РЅРµРЅ");
    setView("analysis");
  }
  state.oauthMessage = "";
  clearResults();
});

