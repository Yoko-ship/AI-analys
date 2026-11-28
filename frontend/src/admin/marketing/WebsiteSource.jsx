import { useState } from 'react';
import { Field, number } from './Widgets.jsx';

const stamp = value => value ? new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' }) : 'Ещё не было';
const states = { queued: 'Ожидает чтения', running: 'Чтение данных', waiting: 'Обход завершён', error: 'Ошибка чтения', disabled: 'Сбор выключен' };

export function WebsiteSource({ source, period, reportDataset, paused, busy, request }) {
  const saved = source?.settings || { version: 0, data: {} };
  const [enabled, setEnabled] = useState(Boolean(saved.data.enabled));
  const runtime = source?.runtime;
  async function save(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await request('/reports/website', { method: 'PUT', body: { expected_version: saved.version, data: {
      enabled, dataset: form.get('dataset') || saved.data.dataset, starts_on: form.get('starts_on'), interval_minutes: Number(form.get('interval_minutes')),
    } } });
  }
  return <section className="mkt-panel" aria-label="События сайта UZStock">
    <div className="mkt-row mkt-between"><h3>События сайта UZStock</h3><button disabled={busy} onClick={() => request('/workspace')}>Обновить состояние сайта</button></div>
    <p>Посещения по сессиям, реальные даты регистрации и наблюдения успешных действий в интерфейсе. Открытия привязаны к эмитенту, новости или точной версии разбора. Адреса почты, пароли, IP и тексты поисковых запросов в отчёт не передаются.</p>
    {!source?.setup_ready && <p className="mkt-callout">Настройте подключение на сервере: базу сайта и приватный ключ идентификаторов аналитики. После этого обновите состояние. Ключ в этой форме не вводится.</p>}
    <form className="mkt-form" onSubmit={save}>
      <div className="mkt-fields">
        <Field label="Среда событий сайта" help="После подключения среда закреплена за источником."><select name="dataset" defaultValue={saved.data.dataset || reportDataset} disabled={source?.dataset_locked}><option value="production">Рабочие данные</option><option value="test">Тестовые данные</option></select></Field>
        <Field label="Начать чтение с" type="date" name="starts_on" required defaultValue={saved.data.starts_on || period.starts_on} />
        <Field label="Повторный обход, минут" type="number" name="interval_minutes" min="5" max="1440" required defaultValue={saved.data.interval_minutes || 15} />
      </div>
      <label className="mkt-checkbox"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Разрешить сбор событий сайта</label>
      <button disabled={busy || (enabled && !source?.setup_ready)}>Сохранить подключение сайта</button>
    </form>
    <p>{saved.data.enabled ? 'Сбор включён' : 'Сбор выключен'} · {states[runtime?.status] || 'Чтение ещё не запускалось'}</p>
    {paused && <p className="mkt-callout">Обработка на паузе. Сбор продолжится после её снятия.</p>}
    {saved.data.enabled && saved.data.dataset !== reportDataset && <p className="mkt-callout">Среда источника отличается от базы отчёта. Для просмотра его событий выберите ту же базу в настройках расчётов.</p>}
    {runtime?.reason && <p role="status" className="mkt-callout">{runtime.reason}</p>}
    {runtime?.stats && <div aria-live="polite"><p>Добавлено событий: {number(runtime.imported)} · Обновлено наблюдений: {number(runtime.revised)} · Связей с аккаунтами: {number(runtime.identity_updates)}</p><p>Старых аккаунтов без дат: {number(runtime.stats.legacy_undated)}. Даты для них не подставляются.</p></div>}
    <p className="mkt-muted">Последнее успешное чтение: {stamp(runtime?.last_success_at)}. Следующая попытка: {runtime?.next_at && saved.data.enabled ? stamp(runtime.next_at) : 'Не запланирована'}. Время Ташкента.</p>
    <div className="mkt-actions"><button disabled={busy || !saved.data.enabled || !source?.setup_ready || paused} onClick={() => request('/reports/website/sync', { method: 'POST', body: { expected_version: saved.version } })}>Прочитать сейчас</button></div>
    <p className="mkt-muted">Сбор идёт частями и продолжается без открытой страницы. Повторный обход находит запоздавшие записи; события не удваиваются. Выключение сбора сохраняет импортированные данные.</p>
    <p className="mkt-callout">Полнота не подтверждена: браузер может не доставить наблюдение, старые регистрации не имеют точных дат. Клик по отчёту не считается его открытием; фиксируется появление загруженного разбора. Поиск измеряется среди загруженных новостей. Оплаты не подключены.</p>
  </section>;
}
