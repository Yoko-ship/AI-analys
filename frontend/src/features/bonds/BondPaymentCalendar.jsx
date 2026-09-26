import React from "react";
import { roundedDisplayValue, compact as fmtCompact } from "../../lib/format.js";
import { calendarBounds, paymentPeriod, periodPreset, validatePeriod } from "./calendarModel.js";

const fmtBondDay = (iso) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : "—");

const MONTH_SHORT = {
  ru: ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"],
  uz: ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avg", "sen", "okt", "noy", "dek"],
  en: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
};

const MONTH_FULL = {
  ru: ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"],
  uz: ["Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun", "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr"],
  en: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
};

/** What the bond market owes, and when. Reads /api/bonds/calendar.
 *
 * The screen exists because the exchange's register does: before it, the only
 * future payment anyone could name was the one an issuer had already announced,
 * so a calendar would have held one coupon of one issue. The dates between
 * placement and redemption are reconstructed from the coupon cycle, and the
 * screen says so rather than letting a plan read as a diary. */
function BondPaymentCalendar({ lang, onOpenBond }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    fetch("/api/bonds/calendar?months=60")
      .then((r) => r.json())
      .then((d) => { if (alive) { if (d && d.ok) setData(d); else setError(true); } })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, []);

  if (error) return <p className="muted">{t("Календарь недоступен", "Taqvim mavjud emas", "Calendar unavailable")}</p>;
  if (!data) return <p className="muted">{t("Загрузка…", "Yuklanmoqda…", "Loading…")}</p>;

  return <PaymentCalendarContent data={data} lang={lang} onOpenBond={onOpenBond} />;
}

