import { useState } from 'react';
import { Dialog, Panel, SafeLink } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';

const labels = {
  no_confirmation: 'Подтверждение не найдено', matched: 'Найдено совпадение', ambiguous: 'Совпадение неоднозначно',
  incomplete_media: 'Альбом подтверждён не полностью', already_linked: 'Публикация уже связана с другим материалом',
  basis_unavailable: 'Исходную версию отправки нельзя восстановить', unsupported: 'Сверка этой площадки ещё недоступна',
};
const time = value => new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' });

function MatchDialog({ match, title, request, busy, error, onClose }) {
  const [reviewed, setReviewed] = useState(false);
  async function confirm(event) {
    event.preventDefault();
    if (!reviewed) return;
    const result = await request(`/deliveries/${match.delivery_id}/confirm-match`, { method: 'POST',
      body: { expected_version: match.delivery_version, match_digest: match.match_digest },
      message: 'Сопоставление подтверждено. Сохранены ID площадки; повторной отправки не было.' });
    if (result) onClose();
  }
  return <Dialog title="Сопоставление с публикацией Telegram" onClose={onClose}><form className="mkt-form" onSubmit={confirm}>
    <p><strong>{title}</strong></p>
    <p>Telegram подтвердил канал, исходные ID и время. Текст совпадает с подготовленной отправкой. Откройте публикацию и проверьте её перед сопоставлением.</p>
    {match.media_review_required && <p className="mkt-callout">Проверьте каждое изображение или видео. Совпадение подписи и количества файлов само по себе не доказывает содержание медиа.</p>}
    {match.publications.map(post => <article className="mkt-item" key={post.external_id}>
      <SafeLink href={post.url}>Публикация {post.external_id} ↗</SafeLink><p className="mkt-muted">{time(post.published_at)} · Ташкент</p>
      {post.text && <div className="mkt-post-preview"><p>{post.text}</p></div>}
    </article>)}
    <label className="mkt-checkbox"><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />Проверил исходную публикацию: текст и все медиа соответствуют этому материалу</label>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <button className="mkt-primary" disabled={busy || !reviewed}>Подтвердить сопоставление</button>
  </form></Dialog>;
}

export function ReconciliationPanel({ data, request, busy, error, onHistory }) {
  const [selected, setSelected] = useState(null);
  const cases = data.reconciliation || [];
  if (!cases.length) return null;
  const read = data.reconciliation_read;
  const ready = data.accounts.some(account => account.platform === 'telegram' && data.channel_setup?.[account.id]?.ready);
  const title = row => data.candidates.find(item => item.id === row.delivery_id)?.title || row.delivery_id;
  return <section aria-label="Сверка публикаций"><Panel title="Сверка публикаций">
    <p>Неясный исход не разрешает повторную отправку. Получите наблюдения Telegram; если исходный пост виден в канале, перешлите его целиком выделенному боту, сохранив автора и весь альбом.</p>
    <p className="mkt-muted">Пустой ответ не доказывает отсутствие поста: обновления хранятся у Telegram не дольше суток. Защищённый или недоступный оригинал может остаться без подтверждения.</p>
    <button disabled={busy || !ready} onClick={() => request('/channels/telegram/reconcile', { method: 'POST', body: {}, message: 'Наблюдения Telegram получены. Проверьте найденные сопоставления.' })}>Получить подтверждения Telegram</button>
    {!ready && <p className="mkt-muted">Сначала проверьте подключение выделенного бота в настройках.</p>}
    {read?.checked_at && <p className="mkt-muted">Последняя успешная сверка: {time(read.checked_at)} · Ташкент</p>}
    {read?.status === 'error' && <p className="mkt-error">{reasonText(read.reason)}</p>}
    {read?.has_more && <p>Получена полная порция обновлений. Повторите чтение, чтобы проверить следующую.</p>}
    {cases.map(row => <article className="mkt-item" key={row.delivery_id}>
      <h4>{title(row)}</h4><p>{labels[row.status]}</p>
      <div className="mkt-actions">{row.status === 'matched' && <button disabled={busy} onClick={() => setSelected(row)}>Проверить совпадение</button>}
        <button onClick={() => onHistory('delivery', row.delivery_id, 'Журнал доставки')}>Журнал доставки</button></div>
    </article>)}
    {selected && <MatchDialog key={selected.match_digest} match={selected} title={title(selected)} request={request} busy={busy} error={error} onClose={() => setSelected(null)} />}
  </Panel></section>;
}
