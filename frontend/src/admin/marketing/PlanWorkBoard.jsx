import { useState } from 'react';
import { Dialog, Field, Panel, Status, date } from './Widgets.jsx';
import { ProductionForm } from './ProductionForm.jsx';
import { reasonText } from './reasonCopy.js';
import { RenderJobs } from './MediaPanel.jsx';

function WorkBrief({ item, data, busy, request, onDone, prepare = false }) {
  const inputs = item.preparation?.inputs || {};
  async function submit(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const result = await request(`/plan-steps/${item.id}/${prepare ? 'prepare' : 'start'}`, { method: 'POST', body: { expected_version: item.version,
      data: { evidence_ids: form.getAll('evidence'), trend_ids: form.getAll('trend'), planning_snapshot_ids: form.getAll('snapshot') } },
      message: prepare ? 'Входные данные сохранены. Координатор начнёт шаг после его даты и принятых зависимостей.' : 'Задание связано с утверждённым шагом. Результат будет сохранён после проверки CMO.' });
    if (result) onDone();
  }
  if (item.step.mode === 'organic') return <ProductionForm data={{ ...data, accounts: data.accounts.filter(account => account.platform === item.step.channel) }}
    {...{ busy, request }} assignment={{ item, onDone, prepare }} />;
  return <form className="mkt-form" onSubmit={submit}>
    <p><strong>Ожидаемый результат:</strong> {item.step.deliverable}</p>
    {prepare && <p className="mkt-callout">Координатор начнёт работу в фоне, когда наступит дата шага и CMO примет предыдущие результаты. Внутренние брифы, исследования и отчёты могут пройти до трёх попыток по замечаниям CMO. Изменение выбранных данных остановит назначение до новой проверки.</p>}
    {item.step.mode === 'paid_proposal' && <p className="mkt-callout">Таргетолог готовит предложение. Создание кампании и расходы требуют отдельного решения в разделе «Эксперименты».</p>}
    {!!data.evidence.length && <fieldset><legend>Исходные материалы</legend><div className="mkt-checks">{data.evidence.map(value => <div key={value.id}><label><input type="checkbox" name="evidence" value={value.id} defaultChecked={inputs.evidence_ids?.includes(value.id)} />{value.title}</label> · <Status value={value.status} /></div>)}</div></fieldset>}
    {!!data.snapshots.length && <fieldset><legend>Измеренная база</legend><div className="mkt-checks">{data.snapshots.map(value => <label key={value.id}><input type="checkbox" name="snapshot" value={value.id} defaultChecked={inputs.planning_snapshot_ids?.includes(value.id)} />{value.name} · {date(value.report.period.starts_on)} — {date(value.report.period.ends_on)}</label>)}</div></fieldset>}
    {!!data.trends?.length && <fieldset><legend>Наблюдения тем</legend><div className="mkt-checks">{data.trends.map(value => <label key={value.id}><input type="checkbox" name="trend" value={value.id} defaultChecked={inputs.trend_ids?.includes(value.id)} />{value.theme}</label>)}</div></fieldset>}
    <p className="mkt-muted">Роль получит точный шаг плана и принятые результаты предыдущих задач. После замечаний CMO новая попытка сохранит прежнюю историю.</p>
    <button className="mkt-primary" disabled={busy}>{prepare ? 'Сохранить для автоматического старта' : 'Назначить задачу'}</button>
  </form>;
}

