import { useState } from 'react';
import { Dialog, Panel, SafeLink, Status, date } from './Widgets.jsx';
import { ContentForm, contentFormats } from './ContentForm.jsx';
import { EvidenceDetail } from './EvidenceDetail.jsx';
import { reasonText } from './reasonCopy.js';
import { MediaFiles, RenderForm, RenderJobs } from './MediaPanel.jsx';
import { IncidentsPanel } from './IncidentsPanel.jsx';
import { ReconciliationPanel } from './ReconciliationPanel.jsx';
import { FacebookConfirmation, UploadProgress, VisibilityPanel } from './VisibilityPanel.jsx';
import { PublicationPreview } from './PublicationPreview.jsx';
import { OccasionSummary } from './OccasionField.jsx';

const terminal = new Set(['skipped', 'published', 'submitted', 'cancelled', 'unknown', 'sending']);
const time = value => value ? new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent', dateStyle: 'short', timeStyle: 'short' }) : 'Не задано';

function QueueCalendar({ data, onHistory }) {
  const jobs = [...data.deliveries].sort((a, b) => (a.next_attempt_at || '').localeCompare(b.next_attempt_at || ''));
  return <section aria-label="Календарь очереди"><Panel title="Календарь очереди"><p className="mkt-muted">Время Ташкента. Указано ближайшее время попытки; фактическая отправка зависит от окна, интервала, доступов и актуальности оригиналов.</p>
    {!jobs.length && <p>В очереди пока нет материалов.</p>}
    {jobs.map(job => <article className="mkt-item" key={job.id}>
      <div className="mkt-row mkt-between"><strong>{time(job.finished_at || job.next_attempt_at)}</strong><Status value={job.status} /></div>
      <p>{data.candidates.find(item => item.id === job.candidate_id)?.title} · {data.accounts.find(account => account.id === job.account_id)?.label || job.account_id}</p>
      {job.not_before && <p>Не раньше {time(job.not_before)} · Ташкент</p>}
      <p>{reasonText(job.reason)}</p><p className="mkt-muted">Попыток: {job.attempts}{job.external_id && ` · ID площадки: ${job.external_id}`}</p>
      {job.url && <p><SafeLink href={job.url}>Открыть публикацию ↗</SafeLink></p>}
      <button onClick={() => onHistory('delivery', job.id, 'Журнал доставки')}>Журнал доставки</button>
    </article>)}
  </Panel></section>;
}

