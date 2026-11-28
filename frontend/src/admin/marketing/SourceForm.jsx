import { Field } from './Widgets.jsx';

export const sourceMethods = { manual: 'Ручная загрузка', internal_news: 'Сохранённые новости UZStock', internal_market: 'Внутренние итоги торгов', internal_analysis: 'Готовые разборы UZStock', rss: 'Публичный RSS / Atom' };
export const rightsLabels = { unknown: 'Условия ещё не проверены', link_and_excerpt: 'Ссылка и разрешённый фрагмент', owned: 'Собственный материал', licensed: 'Есть лицензия' };

export function SourceForm({ source, request, busy, error, onDone }) {
  async function save(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const data = Object.fromEntries(['name', 'url', 'method', 'category', 'language', 'owner', 'geography', 'rights', 'restrictions', 'fallback', 'data_type', 'access_owner'].map(key => [key, f.get(key)]));
    for (const key of ['frequency_minutes', 'stale_after_hours']) data[key] = Number(f.get(key));
    for (const key of ['may_store', 'may_display', 'commercial_use', 'authorization_required']) data[key] = f.has(key);
    data.terms_checked_on = f.get('terms_checked_on') || null;
    data.topics = String(f.get('topics')).split(',').map(s => s.trim()).filter(Boolean);
    if (await request(`/sources/${source?.id || crypto.randomUUID()}`, { method: 'PUT', body: { data, expected_version: source?.version || 0 }, message: 'Источник сохранён. Мониторинг включается отдельным решением.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <Field label="Название источника" name="name" defaultValue={source?.name || ''} maxLength={200} required />
    <Field label="Адрес источника" name="url" type="url" defaultValue={source?.url || ''} placeholder="https://…" required help="Оригинальный ресурс или RSS. Для данных UZStock выберите внутренний адаптер." />
    <div className="mkt-fields">
      <Field label="Способ получения"><select name="method" defaultValue={source?.method || 'manual'}>{Object.entries(sourceMethods).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
      <Field label="Категория"><select name="category" defaultValue={source?.category || 'manual'}>{[['manual', 'Ручной источник'], ['uzstock', 'UZStock'], ['issuer', 'Эмитент'], ['exchange', 'Биржа'], ['regulator', 'Регулятор'], ['macro', 'Макроэкономика'], ['media', 'СМИ'], ['social', 'Социальная сеть']].map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
      <Field label="Язык источника" name="language" defaultValue={source?.language || 'ru'} required maxLength={10} />
      <Field label="Ответственный" name="owner" defaultValue={source?.owner || 'Владелец'} required maxLength={100} />
      <Field label="Регион" name="geography" defaultValue={source?.geography || 'UZ'} maxLength={100} />
      <Field label="Темы через запятую" name="topics" defaultValue={source?.topics.join(', ') || ''} />
      <Field label="Проверять каждые · минуты" name="frequency_minutes" type="number" min={5} max={10080} defaultValue={source?.frequency_minutes || 60} required />
      <Field label="Срок свежести · часы" name="stale_after_hours" type="number" min={1} max={8760} defaultValue={source?.stale_after_hours || 24} required />
    </div>
    <fieldset><legend>Доступ и права</legend><div className="mkt-stack">
      <Field label="Условия использования"><select name="rights" defaultValue={source?.rights || 'unknown'}>{Object.entries(rightsLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
      <Field label="Дата проверки условий" name="terms_checked_on" type="date" defaultValue={source?.terms_checked_on || ''} />
      <Field label="Тип сохраняемых данных"><select name="data_type" defaultValue={source?.data_type || 'extract'}>{[['extract', 'Фрагмент'], ['headline', 'Заголовок'], ['numeric', 'Числовые факты'], ['document', 'Документ'], ['full', 'Полный материал']].map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
      <div className="mkt-checks">{[['may_store', 'Разрешено сохранять материалы'], ['may_display', 'Разрешено показывать фрагменты'], ['commercial_use', 'Разрешено коммерческое использование'], ['authorization_required', 'Для доступа требуется вход']].map(([name, label]) => <label key={name}><input type="checkbox" name={name} defaultChecked={source?.[name] || false} />{label}</label>)}</div>
      <Field label="Кто предоставит доступ" name="access_owner" defaultValue={source?.access_owner || ''} maxLength={100} />
      <Field label="Ограничения использования"><textarea name="restrictions" defaultValue={source?.restrictions || ''} maxLength={3000} /></Field>
      <Field label="Действие при недоступности" name="fallback" defaultValue={source?.fallback || 'Остановить сбор и показать причину'} maxLength={1000} />
    </div></fieldset>
    <p className="mkt-muted">Секреты и пароли в эту форму не вводятся. Изменение настроек останавливает мониторинг до нового разрешения.</p>
    <button className="mkt-primary" disabled={busy}>Сохранить источник</button>
  </form>;
}