function OwnerWork({ item, busy, request, onDone }) {
  async function submit(event) {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget));
    if (await request(`/plan-steps/${item.id}/owner-result`, { method: 'POST', body: { expected_version: item.version, data: form }, message: 'Результат и основание записаны от имени владельца.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={submit}>
    <p>Запись фиксирует ваше подтверждение. Она не выполняет действие во внешнем сервисе.</p>
    <Field label="Что выполнено"><textarea name="summary" required minLength={20} maxLength={6000} /></Field>
    <Field label="Основание результата" name="reference" required minLength={10} maxLength={2000} help="Укажите исходный документ, запись или другой проверяемый результат." />
    <button className="mkt-primary" disabled={busy}>Сохранить результат</button>
  </form>;
}

export function PlanWorkBoard({ data, busy, request, error, onHistory, onInspectTask, onInspectVariants }) {
  const [selected, setSelected] = useState(null);
  const close = () => setSelected(null);
  const item = selected?.item;
  return <><Panel title="Рабочие планы">
    {!data.plans?.length && <p className="mkt-muted">Откройте утверждённую стратегию и добавьте её шаги в рабочий цикл.</p>}
    {(data.plans || []).map(plan => <section className="mkt-plan" key={plan.id}>
      <div className="mkt-row mkt-between"><h4>{plan.title}</h4><Status value={plan.status} /></div>
      <p className="mkt-muted">Стратегия версии {plan.strategy_version} · цель версии {plan.goal_version}. Просрочка не означает выполнение. Новый шаг использует принятые результаты зависимостей.</p>
      <div className="mkt-actions">{plan.replaced_by ? <span>Заменён новой утверждённой версией</span> : <button disabled={busy} onClick={() => request(`/plans/${plan.id}/pause`, { method: 'POST', body: { expected_version: plan.version, paused: plan.status !== 'paused' } })}>{plan.status === 'paused' ? 'Продолжить план' : 'Приостановить план'}</button>}
        <button onClick={() => onHistory('plan_run', plan.id, 'История рабочего плана')}>История плана</button></div>
      {plan.items.map(row => {
        const task = data.tasks.find(value => value.id === row.task_id);
        const variants = data.variants.filter(value => row.task_ids.includes(value.task_id));
        const hasPackage = row.step.mode === 'organic' && row.task_ids.some(id => data.tasks.find(value => value.id === id)?.candidate_ids?.length);
        const canStart = row.readiness.status === 'ready';
        const assignable = ['pending', 'needs_revision', 'blocked', 'cancelled'].includes(row.status) && row.attempts < 3;
        const prepared = row.automatic_assignment;
        return <article className="mkt-plan-card" aria-label={row.step.action} key={row.id}>
          <div className="mkt-row mkt-between"><h5>{row.step.action}</h5><Status value={row.status} /></div>
          <p>{row.step.owner === 'owner' ? 'Владелец' : data.roles.find(role => role.id === row.step.owner)?.name} · {date(row.step.starts_on)} — {date(row.step.due)}{row.overdue && <strong> · Просрочено</strong>}</p>
          <p><strong>Результат:</strong> {row.step.deliverable}</p>
          {!!row.dependencies.length && <p className="mkt-muted">После: {row.dependencies.map(id => plan.items.find(value => value.id === id)?.step.action || id).join('; ')}</p>}
          {row.owner_result ? <div className="mkt-callout"><strong>Подтверждение владельца</strong><p>{row.owner_result.summary}</p><p>{row.owner_result.reference}</p></div> : <p>{reasonText(row.reason)}</p>}
          {row.preparation && <details><summary>Сохранённые входные данные · {date(row.preparation.prepared_at)}</summary>
            {Object.entries(row.preparation.basis.evidence_versions).map(([id, version]) => <p key={id}>{data.evidence.find(value => value.id === id)?.title || id} · версия {version}</p>)}
            {Object.entries(row.preparation.basis.trend_versions).map(([id, version]) => <p key={id}>{data.trends.find(value => value.id === id)?.theme || id} · версия {version}</p>)}
            {row.preparation.basis.planning_snapshots.map(value => <p key={value.snapshot_id}>{value.name} · {value.eligible ? 'Измеренная база' : 'Без численного прогноза'}</p>)}
            {!Object.keys(row.preparation.basis.evidence_versions).length && <p>Оригиналы не выбраны. Утверждения потребуют проверяемого источника.</p>}
          </details>}
          {!canStart && <p className="mkt-callout">{reasonText(row.readiness.reason)}</p>}
          <div className="mkt-actions">
            {row.step.owner === 'owner' ? row.status === 'pending' && <button disabled={busy || !canStart} onClick={() => setSelected({ item: row })}>Записать результат владельца</button>
              : <>{assignable && !prepared && !hasPackage && <button disabled={busy || !canStart || data.pause.processing} onClick={() => setSelected({ item: row })}>Подготовить задание</button>}
                {(assignable || prepared) && !hasPackage && <button disabled={busy || plan.status !== 'active'} onClick={() => setSelected({ item: row, prepare: true })}>{prepared ? 'Изменить подготовку' : 'Подготовить заранее'}</button>}</>}
            {prepared && <button disabled={busy} onClick={() => request(`/plan-steps/${row.id}/cancel-preparation`, { method: 'POST', body: { expected_version: row.version }, message: 'Автоматический старт отменён. Сохранённые данные доступны в истории.' })}>Отменить автоматический старт</button>}
            {hasPackage && row.can_review && <button disabled={busy || data.pause.processing} onClick={() => request(`/plan-steps/${row.id}/review-drafts`, { method: 'POST', body: { expected_version: row.version }, message: 'Текущие проверенные черновики переданы CMO. Новая публикация не создаётся.' })}>Передать текущие черновики CMO</button>}
            {task && <button onClick={() => onInspectTask(task)}>Результат задачи</button>}
            {!!variants.length && <button onClick={() => onInspectVariants(variants)}>Открыть варианты · {variants.length}</button>}
            {task && ['queued', 'running', 'waiting_assets'].includes(task.status) && <button disabled={busy} onClick={() => request(`/tasks/${task.id}/cancel`, { method: 'POST', body: { expected_version: task.version } })}>Отменить задание</button>}
            {task?.status === 'error' && task.attempts < 3 && <button disabled={busy || !canStart} onClick={() => request(`/tasks/${task.id}/retry`, { method: 'POST', body: { expected_version: task.version } })}>Повторить сохранённый шаг</button>}
            <button onClick={() => onHistory('plan_step', row.id, 'История шага')}>История шага</button>
          </div>
          {row.task_ids.length > 1 && <details><summary>Предыдущие задания и проверки</summary>{row.task_ids.filter(id => id !== row.task_id).map(id => {
            const prior = data.tasks.find(value => value.id === id);
            return prior && <p key={id}><button onClick={() => onInspectTask(prior)}>{prior.title}</button> · <Status value={prior.status} /></p>;
          })}</details>}
          <RenderJobs jobs={data.renders.filter(job => row.task_ids.includes(job.task_id))} {...{ request, busy, onHistory }} />
        </article>;
      })}
    </section>)}
  </Panel>{item && <Dialog title={item.step.action} onClose={close}>{error && <p role="alert" className="mkt-error">{error}</p>}{item.step.owner === 'owner'
    ? <OwnerWork {...{ item, busy, request }} onDone={close} /> : <WorkBrief {...{ item, data, busy, request }} prepare={selected.prepare} onDone={close} />}</Dialog>}</>;
}