export function ContentSection({ data, request, busy, error, onHistory, readFile, downloadFile }) {
  const [dialog, setDialog] = useState(null);
  const [calendar, setCalendar] = useState(false);
  const [filter, setFilter] = useState('all');
  const close = () => setDialog(null);
  const shared = { data, request, busy, error, onDone: close };
  const items = data.candidates.filter(item => filter === 'all' || item.status === filter);
  function action(item, path, body, message) { return request(`/candidates/${item.id}/${path}`, { method: 'POST', ...(body ? { body } : {}), message }); }
  async function preview(item) {
    const value = await request(`/candidates/${item.id}/publication-preview`);
    if (value) setDialog({ kind: 'preview', title: 'Текст для отправки', preview: value });
  }
  return <div className="mkt-stack">
    <div className="mkt-actions"><button className="mkt-primary" onClick={() => setDialog({ kind: 'content', title: 'Новый материал' })} disabled={!data.accounts.length}>Новый материал</button><button aria-expanded={calendar} onClick={() => setCalendar(value => !value)}>Календарь очереди</button><button disabled={busy} onClick={() => request('/workspace')}>Обновить материалы</button></div>
    {!data.accounts.length && <p className="mkt-callout">Сначала добавьте целевой аккаунт в настройках. Для подготовки достаточно режима «Только черновики».</p>}
    {calendar && <QueueCalendar data={data} onHistory={onHistory} />}
    <VisibilityPanel data={data} request={request} busy={busy} error={error} />
    <ReconciliationPanel data={data} request={request} busy={busy} error={error} onHistory={onHistory} />
    <IncidentsPanel data={data} request={request} busy={busy} error={error} onHistory={onHistory} />
    <Panel title="Материалы" action={<label className="mkt-filter">Статус <select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">Все</option><option value="draft">Черновики</option><option value="awaiting_approval">Ожидают решения</option><option value="scheduled">Запланированы</option><option value="skipped">Пропущены</option><option value="submitted">Приняты площадкой</option><option value="published">Опубликованы</option><option value="unknown">Исход неясен</option><option value="error">Ошибка доставки</option></select></label>}>
      {!items.length && <p className="mkt-muted">Материалов с выбранным статусом пока нет.</p>}
      {items.map(item => {
        const account = data.accounts.find(a => a.id === item.account_id);
        const job = data.deliveries.find(d => d.candidate_id === item.id);
        const renders = data.renders.filter(render => render.target_kind === 'candidate' && render.target_id === item.id);
        const internal = item.mode === 'draft' && item.publication_type === 'organic' && !terminal.has(item.status);
        const canRequestRelease = internal && account && account.mode !== 'draft';
        return <article className="mkt-item mkt-content-card" key={item.id}>
          <div className="mkt-row mkt-between"><h4>{item.title}</h4><Status value={item.status} /></div>
          <p className="mkt-muted">{account?.label || item.account_id} · {item.language.toUpperCase()} · {contentFormats[item.format]} · версия {item.version}</p>
          <OccasionSummary value={item.occasion} evidence={data.evidence} />
          {item.publication_type === 'paid' && <p className="mkt-callout">Платный креатив. Проверка фактов не разрешает рекламное действие. Его параметры и бюджет утверждаются отдельно в экспериментах.</p>}
          <div className="mkt-post-preview"><p>{item.body}</p>{item.destination_url && <SafeLink href={item.destination_url} uzstock>Материал на UZStock ↗</SafeLink>}</div>
          {item.destination_review?.url === item.destination_url && <p className="mkt-muted">Ссылку выбрал владелец · {time(item.destination_review.at)}</p>}
          {item.release_decision && <p className="mkt-muted">Владелец перевёл черновик к выпуску · {time(item.release_decision.at)} · версия настроек аккаунта {item.release_decision.account_version}</p>}
          <p className="mkt-muted">Актуален до {time(item.expires_at)} · событие {item.event_id}</p>
          {item.not_before && <p className="mkt-muted">Не раньше {time(item.not_before)} · Ташкент</p>}
          <details><summary>Доказательства · {item.evidence_ids.length}</summary><div className="mkt-actions">{item.evidence_ids.map(id => {
            const ev = data.evidence.find(value => value.id === id);
            return ev ? <button key={id} onClick={() => setDialog({ kind: 'evidence', title: ev.title, item: ev })}>{ev.title}</button> : <p key={id}>Оригинал недоступен: {id}</p>;
          })}</div></details>
          {item.check && <div className={item.check.passed ? 'mkt-callout' : 'mkt-error'}><strong>{item.check.passed ? 'Автоматические проверки пройдены' : 'Проверка не пройдена'}</strong><p>{reasonText(item.check.reason)}</p><small>Проверено: {time(item.check.checked_at)}</small></div>}
          {internal && <p className="mkt-callout">Внутренний черновик. {canRequestRelease
            ? account.mode === 'automatic' ? 'Допуск к автовыпуску заново проверит материал. При успехе фоновый процесс сможет отправить его по правилам этого аккаунта; отрицательная проверка завершит материал как пропущенный.' : 'Проверка для ручного выпуска заново проверит материал. Затем потребуется утвердить точную версию для этого аккаунта.'
            : 'Для выпуска настройте отдельное разрешение аккаунта. Подключение аккаунта само по себе не разрешает отправку.'}</p>}
          {item.status === 'skipped' && <p>Материал завершён без публикации. Повторный сигнал не возобновляет выпуск; история проверки сохранена.</p>}
          {item.status === 'unknown' && <p className="mkt-callout">{item.recovery_review_version ? item.reason : 'Площадка могла принять отправку. Автоматический повтор остановлен до сверки.'}</p>}
          {job && <p>Доставка: {reasonText(job.reason)}{job.finished_at && ` · ${date(job.finished_at)}`}</p>}
          {job?.external_id && <p>ID площадки: {job.external_id}{job.url && <> · <SafeLink href={job.url}>Открыть публикацию ↗</SafeLink></>}</p>}
          <RenderJobs jobs={renders} request={request} busy={busy} onHistory={onHistory} />
          <UploadProgress item={item} uploads={data.uploads} onHistory={onHistory} />
          {account?.platform === 'facebook' && item.format === 'video' && <p>Общедоступный Reel · с отметкой об использовании ИИ</p>}
          {account?.platform === 'instagram' && ['image', 'carousel'].includes(item.format) && <p>Instagram · с отметкой об использовании ИИ</p>}
          {account?.platform === 'instagram' && item.format === 'video' && <p>Reel Instagram · с отметкой об использовании ИИ. Дополнительное размещение в ленте профиля отключено.</p>}
          {account?.platform === 'instagram' && item.format === 'story' && <p>Story Instagram · текст в изображении, с отметкой об использовании ИИ. Доступно только для бизнес-аккаунта.</p>}
          {item.instagram_link === 'profile' && <p>{job?.dispatch_payload?.profile_link ? <>Ссылка профиля проверена перед отправкой · {time(job.dispatch_payload.profile_link.checked_at)} · Ташкент</> : 'Переход через профиль · проверка перед отправкой'}</p>}
          <FacebookConfirmation job={job} />
          <div className="mkt-actions">
            <button disabled={busy} onClick={() => preview(item)}>Текст для отправки</button>
            {!!item.assets.length && <button onClick={() => setDialog({ kind: 'media', title: 'Готовые медиафайлы', item })}>Открыть медиа</button>}
            {!terminal.has(item.status) && item.format !== 'post' && <button disabled={busy || renders.some(render => ['queued', 'running'].includes(render.status))} onClick={() => setDialog({ kind: 'render', title: 'Создать медиа', item })}>Создать медиа</button>}
            <button disabled={busy} onClick={() => downloadFile(`/candidates/${item.id}/export`, `${item.id}.zip`)}>Скачать черновик ZIP</button>
            {!terminal.has(item.status) && <><button disabled={busy} onClick={() => setDialog({ kind: 'content', title: 'Редактирование материала', item })}>Изменить материал</button><button disabled={busy} onClick={() => action(item, 'check')}>Проверить факты</button></>}
            {canRequestRelease && <button disabled={busy} onClick={() => action(item, 'release-draft', { expected_version: item.version, account_version: account.version }, 'Решение о выпуске записано. Результат новой проверки указан в карточке.')}>{account.mode === 'automatic' ? 'Проверить и допустить к автовыпуску' : 'Проверить для ручного выпуска'}</button>}
            {item.status === 'awaiting_approval' && <button disabled={busy} onClick={() => action(item, 'approve', { expected_version: item.version }, `Утверждена показанная версия для ${account?.label || item.account_id}.`)}>Утвердить эту версию</button>}
            {item.status === 'ready' && (!job || ['scheduled', 'retry', 'blocked'].includes(job.status) && (job.attempts === 0 || job.confirmed_not_sent)) && <button disabled={busy} onClick={() => action(item, 'schedule', null, 'Материал поставлен в очередь. Успех фиксируется только после подтверждения площадки.')}>Поставить в очередь</button>}
            {!terminal.has(item.status) && <button disabled={busy} onClick={() => action(item, 'cancel', { expected_version: item.version })}>Отменить материал</button>}
            <button onClick={() => onHistory('candidate', item.id, 'История материала')}>Версии и проверка</button>
          </div>
        </article>;
      })}
    </Panel>
    {dialog && <Dialog title={dialog.title} onClose={close}>{dialog.kind === 'preview' ? <PublicationPreview value={dialog.preview} /> : dialog.kind === 'content' ? <ContentForm item={dialog.item} {...shared} /> : dialog.kind === 'media' ? <MediaFiles item={dialog.item} data={data} readFile={readFile} downloadFile={downloadFile} busy={busy} /> : dialog.kind === 'render' ? <RenderForm item={dialog.item} {...shared} /> : <EvidenceDetail item={dialog.item} {...shared} />}</Dialog>}
  </div>;
}
