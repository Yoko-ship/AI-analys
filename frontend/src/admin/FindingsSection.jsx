import { Icon } from "./icons.jsx";
import { fmtInt } from "./adminModel.js";
import { Skeleton } from "./AdminWidgets.jsx";
import { FindingsTable } from "./FindingsTable.jsx";
export function FindingsSection({
  filters,
  setFilters,
  t,
  openCounts,
  loading,
  findings,
  rules,
  selected,
  toggleSelected,
  acceptFindings,
  busy
}) {
  return <div className="admin-section">
      <div className="panel">
        <div className="admin-panel-bar">
          <div className="admin-seg">
            {["blocking", "warning", "info"].map(severity => <button key={severity} type="button" aria-selected={filters.severity === severity} onClick={() => setFilters(f => ({
            ...f,
            severity
          }))}>
                {severity === "blocking" ? t("Блокирующие", "Bloklovchi", "Blocking") : severity === "warning" ? t("Предупреждения", "Ogohlantirish", "Warnings") : t("Информация", "Ma'lumot", "Info")}
                <span className="n">{fmtInt(openCounts[severity])}</span>
              </button>)}
          </div>
          <span className="admin-sp" />
          <button type="button" className="admin-btn sm" onClick={() => setFilters(f => ({
          ...f,
          status: f.status ? "" : "new"
        }))}>
            {filters.status ? t("Показать разобранные", "Ko'rib chiqilganlarni ko'rsatish", "Include triaged") : t("Только открытые", "Faqat ochiq", "Open only")}
          </button>
        </div>
        {loading ? <Skeleton rows={4} /> : <>
            <FindingsTable items={findings} rules={rules} t={t} selected={selected} onToggle={toggleSelected} onAccept={acceptFindings} busy={busy} />
            <div className="admin-table-foot">
              <span>
                {t(`Показано ${findings.length}`, `${findings.length} ta ko'rsatildi`, `Showing ${findings.length}`)}
                {selected.size ? t(` · выбрано ${selected.size}`, ` · ${selected.size} tanlandi`, ` · ${selected.size} selected`) : ""}
              </span>
              <span className="admin-sp" />
              <button type="button" className="admin-btn sm" disabled={!selected.size || busy} onClick={() => acceptFindings([...selected])}>
                <Icon name="check" />
                {t("Принять выбранные", "Tanlanganlarni qabul qilish", "Accept selected")}
              </button>
            </div>
          </>}
      </div>
    </div>;
}
