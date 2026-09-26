import { Icon } from "./icons.jsx";
import { fmtInt, fmtShare, fmtStamp, fmtDay, SEVERITY_TONE } from "./adminModel.js";
export function Stat({
  label,
  value,
  warn,
  badge,
  badgeIcon,
  line1,
  line2
}) {
  return <div className="panel admin-stat">
      <div className="admin-stat-top">
        <span className="admin-stat-label">{label}</span>
        {badge ? <span className="admin-stat-badge">
            {badgeIcon ? <Icon name={badgeIcon} /> : null}{badge}
          </span> : null}
      </div>
      <div className={`admin-stat-value${warn ? " warn" : ""}`}>{value}</div>
      {line1 ? <div className="admin-stat-l1">{line1}</div> : null}
      {line2 ? <div className="admin-stat-l2">{line2}</div> : null}
    </div>;
}
export function deltaBadge(now, prev) {
  if (now === null || now === undefined || !prev) return null;
  const change = (now - prev) / prev;
  const text = `${change >= 0 ? "+" : ""}${(change * 100).toFixed(Math.abs(change) < 0.1 ? 1 : 0)}%`;
  return {
    text,
    icon: change >= 0 ? "up" : "down"
  };
}
export function Severity({
  value,
  t
}) {
  const label = value === "blocking" ? t("Блокирующая", "Bloklovchi", "Blocking") : value === "warning" ? t("Предупреждение", "Ogohlantirish", "Warning") : t("Информация", "Ma'lumot", "Info");
  return <span className="admin-pill">
      <span className={`admin-dot ${SEVERITY_TONE[value] || ""}`} />{label}
    </span>;
}
export function RunHistory({
  runs,
  t
}) {
  const peak = Math.max(1, ...runs.map(r => Number(r.blocking) || 0));
  return <div className="admin-bars">
      {runs.map((run, index) => {
      const value = Number(run.blocking) || 0;
      const last = index === runs.length - 1;
      const label = fmtStamp(run.finished_at || run.started_at, {
        withTime: false
      }).slice(0, 5);
      const cls = ["bar", last ? "now" : "", run.status === "failed" ? "failed" : ""].filter(Boolean).join(" ");
      return <div key={run.id || index} className={cls} style={{
        height: `${Math.max(4, (value / peak * 100))}%`
      }} title={`${label} · ${value} ${t("блокирующих", "bloklovchi", "blocking")}`}>
            {last || index === 0 || index === Math.floor(runs.length / 2) ? <span>{label}</span> : null}
          </div>;
    })}
    </div>;
}
export function DailyBars({
  data,
  valueKey,
  titleFn
}) {
  const rows = data || [];
  if (!rows.length) return null;
  const peak = Math.max(1, ...rows.map(r => Number(r[valueKey]) || 0));
  const step = Math.max(1, Math.ceil(rows.length / 7));
  return <div className="admin-bars">
      {rows.map((row, index) => {
      const value = Number(row[valueKey]) || 0;
      const last = index === rows.length - 1;
      return <div key={row.day || index} className={`bar${last ? " now" : ""}`} style={{
        height: `${Math.max(3, (value / peak * 100))}%`
      }} title={titleFn ? titleFn(row) : `${fmtDay(row.day)} · ${fmtInt(value)}`}>
            {last || index % step === 0 ? <span>{fmtDay(row.day)}</span> : null}
          </div>;
    })}
    </div>;
}
export function HBarList({
  rows,
  nameFn,
  valueFn,
  detailFn,
  onClickRow
}) {
  const items = rows || [];
  if (!items.length) return null;
  const peak = Math.max(1, ...items.map(r => Number(valueFn(r)) || 0));
  return <div className="admin-hbars">
      {items.map((row, index) => {
      const value = Number(valueFn(row)) || 0;
      const name = nameFn(row);
      return <div key={`${name}-${index}`} className="admin-hbar">
            <span className="admin-hbar-name">
              {onClickRow ? <button type="button" className="admin-link" onClick={() => onClickRow(row)}>{name}</button> : name}
              {detailFn ? <span className="admin-hbar-detail">{detailFn(row)}</span> : null}
            </span>
            <span className="admin-hbar-track">
              <span className="admin-hbar-fill" style={{
            width: `${Math.max(2, value / peak * 100)}%`
          }} />
            </span>
            <span className="admin-hbar-val">{fmtInt(value)}</span>
          </div>;
    })}
    </div>;
}
export function Funnel({
  steps,
  labels
}) {
  const rows = steps || [];
  const first = rows.length ? Number(rows[0].count) : 0;
  return <div className="admin-funnel">
      {rows.map((step, index) => {
      const value = step.count === null || step.count === undefined ? null : Number(step.count);
      const width = first && value !== null ? Math.max(2, value / first * 100) : 2;
      const prev = index > 0 ? rows[index - 1].count : null;
      const share = prev && value !== null && Number(prev) > 0 ? value / Number(prev) : null;
      return <div key={step.key} className="admin-funnel-step">
            <span className="admin-funnel-label">{labels[step.key] || step.key}</span>
            <span className="admin-funnel-track">
              <span className="admin-funnel-fill" style={{
            width: `${width}%`
          }} />
            </span>
            <span className="admin-funnel-val">
              {fmtInt(value)}
              {share !== null && index > 0 ? <em>{fmtShare(share)}</em> : null}
            </span>
          </div>;
    })}
    </div>;
}
export function RangePicker({
  value,
  onChange,
  t
}) {
  return <div className="admin-seg">
      {[7, 30, 90].map(days => <button key={days} type="button" aria-selected={value === days} onClick={() => onChange(days)}>
          {t(`${days} дней`, `${days} kun`, `${days} days`)}
        </button>)}
    </div>;
}
export function Skeleton({
  rows = 3
}) {
  return <div style={{
    display: "flex",
    flexDirection: "column",
    gap: 14
  }}>
      {Array.from({
      length: rows
    }, (_, i) => <div key={i} className="admin-skel" style={{
      height: i === 0 ? 96 : 58
    }} />)}
    </div>;
}
export function NoTraffic({
  t
}) {
  return <div className="admin-empty">
      <b>{t("Записей о посещениях пока нет", "Tashriflar yozuvi hali yo'q", "No visit records yet")}</b>
      {t("Счётчик начал писать с этого развёртывания; цифры появятся, как только на сайт кто-то зайдёт.", "Hisoblagich shu joylashuvdan boshlab yozadi.", "The counter started writing with this deployment; numbers appear as soon as someone visits.")}
    </div>;
}
