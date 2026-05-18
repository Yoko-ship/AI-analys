const API_BASE = window.location.origin;
const STORAGE_KEY = "uz_stock_analyzer_token";

const state = {
  token: localStorage.getItem(STORAGE_KEY) || "",
  user: null,
  profile: null,
  companies: [],
  lastResult: null,
  oauthMessage: "",
  profileAvatarCleared: false,
};

let loadingSkeletonTimer = null;

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
  profileStatus: document.getElementById("profileStatus"),
  profileAvatar: document.getElementById("profileAvatar"),
  profileName: document.getElementById("profileName"),
  profileEmail: document.getElementById("profileEmail"),
  profileMemberSince: document.getElementById("profileMemberSince"),
  profileStats: document.getElementById("profileStats"),
  profileRecent: document.getElementById("profileRecent"),
  profileFavorites: document.getElementById("profileFavorites"),
  profileHistorySearch: document.getElementById("profileHistorySearch"),
  profileHistoryMode: document.getElementById("profileHistoryMode"),
  profileHistorySummary: document.getElementById("profileHistorySummary"),
  profileEditForm: document.getElementById("profileEditForm"),
  profileFullName: document.getElementById("profileFullName"),
  profileAvatarInput: document.getElementById("profileAvatarInput"),
  profileEditHint: document.getElementById("profileEditHint"),
  profileSaveBtn: document.getElementById("profileSaveBtn"),
  profileClearAvatarBtn: document.getElementById("profileClearAvatarBtn"),
  profileAnalyzeBtn: document.getElementById("profileAnalyzeBtn"),
  profileRefreshBtn: document.getElementById("profileRefreshBtn"),
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
  resultFavoriteBtn: document.getElementById("resultFavoriteBtn"),
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

  const label = tone === "error" ? "Ошибка" : tone === "success" ? "Готово" : "Инфо";
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
  state.oauthMessage = providerLabel ? `Вход через ${providerLabel} выполнен` : "OAuth-вход выполнен";
  showToast(state.oauthMessage, "success");
  clearHash();
  return true;
}

function setAuthState(user) {
  state.user = user;
  const signedIn = Boolean(user);

  els.userCard.classList.toggle("hidden", !signedIn);
  els.authStatus.textContent = signedIn ? "Вход выполнен" : "Вход не выполнен";
  els.authStatus.className = signedIn ? "status-badge" : "status-badge muted";

  if (signedIn) {
    els.userName.textContent = user.full_name || user.email;
    els.userEmail.textContent = user.email;
    setMessage(`В системе: ${user.email}`);
  } else {
    els.userName.textContent = "-";
    els.userEmail.textContent = "-";
  }
}

function getProfileInitials(user) {
  const source = (user?.full_name || user?.email || "?").trim();
  const parts = source.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  const first = parts[0][0] || "";
  const second = parts.length > 1 ? parts[1][0] : (parts[0][1] || "");
  return (first + second).toUpperCase();
}

function hashToHue(source) {
  const value = String(source || "").split("").reduce((acc, char) => (acc * 31 + char.charCodeAt(0)) % 360, 47);
  return value;
}

