import { Icon } from "./icons.jsx";
import { useCallback } from "react";
import { DASH, fmtStamp } from "./adminModel.js";
import { Severity } from "./AdminWidgets.jsx";
export function FindingsTable({
  items,
  rules,
  t,
  selected,
  onToggle,
  onAccept,
  busy
}) {
  const ruleTitle = useCallback(code => {
    const rule = rules.find(r => r.code === code);
    return rule ? rule.title : "";
  }, [rules]);
  if (!items.length) {
    return <div className="admin-empty">
        <b>{t("Ничего не ждёт решения", "Hech narsa kutmayapti", "Nothing is waiting")}</b>
        {t("Все открытые находки разобраны.", "Barcha topilmalar ko'rib chiqilgan.", "Every open finding has been dealt with.")}
      </div>;
  }
  return <div className="admin-scroll">
      <table>
        <thead>
          <tr>
            <th style={{
            width: 42
          }} />
            <th>{t("Правило", "Qoida", "Rule")}</th>
            <th style={{
            width: 156
          }}>{t("Уровень", "Daraja", "Severity")}</th>
            <th style={{
            width: 96
          }}>{t("Бумага", "Qog'oz", "Security")}</th>
            <th style={{
            width: 116
          }}>{t("Держится", "Ushlanib turibdi", "Seen")}</th>
            <th className="r" style={{
            width: 118
          }}>{t("Открыта", "Ochilgan", "Opened")}</th>
            <th style={{
            width: 46
          }} />
          </tr>
        </thead>
        <tbody>
          {items.map(item => {
          const checked = selected.has(item.id);
          return <tr key={item.id}>
                <td>
                  <button
                    type="button"
                    className="admin-check"
                    role="checkbox"
                    aria-checked={checked}
                    aria-label={t("Выбрать находку", "Topilmani tanlash", "Select finding")}
                    onClick={() => onToggle(item.id)}
                  />
                </td>
                <td>
                  <div className="admin-rule"><code>{item.rule_code}</code>{ruleTitle(item.rule_code)}</div>
                  {item.message ? <div className="admin-sub">{item.message}</div> : null}
                </td>
                <td><Severity value={item.severity} t={t} /></td>
                <td className="admin-num">{item.ticker || DASH}</td>
                <td className="admin-num">
                  {item.seen_count ? t(`${item.seen_count} прогон(ов)`, `${item.seen_count} marta`, `${item.seen_count} runs`) : DASH}
                </td>
                <td className="r admin-num">{fmtStamp(item.first_seen, {
                withTime: false
              })}</td>
                <td>
                  <button
                    type="button"
                    className="admin-row-act"
                    title={t("Принять как известное", "Ma'lum deb qabul qilish", "Accept as known")}
                    disabled={busy}
                    onClick={() => onAccept([item.id])}
                  >
                    <Icon name="check" />
                  </button>
                </td>
              </tr>;
        })}
        </tbody>
      </table>
    </div>;
}
