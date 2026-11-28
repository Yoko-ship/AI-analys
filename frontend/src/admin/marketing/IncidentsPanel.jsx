import { useState } from 'react';
import { Dialog, Field, Panel, SafeLink, Status, date } from './Widgets.jsx';
import { EvidenceSelection } from './EvidenceSelection.jsx';
import { contentFormats } from './ContentForm.jsx';

const fieldNames = { data: 'Факты', units: 'Единицы', excerpt: 'Текст источника', entity: 'Эмитент', period: 'Период', standard: 'Стандарт', scope: 'Периметр', currency: 'Валюта', url: 'Адрес оригинала', withdrawn: 'Источник отозван', event_at: 'Дата события', published_at: 'Дата публикации', analysis_version: 'Версия разбора', current_analysis_version: 'Опубликованная версия разбора', dividend: 'Дивиденд', dividend_state: 'Статус дивиденда', share_class: 'Класс акции' };
const values = { approved: 'Утверждён', proposed: 'Предложен', paid: 'Выплачен', ordinary: 'Простая акция', preferred: 'Привилегированная акция' };
function shown(value) {
  if (value == null) return 'Нет данных';
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
  if (typeof value === 'object') return JSON.stringify(value);
  return values[value] || String(value);
}

function Changes({ change }) {
  const rows = change.fields.flatMap(field => {
    if (['data', 'units'].includes(field)) {
      const before = change.before?.[field] || {}, after = change.after?.[field] || {};
      return [...new Set([...Object.keys(before), ...Object.keys(after)])].filter(key => JSON.stringify(before[key]) !== JSON.stringify(after[key])).map(key => ({ label: `${fieldNames[field]} · ${fieldNames[key] || key}`, before: before[key], after: after[key] }));
    }
    return [{ label: fieldNames[field] || field, before: change.before?.[field], after: change.after?.[field] }];
  });
  return <div className="mkt-source-diff">{rows.map(row => <div key={row.label}>
    <strong>{row.label}</strong><div className="mkt-fields"><p><small>При публикации · версия {change.original_version}</small><br />{shown(row.before)}</p><p><small>Сейчас · версия {change.current_version || 'недоступна'}</small><br />{shown(row.after)}</p></div>
  </div>)}</div>;
}