function formatDateLabel(value) {
  if (!value) return "Нет данных";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Нет данных";
  return new Intl.DateTimeFormat("ru-RU", {
    day: "2-digit",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function getFavoriteTickers(profile = state.profile) {
  const favorites = Array.isArray(profile?.favorites) ? profile.favorites : [];
  return new Set(
    favorites
      .map((item) => String(item?.ticker || "").trim().toUpperCase())
      .filter(Boolean)
  );
}

function isTickerFavorite(ticker, profile = state.profile) {
  if (!ticker) return false;
  return getFavoriteTickers(profile).has(String(ticker).trim().toUpperCase());
}

function renderAvatarInto(el, user) {
  if (!el) return;
  const avatar = user?.avatar_data_url;
  const initials = getProfileInitials(user);
  if (avatar) {
    el.classList.add("has-image");
    el.innerHTML = `<img src="${escapeHtml(avatar)}" alt="${escapeHtml(user?.full_name || user?.email || "Аватар")}" />`;
    return;
  }
  el.classList.remove("has-image");
  el.innerHTML = "";
  el.textContent = initials;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Не удалось прочитать изображение"));
    reader.readAsDataURL(file);
  });
}

function setProfileEditorEnabled(enabled) {
  if (!els.profileEditForm) return;
  els.profileEditForm.querySelectorAll("input, button").forEach((control) => {
    control.disabled = !enabled;
  });
}

function renderProfile(profile = null) {
  state.profile = profile;

  if (
    !els.profileStatus ||
    !els.profileAvatar ||
    !els.profileName ||
    !els.profileEmail ||
    !els.profileMemberSince ||
    !els.profileStats ||
    !els.profileRecent ||
    !els.profileFavorites
  ) {
    return;
  }

  if (!profile || !state.user) {
    els.profileStatus.textContent = "Профиль не загружен";
    els.profileStatus.className = "status-badge muted";
    renderAvatarInto(els.profileAvatar, null);
    els.profileAvatar.style.background = "linear-gradient(135deg, rgba(245, 184, 77, 0.18), rgba(110, 240, 193, 0.16))";
    els.profileName.textContent = "Профиль недоступен";
    els.profileEmail.textContent = "Войдите в учетную запись, чтобы увидеть персональные данные.";
    els.profileMemberSince.textContent = "Дата регистрации будет отображаться здесь.";
    els.profileStats.classList.add("empty-state");
    els.profileStats.innerHTML = '<p class="empty-copy">Статистика появится после первого анализа.</p>';
    els.profileRecent.classList.add("empty-state");
    els.profileRecent.innerHTML = '<p class="empty-copy">После первого анализа здесь появится история действий.</p>';
    els.profileFavorites.classList.add("empty-state");
    els.profileFavorites.innerHTML = '<p class="empty-copy">Добавляйте компании в избранное из анализа или из истории.</p>';
    if (els.profileHistorySummary) {
      els.profileHistorySummary.textContent = "";
    }
    if (els.profileEditForm) {
      els.profileEditForm.reset();
    }
    state.profileAvatarCleared = false;
    setProfileEditorEnabled(false);
    renderResultFavoriteButton();
    return;
  }

  const user = profile.user || state.user;
  const stats = profile.stats || {};
  const recent = Array.isArray(profile.recent_analyses) ? profile.recent_analyses : [];
  const favorites = Array.isArray(profile.favorites) ? profile.favorites : [];
  const favoritesByTicker = getFavoriteTickers(profile);
  const initials = getProfileInitials(user);
  const hue = hashToHue(user.email || user.full_name || user.id);
  const accent = `hsl(${hue} 78% 62%)`;
  const accentSoft = `hsla(${hue}, 78%, 62%, 0.18)`;

  els.profileStatus.textContent = "Профиль обновлен";
  els.profileStatus.className = "status-badge";
  renderAvatarInto(els.profileAvatar, user);
  if (!user.avatar_data_url) {
    els.profileAvatar.style.background = `linear-gradient(135deg, ${accent}, ${accentSoft})`;
  } else {
    els.profileAvatar.style.background = "#09111d";
  }
  els.profileName.textContent = user.full_name || user.email;
  els.profileEmail.textContent = user.email;
  els.profileMemberSince.textContent = `В системе с ${formatDateLabel(user.created_at)}`;

  if (els.profileEditForm) {
    if (els.profileFullName && document.activeElement !== els.profileFullName) {
      els.profileFullName.value = user.full_name || "";
    }
    if (els.profileEditHint) {
      els.profileEditHint.textContent = "Можно обновить имя, загрузить аватар или очистить текущее изображение.";
    }
  }
  state.profileAvatarCleared = false;
  setProfileEditorEnabled(true);

  const statsCards = [
    { label: "Всего анализов", value: stats.total_analyses ?? 0, sub: "Все выполненные запросы" },
    { label: "За 7 дней", value: stats.analyses_7d ?? 0, sub: "Активность за неделю" },
    { label: "За 30 дней", value: stats.analyses_30d ?? 0, sub: "Активность за месяц" },
    { label: "Компаний в истории", value: stats.analyzed_companies ?? 0, sub: "Уникальные тикеры" },
    { label: "Средний скор", value: stats.avg_score != null ? Number(stats.avg_score).toFixed(1) : "—", sub: "Средний итог по анализам" },
    { label: "Лучшая оценка", value: stats.best_score != null ? Number(stats.best_score).toFixed(1) : "—", sub: "Максимальный скор" },
    {
      label: "Чаще всего смотрит",
      value: stats.top_company || "—",
      sub: stats.top_company_count ? `${stats.top_company_count} анализов` : "Пока нет данных",
    },
    {
      label: "Кэшированных",
      value: stats.cached_analyses ?? 0,
      sub: "Сколько ответов пришло из кэша",
    },
    {
      label: "Последний анализ",
      value: stats.last_analysis_at ? formatDateLabel(stats.last_analysis_at) : "—",
      sub: "Время последнего запроса",
    },
  ];

  els.profileStats.classList.remove("empty-state");
  els.profileStats.innerHTML = statsCards
    .map(
      (item) => `
        <article class="profile-stat-card">
          <div class="metric-label">${escapeHtml(item.label)}</div>
          <div class="profile-stat-value">${escapeHtml(item.value)}</div>
          <div class="metric-sub">${escapeHtml(item.sub)}</div>
        </article>
      `
    )
    .join("");

  if (!recent.length) {
    els.profileRecent.classList.add("empty-state");
    els.profileRecent.innerHTML = '<p class="empty-copy">После первого анализа здесь появится история действий.</p>';
  } else {
    const searchValue = String(els.profileHistorySearch?.value || "").trim().toLowerCase();
    const mode = String(els.profileHistoryMode?.value || "all");
    const filteredRecent = recent.filter((item) => {
      const haystack = [
        item.company_name,
        item.company_input,
        item.ticker,
        item.verdict,
        item.summary_text,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (searchValue && !haystack.includes(searchValue)) {
        return false;
      }
      if (mode === "favorites") {
        return isTickerFavorite(item.ticker, profile);
      }
      return true;
    });

    if (els.profileHistorySummary) {
      const totalLabel = `${filteredRecent.length} из ${recent.length}`;
      const favoriteLabel = favorites.length ? ` · ${favorites.length} в избранном` : "";
      els.profileHistorySummary.textContent = `Показано ${totalLabel}${favoriteLabel}`;
    }

    if (!filteredRecent.length) {
      els.profileRecent.classList.add("empty-state");
      els.profileRecent.innerHTML = '<p class="empty-copy">По выбранному фильтру ничего не найдено.</p>';
    } else {
      els.profileRecent.classList.remove("empty-state");
      els.profileRecent.innerHTML = filteredRecent
        .map((item) => {
          const title = item.company_name || item.company_input || "Без названия";
          const subtitle = [item.ticker ? item.ticker : "", item.from_cache ? "из кэша" : "свежий расчет", item.model ? `модель ${item.model}` : ""]
            .filter(Boolean)
            .join(" · ");
          const favorite = item.ticker && favoritesByTicker.has(String(item.ticker).trim().toUpperCase());
          return `
            <article class="profile-history-item fade-in">
              <div class="profile-history-main">
                <div>
                  <div class="profile-history-title">${escapeHtml(title)}</div>
                  <div class="profile-history-sub">${escapeHtml(item.verdict || item.summary_text || "Анализ выполнен")}</div>
                </div>
                <div class="profile-history-score">${escapeHtml(item.score != null ? String(item.score) : "—")}</div>
              </div>
              <div class="profile-history-meta">
                <span>${escapeHtml(subtitle)}</span>
                <span>${escapeHtml(formatDateLabel(item.created_at))}</span>
              </div>
              <div class="profile-history-actions">
                <button
                  class="ghost-btn history-favorite-btn"
                  type="button"
                  data-ticker="${escapeHtml(item.ticker || "")}"
                  data-company-name="${escapeHtml(item.company_name || item.company_input || "")}"
                >${favorite ? "Убрать из избранного" : "В избранное"}</button>
              </div>
            </article>
          `;
        })
        .join("");
    }
  }

  if (!favorites.length) {
    els.profileFavorites.classList.add("empty-state");
    els.profileFavorites.innerHTML = '<p class="empty-copy">Добавляйте компании в избранное из анализа или из истории.</p>';
  } else {
    els.profileFavorites.classList.remove("empty-state");
    els.profileFavorites.innerHTML = favorites
      .map((item) => {
        const label = item.company_name || item.ticker;
        return `
          <article class="favorite-item fade-in">
            <div class="favorite-item-main">
              <div class="favorite-item-title">${escapeHtml(label || "Без названия")}</div>
              <div class="favorite-item-sub">${escapeHtml(item.ticker || "—")} · ${escapeHtml(formatDateLabel(item.created_at))}</div>
            </div>
            <button
              class="ghost-btn favorite-toggle-btn"
              type="button"
              data-ticker="${escapeHtml(item.ticker || "")}"
              data-company-name="${escapeHtml(item.company_name || "")}"
            >Убрать</button>
          </article>
        `;
      })
      .join("");
  }

  if (els.profileHistorySearch || els.profileHistoryMode) {
    document.querySelectorAll(".history-favorite-btn, .favorite-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        toggleFavoriteFromButton(btn.dataset.ticker, btn.dataset.companyName);
      });
    });
  }

  renderResultFavoriteButton();
}

