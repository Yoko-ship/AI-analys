import { useState } from 'react';
import { Field, Panel, Status, date, number } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';
import { ReportDecisions } from './ReportDecisions.jsx';
import { ReportExperiments } from './ReportExperiments.jsx';

export function ReportReview({ report, frozen, request, busy, refresh, roles }) {
  const [decisions, setDecisions] = useState(report.review.decisions);
  const [nextActions, setNextActions] = useState(report.review.next_actions);
  const [task, setTask] = useState(null);
  const period = { starts_on: report.period.starts_on, ends_on: report.period.ends_on };
  async function analyze() {
    const result = await request('/reports/analysis', { method: 'POST', body: period });
    if (result) setTask(result.item);
  }
  async function save(event) {
    event.preventDefault();
    const result = await request('/reports/review', { method: 'PUT', body: { period, data: { decisions, next_actions: nextActions }, expected_version: report.review.version } });
    if (result) await refresh();
  }
  const goal = report.goal;
  const analysis = report.analysis;
  return <>
    <Panel title="Цель и план-факт">{goal ? <><h4>{goal.title}</h4><p>Утверждённая цель v{goal.version} · {date(goal.starts_on)} — {date(goal.deadline)}</p><p>План: {number(report.plan_fact.target)} {goal.unit} · Факт за полный период: {report.plan_fact.actual == null ? 'Не сопоставляем' : number(report.plan_fact.actual)} · Отклонение: {report.plan_fact.difference == null ? 'Не рассчитывается' : number(report.plan_fact.difference)}</p>
      {report.plan_fact.observed != null && report.plan_fact.actual == null && <p>Наблюдаемое значение на дату среза: {number(report.plan_fact.observed)} {goal.unit}</p>}
      <p>{report.plan_fact.reason}</p><p>{report.strategy ? `Утверждённый план: ${report.strategy.title}, v${report.strategy.version}` : 'Нет утверждённого плана для этой версии цели.'}</p></> : <p>Цель ещё не утверждена. Результаты не сравниваются с вымышленным планом.</p>}</Panel>
    <Panel title="Работа команды"><div className="mkt-kpis">{[['created', 'Подготовлено'], ['checked', 'Проверено'], ['skipped', 'Пропущено'], ['published', 'Опубликовано'], ['failed', 'Сбоев доставки'], ['tasks_completed', 'Завершено задач']].map(([key, label]) => <div key={key}><span>{label}</span><strong>{number(report.team[key])}</strong></div>)}</div><p className="mkt-muted">Уникальные материалы и задачи по истории действий внутри периода. Это показатели работы, а не роста аудитории.</p>{report.team.skipped_items.map(item => <details key={item.id}><summary>{item.title} · пропущен · v{item.version}</summary><p>{reasonText(item.reason)}</p><button onClick={() => request(`/history/candidate/${item.id}`).then(result => { if (result) setTask({ history: result.items }); })}>Проверить историю пропуска</button></details>)}
      {task?.history && <ol>{task.history.map(({ record }) => <li key={record.version}>v{record.version} · <Status value={record.status} /> · {reasonText(record.check?.reason || '')}</li>)}</ol>}
    </Panel>
    <ReportExperiments value={report.experiment_results} />
    <section className="mkt-panel" aria-label="Выводы команды"><h3>Выводы команды</h3><p>Аналитик и CMO получают рассчитанные агрегаты. Выводы и предложения не меняют цель, срок или бюджет.</p>
      {analysis ? <><Status value={analysis.status} />{['analytics', 'cmo'].map(role => analysis[role] && <article className="mkt-item" key={role}><h4>{role === 'cmo' ? 'CMO' : 'Data / Web Analyst'}</h4><p>{analysis[role].summary}</p>{analysis[role].recommendations.length > 0 && <ul>{analysis[role].recommendations.map((text, index) => <li key={index}>{text}</li>)}</ul>}{analysis[role].risks.length > 0 && <p>Ограничения: {analysis[role].risks.join('; ')}</p>}</article>)}</> : <p>Выводов для этой базы расчёта пока нет.</p>}
      <ReportDecisions review={analysis?.cmo?.cmo_review} roles={roles} />
      {!frozen && <div className="mkt-actions"><button disabled={busy} onClick={analyze}>Запросить анализ CMO</button><button disabled={busy} onClick={refresh}>Обновить отчёт</button></div>}
      {task?.status && task.id !== analysis?.task_id && <p>Новый анализ: <Status value={task.status} /> · Результат появится после обработки. Обновите отчёт.</p>}
    </section>
    <Panel title="Решения и следующая неделя">{frozen ? <><p>{report.review.decisions || 'Решения не зафиксированы.'}</p><p>{report.review.next_actions || 'Следующие действия не заданы.'}</p></> : <form className="mkt-form" onSubmit={save}><Field label="Решения владельца"><textarea maxLength="6000" value={decisions} onChange={e => setDecisions(e.target.value)} /></Field><Field label="Следующие действия"><textarea maxLength="6000" value={nextActions} onChange={e => setNextActions(e.target.value)} /></Field><button disabled={busy}>Сохранить решения</button></form>}</Panel>
  </>;
}
