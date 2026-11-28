import { useState } from 'react';
import { Dialog, Panel, SafeLink, Status, date } from './Widgets.jsx';
import { ProductionForm } from './ProductionForm.jsx';
import { reasonText } from './reasonCopy.js';
import { MediaFiles, RenderJobs } from './MediaPanel.jsx';
import { ResearchForm, ResearchReferences } from './ResearchReferences.jsx';
import { CompetitorCards } from './CompetitorCards.jsx';
import { PlanWorkBoard } from './PlanWorkBoard.jsx';
import { EditorialRules } from './EditorialRules.jsx';
import { OccasionSummary } from './OccasionField.jsx';

const labelFor = (data, id) => data.roles.find(role => role.id === id)?.name || id;

function TaskHandoffs({ task, data }) {
  return <div className="mkt-stack"><p>{task.message}</p>
    <OccasionSummary value={task.production?.occasion} evidence={task.evidence || []} />
    {!!task.trend_context?.length && <div><strong>Наблюдения в задаче</strong>{task.trend_context.map(item => <p key={item.id}>{item.theme} · версия {item.version} · {date(item.starts_on)}–{date(item.ends_on)} · упоминания {item.baseline.mentions} → {item.current.mentions}</p>)}</div>}
    <ol className="mkt-history">{task.outputs.map((entry, index) => <li key={index}>
      <div className="mkt-row"><strong>{labelFor(data, entry.role)}</strong><Status value={entry.result.verdict} /></div>
      <p>{entry.result.summary}</p>
      {!!entry.result.questions.length && <ul>{entry.result.questions.map((text, i) => <li key={i}>{text}</li>)}</ul>}
      {!!entry.result.risks.length && <p className="mkt-callout">{entry.result.risks.join(' · ')}</p>}
      <p><strong>Передача:</strong> {entry.result.handoff}</p>
      <ResearchReferences cards={entry.result.reference_cards} />
      <CompetitorCards cards={entry.result.competitor_cards} />
      <small>Версии оригиналов: {Object.entries(entry.evidence_versions).map(([id, version]) => `${id} · v${version}`).join('; ') || 'Не выбраны'}</small>
    </li>)}</ol>
    {!task.outputs.length && <p>Завершённых шагов пока нет. Входные данные сохранены.</p>}
  </div>;
}

function DraftVariants({ variants, data, request, busy, error, onDone, readFile, downloadFile }) {
  async function select(variant, candidate) {
    if (await request(`/drafts/${variant.id}/select`, { method: 'POST', body: { expected_version: candidate.version }, message: 'Языковой вариант выбран. Прежнее разрешение отменено; результат новой проверки сохранён.' })) onDone();
  }
  return <div className="mkt-stack">
    <p>Варианты одного события сохраняются вместе. Выбор языка заменяет версию в том же материале; новая публикация не создаётся.</p>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    {variants.map(variant => {
      const candidate = data.candidates.find(item => item.origin_task === variant.task_id && item.account_id === variant.account_id);
      const chosen = candidate?.language === variant.language && candidate.body === variant.body;
      const editable = candidate && candidate.mode !== 'automatic' && !['skipped', 'published', 'submitted', 'cancelled', 'sending', 'unknown'].includes(candidate.status);
      return <article key={variant.id} className="mkt-item"><div className="mkt-row mkt-between"><h4>{variant.title}</h4><Status value={variant.status} /></div>
        <p className="mkt-muted">{data.accounts.find(a => a.id === variant.account_id)?.label || variant.account_id} · {variant.language.toUpperCase()}</p>
        <div className="mkt-post-preview"><p>{variant.body}</p><SafeLink href={variant.destination_url} uzstock>Материал на UZStock ↗</SafeLink></div>
        {!!variant.assets?.length && <MediaFiles item={variant} data={data} readFile={readFile} downloadFile={downloadFile} busy={busy} />}
        {variant.review && <p>{variant.review.verdict === 'accept' ? 'Редактор рассмотрел эту версию.' : 'Редактор отклонил эту версию.'} {variant.review.reason}</p>}
        {chosen ? <p><strong>Выбрана для материала</strong> · <Status value={candidate.status} /></p> : editable && variant.review?.verdict === 'accept' && <button disabled={busy} onClick={() => select(variant, candidate)}>Выбрать эту версию</button>}
      </article>;
    })}
  </div>;
}

