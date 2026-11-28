import { useState } from 'react';
import { Field, Panel, Status, date, number } from './Widgets.jsx';
import { CmoChat } from './CmoChat.jsx';
import { StrategyDetail } from './StrategyDetail.jsx';
import { DraftVersionNotice, useVersionedDraft } from './VersionedEditor.jsx';

export function GoalSection({ data, busy, request, error, onHistory }) {
  const draft = useVersionedDraft(data.goal);
  const goal = draft.value;
  const [strategyId, setStrategyId] = useState(null);
  const selectedStrategy = data.strategies.find(item => item.id === strategyId);
  async function save(event) {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    const fields = { ...form, target: Number(form.target), budget: Number(form.budget),
      baseline: form.baseline === '' ? null : Number(form.baseline), audiences: form.audiences.split('\n').map(s => s.trim()).filter(Boolean) };
    if (await request('/goal', { method: 'PUT', body: { data: fields, expected_version: goal?.version || 0 }, message: 'Проект сохранён. Утверждение цели — отдельное решение.' })) draft.reset();
  }
  return <div className="mkt-columns">
    <Panel title="Цель владельца" action={goal && <button type="button" onClick={() => onHistory('goal', 'primary', 'История цели')}>История цели</button>}>
      {data.active_goal && <p className="mkt-callout">Действует версия {data.active_goal.version}</p>}
      <p className="mkt-muted">CMO может менять план в согласованных пределах. Цель, срок и общий бюджет утверждаете вы.</p>
      <DraftVersionNotice {...draft} />
      <form key={goal?.version || 0} onSubmit={save} onChangeCapture={draft.edit} className="mkt-form" aria-describedby="marketing-error">
        <Field label="Бизнес-цель" name="title" defaultValue={goal?.title || ''} required minLength={3} maxLength={200} />
        <div className="mkt-fields">
          <Field label="Метрика" name="metric" defaultValue={goal?.metric || ''} required />
          <Field label="Единица измерения" name="unit" defaultValue={goal?.unit || ''} required />
        </div>
        <Field label="Формула KPI" name="formula" defaultValue={goal?.formula || ''} required />
        <Field label="Источник KPI" name="source" defaultValue={goal?.source || ''} required />
        <div className="mkt-fields">
          <Field label="Исходная база" name="baseline" type="number" min="0" step="any" defaultValue={goal?.baseline ?? ''} help="Оставьте пустым, если ещё нужно замерить." />
          <Field label="Целевое значение" name="target" type="number" min="0.01" step="any" defaultValue={goal?.target || ''} required />
          <Field label="Начало периода" name="starts_on" type="date" defaultValue={goal?.starts_on || ''} required />
          <Field label="Срок достижения" name="deadline" type="date" defaultValue={goal?.deadline || ''} required />
          <Field label="Общий бюджет" name="budget" type="number" min="0" step="any" defaultValue={goal?.budget ?? 0} required />
          <Field label="Валюта"><select name="currency" defaultValue={goal?.currency || 'UZS'}><option>UZS</option><option>USD</option></select></Field>
        </div>
        <Field label="Аудитория · один сегмент в строке"><textarea name="audiences" defaultValue={(goal?.audiences || []).join('\n')} maxLength={3000} /></Field>
        <Field label="Доступные функции продукта"><textarea name="product_context" defaultValue={goal?.product_context || ''} maxLength={12000} /></Field>
        <Field label="Ресурсы и ограничения"><textarea name="limitations" defaultValue={goal?.limitations || ''} maxLength={6000} /></Field>
        <div className="mkt-actions"><button className="mkt-primary" disabled={busy}>Сохранить проект цели</button>{goal && <Status value={goal.status} />}</div>
      </form>
      {goal?.status === 'draft' && <div className="mkt-callout">
        <p>Утвердить: {number(goal.target)} {goal.unit}, срок {date(goal.deadline)}, лимит {number(goal.budget)} {goal.currency}.</p>
        <button type="button" disabled={busy || draft.edited} onClick={() => request('/goal/approve', { method: 'POST', body: { expected_version: goal.version }, message: 'Версия цели утверждена владельцем.' })}>Утвердить эту версию цели</button>
        {draft.edited && <p>Сначала сохраните правки цели.</p>}
      </div>}
    </Panel>
    <div className="mkt-stack"><CmoChat {...{ data, busy, request }} /><Panel title="Стратегия">
      {!data.strategies.length && <p className="mkt-muted">Согласованных стратегий пока нет. Сначала зафиксируйте цель и исходные данные.</p>}
      {data.strategies.map(strategy => <article className="mkt-item" key={strategy.id}><h4>{strategy.title}</h4><Status value={strategy.status} /><p>{strategy.positioning}</p><p>{strategy.measurement}</p>
        <button type="button" onClick={() => onHistory('strategy', strategy.id, 'Версии стратегии')}>Версии стратегии</button>
        <button type="button" onClick={() => setStrategyId(strategy.id)}>Открыть полный план</button>
      </article>)}
    </Panel><Panel title="Проверка выполнимости"><p>{goal?.baseline == null ? 'В цели исходная база не задана.' : `Владелец указал базу: ${number(goal.baseline)} ${goal.unit}.`}</p><p>Для числового сценария выберите в обсуждении зафиксированный отчёт с полным измеренным KPI за сопоставимый период. Без такой базы CMO готовит формулу и план измерений.</p><p className="mkt-muted">Бюджет — это предел. Он не считается расходом и не разрешает запуск рекламы.</p></Panel></div>
    {selectedStrategy && <StrategyDetail strategy={selectedStrategy} {...{ data, busy, request, error }} onClose={() => setStrategyId(null)} />}
  </div>;
}