function CorrectionForm({ incident, data, request, error, busy, onDone }) {
  const original = data.candidates.find(item => item.id === incident.publication_id);
  const [selected, setSelected] = useState(original?.evidence_ids || []);
  const [replacements, setReplacements] = useState({});
  const currentClaims = (original?.claims || []).map(claim => ({ ...claim, evidence_id: replacements[claim.evidence_id] || claim.evidence_id }));
  const localTime = new Date(Date.now() + 86400000 + 5 * 3600000).toISOString().slice(0, 16);
  async function save(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = { reason: form.get('reason'), title: form.get('title'), body: form.get('body'), destination_url: form.get('destination_url'),
      expires_at: `${form.get('expires_at')}:00+05:00`, evidence_ids: selected, source_replacements: replacements,
      claims: form.getAll('claims').map(value => JSON.parse(value)).filter(claim => selected.includes(claim.evidence_id)) };
    if (await request(`/incidents/${incident.id}/correction`, { method: 'POST', body: { expected_version: incident.version, data: value }, message: 'Уточнение сохранено. Проверьте факты и пройдите разрешение выпуска в карточке материала.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <p>Отдельная публикация для {data.accounts.find(account => account.id === original?.account_id)?.label}. Формат: {contentFormats[original?.format]}. Текст получит видимую пометку об уточнении и ссылку на прежний пост, если площадка её подтвердила.</p>
    {original?.format !== 'post' && <p className="mkt-callout">После сохранения создайте новые медиафайлы в карточке уточнения.</p>}
    <Field label="Почему нужно уточнение"><textarea name="reason" minLength={3} maxLength={2000} required rows={2} /></Field>
    <Field label="Заголовок уточнения" name="title" maxLength={300} required />
    <Field label="Текст уточнения"><textarea name="body" maxLength={18000} required rows={5} /></Field>
    <Field label="Прямая ссылка уточнения" name="destination_url" type="url" defaultValue={original?.destination_url || ''} required />
    <Field label="Уточнение актуально до · Ташкент" name="expires_at" type="datetime-local" defaultValue={localTime} required />
    <details><summary>Заменить отозванный или недоступный оригинал</summary>
      <p>Явно свяжите замену с изменённым источником. Новый оригинал также должен пройти проверку.</p>
      {incident.changes.map(change => <Field key={change.evidence_id} label={`Источник для уточнения · ${data.evidence.find(ev => ev.id === change.evidence_id)?.title || change.evidence_id}`}><select value={replacements[change.evidence_id] || change.evidence_id} onChange={event => {
        const id = event.target.value;
        setReplacements(previous => ({ ...previous, [change.evidence_id]: id }));
        setSelected(previous => [...new Set([...previous.filter(key => key !== (replacements[change.evidence_id] || change.evidence_id)), id])]);
      }}><option value={change.evidence_id}>Текущая версия исходного источника</option>{data.evidence.filter(ev => ev.id !== change.evidence_id).map(ev => <option key={ev.id} value={ev.id}>{ev.title}</option>)}</select></Field>)}
    </details>
    <EvidenceSelection evidence={data.evidence} selected={selected} onChange={setSelected} claims={currentClaims} />
    <button className="mkt-primary" disabled={busy || !selected.length}>Сохранить уточнение</button>
  </form>;
}

function DismissForm({ incident, request, busy, error, onDone }) {
  async function save(event) {
    event.preventDefault();
    const reason = new FormData(event.currentTarget).get('reason');
    if (await request(`/incidents/${incident.id}/dismiss`, { method: 'POST', body: { expected_version: incident.version, reason }, message: 'Решение и основание сохранены в истории.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <p>Изменение источника не всегда означает ошибку в посте. Укажите, почему публичное уточнение не требуется. Подготовленное уточнение будет отменено, если отправка ещё не началась.</p>
    <Field label="Почему уточнение не требуется"><textarea name="reason" minLength={3} maxLength={2000} rows={4} required /></Field>
    <button disabled={busy}>Сохранить решение</button>
  </form>;
}

export function IncidentsPanel({ data, request, busy, error, onHistory }) {
  const [dialog, setDialog] = useState(null);
  const close = () => setDialog(null);
  const items = data.incidents || [];
  return <section aria-label="Изменения после публикации"><Panel title="Изменения после публикации" action={<button disabled={busy || data.pause.processing} onClick={() => request('/incidents/scan', { method: 'POST', message: 'Опубликованные версии сверены с текущими источниками.' })}>Проверить изменения источников</button>}>
    <p className="mkt-muted">Сравниваем факты с оригиналами, использованными при публикации. Вы оцениваете существенность изменения; история прежнего поста сохраняется. Уточнение считается опубликованным только после подтверждения площадки.</p>
    {data.pause.processing && <p className="mkt-callout">Обработка приостановлена. Возобновите её, чтобы проверить изменения.</p>}
    {!items.length && <p>Изменений в опубликованных материалах пока не зафиксировано.</p>}
    {items.map(incident => {
      const correction = data.candidates.find(item => item.id === incident.correction_id);
      const canDismiss = ['open', 'correction_prepared'].includes(incident.status) && !['sending', 'unknown', 'published', 'submitted'].includes(correction?.status);
      return <article key={incident.id} className="mkt-item">
        <div className="mkt-row mkt-between"><strong>{incident.publication.title}</strong><Status value={incident.status} /></div>
        <p className="mkt-muted">Обнаружено {date(incident.detected_at)} · {data.accounts.find(account => account.id === incident.publication.account_id)?.label || incident.publication.account_id}</p>
        {incident.changes.map(change => <div key={change.evidence_id}><p><strong>{data.evidence.find(ev => ev.id === change.evidence_id)?.title || change.evidence_id}</strong></p><Changes change={change} /></div>)}
        <details><summary>Прежняя публикация</summary><p className="mkt-post-preview">{incident.publication.body}</p>{incident.publication.url && <SafeLink href={incident.publication.url}>Открыть прежний пост ↗</SafeLink>}</details>
        {incident.reason && <p>Решение: {incident.reason}</p>}
        {correction && <p>Уточнение: {correction.title} · <Status value={correction.status} /></p>}
        {correction?.status === 'unknown' && <p className="mkt-callout">Площадка могла принять уточнение. Нужна сверка результата; повторная отправка остановлена.</p>}
        {incident.correction_publication?.url && <p><SafeLink href={incident.correction_publication.url}>Открыть опубликованное уточнение ↗</SafeLink></p>}
        <div className="mkt-actions">
          {incident.status === 'open' && <button disabled={busy} onClick={() => setDialog({ incident, kind: 'correction' })}>Подготовить уточнение</button>}
          {canDismiss && <button disabled={busy} onClick={() => setDialog({ incident, kind: 'dismiss' })}>Уточнение не требуется</button>}
          <button onClick={() => onHistory('incident', incident.id, 'История изменения источника')}>История решения</button>
        </div>
      </article>;
    })}
  </Panel>{dialog && <Dialog title={dialog.kind === 'correction' ? 'Подготовить уточнение' : 'Оценка изменения'} onClose={close}>{dialog.kind === 'correction' ? <CorrectionForm incident={dialog.incident} data={data} request={request} busy={busy} error={error} onDone={close} /> : <DismissForm incident={dialog.incident} request={request} busy={busy} error={error} onDone={close} />}</Dialog>}</section>;
}