function PaymentCalendarContent({ data, lang, onOpenBond }) {
  const t = (ru, uz, en) => (lang === "uz" ? uz : lang === "en" ? en : ru);
  const bounds = calendarBounds(data);
  const [period, setPeriod] = React.useState(() => periodPreset(bounds, 30));
  const [draft, setDraft] = React.useState(period);
  const [periodError, setPeriodError] = React.useState(null);
  const [visibleMonth, setVisibleMonth] = React.useState(period.from.slice(0, 7));
  const flows = data.flows || [];
  if (!flows.length) {
    return (
      <div className="bondsec-empty">
        <b>{t("Будущих выплат не видно", "Kelgusi to'lovlar ko'rinmaydi", "No future payments visible")}</b>
        {t("Ни у одного выпуска нет одновременно ставки купона, цикла и обеих дат — без них график выплат не восстановить.",
           "Hech bir chiqarilishda kupon stavkasi, sikli va ikkala sana birga yo'q.",
           "No issue has a coupon rate, a cycle and both dates at once — without them no schedule can be built.")}
      </div>
    );
  }

  const short = MONTH_SHORT[lang] || MONTH_SHORT.ru;
  const full = MONTH_FULL[lang] || MONTH_FULL.ru;
  const today = new Date(`${bounds.from}T00:00:00Z`);
  const selected = paymentPeriod(data, period);
  const { months, flows: soon } = selected;
  const periodLabel = `${fmtBondDay(period.from)} — ${fmtBondDay(period.to)}`;
  const applyPeriod = (next) => {
    const error = validatePeriod(next, bounds);
    setPeriodError(error);
    if (error) return;
    setPeriod(next);
    setDraft(next);
    setVisibleMonth(next.from.slice(0, 7));
  };
  const errorText = periodError === "order"
    ? t("Дата окончания должна быть не раньше даты начала.", "Tugash sanasi boshlanish sanasidan oldin bo'lmasligi kerak.", "The end date must be on or after the start date.")
    : periodError === "bounds"
      ? t("Выберите даты в доступном периоде.", "Mavjud davrdagi sanalarni tanlang.", "Choose dates within the available period.")
      : t("Укажите обе даты.", "Ikkala sanani kiriting.", "Enter both dates.");

  // ---- the monthly bar chart -----------------------------------------------
  const W = Math.max(1060, months.length * 70); const H = 300; const L = 74; const R = 18; const T = 22; const B = 46;
  const pw = W - L - R; const ph = H - T - B;
  const peak = Math.max(...months.map((m) => (m.coupon || 0) + (m.principal || 0)), 1);
  const step = Math.pow(10, Math.floor(Math.log10(peak)));
  const top = Math.ceil((peak * 1.1) / step) * step;
  const ticks = 4;
  const band = pw / Math.max(months.length, 1);
  const bw = Math.min(26, band * 0.55);

  // ---- one selected month, navigable within the applied period --------------
  const monthIndex = Math.max(0, months.findIndex((month) => month.key === visibleMonth));
  const gridMonth = new Date(`${months[monthIndex].key}-01T00:00:00Z`);
  const gridYear = gridMonth.getUTCFullYear(); const gridIdx = gridMonth.getUTCMonth();
  const daysInMonth = new Date(Date.UTC(gridYear, gridIdx + 1, 0)).getUTCDate();
  const leading = (gridMonth.getUTCDay() + 6) % 7; // Monday-first
  const byDay = {};
  soon.forEach((f) => {
    if (Number(f.date.slice(0, 4)) !== gridYear || Number(f.date.slice(5, 7)) - 1 !== gridIdx) return;
    const day = Number(f.date.slice(8, 10));
    byDay[day] = byDay[day] || { total: 0, count: 0, items: [] };
    byDay[day].total += (f.coupon || 0) + (f.principal || 0);
    byDay[day].count += 1;
    byDay[day].items.push(f);
  });
  const dayPeak = Math.max(...Object.values(byDay).map((d) => d.total), 1);

  // ---- the selected period, grouped by day ---------------------------------
  const feedDays = [];
  soon.forEach((f) => {
    const last = feedDays[feedDays.length - 1];
    if (last && last.date === f.date) last.items.push(f);
    else feedDays.push({ date: f.date, items: [f] });
  });

  const money = (v) => fmtCompact(v, lang);
  const tile = (label, value, note) => (
    <div className="bondsec-tile" key={label}>
      <div className="bondsec-tile-k">{label}</div>
      <div className="bondsec-tile-v">{value}</div>
      <div className="bondsec-tile-d muted">{note}</div>
    </div>
  );

  return (
    <div className="bondsec-calendar">
      <form className="bondsec-period" noValidate onSubmit={(event) => { event.preventDefault(); applyPeriod(draft); }}>
        <div className="bondsec-period-heading">
          <strong>{t("Период выплат", "To'lovlar davri", "Payment period")}</strong>
          <span className="muted">{t("План доступен", "Reja mavjud", "Schedule available")}: {fmtBondDay(bounds.from)} — {fmtBondDay(bounds.to)}</span>
        </div>
        <div className="bondsec-period-presets" role="group" aria-label={t("Быстрый выбор периода", "Davrni tez tanlash", "Quick period selection")}>
          {[[30, t("30 дней", "30 kun", "30 days")], [90, t("90 дней", "90 kun", "90 days")], [365, t("1 год", "1 yil", "1 year")]].map(([days, label]) => {
            const preset = periodPreset(bounds, days);
            return <button key={days} type="button" className="ghost-btn"
              aria-pressed={period.from === preset.from && period.to === preset.to}
              onClick={() => applyPeriod(preset)}>{label}</button>;
          })}
        </div>
        <div className="bondsec-period-dates">
          <label>{t("С", "Boshlanish", "From")}
            <input type="date" required value={draft.from} min={bounds.from} max={bounds.to}
              aria-invalid={!!periodError} aria-describedby={periodError ? "bond-period-error" : undefined}
              onChange={(event) => { setDraft({ ...draft, from: event.target.value }); setPeriodError(null); }} />
          </label>
          <label>{t("По", "Tugash", "To")}
            <input type="date" required value={draft.to} min={draft.from || bounds.from} max={bounds.to}
              aria-invalid={!!periodError} aria-describedby={periodError ? "bond-period-error" : undefined}
              onChange={(event) => { setDraft({ ...draft, to: event.target.value }); setPeriodError(null); }} />
          </label>
          <button type="submit" className="ghost-btn">{t("Показать", "Ko'rsatish", "Show")}</button>
        </div>
        {periodError && <p id="bond-period-error" className="bondsec-period-error" role="alert">{errorText}</p>}
      </form>
      <div className="bondsec-tiles">
        {tile(t("Первая выплата в периоде", "Davrdagi birinchi to'lov", "First payment in period"),
              fmtBondDay(selected.next?.date),
              selected.next ? `${selected.next.ticker} · ${money((selected.next.coupon || 0) + (selected.next.principal || 0))}` : "—")}
        {tile(t("Выплат за период", "Davrdagi to'lovlar", "Payments in period"),
              soon.length,
              `${money(selected.coupon)} ${t("купонами", "kupon bilan", "in coupons")}`)}
        {tile(t("Погашения за период", "Davrdagi so'ndirishlar", "Redemptions in period"),
              money(selected.principal),
              t("возврат номинала", "nominal qaytarish", "principal returned"))}
        {tile(t("Купонный поток за период", "Davrdagi kupon oqimi", "Coupon flow in period"),
              money(selected.coupon),
              `${selected.issues} ${t("выпусков", "chiqarilish", "issues")}`)}
      </div>

      <h3 className="bondsec-h3">{t("Денежный поток рынка по месяцам", "Bozorning oylik pul oqimi", "The market's monthly cash flow")}</h3>
      <div className="bondsec-legend muted">
        <span><i className="bondsec-sq bondsec-sq-coupon" />{t("Купоны", "Kuponlar", "Coupons")}</span>
        <span><i className="bondsec-sq bondsec-sq-principal" />{t("Погашение номинала", "Nominalni so'ndirish", "Principal")}</span>
      </div>
      <div className="bondsec-month-chart-scroll">
        <svg className="bondsec-chart" style={{ minWidth: months.length > 12 ? months.length * 50 : undefined }} viewBox={`0 0 ${W} ${H}`} role="img"
             aria-label={t("Выплаты по месяцам", "Oylar bo'yicha to'lovlar", "Payments by month")}>
          {Array.from({ length: ticks + 1 }, (_, i) => {
            const v = (top * i) / ticks; const y = T + ph - (ph * i) / ticks;
            return (
              <g key={i}>
                <line x1={L} x2={W - R} y1={y} y2={y} className="bondsec-grid" />
                <text x={L - 8} y={y + 4} textAnchor="end" className="bondsec-tick">{fmtCompact(v, lang)}</text>
              </g>
            );
          })}
          <line x1={L} x2={W - R} y1={T + ph} y2={T + ph} className="bondsec-axis" />
          {months.map((m, i) => {
            const cx = L + band * (i + 0.5);
            const hC = (ph * (m.coupon || 0)) / top;
            const hP = (ph * (m.principal || 0)) / top;
            return (
              <g key={`${m.year}-${m.month}`}>
                {hP > 0 && <rect x={cx - bw / 2} y={T + ph - hC - hP} width={bw} height={Math.max(hP - 1, 0)} className="bondsec-bar-principal" rx="2" />}
                <rect x={cx - bw / 2} y={T + ph - hC} width={bw} height={hC} className="bondsec-bar-coupon" rx={hP > 0 ? 0 : 2} />
                <text x={cx} y={T + ph + 17} textAnchor="middle" className="bondsec-tick">
                  {short[m.month - 1]}{(m.month === 1 || i === 0) ? ` ${String(m.year).slice(2)}` : ""}
                </text>
                <rect x={cx - band / 2} y={T} width={band} height={ph} fill="transparent">
                  <title>
                    {`${full[m.month - 1]} ${m.year}\n`}
                    {`${t("Купоны", "Kuponlar", "Coupons")}: ${money(m.coupon)}\n`}
                    {`${t("Погашения", "So'ndirish", "Redemptions")}: ${money(m.principal)}\n`}
                    {`${t("Выпусков платит", "Chiqarilish to'laydi", "Issues paying")}: ${m.issues}`}
                  </title>
                </rect>
              </g>
            );
          })}
        </svg>
      </div>

      <div className="bondsec-calendar-cols">
        <div className="bondsec-calendar-feed">
          <h3 className="bondsec-h3">{t("Выплаты за период", "Davrdagi to'lovlar", "Payments in period")}</h3>
          <p className="muted bondsec-sub" aria-live="polite">
            {periodLabel} · {soon.length} {t("выплат", "to'lov", "payments")} · {money(selected.coupon)} {t("купонами", "kupon bilan", "in coupons")}
          </p>
          <div className="bondsec-days" key={`${period.from}-${period.to}`}>
            {feedDays.map((day) => {
              const total = day.items.reduce((s, f) => s + (f.coupon || 0) + (f.principal || 0), 0);
              const inDays = roundedDisplayValue((new Date(day.date) - today) / 864e5);
              return (
                <div className="bondsec-day" key={day.date}>
                  <div className="bondsec-day-when">
                    <b>{fmtBondDay(day.date)}</b>
                    <span className="muted">{t("через", "keyin", "in")} {inDays} {t("дн.", "kun", "d")} · {money(total)}</span>
                  </div>
                  <div className="bondsec-day-items">
                    {day.items.map((f, i) => (
                      <button type="button" className="bondsec-pay" key={`${f.ticker}-${i}`}
                              onClick={() => onOpenBond && onOpenBond(f.ticker)}>
                        <span className="bondsec-pay-tk">{f.ticker}</span>
                        {f.principal ? <span className="bondsec-pill-red">{t("погашение", "so'ndirish", "redemption")}</span> : null}
                        <span className="bondsec-pay-amt">
                          {f.coupon ? money(f.coupon) : "—"}
                          {f.principal ? ` + ${money(f.principal)}` : ""}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
            {!feedDays.length && <p className="muted">{t("В выбранном периоде выплат нет.", "Tanlangan davrda to'lov yo'q.", "No payments in the selected period.")}</p>}
          </div>
        </div>

        <div className="bondsec-calendar-grid">
          <div className="bondsec-month-nav">
            <button type="button" className="ghost-btn" disabled={monthIndex === 0}
              aria-label={t("Предыдущий месяц", "Oldingi oy", "Previous month")}
              onClick={() => setVisibleMonth(months[monthIndex - 1].key)}>‹</button>
            <select aria-label={t("Месяц календаря", "Taqvim oyi", "Calendar month")} value={months[monthIndex].key}
              onChange={(event) => setVisibleMonth(event.target.value)}>
              {months.map((month) => <option key={month.key} value={month.key}>{full[month.month - 1]} {month.year}</option>)}
            </select>
            <button type="button" className="ghost-btn" disabled={monthIndex === months.length - 1}
              aria-label={t("Следующий месяц", "Keyingi oy", "Next month")}
              onClick={() => setVisibleMonth(months[monthIndex + 1].key)}>›</button>
          </div>
          <p className="muted bondsec-sub">{t("Насыщенность клетки — размер выплат дня", "Katak to'yinganligi — kun to'lovlari hajmi", "Cell intensity is the size of the day's payments")}</p>
          <div className="bondsec-dow">
            {(lang === "en" ? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] : lang === "uz" ? ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"] : ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]).map((d) => (
              <span key={d}>{d}</span>
            ))}
          </div>
          <div className="bondsec-cells">
            {Array.from({ length: leading }, (_, i) => <span key={`pad${i}`} />)}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const day = i + 1; const cell = byDay[day];
              const date = `${months[monthIndex].key}-${String(day).padStart(2, "0")}`;
              const outside = date < period.from || date > period.to;
              const share = cell ? cell.total / dayPeak : 0;
              const level = !cell ? 0 : share > 0.66 ? 4 : share > 0.33 ? 3 : share > 0.1 ? 2 : 1;
              const tip = !cell ? "" : [
                `${day} ${full[gridIdx]} · ${money(cell.total)} · ${cell.count} ${t("выпусков", "chiqarilish", "issues")}`,
                ...cell.items.map((f) => {
                  const parts = [];
                  if (f.coupon) parts.push(`${t("купон", "kupon", "coupon")} ${money(f.coupon)}`);
                  if (f.principal) parts.push(`${t("погашение", "so'ndirish", "redemption")} ${money(f.principal)}`);
                  return `${f.ticker}${f.issuer ? ` — ${f.issuer}` : ""}: ${parts.join(" + ")}`;
                }),
              ].join("\n");
              return (
                <span key={day} className={`bondsec-cell level-${level}${outside ? " outside-period" : ""}`} title={tip} data-date={date}>
                  <i className="bondsec-cell-n">{day}</i>
                  {cell && (
                    <span className="bondsec-cell-tks">
                      {cell.items.slice(0, 2).map((f) => f.ticker).join(" ")}
                      {cell.items.length > 2 ? ` +${cell.items.length - 2}` : ""}
                    </span>
                  )}
                  {cell && <b className="bondsec-cell-v">{money(cell.total)}</b>}
                </span>
              );
            })}
          </div>
        </div>
      </div>

      <p className="muted bondsec-note">
        {t("Источник условий — реестр обращающихся выпусков РФБ «Тошкент». Реестр публикует ставку, цикл купона и даты размещения и погашения; сами даты платежей между ними раскладываются равномерно по циклу, поэтому это план, а не подтверждённые выплаты. Купон считается по размещённому количеству бумаг.",
           "Shartlar manbai — RFB «Toshkent» muomaladagi chiqarilishlar reestri. To'lov sanalari sikl bo'yicha teng taqsimlanadi.",
           "The terms come from the RFB Tashkent register of circulating issues. The register publishes the rate, the coupon cycle and the placement and redemption dates; the payment dates between them are laid evenly across the cycle, so this is a plan and not confirmed payments. A coupon is computed on the number of securities placed.")}
        {data.reconstructed ? ` ${t("Восстановлено", "Tiklandi", "Reconstructed")}: ${data.reconstructed} / ${flows.length}.` : ""}
      </p>
    </div>
  );
}


export default BondPaymentCalendar;