async function loadProfile() {
  if (!state.token) {
    renderProfile(null);
    return;
  }

  if (!els.profileStatus) return;

  els.profileStatus.textContent = "Загрузка профиля...";
  els.profileStatus.className = "status-badge muted";

  try {
    const res = await apiFetch("/api/profile");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Не удалось загрузить профиль");
    renderProfile(data);
  } catch (error) {
    renderProfile(null);
    els.profileStatus.textContent = "Профиль недоступен";
    setMessage(error.message, "error");
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
    throw new Error(data.detail || "Запрос не выполнен");
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
  if (loadingSkeletonTimer) {
    window.clearTimeout(loadingSkeletonTimer);
    loadingSkeletonTimer = null;
  }
  state.lastResult = null;
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
  renderResultFavoriteButton();
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
    label: "Итоговая оценка",
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
    label: "Критерии Баффета",
    value: `${buffett.passed ?? "—"}/${buffett.total ?? "—"}`,
    sub: buffett.verdict || "",
    tone: buffett.passed >= 4 ? "good" : buffett.passed >= 2 ? "warning" : "danger",
  });

  const graham = metrics.graham_number || {};
  pushCard({
    label: "Число Грэма",
    value: graham.graham_number ?? graham.value ?? "—",
    sub: [graham.verdict, graham.upside_pct != null ? `${graham.upside_pct}% потенциал` : ""]
      .filter(Boolean)
      .join(" · "),
    tone: graham.upside_pct > 0 ? "good" : "warning",
  });

  const dcf = metrics.dcf || {};
  pushCard({
    label: "DCF-оценка",
    value: dcf.intrinsic_value_bn ?? "—",
    sub: dcf.verdict || dcf.signal || "",
    tone: dcf.signal === "bullish" ? "good" : dcf.signal === "bearish" ? "danger" : "warning",
  });

  const industry = metrics.industry || {};
  pushCard({
    label: "Отрасль",
    value: industry.sector_name ?? "—",
    sub: [industry.verdict || "", `${industry.good_count ?? 0} сильных / ${industry.weak_count ?? 0} слабых`]
      .filter(Boolean)
      .join(" · "),
    tone: industry.good_count > industry.weak_count ? "good" : "warning",
  });

  const liquidity = metrics.market_liquidity || {};
  pushCard({
    label: "Ликвидность",
    value: liquidity.liquidity_label ?? "—",
    sub: [
      `Сделки: ${liquidity.trade_days ?? "—"}/30`,
      liquidity.avg_trade_value ? `Средний оборот: ${Number(liquidity.avg_trade_value).toLocaleString()}` : "",
    ]
      .filter(Boolean)
      .join(" · "),
    tone: liquidity.liquidity_label === "high" ? "good" : "warning",
  });

  const momentum = metrics.momentum || {};
  pushCard({
    label: "Импульс",
    value: momentum.overall || "—",
    sub: momentum.acceleration || "",
    tone: momentum.css === "bullish" ? "good" : momentum.css === "bearish" ? "danger" : "warning",
  });

  if (!cards.length) {
    els.metricsGrid.classList.add("empty-state");
    els.metricsGrid.innerHTML = '<p class="empty-copy">После первого запроса здесь появятся метрики.</p>';
    return;
  }

  els.metricsGrid.classList.remove("empty-state");
  els.metricsGrid.innerHTML = cards.join("");
}

