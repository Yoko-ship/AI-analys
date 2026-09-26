import { normalizeLanguage } from "../../shared/i18n.jsx";
import React from "react";
import { ProFeatureGate } from "../../shared/ProFeatureGate.jsx";
import { formatMarketNumber, formatRatio, formatSignedPercent } from "../../shared/format.jsx";

function PortfolioView({ language, apiFetch, signedIn, hasProAccess, onUpgrade, onOpenCompany }) {
  const lang = normalizeLanguage(language);
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [portfolio, setPortfolio] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState("");
  const [form, setForm] = React.useState({ ticker: "", quantity: "", average_cost: "", note: "" });
  const [saving, setSaving] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true); setError("");
    return apiFetch("/api/portfolio").then(async (response) => {
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.ok) throw new Error(body?.detail?.message || body?.detail || "Portfolio unavailable");
      setPortfolio(body);
    }).catch((err) => setError(String(err?.message || err))).finally(() => setLoading(false));
  }, [apiFetch]);
  React.useEffect(() => { if (hasProAccess) load(); else setLoading(false); }, [hasProAccess, load]);

  const title = t("Портфель", "Portfel", "Portfolio");
  if (!hasProAccess) return <ProFeatureGate language={lang} title={title}
    description={t("В PRO можно вести собственные позиции и видеть их стоимость по последней подтверждённой биржевой сделке.", "PROda o‘z pozitsiyalaringizni yuritib, ularning qiymatini so‘nggi tasdiqlangan birja bitimi bo‘yicha ko‘rishingiz mumkin.", "PRO lets you maintain your positions and value them from the last confirmed exchange trade.")}
    signedIn={signedIn} onUpgrade={onUpgrade} />;
  const money = (value) => Number.isFinite(Number(value)) ? `${formatMarketNumber(value, lang)} ${t("сум", "so‘m", "UZS")}` : "—";
  const submit = async (event) => {
    event.preventDefault(); setSaving(true); setError("");
    try {
      const response = await apiFetch("/api/portfolio/positions", { method: "PUT", body: JSON.stringify({
        ticker: form.ticker.trim().toUpperCase(), quantity: Number(form.quantity), average_cost: Number(form.average_cost), note: form.note,
      }) });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.ok) throw new Error(body?.detail?.message || body?.detail || "Could not save position");
      setForm({ ticker: "", quantity: "", average_cost: "", note: "" }); await load();
    } catch (err) { setError(String(err?.message || err)); } finally { setSaving(false); }
  };
  const remove = async (ticker) => {
    try {
      const response = await apiFetch(`/api/portfolio/positions/${encodeURIComponent(ticker)}`, { method: "DELETE" });
      const body = await response.json().catch(() => null);
      if (!response.ok || !body?.ok) throw new Error(body?.detail?.message || body?.detail || "Could not remove position");
      await load();
    } catch (err) { setError(String(err?.message || err)); }
  };
  return <section className="stack portfolio-view">
    <header className="page-head"><div><h1>{title}</h1><p>{t("Только вручную добавленные позиции. Нереализованный результат не учитывает комиссии, налоги и корпоративные действия.", "Faqat qo‘lda qo‘shilgan pozitsiyalar. Hisoblangan natija komissiya, soliq va korporativ harakatlarni hisobga olmaydi.", "Only positions you enter. Unrealized P/L excludes fees, tax, and corporate actions.")}</p></div></header>
    <div className="grid3">
      <article className="kpi panel"><div className="label">{t("Стоимость", "Qiymat", "Market value")}</div><div className="value">{money(portfolio?.market_value)}</div><div className="hint">{portfolio?.priced_count || 0}/{portfolio?.count || 0} {t("переоценено", "baholangan", "priced")}</div></article>
      <article className="kpi panel"><div className="label">{t("Себестоимость", "Tannarx", "Cost basis")}</div><div className="value">{money(portfolio?.cost_value)}</div><div className="hint">{portfolio?.price_basis || "—"}</div></article>
      <article className="kpi panel"><div className="label">{t("Нереализованный P/L", "Amalga oshmagan P/L", "Unrealized P/L")}</div><div className={`value ${Number(portfolio?.unrealized_pnl) >= 0 ? "pos" : "neg"}`}>{money(portfolio?.unrealized_pnl)}</div><div className="hint">UZS</div></article>
    </div>
    <article className="panel pad"><h2 className="section-heading">{t("Добавить или обновить позицию", "Pozitsiya qo‘shish yoki yangilash", "Add or update position")}</h2><form className="form-grid" onSubmit={submit}>
      <label className="field"><span>{t("Тикер", "Ticker", "Ticker")}</span><input required maxLength="40" value={form.ticker} onChange={(e) => setForm({ ...form, ticker: e.target.value.toUpperCase() })} placeholder="KSCM" /></label>
      <label className="field"><span>{t("Количество", "Miqdor", "Quantity")}</span><input required min="0.000001" step="any" type="number" value={form.quantity} onChange={(e) => setForm({ ...form, quantity: e.target.value })} /></label>
      <label className="field"><span>{t("Средняя цена, UZS", "O‘rtacha narx, UZS", "Average cost, UZS")}</span><input required min="0" step="any" type="number" value={form.average_cost} onChange={(e) => setForm({ ...form, average_cost: e.target.value })} /></label>
      <label className="field"><span>{t("Заметка", "Izoh", "Note")}</span><input maxLength="1000" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></label>
      <div className="profile-form-actions"><button className="primary-btn" type="submit" disabled={saving}>{saving ? t("Сохранение…", "Saqlanmoqda…", "Saving…") : t("Сохранить", "Saqlash", "Save")}</button></div>
    </form></article>
    {error && <div className="callout red"><span className="ico">!</span><div>{error}</div><button type="button" onClick={load}>{t("Повторить", "Qayta urinish", "Retry")}</button></div>}
    <article className="panel"><div className="panel-head"><h2>{t("Позиции", "Pozitsiyalar", "Positions")}</h2><span className="muted">{portfolio?.price_basis || "—"}</span></div>
      {loading ? <div className="chart-loading muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</div> : !(portfolio?.items || []).length ? <div className="empty-state"><h2>{t("Пока нет позиций", "Hozircha pozitsiyalar yo‘q", "No positions yet")}</h2><p>{t("Добавьте тикер, количество и среднюю цену выше.", "Yuqorida ticker, miqdor va o‘rtacha narxni qo‘shing.", "Add a ticker, quantity, and average cost above.")}</p></div> : <div className="table-wrap"><table><thead><tr><th>{t("Бумага", "Qimmatli qog‘oz", "Security")}</th><th>{t("Количество", "Miqdor", "Quantity")}</th><th>{t("Цена / стоимость", "Narx / qiymat", "Price / value")}</th><th>P/L</th><th /></tr></thead><tbody>{portfolio.items.map((item) => <tr key={item.ticker}><td><button className="rowlink" type="button" onClick={() => onOpenCompany?.(item.ticker)}><b>{item.ticker}</b><span className="meta">{item.company_name || item.note || "—"}</span></button></td><td>{formatRatio(item.quantity, 4, lang)}</td><td>{item.valuation_status === "AVAILABLE" ? <><b>{money(item.last_price)}</b><span className="meta">{money(item.market_value)}</span></> : <span className="muted">{t("Нет подтверждённой цены", "Tasdiqlangan narx yo‘q", "No confirmed price")}</span>}</td><td className={Number(item.unrealized_pnl) >= 0 ? "pos" : "neg"}>{money(item.unrealized_pnl)}<span className="meta">{item.unrealized_pnl_pct == null ? "—" : formatSignedPercent(item.unrealized_pnl_pct, 2)}</span></td><td><button className="icon-btn" type="button" onClick={() => setForm({ ticker: item.ticker, quantity: String(item.quantity), average_cost: String(item.average_cost), note: item.note || "" })}>{t("Изменить", "Tahrirlash", "Edit")}</button><button className="icon-btn" type="button" onClick={() => remove(item.ticker)}>{t("Удалить", "O‘chirish", "Delete")}</button></td></tr>)}</tbody></table></div>}
    </article>
  </section>;
}

export { PortfolioView };
