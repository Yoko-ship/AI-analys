import { datasetNames, issueText, nextAction, runIssues, runSummary } from "./collection-messages.js";

export function CollectionExplanation({ run, t, expanded = false }) {
  const issues = runIssues(run);
  const action = nextAction(run, t);
  return <div className="collection-explanation">
    <p className="collection-reason">{runSummary(run, t)}</p>
    {!!issues.length && <ul className="collection-causes">{(expanded ? issues : issues.slice(0, 2)).map((issue, index) => <li key={index}>
      {issueText(issue, t)}
      {expanded && issue.datasets?.length > 1 && <span className="collection-cause-scope">{datasetNames(issue, t).join(", ")}</span>}
    </li>)}</ul>}
    {!expanded && issues.length > 2 && <p className="muted">{t(`Ещё причин: ${issues.length - 2}. Откройте подробности.`, `Yana ${issues.length - 2} ta sabab bor. Tafsilotlarni oching.`, `${issues.length - 2} more reasons. Open Details.`)}</p>}
    {run.diagnosis?.saved_datasets > 0 && <p>{t(`Обновлено разделов: ${run.diagnosis.saved_datasets}.`, `Yangilangan bo‘limlar: ${run.diagnosis.saved_datasets}.`, `Datasets saved: ${run.diagnosis.saved_datasets}.`)}</p>}
    {["failed", "partial"].includes(run.status) && <p className="collection-impact">{run.publication === "acknowledged" || run.publication === "partial"
      ? t("Часть данных сохранена. Полнота остальных обновлений не подтверждена.", "Ma’lumotlarning bir qismi saqlandi. Qolgan yangilanishlar to‘liqligi tasdiqlanmagan.", "Some data was saved. The remaining updates are not confirmed complete.")
      : t("Сохранение новых данных этим запуском не подтверждено.", "Bu ishga tushirishda yangi ma’lumotlar saqlangani tasdiqlanmadi.", "This run has no confirmed new data saved.")}</p>}
    {action && <p className="collection-next"><strong>{t("Что делать", "Nima qilish kerak", "What to do")}: </strong>{action}</p>}
    {expanded && run.diagnosis?.evidence_limited && <p className="muted">{t("Журнал сохранён не полностью: здесь могут быть не все причины.", "Jurnal to‘liq saqlanmagan: ayrim sabablar ko‘rinmasligi mumkin.", "Only part of the log was retained, so this may not include every cause.")}</p>}
  </div>;
}