function renderSections(sections = {}) {
  const entries = Object.entries(sections);
  if (!entries.length) {
    els.sectionsWrap.classList.add("empty-state");
    els.sectionsWrap.innerHTML = '<p class="empty-copy">После анализа здесь появятся разделы отчета.</p>';
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
          <div class="section-content">${escapeHtml(value || "Нет содержимого")}</div>
        </details>
      `
    )
    .join("");
}

function renderResult(data) {
  state.lastResult = data;
  if (els.resultHero) {
    els.resultHero.classList.remove("is-loading");
  }
  els.resultCompany.textContent = data.company_name || data.input || "Результат анализа";
  els.resultCache.textContent = data.from_cache ? "Из кэша" : "Свежий расчет";

  const score = data.summary?.score ?? data.metrics?.total_score?.score ?? null;
  const grade = data.summary?.grade ?? data.metrics?.total_score?.grade ?? "-";
  const verdict = data.summary?.verdict ?? "";
  const itog = data.summary?.itog ?? data.summary?.score_summary ?? "";

  els.scoreValue.textContent = score ?? "--";
  els.scoreValue.className = `score-value ${score != null ? renderScoreTone(score) : ""}`;
  els.gradeValue.textContent = grade || "-";
  els.verdictValue.textContent = verdict || "Итоговое заключение не сформировано";
  els.summaryValue.textContent = itog || "";

  renderMetrics(data.metrics || {});
  renderSections(data.sections || {});
  renderResultFavoriteButton();
}

function renderScoreTone(score) {
  if (score >= 70) return "metric-good";
  if (score >= 45) return "metric-warning";
  return "metric-danger";
}

function renderResultFavoriteButton() {
  if (!els.resultFavoriteBtn) return;

  const ticker = state.lastResult?.ticker;
  if (!state.token || !ticker) {
    els.resultFavoriteBtn.disabled = true;
    els.resultFavoriteBtn.textContent = "Добавить в избранное";
    els.resultFavoriteBtn.classList.remove("is-active");
    return;
  }

  const favorite = isTickerFavorite(ticker);
  els.resultFavoriteBtn.disabled = false;
  els.resultFavoriteBtn.textContent = favorite ? "Убрать из избранного" : "Добавить в избранное";
  els.resultFavoriteBtn.classList.toggle("is-active", favorite);
}

async function toggleFavoriteFromButton(ticker, companyName = "") {
  const normalizedTicker = String(ticker || "").trim();
  if (!state.token) {
    showToast("Сначала выполните вход", "error");
    setView("auth");
    return;
  }
  if (!normalizedTicker) return;

  try {
    const res = await apiFetch("/api/favorites/toggle", {
      method: "POST",
      body: JSON.stringify({
        ticker: normalizedTicker,
        company_name: companyName || undefined,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Не удалось обновить избранное");
    showToast(data.favorited ? `${normalizedTicker} добавлен в избранное` : `${normalizedTicker} удалён из избранного`, "success");
    await loadProfile();
    renderResultFavoriteButton();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function saveProfileChanges(event) {
  event.preventDefault();
  if (!state.token) {
    showToast("Сначала выполните вход", "error");
    return;
  }
  if (!els.profileEditForm) return;

  const form = new FormData(els.profileEditForm);
  const nextFullName = String(form.get("full_name") || "").trim();
  const currentFullName = String(state.user?.full_name || "").trim();
  const payload = {};

  if (nextFullName && nextFullName !== currentFullName) {
    payload.full_name = nextFullName;
  }

  const file = els.profileAvatarInput?.files?.[0];
  if (file) {
    payload.avatar_data_url = await readFileAsDataUrl(file);
  } else if (state.profileAvatarCleared) {
    payload.avatar_data_url = null;
  }

  if (!Object.keys(payload).length) {
    showToast("Изменений нет", "info");
    return;
  }

  try {
    const res = await apiFetch("/api/profile", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Не удалось сохранить профиль");
    state.user = data.user;
    setAuthState(data.user);
    state.profileAvatarCleared = false;
    if (els.profileAvatarInput) {
      els.profileAvatarInput.value = "";
    }
    if (els.profileEditHint) {
      els.profileEditHint.textContent = "Профиль обновлен.";
    }
    showToast("Профиль обновлен", "success");
    await loadProfile();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function loadCompanies() {
  const res = await apiFetch("/api/companies");
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Не удалось загрузить список компаний");

  state.companies = data.companies || [];
  els.companyCount.textContent = `${data.count || state.companies.length} компаний`;

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
    if (!res.ok) throw new Error(data.detail || "Сессия недействительна");
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

if (els.profileAnalyzeBtn) {
  els.profileAnalyzeBtn.addEventListener("click", () => setView("analysis"));
}

if (els.profileRefreshBtn) {
  els.profileRefreshBtn.addEventListener("click", async () => {
    if (!state.token) {
      showToast("Сначала выполните вход", "error");
      return;
    }
    await loadProfile();
    showToast("Профиль обновлен", "success");
  });
}

if (els.profileEditForm) {
  els.profileEditForm.addEventListener("submit", saveProfileChanges);
}

if (els.profileClearAvatarBtn) {
  els.profileClearAvatarBtn.addEventListener("click", () => {
    state.profileAvatarCleared = true;
    if (els.profileAvatarInput) {
      els.profileAvatarInput.value = "";
    }
    if (els.profileEditHint) {
      els.profileEditHint.textContent = "После сохранения текущий аватар будет удалён.";
    }
    showToast("Аватар будет удалён после сохранения", "info");
  });
}

if (els.profileHistorySearch) {
  els.profileHistorySearch.addEventListener("input", () => {
    if (state.profile) {
      renderProfile(state.profile);
    }
  });
}

if (els.profileHistoryMode) {
  els.profileHistoryMode.addEventListener("change", () => {
    if (state.profile) {
      renderProfile(state.profile);
    }
  });
}

if (els.resultFavoriteBtn) {
  els.resultFavoriteBtn.addEventListener("click", () => {
    if (!state.lastResult) return;
    toggleFavoriteFromButton(state.lastResult.ticker, state.lastResult.company_name || state.lastResult.input || "");
  });
}

els.googleLoginBtn.addEventListener("click", () => {
  window.location.href = `${API_BASE}/api/auth/oauth/google/start`;
});

els.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Выполняется вход...");
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
    setMessage(`Добро пожаловать, ${data.user.full_name || data.user.email}`);
    showToast(`Вход выполнен: ${data.user.email}`, "success");
    setView("profile");
    await loadProfile();
  } catch (error) {
    setMessage(error.message, "error");
    showToast(error.message, "error");
  }
});

els.registerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Создание учетной записи...");
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
    setMessage(`Учетная запись создана: ${data.user.email}`);
    showToast(`Учетная запись создана: ${data.user.email}`, "success");
    document.querySelector('.tab-btn[data-tab="login"]').click();
    setView("profile");
    await loadProfile();
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
  renderProfile(null);
  setMessage("Выход выполнен");
  showToast("Выход выполнен", "info");
  setView("auth");
});

els.analysisForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (!state.token) {
    setMessage("Чтобы запустить анализ, сначала выполните вход.", "error");
    showToast("Сначала выполните вход", "error");
    return;
  }

  const form = new FormData(els.analysisForm);
  const company = String(form.get("company") || "").trim();
  if (!company) {
    setMessage("Сначала выберите компанию.", "error");
    showToast("Сначала выберите компанию", "error");
    return;
  }

  els.apiState.textContent = "Выполняется анализ...";
  setMessage("Анализ выполняется...");
  if (loadingSkeletonTimer) {
    window.clearTimeout(loadingSkeletonTimer);
  }
  loadingSkeletonTimer = window.setTimeout(() => {
    setLoadingSkeleton(company);
    loadingSkeletonTimer = null;
  }, 220);

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
    if (!res.ok) throw new Error(data.detail || "Не удалось выполнить анализ");
    if (loadingSkeletonTimer) {
      window.clearTimeout(loadingSkeletonTimer);
      loadingSkeletonTimer = null;
    }
    renderResult(data);
    els.apiState.textContent = "Готово";
    setMessage(`Анализ завершен: ${data.company_name || company}`);
    showToast(`Анализ завершен: ${data.company_name || company}`, "success");
    loadProfile().catch(() => {});
  } catch (error) {
    if (loadingSkeletonTimer) {
      window.clearTimeout(loadingSkeletonTimer);
      loadingSkeletonTimer = null;
    }
    els.apiState.textContent = "API готов";
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
    els.companyCount.textContent = "Недоступно";
    setMessage(error.message, "error");
  }

  await refreshSession();
  await loadProfile();
  if (oauthReturned) {
    setMessage(state.oauthMessage || "Вход через OAuth выполнен");
    setView("profile");
  } else if (state.user) {
    setView("profile");
  }
  state.oauthMessage = "";
  clearResults();
});