export function WorkflowSection({ data, request, busy, error, onHistory, readFile, downloadFile }) {
  const [dialog, setDialog] = useState(null);
  const close = () => setDialog(null);
  const tasks = data.tasks.filter(task => !task.plan && !['dialogue', 'strategy'].includes(task.kind));
  return <div className="mkt-stack">
    <PlanWorkBoard {...{ data, request, busy, error, onHistory }} onInspectTask={task => setDialog({ kind: 'handoffs', title: 'Передачи между ролями', task })}
      onInspectVariants={variants => setDialog({ kind: 'variants', title: 'Версии для площадок', variants })} />
    <EditorialRules {...{ data, request, busy, error, onHistory }} onInspectTask={task => setDialog({ kind: 'handoffs', title: 'Передачи между ролями', task })} />
    <Panel title="Новое задание команде"><ProductionForm data={data} request={request} busy={busy} /></Panel>
    <Panel title="Исследование"><ResearchForm data={data} request={request} busy={busy} /></Panel>
    <Panel title="Задачи и передача работы" action={<button disabled={busy} onClick={() => request('/workspace')}>Обновить рабочий цикл</button>}>
      <p className="mkt-muted">Роли получают сохранённые результаты предыдущих шагов. Финальная проверка и правила аккаунта определяют дальнейший выпуск.</p>
      {!tasks.length && <p>Задач пока нет.</p>}
      {tasks.map(task => {
        const variants = data.variants.filter(variant => variant.task_id === task.id);
        return <article key={task.id} className="mkt-item">
          <div className="mkt-row mkt-between"><h4>{task.title}</h4><Status value={task.status} /></div>
          <ol className="mkt-flow" aria-label="Этапы задачи">{task.steps.map((role, i) => <li key={`${role}-${i}`} aria-current={i === task.step && ['queued', 'running'].includes(task.status) ? 'step' : undefined}><span>{i + 1}</span>{labelFor(data, role)}{i < task.step ? ' ✓' : ''}</li>)}</ol>
          <p>{reasonText(task.reason)}</p>
          {!!task.candidate_ids?.length && <p>Материалов в рабочем пространстве: {task.candidate_ids.length}. Их проверки, разрешения и статусы показаны в разделе «Контент и очередь».</p>}
          {!!task.experiment_ids?.length && <p>Предложений платных экспериментов: {task.experiment_ids.length}. Параметры и отдельные решения доступны в разделе «Эксперименты».</p>}
          <div className="mkt-actions">
            <button onClick={() => setDialog({ kind: 'handoffs', title: 'Передачи между ролями', task })}>Результаты ролей</button>
            {!!variants.length && <button onClick={() => setDialog({ kind: 'variants', title: 'Версии для площадок', variants })}>Открыть варианты · {variants.length}</button>}
            {['queued', 'running', 'waiting_assets'].includes(task.status) && <button disabled={busy} onClick={() => request(`/tasks/${task.id}/cancel`, { method: 'POST', body: { expected_version: task.version } })}>Отменить задачу</button>}
            {task.status === 'error' && task.attempts < 3 && <button disabled={busy} onClick={() => request(`/tasks/${task.id}/retry`, { method: 'POST', body: { expected_version: task.version } })}>Повторить сохранённый шаг</button>}
            <button onClick={() => onHistory('task', task.id, 'История задачи')}>История задачи</button>
          </div>
          <RenderJobs jobs={data.renders.filter(job => job.task_id === task.id)} request={request} busy={busy} onHistory={onHistory} />
        </article>;
      })}
    </Panel>
    {dialog && <Dialog title={dialog.title} onClose={close}>{dialog.kind === 'handoffs' ? <TaskHandoffs task={data.tasks.find(task => task.id === dialog.task.id) || dialog.task} data={data} /> : <DraftVariants variants={dialog.variants.map(saved => data.variants.find(variant => variant.id === saved.id) || saved)} data={data} request={request} busy={busy} error={error} onDone={close} readFile={readFile} downloadFile={downloadFile} />}</Dialog>}
  </div>;
}
