import { normalizeLanguage } from "../../shared/i18n.jsx";
import React from "react";
import { ProFeatureGate } from "../../shared/ProFeatureGate.jsx";
import { formatMarketNumber, formatRatio, formatSignedPercent } from "../../shared/format.jsx";

function CompanyForecastTab({ ticker, language, apiFetch, signedIn, hasProAccess, onUpgrade }) {
  const lang = normalizeLanguage(language);
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [standard, setStandard] = React.useState("NSBU");
  const [state, setState] = React.useState({ loading: false, forecast: null, backtest: null, error: "" });
  const [retry, setRetry] = React.useState(0);

  React.useEffect(() => {
    if (!hasProAccess || !ticker) return undefined;
    let alive = true;
    setState({ loading: true, forecast: null, backtest: null, error: "" });
    const qs = `form=${encodeURIComponent(standard)}`;
    Promise.all([
      apiFetch(`/api/company/${encodeURIComponent(ticker)}/forecast?${qs}`).then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok || !body?.ok) throw new Error(body?.detail?.message || body?.detail || "Forecast unavailable");
        return body;
      }),
      apiFetch(`/api/company/${encodeURIComponent(ticker)}/forecast/backtest?${qs}`).then(async (response) => {
        const body = await response.json().catch(() => null);
        if (!response.ok || !body?.ok) throw new Error(body?.detail?.message || body?.detail || "Backtest unavailable");
        return body;
      }),
    ]).then(([forecast, backtest]) => {
      if (alive) setState({ loading: false, forecast, backtest, error: "" });
    }).catch((error) => {
      if (alive) setState({ loading: false, forecast: null, backtest: null, error: String(error?.message || error) });
    });
    return () => { alive = false; };
  }, [ticker, standard, retry, hasProAccess, apiFetch]);

  const title = t("Прогноз и справедливая цена", "Prognoz va adolatli qiymat", "Forecast & fair value");
  if (!hasProAccess) return <ProFeatureGate language={lang} title={title}
    description={t("Три сценария, прозрачные предпосылки, диапазон справедливой цены и бэктест доступны в PRO.", "Uchta ssenariy, shaffof taxminlar, adolatli narx oralig‘i va backtest PROda mavjud.", "Three scenarios, transparent assumptions, fair-value range and backtest are available with PRO.")}
    signedIn={signedIn} onUpgrade={onUpgrade} />;

  const forecast = state.forecast;
  const backtest = state.backtest;
  const fmtMoney = (value) => Number.isFinite(Number(value))
    ? `${formatMarketNumber(Number(value) * 1000, lang)} ${t("сум", "so‘m", "UZS")}` : "—";
  const fmtPrice = (value) => Number.isFinite(Number(value))
    ? `${formatMarketNumber(value, lang)} ${t("сум", "so‘m", "UZS")}` : "—";
  return (
    <section className="company-forecast stack">
      <div className="basis-bar">
        <div>
          <strong>{title}</strong>
          <span className="muted" style={{ display: "block", marginTop: 4, fontSize: 12 }}>
            {t("Модель не является инвестиционной рекомендацией. Вероятности не публикуются без калибровки.", "Model investitsiya tavsiyasi emas. Kalibrlashsiz ehtimollar chop etilmaydi.", "This model is not investment advice. Probabilities are withheld until calibrated.")}
          </span>
        </div>
        <div className="fin-freq" role="group" aria-label={t("Стандарт", "Standart", "Standard")}>
          {["NSBU", "MSFO"].map((code) => <button key={code} type="button"
            className={`fin-freq-btn ${standard === code ? "active" : ""}`} onClick={() => setStandard(code)}>{code === "NSBU" ? "НСБУ" : "МСФО"}</button>)}
        </div>
      </div>
      {state.loading && <div className="chart-loading muted">{t("Загрузка прогноза…", "Prognoz yuklanmoqda…", "Loading forecast…")}</div>}
      {state.error && <div className="panel" style={{ padding: 20 }}><p>{state.error}</p><button className="primary-btn" type="button" onClick={() => setRetry((n) => n + 1)}>{t("Повторить", "Qayta urinish", "Retry")}</button></div>}
      {!state.loading && forecast?.status === "NO_DATA" && <div className="panel" style={{ padding: 24 }}>
        <h3>{t("Прогноз пока недоступен", "Prognoz hozircha mavjud emas", "Forecast is not available yet")}</h3><p className="muted">{forecast.reason}</p>
      </div>}
      {!state.loading && forecast?.status === "AVAILABLE" && <>
        <div className="grid3">
          {(forecast.scenarios || []).map((row) => <article className="panel pad" key={row.scenario}>
            <span className="panel-label">{row.scenario === "downside" ? t("Негативный", "Salbiy", "Downside") : row.scenario === "upside" ? t("Позитивный", "Ijobiy", "Upside") : t("Базовый", "Asosiy", "Base")}</span>
            <strong className="big-number">{formatSignedPercent(row.revenue_growth_pct, 1)}</strong>
            <div className="metric-list"><div><span>{t("Выручка", "Tushum", "Revenue")}</span><b>{fmtMoney(row.revenue)}</b></div><div><span>{t("Чистая прибыль", "Sof foyda", "Net income")}</span><b>{fmtMoney(row.net_profit)}</b></div><div><span>EPS</span><b>{fmtPrice(row.eps)}</b></div></div>
          </article>)}
        </div>
        <article className="panel pad">
          <div className="section-title" style={{ marginTop: 0 }}><h2>{t("Справедливая цена", "Adolatli narx", "Fair value")}</h2><span className="muted">{forecast.fair_value?.method || t("Нет проверяемого метода", "Tekshiriladigan usul yo‘q", "No verified method")}</span></div>
          {forecast.fair_value?.status === "AVAILABLE" ? <div className="grid3">
            {[["lower", t("Нижняя", "Pastki", "Lower")], ["mid", t("Базовая", "Asosiy", "Mid")], ["upper", t("Верхняя", "Yuqori", "Upper")]].map(([key, label]) => <div className="kpi" key={key}><div className="label">{label}</div><div className="value">{fmtPrice(forecast.fair_value[key])}</div><div className="hint">P/E {formatRatio(forecast.fair_value.peer_pe?.[key], 2, lang)}</div></div>)}
          </div> : <p className="muted">{forecast.fair_value?.reason}</p>}
          <div className="panel-foot">{t("Факты по состоянию на", "Faktlar holati", "Facts as of")}: {forecast.facts_as_of_year || "—"} · {t("Группа аналогов", "Taqqoslanadigan guruh", "Peer group")}: {forecast.peer_population?.count || 0} ({forecast.peer_population?.sector || t("не определён", "aniqlanmagan", "not mapped")})</div>
        </article>
        <article className="panel pad">
          <h2 className="section-heading">{t("Предпосылки и контроль качества", "Taxminlar va sifat nazorati", "Assumptions & quality control")}</h2>
          <div className="metric-list"><div><span>{t("Метод", "Usul", "Method")}</span><b>{forecast.assumptions?.method}</b></div><div><span>{t("Исторические годы", "Tarixiy yillar", "Historical years")}</span><b>{(forecast.historical_years || []).join(", ") || "—"}</b></div><div><span>{t("Версия модели", "Model versiyasi", "Model version")}</span><b>{forecast.model_version || "—"}</b></div></div>
          <div className="callout amber" style={{ marginTop: 14 }}><span className="ico">!</span><div><strong>{t("Публикация заблокирована", "Chop etish bloklangan", "Publication blocked")}</strong><br />{forecast.quality?.reason}</div></div>
        </article>
      </>}
      {!state.loading && backtest && <article className="panel pad">
        <div className="section-title" style={{ marginTop: 0 }}><h2>{t("Walk-forward бэктест", "Walk-forward backtest", "Walk-forward backtest")}</h2><span className={`status-tag ${backtest.status === "AVAILABLE" ? "warn" : ""}`}>{backtest.status}</span></div>
        {backtest.status === "AVAILABLE" ? <><div className="grid3"><div className="kpi"><div className="label">MAE</div><div className="value">{formatRatio(backtest.mae_pct, 2, lang)}%</div></div><div className="kpi"><div className="label">{t("Наблюдения", "Kuzatuvlar", "Observations")}</div><div className="value">{backtest.trials?.length || 0}</div></div><div className="kpi"><div className="label">{t("Хронология", "Xronologiya", "Chronology")}</div><div className="value">{backtest.chronology_verified ? t("Проверена", "Tekshirilgan", "Verified") : t("Неполная", "To‘liq emas", "Incomplete")}</div></div></div><p className="muted" style={{ marginTop: 14 }}>{backtest.reason}</p></> : <p className="muted">{backtest.reason}</p>}
      </article>}
    </section>
  );
}

export {  };
