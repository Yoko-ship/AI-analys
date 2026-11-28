import { useState } from 'react';
import { Dialog, Panel, SafeLink } from './Widgets.jsx';

function VisibilityReview({ review, request, busy, error, onClose }) {
  const [reviewed, setReviewed] = useState(false);
  async function confirm(event) {
    event.preventDefault();
    if (!reviewed) return;
    const result = await request(`/deliveries/${review.delivery_id}/confirm-visible`, { method: 'POST',
      body: { expected_version: review.delivery_version, review_digest: review.review_digest },
      message: 'Видимость подтвердил владелец. Публикация не отправлялась повторно.' });
    if (result) onClose();
  }
  return <Dialog title="Проверка видимости LinkedIn" onClose={onClose}><form className="mkt-form" onSubmit={confirm}>
    <p><strong>{review.title}</strong></p>
    <p>Откройте созданный пост. Сравните его с отправленным текстом ниже и проверьте все медиа. Подтверждение сохранится как ваша проверка видимости.</p>
    <SafeLink href={review.url}>Открыть созданный пост ↗</SafeLink>
    <div className="mkt-post-preview"><p>{review.payload.text}</p></div>
    <p>Отправлено медиафайлов: {review.payload.media_count}.</p>
    <label className="mkt-checkbox"><input type="checkbox" checked={reviewed} onChange={event => setReviewed(event.target.checked)} />Открыл пост в LinkedIn: он виден, текст и все медиа соответствуют материалу</label>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <button className="mkt-primary" disabled={busy || !reviewed}>Подтвердить видимость</button>
  </form></Dialog>;
}

export function VisibilityPanel({ data, request, busy, error }) {
  const [selected, setSelected] = useState(null);
  const reviews = data.visibility_reviews || [];
  if (!reviews.length) return null;
  return <section aria-label="Видимость публикаций LinkedIn"><Panel title="Видимость публикаций LinkedIn">
    <p>LinkedIn вернул ID созданного поста. Это ещё не подтверждает, что пост виден: обработка может продолжаться или завершиться ошибкой. Откройте пост и проверьте результат.</p>
    {reviews.map(review => <article className="mkt-item" key={review.delivery_id}>
      <h4>{review.title}</h4>
      <button disabled={busy} onClick={() => setSelected(review)}>Проверить опубликованный пост</button>
    </article>)}
    {selected && <VisibilityReview key={selected.review_digest} review={selected} request={request} busy={busy} error={error} onClose={() => setSelected(null)} />}
  </Panel></section>;
}

const uploadLabels = { registered: 'Подготовлено к загрузке', uploading: 'Загружается', uploaded: 'Файл загружен',
  finalizing: 'Загрузка завершается', processing: 'Обработка видео', ready: 'Медиа готово', failed: 'Ошибка обработки видео', expired: 'Срок загрузки истёк' };

export function UploadProgress({ item, uploads = [], onHistory }) {
  const current = item.assets.map(asset => uploads.find(upload => upload.candidate_id === item.id && upload.asset_id === asset.id)).filter(Boolean);
  if (!current.length) return null;
  const provider = { facebook: 'Facebook', instagram: 'Instagram', linkedin: 'LinkedIn' }[current[0].provider] || 'площадку';
  return <details><summary>Загрузка медиа в {provider}</summary>
    <p className="mkt-muted">Загруженный файл ещё не означает, что пост опубликован.</p>
    {current.map((upload, index) => <div className="mkt-item" key={upload.id}>
      <p>{provider === 'Instagram' ? 'Материал' : `Файл ${index + 1}`}: {upload.status === 'processing' ? `${provider} обрабатывает ${provider === 'Instagram' ? 'медиа' : 'видео'}` : uploadLabels[upload.status] || upload.status} · {provider === 'Instagram' ? 'готово файлов' : 'частей'} {upload.parts_completed} из {upload.part_count}</p>
      <button onClick={() => onHistory('provider_upload', upload.id, 'История загрузки медиа')}>История загрузки файла {index + 1}</button>
    </div>)}
  </details>;
}

function LocalTime({ value }) {
  return <time dateTime={value}>{new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent', dateStyle: 'short', timeStyle: 'short' })}</time>;
}

export function FacebookConfirmation({ job }) {
  const platform = job?.provider || job?.platform;
  if (!['facebook', 'instagram'].includes(platform)) return null;
  const provider = platform === 'instagram' ? 'Instagram' : 'Facebook';
  const story = platform === 'instagram' && job.dispatch_payload?.format === 'story';
  if (job.status === 'published' && job.visibility_confirmation?.method === 'provider_read') {
    if (story) return <p>Instagram подтвердил Story в выбранном аккаунте. Опубликовано <LocalTime value={job.published_at} />. Срок показа — до <LocalTime value={job.visibility_expires_at} />. Время Ташкента.</p>;
    return <p>{provider} подтвердил {platform === 'instagram' ? 'аккаунт, текст и состав медиа' : 'страницу, текст и медиа'}. Опубликовано <LocalTime value={job.published_at} />. Время Ташкента.</p>;
  }
  if (story && job.confirmation?.status === 'expired_unverified') return <div className="mkt-callout">
    <p><strong>Срок проверки Story истёк</strong></p><p>Видимость не подтверждена. Instagram принял материал, но до окончания срока показа мы не подтвердили его среди активных Stories аккаунта. Повторная отправка не выполняется.</p>
    <p>Последняя сверка: <LocalTime value={job.confirmation.checked_at} />. Время Ташкента.</p>
  </div>;
  const unknownReel = platform === 'facebook' && job.status === 'unknown' && job.dispatch_payload?.format === 'video';
  if (job.status !== 'submitted' && !unknownReel) return null;
  return <div className="mkt-callout">
    <p><strong>{unknownReel ? 'Сверяем исход отправки Reel' : `${provider} проверяет видимость`}</strong></p>
    <p>{unknownReel ? 'Ответ на публикацию потерян. По сохранённому ID видео проверяем страницу, текст и состояние Reel.' : story ? 'Площадка приняла изображение. Проверяем его ID среди активных Stories выбранного аккаунта.' : 'Площадка приняла материал. Ждём подтверждения аккаунта, точного текста и состава медиа.'} Повторная отправка не выполняется.</p>
    {job.confirmation?.checked_at && <p>Последняя сверка: <LocalTime value={job.confirmation.checked_at} />.{job.confirmation.next_check_at && <> Следующая: <LocalTime value={job.confirmation.next_check_at} />.</>} Время Ташкента.</p>}
  </div>;
}
