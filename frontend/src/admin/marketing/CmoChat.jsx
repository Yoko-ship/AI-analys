import { useState } from 'react';
import { Field, Panel, Status, date } from './Widgets.jsx';
import { ScenarioCards } from './ScenarioCards.jsx';
import { reasonText } from './reasonCopy.js';

export function CmoChat({ data, request, busy }) {
  const conversations = data.tasks.filter(task => !task.plan && ['dialogue', 'strategy'].includes(task.kind));
  const [conversation, setConversation] = useState(conversations[0]?.conversation_id || null);
  const [message, setMessage] = useState('');
  const [kind, setKind] = useState('dialogue');
  const selected = conversation || conversations[0]?.conversation_id;
  const tasks = conversations.filter(task => task.conversation_id === selected).slice().reverse();
  async function send(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const evidence_ids = form.getAll('evidence'), planning_snapshot_ids = form.getAll('planning_snapshot');
    const result = await request('/tasks', { method: 'POST', body: { kind, message, evidence_ids, planning_snapshot_ids, conversation_id: selected || null }, message: 'Задача сохранена. Ответ появится после обработки моделью.' });
    if (result) { setConversation(result.item.conversation_id); setMessage(''); }
  }
  return <Panel title="Обсуждение с CMO" action={<button disabled={busy} onClick={() => request('/workspace')}>Обновить обсуждение</button>}>
    <div className="mkt-runtime"><strong>{data.model.provider === 'disabled' ? 'Модель не выбрана' : `${data.model.provider} · ${data.model.model || 'модель не задана'}`}</strong>
      <p className="mkt-muted">{data.worker ? `Последний завершённый цикл: ${date(data.worker.last_completed_at)}. Фоновая обработка не зависит от открытой вкладки.` : 'Ожидается запуск фонового сервиса. Задачи сохранятся при закрытии вкладки.'}</p>
      {!data.model.configured && <p>Требуется настройка модели или вход владельца. Подготовленные материалы сохраняются.</p>}
    </div>
    {!!conversations.length && <Field label="Обсуждение"><select value={selected || ''} onChange={e => setConversation(e.target.value)}>{conversations.filter((task, i, all) => all.findIndex(other => other.conversation_id === task.conversation_id) === i).map(task => <option key={task.conversation_id} value={task.conversation_id}>{task.title}</option>)}</select></Field>}
    <div className="mkt-conversation" aria-label="Сообщения команды">{tasks.map(task => <article key={task.id}>
      <div className="mkt-message mkt-message-owner"><strong>Вы</strong><p>{task.message}</p></div>
      {(task.outputs || []).map((output, index) => <div className="mkt-message" key={index}><strong>{data.roles.find(role => role.id === output.role)?.name || output.role}</strong><p>{output.result.summary}</p>
        {!!output.result.questions.length && <ul>{output.result.questions.map((question, i) => <li key={i}>{question}</li>)}</ul>}
        {!!output.result.risks.length && <div className="mkt-callout"><strong>Риски и ограничения</strong><ul>{output.result.risks.map((risk, i) => <li key={i}>{risk}</li>)}</ul></div>}
        {!!output.result.recommendations.length && <ul>{output.result.recommendations.map((recommendation, i) => <li key={i}>{recommendation}</li>)}</ul>}
        <ScenarioCards scenarios={output.result.feasibility} assessment={output.result.feasibility_assessment} currency={task.goal?.currency} />
      </div>)}
      <div className="mkt-row"><Status value={task.status} />{['queued', 'running'].includes(task.status) && <button disabled={busy} onClick={() => request(`/tasks/${task.id}/cancel`, { method: 'POST', body: { expected_version: task.version } })}>Отменить задачу</button>}
        {task.status === 'error' && task.attempts < 3 && <button disabled={busy} onClick={() => request(`/tasks/${task.id}/retry`, { method: 'POST', body: { expected_version: task.version } })}>Повторить с сохранённого шага</button>}</div>
      {['error', 'blocked'].includes(task.status) && <p className="mkt-error">{reasonText(task.reason)}</p>}
    </article>)}</div>
    {!tasks.length && <p className="mkt-muted">Опишите задачу, исходные данные и ограничения. CMO использует текущую цель и выбранные материалы.</p>}
    <form className="mkt-form" onSubmit={send}>
      <Field label="Сообщение CMO"><textarea value={message} onChange={e => setMessage(e.target.value)} required maxLength={12000} /></Field>
      <Field label="Что подготовить"><select value={kind} onChange={e => setKind(e.target.value)}><option value="dialogue">Ответить и уточнить вводные</option><option value="strategy">Предложить полную стратегию</option></select></Field>
      {!!data.snapshots.length && <fieldset><legend>Измеренная база для сценариев · до 10 снимков</legend><p className="mkt-muted">Команда проверит KPI, полноту, длительность периода и актуальность выбранной базы. Несопоставимые данные не дают числовой оценки.</p><div className="mkt-checks">{data.snapshots.map(snapshot => <label key={snapshot.id}><input type="checkbox" name="planning_snapshot" value={snapshot.id} aria-label={`База планирования · ${snapshot.name}`} /><span>{snapshot.name} · {date(snapshot.report.period.starts_on)} — {date(snapshot.report.period.ends_on)}{snapshot.report.method.dataset === 'test' && ' · тестовые данные'}</span></label>)}</div></fieldset>}
      {!!data.evidence.length && <fieldset><legend>Материалы для обсуждения</legend><div className="mkt-checks">{data.evidence.map(source => <label key={source.id}><input type="checkbox" name="evidence" value={source.id} />{source.title} · <Status value={source.status} /></label>)}</div></fieldset>}
      <button className="mkt-primary" disabled={busy}>Отправить CMO</button>
    </form>
  </Panel>;
}
