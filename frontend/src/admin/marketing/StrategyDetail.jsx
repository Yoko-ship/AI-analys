import { Dialog, Status, date, number } from './Widgets.jsx';
import { PlanList, ScenarioCards } from './ScenarioCards.jsx';
import { reasonText } from './reasonCopy.js';

const modes = { organic: 'Органический контент', paid_proposal: 'Предложение платного действия', research: 'Исследование', measurement: 'Измерение', operations: 'Рабочая задача' };

export function StrategyDetail({ strategy, data, busy, request, error, onClose }) {
  const role = id => id === 'owner' ? 'Владелец' : data.roles.find(item => item.id === id)?.name || id;
  const rubric = id => data.rubrics.find(item => item.id === id)?.name || id;
  const platform = id => id === 'internal' ? 'Внутренняя работа' : data.platforms.find(item => item.id === id)?.name || id;
  const assessment = strategy.assessment;
  const blocked = strategy.readiness?.status !== 'ready';
  async function approve() {
    const result = await request(`/strategies/${strategy.id}/approve`, { method: 'POST', body: { expected_version: strategy.version }, message: 'Полная стратегия утверждена. Платные действия требуют отдельного решения.' });
    if (result) onClose();
  }
  async function activate() {
    if (await request(`/strategies/${strategy.id}/work`, { method: 'POST', body: { expected_version: strategy.version }, message: 'Шаги добавлены в раздел «Рабочий цикл». Выберите исходные данные для заданий.' })) onClose();
  }
  return <Dialog title={strategy.title} onClose={onClose}><div className="mkt-plan">
    <div className="mkt-row"><Status value={strategy.status} /><span>Версия {strategy.version} · цель версии {strategy.goal_version}</span></div>
    {blocked && <div className="mkt-callout" role="status"><strong>План требует повторной подготовки</strong><p>{reasonText(strategy.readiness?.reason || 'Prepare a complete structured strategy before approval.')}</p></div>}
    <section><h4>Аудитория и позиционирование</h4><p>{strategy.positioning}</p><PlanList title="Сегменты" items={strategy.segments} />
      <p><strong>Каналы:</strong> {(strategy.channels || []).map(platform).join(', ')}</p>
      <p><strong>Рубрики:</strong> {(strategy.rubrics || []).map(rubric).join(', ')}</p>
    </section>
    <section><h4>Состав расходов и календарь</h4>
      {assessment && <div className="mkt-callout"><p>Всего по шагам: <strong>{number(assessment.planned_budget)} {assessment.currency}</strong></p>
        <p>Плановый предел на единицу цели: <strong>{number(assessment.budget_per_target)} {assessment.currency}</strong></p>
        <p>Общий бюджет цели / целевое значение. Это плановый ориентир, фактический CAC рассчитывается по подтверждённым расходам и клиентам.</p>
      </div>}
      <p className="mkt-muted">Утверждение стратегии не запускает рекламу. У каждого платного действия должны быть точные параметры и отдельное разрешение владельца.</p>
      <ol className="mkt-plan-steps">{(strategy.steps || []).map((step, i) => <li className="mkt-plan-card" key={step.id || i}>
        <h5>{step.action}</h5><p>{role(step.owner)} · {date(step.starts_on)} — {date(step.due)}</p>
        <p>{modes[step.mode] || step.mode} · {platform(step.channel)}{step.rubric && ` · ${rubric(step.rubric)}`}</p>
        <p><strong>Результат:</strong> {step.deliverable || 'Не указан'}</p>
        <p><strong>Предел расходов:</strong> {number(step.budget)} {assessment?.currency}</p>
        <p className="mkt-muted">{step.dependencies?.length ? `После: ${step.dependencies.map(id => strategy.steps.find(item => item.id === id)?.action || id).join('; ')}` : 'Без предварительных шагов'}</p>
      </li>)}</ol>
    </section>
    <section><h4>KPI и проверка результата</h4><p>{strategy.measurement}</p>
      {(strategy.kpis || []).map(kpi => <div className="mkt-plan-card" key={kpi.metric}><h5>{kpi.metric}</h5>
        <p><strong>Формула:</strong> {kpi.formula}</p><p><strong>Источник:</strong> {kpi.source}</p>
        <p><strong>Цель:</strong> {kpi.target == null ? 'Сначала измерить' : `${number(kpi.target)} ${kpi.unit}`}</p>
        <p>{role(kpi.owner)} · проверка {date(kpi.checkpoint)}</p>
      </div>)}
    </section>
    <section><h4>Условия трёх сценариев</h4><p className="mkt-muted">Сценарии — альтернативы. Их бюджеты не складываются. Коэффициенты отражают предположения команды.</p>
      <ScenarioCards scenarios={strategy.scenarios} assessment={assessment?.scenarios} currency={assessment?.currency} />
    </section>
    <section><h4>Границы решений CMO</h4><PlanList title="Допустимые изменения" items={strategy.allowed_changes} />
      <PlanList title="Предположения плана" items={strategy.assumptions} /><PlanList title="Риски плана" items={strategy.risks} />
      <p className="mkt-muted">Изменение цели, срока и общего бюджета требует вашего отдельного утверждения.</p>
    </section>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    {strategy.status === 'proposed' && <button type="button" className="mkt-primary" disabled={busy || blocked} onClick={approve}>Утвердить полную стратегию</button>}
    {strategy.status === 'approved' && ((data.plans || []).some(plan => plan.strategy_id === strategy.id && plan.strategy_version === strategy.version)
      ? <p>Шаги этой версии уже доступны в разделе «Рабочий цикл».</p>
      : <button type="button" className="mkt-primary" disabled={busy || blocked} onClick={activate}>Добавить шаги в рабочий цикл</button>)}
  </div></Dialog>;
}
