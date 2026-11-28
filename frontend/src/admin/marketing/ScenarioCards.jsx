import { date, number } from './Widgets.jsx';

const names = { conservative: 'Консервативный сценарий', base: 'Базовый сценарий', target: 'Целевой сценарий' };

export function PlanList({ title, items = [] }) {
  return <div><strong>{title}</strong>{items.length ? <ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className="mkt-muted">Не указано</p>}</div>;
}

export function ScenarioCards({ scenarios = [], assessment = [], currency }) {
  return <div className="mkt-scenarios">{scenarios.map(row => {
    const projection = assessment.find(item => item.kind === row.kind)?.projection;
    return <section className="mkt-plan-card" key={row.kind}>
      <h4>{names[row.kind] || row.kind}</h4>
      <p className="mkt-muted">Проверка {date(row.checkpoint)} · предел {number(row.budget)} {currency}</p>
      {projection ? <div className="mkt-callout">
        <strong>Условная оценка: {number(projection.value)} {projection.unit}</strong>
        <p>Измеренная база {number(projection.baseline)} × предполагаемый коэффициент {number(projection.factor)}. Это условие сценария, а не обещанный результат.</p>
        <p>{projection.assumption}</p>
        <p>Снимок: {projection.name} · версия {projection.snapshot_version}<br />Период: {date(projection.period.starts_on)} — {date(projection.period.ends_on)} (конец не включён).</p>
        <p>Источники: {projection.sources.join(', ') || 'Не указаны'}</p>
        {projection.dataset === 'test' && <strong>Тестовые данные · не подтверждают результат на рабочем сайте</strong>}
      </div> : <p className="mkt-callout"><strong>Числовая оценка не рассчитана</strong><br />Для расчёта нужна полная измеренная база с тем же KPI и длительностью периода.</p>}
      <PlanList title="Предположения" items={row.assumptions} />
      <PlanList title="Действия" items={row.actions} />
      <p><strong>Ресурсы:</strong> {row.resources}</p>
      <PlanList title="Ограничения" items={row.constraints} />
      <PlanList title="Риски" items={row.risks} />
      <p><strong>Формула:</strong> {row.formula}</p>
      <p><strong>План измерений:</strong> {row.measurement_plan}</p>
    </section>;
  })}</div>;
}
