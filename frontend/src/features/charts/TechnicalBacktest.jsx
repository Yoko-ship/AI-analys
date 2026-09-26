import React from "react";
import { formatRatio, formatSignedPercent } from "../../shared/format.jsx";

function TechnicalBacktestCard({ ticker, lang, apiFetch, signedIn, hasProAccess, onUpgrade }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");
  const run = async () => {
    setLoading(true); setError("");
    try {
      const response = await apiFetch(`/api/company/${encodeURIComponent(ticker)}/technical-backtest`);
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.ok) throw new Error(body?.detail?.message || body?.detail || "Backtest unavailable");
      setData(body);
    } catch (err) { setError(String(err?.message || err)); } finally { setLoading(false); }
  };
  const metric = data?.metrics || {};
  return <article className="panel pad" style={{ marginTop: 16 }}>
    <div className="section-title" style={{ marginTop: 0 }}><h2>{t("Бэктест торгового правила", "Savdo qoidasi backtesti", "Trading-rule backtest")}</h2>{data?.model_version && <span className="muted">{data.model_version}</span>}</div>
    {!hasProAccess ? <div className="callout amber"><span className="ico">🔒</span><div><strong>{t("PRO-функция", "PRO funksiya", "PRO feature")}</strong><br />{t("Бэктест использует только подтверждённые сессии, следующую сессию для исполнения, комиссию и проскальзывание.", "Backtest faqat tasdiqlangan sessiyalar, ijro uchun keyingi sessiya, komissiya va sirpanishni ishlatadi.", "The backtest uses confirmed sessions only, next-session execution, fees and slippage.")}</div><button className="primary-btn" type="button" onClick={onUpgrade}>{signedIn ? "PRO" : t("Войти", "Kirish", "Sign in")}</button></div> : <>
      {!data && <button className="primary-btn" type="button" disabled={loading} onClick={run}>{loading ? t("Расчёт…", "Hisoblanmoqda…", "Running…") : t("Запустить SMA(20)", "SMA(20)ni ishga tushirish", "Run SMA(20)")}</button>}
      {error && <p className="neg">{error}</p>}
      {data?.status === "NO_DATA" && <p className="muted">{data.reason}</p>}
      {data?.status === "AVAILABLE" && <><div className="grid3" style={{ marginTop: 14 }}><div className="kpi"><div className="label">{t("Доходность", "Daromadlilik", "Return")}</div><div className="value">{formatSignedPercent(metric.total_return_pct, 2)}</div></div><div className="kpi"><div className="label">Max drawdown</div><div className="value">{formatRatio(metric.max_drawdown_pct, 2, lang)}%</div></div><div className="kpi"><div className="label">Sharpe</div><div className="value">{formatRatio(metric.sharpe, 2, lang)}</div></div></div><p className="muted" style={{ marginTop: 12 }}>{data.rule} · {data.period?.from} — {data.period?.to} · {data.period?.observations} {t("сессий", "sessiya", "sessions")}. {data.disclaimer}</p></>}
    </>}
  </article>;
}

export { TechnicalBacktestCard };
