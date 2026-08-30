import React, { useCallback, useEffect, useState } from "react";
import VerifiedReport from "../analysis/VerifiedReport.jsx";
import "./admin.css";

export function SectorMonitorPage({ apiFetch, language }) {
  const readJson = useCallback(async (path, options) => {
    const response = await apiFetch(path, options);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || body.message || "Access unavailable");
    return body;
  }, [apiFetch]);
  return <AnalysisMonitor readJson={readJson} language={language} />;
}

export default function AnalysisMonitor({ readJson, language = "ru" }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [rule, setRule] = useState({ ticker: "", override_template: "generic_nsbu", evidence_source: "", reason_code: "", valid_from: new Date().toISOString().slice(0, 10), valid_to: "2099-12-31" });
  const t = (ru, uz, en) => ({ ru, uz, en }[language] || ru);
  const can = (capability) => (data?.capabilities || []).includes(capability);
  const refresh = useCallback(async () => {
    try { setData(await readJson("/api/admin/sector-analysis")); setError(""); }
    catch (e) { setError(e.message); }
  }, [readJson]);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try { const result = await readJson("/api/admin/sector-analysis"); if (alive) setData(result); }
      catch (e) { if (alive) setError(e.message); }
    };
    load();
    const timer = setInterval(load, 30000);
    return () => { alive = false; clearInterval(timer); };
  }, [readJson]);
  const open = async (version) => {
    setBusy(true);
    try { setSelected(await readJson("/api/admin/sector-analysis/runs/" + version)); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const retry = async (id) => {
    setBusy(true);
    try {
      await readJson("/api/admin/sector-analysis/jobs/" + id + "/retry", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) });
      await refresh();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const mutate = async (path, body) => {
    setBusy(true);
    try { await readJson(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }); await refresh(); setError(""); setNotice(t("Изменение сохранено и записано в журнал.", "O‘zgarish saqlandi va jurnalga yozildi.", "The change was saved and recorded in the audit log.")); }
    catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return <section className="panel sector-monitor">
    <h3>{t("Мониторинг отраслевого анализа", "Tarmoq tahlili monitoringi", "Sector analysis monitoring")}</h3>
    <p>{t("Автоматические публикации, проверки данных и исключения. Расчётные значения не редактируются вручную.", "Avtomatik nashrlar, ma’lumot tekshiruvlari va istisnolar. Hisoblangan qiymatlar qo‘lda o‘zgartirilmaydi.", "Automatic publications, data checks and exceptions. Calculated values cannot be manually edited.")}</p>
    {error && <p role="alert">{error}</p>}
    {notice && <p className="verified-note" role="status">{notice}</p>}
    {!data && !error && <p role="status">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>}
    <div className="verified-meta">{Object.entries(data?.counts || {}).map(([state, count]) => <span key={state}>{state}: <strong>{count}</strong></span>)}</div>
    {data?.regression && <p>{t("Регрессионные проверки", "Regressiya tekshiruvlari", "Regression gate")}: <strong>{data.regression.status}</strong> · {data.regression.checks?.length}</p>}
    <button type="button" className="ghost-btn" onClick={refresh}>{t("Обновить", "Yangilash", "Refresh")}</button>
    <div className="admin-scroll"><table>
      <thead><tr><th>{t("Эмитент", "Emitent", "Issuer")}</th><th>{t("Период", "Davr", "Period")}</th><th>{t("Статус", "Holat", "Status")}</th><th>{t("Версия", "Versiya", "Version")}</th></tr></thead>
      <tbody>{(data?.runs || []).map((run) => <tr key={run.version}><td>{run.ticker} · {run.language}</td><td>{run.standard.toUpperCase()} · {run.period || "—"}</td><td>{run.status}</td><td><button className="admin-btn sm" type="button" disabled={busy} onClick={() => open(run.version)}>{run.version.slice(0, 12)}</button></td></tr>)}</tbody>
    </table></div>
    {data && data.runs.length === 0 && <p>{t("Запусков пока нет.", "Hali ishga tushirilmagan.", "No runs have been recorded.")}</p>}
    {can("activate") && <details className="verified-block">
      <summary>{t("Правила выбора шаблона", "Shablon tanlash qoidalari", "Template selection rules")}</summary>
      <form className="verified-rule-form" onSubmit={(e) => { e.preventDefault(); mutate("/api/admin/sector-analysis/overrides", rule); }}>
        <label>{t("Тикер", "Tiker", "Ticker")}<input required maxLength={30} value={rule.ticker} onChange={(e) => setRule({ ...rule, ticker: e.target.value })} /></label>
        <label>{t("Шаблон", "Shablon", "Template")}<select aria-label={t("Шаблон", "Shablon", "Template")} value={rule.override_template} onChange={(e) => setRule({ ...rule, override_template: e.target.value })}>
          {["generic_nsbu", "bank", "insurance", "microfinance_bank", "microfinance", "investment_fund_ifrs_annual", "commodity_exchange", "spv", "aviation", "telecom", "leasing", "cement", "metallurgy", "extractive", "trade", "transport", "industry"].map((s) => <option key={s}>{s}</option>)}
        </select></label>
        <label>{t("Источник решения", "Qaror manbasi", "Decision source")}<input required type="url" value={rule.evidence_source} onChange={(e) => setRule({ ...rule, evidence_source: e.target.value })} /></label>
        <label>{t("Причина", "Sabab", "Reason")}<input required minLength={3} maxLength={500} value={rule.reason_code} onChange={(e) => setRule({ ...rule, reason_code: e.target.value })} /></label>
        <label>{t("Действует с", "Amal boshlanishi", "Valid from")}<input required type="date" value={rule.valid_from} onChange={(e) => setRule({ ...rule, valid_from: e.target.value })} /></label>
        <label>{t("Действует до", "Amal tugashi", "Valid until")}<input required type="date" value={rule.valid_to} onChange={(e) => setRule({ ...rule, valid_to: e.target.value })} /></label>
        <button className="admin-btn accent" type="submit" disabled={busy || data?.regression?.status !== "passed"}>{t("Сохранить версию и пересчитать эмитента", "Versiyani saqlash va emitentni qayta hisoblash", "Save version and recalculate issuer")}</button>
      </form>
      <ul>{(data?.overrides || []).map((r) => <li key={r.version}>{r.ticker} → {r.override_template} · {r.valid_from}–{r.valid_to} · {r.approved_by}</li>)}</ul>
    </details>}
    {data?.jobs?.length > 0 && <details>
      <summary>{t("Очередь и повторы", "Navbat va takrorlash", "Queue and retries")}</summary>
      {can("retry") && <label>{t("Причина повтора", "Takrorlash sababi", "Retry reason")}<input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></label>}
      <ul>{data.jobs.map((job) => <li key={job.id}>{job.ticker} · {job.state} · {job.error_code || "—"} · {job.attempts}
        {can("retry") && ["blocked", "incident", "retry"].includes(job.state) && <button className="admin-btn sm" type="button" disabled={busy || reason.trim().length < 3} onClick={() => retry(job.id)}>{t("Повторить", "Takrorlash", "Retry")}</button>}
      </li>)}</ul>
    </details>}
    {data?.audit?.length > 0 && <details><summary>{t("Журнал изменений", "O‘zgarishlar jurnali", "Audit history")}</summary><ul>{data.audit.map((a) => <li key={a.id}>{a.at} · {a.actor} · {a.action} · {a.reason}</li>)}</ul></details>}
    {selected && <section>
      <button className="admin-btn" type="button" onClick={() => setSelected(null)}>{t("Закрыть версию", "Versiyani yopish", "Close version")}</button>
      {selected.status === "available" && can("rollback") && <div className="verified-rule-form">
        <label>{t("Причина восстановления версии", "Versiyani tiklash sababi", "Reason for restoring this version")}<input value={reason} onChange={(e) => setReason(e.target.value)} minLength={3} maxLength={500} /></label>
        <button className="admin-btn danger" type="button" disabled={busy || reason.trim().length < 3} onClick={() => mutate("/api/admin/sector-analysis/runs/" + selected.version + "/rollback", { reason })}>{t("Восстановить публикацию до обновления источника/правила", "Manba/qoida yangilanguncha nashrni tiklash", "Restore publication until source/rule update")}</button>
      </div>}
      <VerifiedReport report={selected} lang={language} narrative />
    </section>}
  </section>;
}
