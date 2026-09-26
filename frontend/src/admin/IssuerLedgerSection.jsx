import { fmtInt, fmtNum } from "./adminModel.js";
export function IssuerLedgerSection({
  t,
  ledgerTicker,
  setLedgerTicker,
  loadLedger,
  ledger
}) {
  const money = v => v == null ? "—" : fmtInt(v);
  const ratio = m => m && m.value != null ? fmtNum(m.value, 2) : <span className="admin-muted" title={m && (m.note || m.status) || ""}>—</span>;
  return <div className="admin-section">
      <div className="panel admin-filters">
        <input className="admin-input" placeholder={t("Тикер, например UZTL", "Ticker, masalan UZTL", "Ticker, e.g. UZTL")} value={ledgerTicker} onChange={e => setLedgerTicker(e.target.value.toUpperCase())} onKeyDown={e => {
        if (e.key === "Enter") loadLedger(ledgerTicker);
      }} />
        <button type="button" className="admin-btn accent" onClick={() => loadLedger(ledgerTicker)}>
          {t("Разобрать", "Tahlil qilish", "Open")}
        </button>
      </div>

      {!ledger ? <div className="panel">
          <div className="admin-empty">
            <b>{t("Выберите эмитента", "Emitentni tanlang", "Pick an issuer")}</b>
            {t("Экран показывает расчёт того же пути, который публикует витрину, — не второй реализации: второй реализации свойственно расходиться с первой, и тогда панель сообщает о собственной ошибке.", "Ekran vitrinani e'lon qiladigan yo'lning hisobini ko'rsatadi.", "The screen shows the calculation of the same path that publishes the market screen — not a second implementation.")}
          </div>
        </div> : <>
          <div className="panel">
            <div className="admin-panel-head">
              <h2>{ledger.issuer} · {ledger.ticker}</h2>
              <span className="admin-muted">
                {ledger.form && ledger.form.org_type ? `${ledger.form.org_type} · ` : ""}
                {t("база", "baza", "base")}: {ledger.form && ledger.form.base_period ? ledger.form.base_period : "—"}
              </span>
            </div>

            <div className="admin-ledger">
              <div className="admin-ledger-head">
                <span>{t("Числитель · двенадцать месяцев прибыли", "Numerator", "Numerator · twelve months of profit")}</span>
                <span className="admin-muted">{ledger.ttm && ledger.ttm.method_note}</span>
              </div>
              {(ledger.ttm && ledger.ttm.components || []).map((c, i) => <div key={i} className={`admin-ledger-row${c.dropped ? " dropped" : ""}`}>
                  <span className="admin-ledger-sign">{c.sign}</span>
                  <span className="admin-ledger-label">
                    <b>{c.label}</b>
                    <span className="admin-muted">
                      {c.period || "—"}{c.months ? ` · ${c.months} ${t("мес.", "oy", "mo")}` : ""}
                      {c.report_id ? ` · report ${c.report_id}` : ""}
                      {c.dropped ? ` · ${t("не вошло в базу", "bazaga kirmadi", "not used")}` : ""}
                    </span>
                  </span>
                  <span className="admin-ledger-val">{money(c.net_income)}</span>
                </div>)}
              <div className="admin-ledger-row total">
                <span className="admin-ledger-sign">=</span>
                <span className="admin-ledger-label">
                  <b>{t("Принято к расчёту", "Hisobga qabul qilindi", "Taken into the calculation")}</b>
                  <span className="admin-muted">{ledger.ttm && ledger.ttm.period || "—"}
                    {ledger.ttm && ledger.ttm.estimate ? ` · ${t("ОЦЕНКА", "BAHO", "ESTIMATE")}` : ""}</span>
                </span>
                <span className="admin-ledger-val">
                  {money(ledger.ttm && ledger.ttm.result && ledger.ttm.result.net_income)}
                </span>
              </div>
            </div>
          </div>

          <div className="admin-cols3">
            <div className="panel">
              <h3>{t("Капитализация", "Kapitalizatsiya", "Capitalisation")}</h3>
              <table className="admin-kv">
                <tbody>
                  {(ledger.classes || []).map(c => <tr key={c.ticker}>
                      <td>{c.ticker} · {c.share_class === "preferred" ? t("привилег.", "imtiyozli", "preferred") : t("обыкн.", "oddiy", "ordinary")}</td>
                      <td className="n">{c.counted ? money(c.market_cap) : <span className="admin-muted" title={t("Класс ни разу не торговался: цена была бы номиналом из реестра, а капитализация на номинале — вымысел.", "Sinf hech qachon savdo bo'lmagan.", "The class has never traded: its price would be the registry's nominal.")}>{t("не учтён", "hisobga olinmagan", "not counted")}</span>}</td>
                    </tr>)}
                  <tr className="total">
                    <td><b>{t("По компании", "Kompaniya bo'yicha", "Whole company")}</b></td>
                    <td className="n"><b>{money(ledger.market_cap && ledger.market_cap.value)}</b></td>
                  </tr>
                </tbody>
              </table>
              {ledger.market_cap && ledger.market_cap.note ? <p className="admin-muted admin-note">{ledger.market_cap.note}</p> : null}
            </div>

            <div className="panel">
              <h3>{t("Знаменатели · остатки", "Maxrajlar · qoldiqlar", "Denominators · balances")}</h3>
              <table className="admin-kv">
                <tbody>
                  <tr><td>{t("Период баланса", "Balans davri", "Balance period")}</td><td className="n">{ledger.balance && ledger.balance.period || "—"}</td></tr>
                  <tr><td>{t("Капитал на конец", "Oxiriga kapital", "Equity, close")}</td><td className="n">{money(ledger.balance && ledger.balance.equity)}</td></tr>
                  <tr><td>{t("Капитал средний", "O'rtacha kapital", "Equity, average")}</td><td className="n">{money(ledger.balance && ledger.balance.equity_avg)}</td></tr>
                  <tr><td>{t("Активы на конец", "Oxiriga aktivlar", "Assets, close")}</td><td className="n">{money(ledger.balance && ledger.balance.assets)}</td></tr>
                  <tr><td>{t("Активы средние", "O'rtacha aktivlar", "Assets, average")}</td><td className="n">{money(ledger.balance && ledger.balance.assets_avg)}</td></tr>
                </tbody>
              </table>
              <p className="admin-muted admin-note">{ledger.balance && ledger.balance.rule}</p>
            </div>

            <div className="panel">
              <h3>{t("Проверки", "Tekshiruvlar", "Validations")}</h3>
              <div className="admin-checklist">
                {Object.entries(ledger.checks && ledger.checks.results || {}).map(([code, ok]) => <div key={code}>
                    <span className="admin-pill"><span className={`admin-dot ${ok ? "ok" : "err"}`} />{code}</span>
                  </div>)}
                {!Object.keys(ledger.checks && ledger.checks.results || {}).length ? <span className="admin-muted">{t("Тождества не проверялись: не хватает входов.", "Tekshirilmadi.", "Not checked: inputs missing.")}</span> : null}
              </div>
              {ledger.validation && ledger.validation.reason ? <p className="admin-muted admin-note">{ledger.validation.reason}</p> : null}
            </div>
          </div>

          <div className="panel">
            <h3>{t("Показатели", "Ko'rsatkichlar", "Multiples")}</h3>
            <div className="admin-table">
              <table>
                <thead>
                  <tr>
                    <th>{t("Показатель", "Ko'rsatkich", "Metric")}</th>
                    <th>{t("Формула", "Formula", "Formula")}</th>
                    <th className="n">{t("Числитель", "Surat", "Numerator")}</th>
                    <th className="n">{t("Знаменатель", "Maxraj", "Denominator")}</th>
                    <th className="n">{t("Значение", "Qiymat", "Value")}</th>
                    <th className="n">{t("На витрине", "Vitrinada", "Published")}</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(ledger.inputs || {}).map(([name, b]) => <tr key={name}>
                      <td><b>{name.toUpperCase().replace("_", " ")}</b></td>
                      <td className="admin-muted">{b.formula}</td>
                      <td className="n">{money(b.numerator)}</td>
                      <td className="n">{money(b.denominator)}</td>
                      <td className="n">{b.value == null ? <span className="admin-muted" title={b.note || b.status || ""}>—</span> : fmtNum(b.value, 2)}</td>
                      <td className="n">{ratio(ledger.published && ledger.published[name])}</td>
                    </tr>)}
                </tbody>
              </table>
            </div>
            <p className="admin-muted admin-note">
              {t("Обе колонки приходят из одного вызова: расхождение здесь — ошибка этого экрана, а не рынка, и её тоже стоит видеть.", "Ikkala ustun bitta chaqiruvdan keladi.", "Both columns come from one call: a difference here is a bug in this screen, not in the market — and worth seeing too.")}
            </p>
          </div>
        </>}
    </div>;
}
