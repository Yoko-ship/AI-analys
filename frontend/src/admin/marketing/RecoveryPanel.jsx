import { useState } from 'react';
import { Dialog, Field, SafeLink, Status } from './Widgets.jsx';

const time = value => new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' });
const local = value => new Date(new Date(value).getTime() + 5 * 3600000).toISOString().slice(0, 23);

function RecoveryForm({ state, data, request, busy, error, onDone }) {
  const [stopped, setStopped] = useState(false);
  const [publications, setPublications] = useState([]);
  const [problem, setProblem] = useState('');
  const label = row => `${data.accounts.find(account => account.id === row.account_id)?.label || row.account_id} · ${row.platform} · ${row.external_id || 'получатель не задан'}`;
  async function submit(event) {
    event.preventDefault();
    setProblem('');
    const form = new FormData(event.currentTarget);
    const missing = publications.map(id => ({ ...state.accounts[Number(form.get(`${id}:account`))],
      event_id: form.get(`${id}:event`), publication_type: form.get(`${id}:type`),
      url: form.get(`${id}:url`), published_at: `${form.get(`${id}:at`)}+05:00` }));
    if (missing.some(row => !row.account_id)) { setProblem('Выберите проверенный аккаунт для каждой найденной публикации.'); return; }
    const body = { expected_version: state.version, basis_digest: state.basis_digest, old_worker_stopped: stopped,
      reviewed_through: `${form.get('through')}+05:00`, accounts: state.accounts.map((row, index) => ({ ...row, reference: form.get(`account:${index}`) })),
      missing_publications: missing, reason: form.get('reason') };
    if (await request('/recovery/complete', { method: 'POST', body,
      message: 'Сверка записана. Прежние неподтверждённые выпуски закрыты для повтора; паузы и подключения проверяются отдельно.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={submit}>
    <p>Проверьте историю каждого исходного получателя с <strong>{time(state.backup_created_at)}</strong> до указанного ниже момента. Время Ташкента. Учтите публикации, отправленные после копии, пока исходная система ещё работала.</p>
    <label className="mkt-checkbox"><input type="checkbox" checked={stopped} onChange={event => setStopped(event.target.checked)} required />Старый обработчик остановлен и больше не отправляет публикации</label>
    <Field label="История проверена по · Ташкент" name="through" type="datetime-local" step="0.001" required defaultValue={local(new Date().toISOString())} />
    {state.accounts.map((row, index) => <fieldset className="mkt-stack" key={`${row.account_id}:${row.platform}:${row.external_id}`}>
      <legend>{label(row)}</legend>
      <Field label={`Основание сверки аккаунта ${index + 1}`} help="Укажите проверенную историю, журнал или ссылки, результат сверки и все найденные пропуски.">
        <textarea name={`account:${index}`} minLength={20} maxLength={3000} rows={3} required />
      </Field>
    </fieldset>)}
    {!state.accounts.length && <p>В копии нет аккаунтов или получателей отправки.</p>}
    <div className="mkt-callout"><strong>Прежние версии, которые будут закрыты для повтора · {state.quarantine.length}</strong>
      <ul>{state.quarantine.map(item => <li key={item.id}>{item.title} · <Status value={item.status} /></li>)}</ul>
      <p>Их история останется доступна со статусом «Исход неясен». Повторная отправка этих версий будет закрыта. Для подтверждённого внешнего результата используйте сверку конкретной публикации.</p>
    </div>
    <p>Запишите публикации, найденные в промежутке после копии. Ключ события, аккаунт и тип будут зарезервированы от повтора. Запись сохраняет ваше основание проверки; подтверждение площадки учитывается отдельно.</p>
    {publications.map((id, index) => <fieldset className="mkt-stack" key={id}><legend>Найденная публикация {index + 1}</legend>
      <Field label="Аккаунт"><select name={`${id}:account`} required>{state.accounts.map((row, i) => <option key={i} value={i}>{label(row)}</option>)}</select></Field>
      <Field label="Ключ события" name={`${id}:event`} maxLength={200} required help="Используйте тот же ключ, что в исходном задании или подтверждённом событии. Это предотвращает повторный выпуск." />
      <Field label="Тип публикации"><select name={`${id}:type`}><option value="organic">Органическая</option><option value="paid">Платная</option></select></Field>
      <Field label="Ссылка на публикацию" name={`${id}:url`} type="url" required maxLength={2000} />
      <Field label="Опубликовано · Ташкент" name={`${id}:at`} type="datetime-local" step="0.001" required />
      <button type="button" onClick={() => setPublications(previous => previous.filter(value => value !== id))}>Убрать публикацию {index + 1}</button>
    </fieldset>)}
    <button type="button" disabled={!state.accounts.length || publications.length >= 500} onClick={() => setPublications(previous => [...previous, crypto.randomUUID()])}>Добавить найденную публикацию</button>
    <Field label="Итог сверки"><textarea name="reason" required minLength={20} maxLength={6000} rows={3} /></Field>
    <p>Завершение сверки сохраняет обе паузы и текущие настройки аккаунтов. Для новой работы отдельно проверьте подключения и разрешения, затем снимите нужную паузу.</p>
    {(problem || error) && <p className="mkt-error" role="alert">{problem || error}</p>}
    <button className="mkt-primary" disabled={busy || !stopped}>Завершить сверку и закрыть прежние выпуски</button>
  </form>;
}

export function RecoveryPanel({ data, request, busy, error, onHistory }) {
  const [reviewing, setReviewing] = useState(null);
  const state = data.recovery;
  if (!state) return null;
  const history = <button disabled={busy} onClick={() => onHistory('settings', 'recovery', 'История восстановления')}>История восстановления</button>;
  if (state.status === 'reconciled') return <section className="mkt-callout" aria-label="Восстановление очереди">
    <details><summary>Сверка восстановления завершена</summary><p>{time(state.reviewed_at)} · Ташкент. {state.reason}</p>
      <p>Прежние неопределённые выпуски остаются закрытыми для повтора. Подключения, разрешения и паузы управляются отдельно.</p>
      {state.review.missing_publications.map(row => <p key={`${row.event_id}:${row.account_id}:${row.publication_type}`}>{row.event_id} · {row.platform} · <SafeLink href={row.url}>Публикация из сверки ↗</SafeLink></p>)}
      {history}
    </details>
  </section>;
  return <section className="mkt-callout" aria-label="Восстановление очереди">
    <h3>Сверка после восстановления</h3>
    <p>Очередь восстановлена из копии от {time(state.backup_created_at)} · Ташкент. После этой даты исходная система могла отправить материалы.</p>
    <p>Снятие обычной паузы не разрешает отправку. Сначала проверьте публикации на площадках за период после копии. История и медиа доступны для проверки.</p>
    {!state.paused && <p>Перед сверкой остановите обработку и публикации.</p>}
    <div className="mkt-actions">{!state.paused && <button disabled={busy} onClick={() => request('/pause', { method: 'PUT', body: { publications: true, processing: true } })}>Остановить обработку и публикации</button>}
      <button disabled={busy || !state.paused} onClick={() => setReviewing(state)}>Проверить промежуток после копии</button>{history}
    </div>
    {reviewing && <Dialog title="Сверка промежутка после копии" onClose={() => setReviewing(null)}><RecoveryForm state={reviewing} {...{ data, request, busy, error }} onDone={() => setReviewing(null)} /></Dialog>}
  </section>;
}
