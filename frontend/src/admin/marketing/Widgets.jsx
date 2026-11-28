import { cloneElement, useEffect, useId, useRef } from 'react';
import { reasonText } from './reasonCopy.js';

export const statusLabels = {
  pending: 'Ожидает назначения', prepared: 'Ожидает автоматического старта', paused: 'На паузе', active: 'В работе',
  submitted: 'Принято площадкой',
  queued: 'В очереди', running: 'В работе', complete: 'Готово', blocked: 'Нужны данные или решение',
  draft: 'Черновик', proposed: 'Предложено', approved: 'Утверждено', ready: 'Готов', scheduled: 'Запланирован',
  sending: 'Отправляется', published: 'Опубликован', skipped: 'Пропущен', unknown: 'Исход неясен',
  error: 'Ошибка', retry: 'Ожидает повторной попытки', awaiting_approval: 'Ожидает решения',
  needs_revision: 'Нужна доработка', cancelled: 'Отменён', verified: 'Проверен', unavailable: 'Недоступен',
  candidate: 'Кандидат', disabled: 'Отключён', connected: 'Подключён', not_connected: 'Не подключён',
  reviewing: 'Ожидает проверки',
  registered: 'Дизайн зарегистрирован', stopped: 'Остановлен',
  waiting: 'Ожидает события', expired: 'Период завершён',
  reviewed: 'Рассмотрен редактором', rejected: 'Отклонён редактором', accept: 'Принято', revise: 'Нужна правка',
  waiting_assets: 'Ожидает медиа',
  revoked: 'Отозвано',
  open: 'Требует оценки', correction_prepared: 'Уточнение подготовлено', corrected: 'Уточнение опубликовано', not_material: 'Уточнение не требуется', superseded: 'Источник изменён снова',
  incomplete: 'Неполные данные', no_data: 'Нет данных', not_applicable: 'Не применяется', not_comparable: 'Несопоставимо',
};
export const number = value => value == null ? 'Нет данных' : Number(value).toLocaleString('ru-RU');
export const experimentActions = { repeat: 'Повторить', change: 'Изменить', stop: 'Остановить' };
export const date = value => value ? new Date(value.length === 10 ? `${value}T00:00:00+05:00` : value).toLocaleDateString('ru-RU', { timeZone: 'Asia/Tashkent' }) : 'Не задан';
export function Status({ value }) { return <span className={`mkt-status mkt-status-${value}`}>{statusLabels[value] || value}</span>; }
export function SafeLink({ href, children, uzstock = false }) {
  let allowed = false;
  try {
    const url = new URL(href);
    allowed = url.protocol === 'https:' && !url.username && !url.password && (!uzstock || ['uzstock.uz', 'www.uzstock.uz'].includes(url.hostname));
  } catch { /* An unreviewed draft can contain an invalid address. */ }
  return allowed ? <a href={href} target="_blank" rel="noreferrer">{children}</a> : <span className="mkt-muted">Ссылка не прошла проверку адреса</span>;
}
export function Panel({ title, children, action, labelled = false }) {
  const id = useId();
  return <section className="mkt-panel" aria-labelledby={labelled ? id : undefined}><div className="mkt-row mkt-between"><h3 id={id}>{title}</h3>{action}</div>{children}</section>;
}
export function Field({ label, help, children, ...props }) {
  const id = useId();
  const controlProps = { id, 'aria-describedby': help ? `${id}-help` : undefined };
  return <div className="mkt-field"><label htmlFor={id}>{label}</label>{children ? cloneElement(children, controlProps) : <input {...controlProps} {...props} />}{help && <small id={`${id}-help`}>{help}</small>}</div>;
}
export function Dialog({ title, children, onClose }) {
  const ref = useRef(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    const trigger = document.activeElement;
    dialog.showModal();
    return () => { dialog.close(); if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus(); };
  }, []);
  return <dialog ref={ref} className="mkt-dialog" aria-labelledby={id} onCancel={onClose} onClose={onClose}>
    <div className="mkt-row mkt-between"><h3 id={id}>{title}</h3><button type="button" onClick={onClose}>Закрыть</button></div>
    {children}
  </dialog>;
}
export function History({ items }) {
  return <ol className="mkt-history">{items.map(({ record, action, actor }) => <li key={record.version}>
    <div className="mkt-row"><strong>Версия {record.version}</strong><Status value={record.status} /><small>{date(record.updated_at)}</small></div>
    <p>{record.title || record.label || action}</p>
    {record.basis?.method === 'distinct-canonical-mentions-v1' && <><p>{record.theme} · {date(record.starts_on)}–{date(record.ends_on)} (конец не включён)</p><p>Упоминания: {number(record.baseline.mentions)} → {number(record.current.mentions)}</p><p>{record.complete ? 'Полнота подтверждена при сохранении' : 'Неполная подборка'} · {record.review_reason}</p></>}
    {record.reason && <p>{record.reason}</p>}
    {record.design && record.decision && <><p>{experimentActions[record.decision.action]} · {record.decision.reason}</p><small>Сохранённая оценка: {record.decision.evaluation_id}</small></>}
    {record.budget_limit != null && <p>Лимит: {number(record.budget_limit)} {record.currency} · {record.advertiser_account_id} · {record.campaign_ref} · {date(record.starts_at)}–{date(record.ends_at)}</p>}
    {typeof record.target === 'number' && <p>{number(record.target)} {record.unit} · до {date(record.deadline)} · {number(record.budget)} {record.currency}</p>}
    {record.strategy_id && record.source_ids && <p>{record.enabled ? 'Автоматический выбор включён' : 'Автоматический выбор отключён'} · стратегия v{record.strategy_version} · {date(record.starts_on)}–{date(record.ends_on)} · до {record.max_daily} заданий в день</p>}
    {record.check?.reason && <p>{reasonText(record.check.reason)}</p>}<small>Роль: {actor.role || actor.id}</small>
  </li>)}</ol>;
}
