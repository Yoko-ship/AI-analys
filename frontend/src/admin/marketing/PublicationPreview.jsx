import { SafeLink } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';

export function PublicationPreview({ value }) {
  return <>
    <p className="mkt-muted">Версия материала: {value.candidate_version}. Перед выпуском проверяются факты и разрешение аккаунта.</p>
    {value.media_only ? <><p>Отправляется готовое изображение с текстом. Откройте медиа и проверьте его перед утверждением.</p><p>Ссылка-стикер и отдельная подпись не добавляются.</p></> : <><p>Текст включает прямую ссылку и оригиналы.</p><div className="mkt-post-preview"><p>{value.text}</p></div></>}
    {value.instagram_link === 'profile' && <div className="mkt-callout"><p>Призыв ведёт через профиль. Перед отправкой проверим, что ссылка в выбранном Instagram точно совпадает с адресом материала.</p><SafeLink href={value.link_destination} uzstock>Ссылка для профиля Instagram ↗</SafeLink></div>}
    {value.tracked_destination && <div className="mkt-callout"><p>Набор данных: {value.tracking_dataset === 'test' ? 'тестовый' : 'рабочий'}. Метка относится к этой версии материала. Переход можно связать с публикацией после подтверждения выпуска; открытие предпросмотра не считается переходом.</p><SafeLink href={value.tracked_destination} uzstock>Ссылка с меткой публикации ↗</SafeLink><p className="mkt-link-address">{value.tracked_destination}</p></div>}
    {value.reasons.map(reason => <p className="mkt-error" key={reason}>{reasonText(reason)}</p>)}
  </>;
}
