import { useState } from 'react';
import { Dialog, Field } from './Widgets.jsx';
import { VersionedEditor } from './VersionedEditor.jsx';

const activity = [['report_open', 'Отчёт'], ['chart_open', 'График'], ['issuer_open', 'Эмитент'], ['news_open', 'Новость'], ['search_open', 'Переход из поиска'], ['favorite', 'Избранное'], ['visit', 'Посещение']];
const costs = [['advertising', 'Реклама'], ['marketing', 'Маркетинг'], ['sales', 'Продажи']];

export function ReportSetup({ saved, request, busy, onClose }) {
  return <Dialog title="Правила расчёта" onClose={onClose}><VersionedEditor value={saved} request={request}>{(basis, save) => <ReportSetupForm saved={basis} request={save} busy={busy} onClose={onClose} />}</VersionedEditor></Dialog>;
}

function ReportSetupForm({ saved, request, busy, onClose }) {
  const [value, setValue] = useState(saved.data);
  const [stability, setStability] = useState(JSON.stringify(saved.data.ltv_stability, null, 2));
  const [error, setError] = useState('');
  const change = (key, next) => setValue(old => ({ ...old, [key]: next }));
  const toggle = (key, item, checked) => change(key, checked ? [...value[key], item] : value[key].filter(v => v !== item));
  async function submit(event) {
    event.preventDefault();
    let ltv;
    try { ltv = JSON.parse(stability); } catch { setError('Проверьте JSON решения по LTV.'); return; }
    const result = await request('/reports/settings', { method: 'PUT', body: { data: { ...value, ltv_stability: ltv }, expected_version: saved.version }, message: 'Правила сохранены. Пересчитайте период, чтобы применить их.' });
    if (result) onClose();
  }
  return <form className="mkt-form" onSubmit={submit}>
    <p>Версия {saved.version}. Изменения применяются к новым расчётам. Сохранённые снимки остаются прежними.</p>
    {error && <p role="alert">{error}</p>}
    <div className="mkt-fields">
      <Field label="Среда данных"><select value={value.dataset} onChange={e => change('dataset', e.target.value)}><option value="production">Рабочая</option><option value="test">Тестовая</option></select></Field>
      <Field label="Валюта отчёта"><select value={value.currency} onChange={e => change('currency', e.target.value)}><option>UZS</option><option>USD</option></select></Field>
      {[['attribution_days', 'Окно атрибуции, дней', 90], ['conversion_days', 'Окно первой оплаты, дней', 365], ['activation_days', 'Окно активации, дней', 365], ['retention_days', 'Период исходной когорты удержания, дней', 365]].map(([key, label, max]) => <Field key={key} label={label} type="number" min="1" max={max} required value={value[key]} onChange={e => change(key, Number(e.target.value))} />)}
      <Field label="Действие активации"><select value={value.activation_event} onChange={e => change('activation_event', e.target.value)}>{activity.map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></Field>
      <Field label="Каналы привлечения" help="Через запятую. Пусто — каналы с подтверждённым рекламным расходом." value={value.acquisition_channels.join(', ')} onChange={e => change('acquisition_channels', e.target.value.split(',').map(v => v.trim()).filter(Boolean))} />
    </div>
    <p className="mkt-muted">Атрибуция: последний недиректный переход. Неизвестный канал остаётся неизвестным. Расходы относятся по подтверждённому каналу события.</p>
    <fieldset><legend>Активная база ARPU и удержания</legend><div className="mkt-checks">{activity.map(([id, label]) => <label key={id}><input type="checkbox" checked={value.activity_events.includes(id)} onChange={e => toggle('activity_events', id, e.target.checked)} />{label}</label>)}</div></fieldset>
    <fieldset><legend>Состав полного CAC и ROI</legend><div className="mkt-checks">{costs.map(([id, label]) => <label key={id}><input type="checkbox" checked={value.cost_categories.includes(id)} onChange={e => toggle('cost_categories', id, e.target.checked)} />{label}</label>)}</div></fieldset>
    <fieldset><legend>Фактическая монетизация</legend><div className="mkt-checks">
      <label><input type="checkbox" checked={value.monetization_live} onChange={e => change('monetization_live', e.target.checked)} />Платные услуги фактически запущены</label>
      <label><input type="checkbox" checked={value.shared_customer_ids} onChange={e => change('shared_customer_ids', e.target.checked)} />Общий идентификатор клиента проверен между ИП и ООО</label>
      {[['ip', 'ИП'], ['llc', 'ООО']].map(([id, label]) => <div key={id}><label><input type="checkbox" checked={value.legal_entities.includes(id)} onChange={e => toggle('legal_entities', id, e.target.checked)} />{label} участвует в отчёте</label>
        <Field label={`Дата запуска ${label}`} type="date" value={value.entity_launches[id]?.slice(0, 10) || ''} onChange={e => { const launches = { ...value.entity_launches }; if (e.target.value) launches[id] = `${e.target.value}T00:00:00+05:00`; else delete launches[id]; change('entity_launches', launches); }} /></div>)}
    </div></fieldset>
    <details><summary>Основание оценки LTV</summary><p>Стабильность оценивает владелец. Нужны три последовательных месяца непосредственно перед оцениваемым, ненулевой отток и подтверждённая маржа. monthly_rates содержит period «2025-01», rate от 0 до 1 и source.</p><p>Решение confirmed требует note, period оцениваемого месяца, reviewed_at с часовым поясом после его закрытия, currency, dataset, legal_entities, opening_customers (платящие на начало) и lost_customers (ушедшие). Числа должны совпадать с расчётом оттока. Старое решение без этой привязки не разрешает новую оценку LTV.</p><Field label="Решение по стабильности LTV, JSON"><textarea rows="12" value={stability} onChange={e => setStability(e.target.value)} /></Field></details>
    <label className="mkt-checkbox"><input type="checkbox" checked={value.automatic_weekly} onChange={e => change('automatic_weekly', e.target.checked)} />Автоматически сохранять завершённую неделю при работающем фоновом сервисе</label>
    <button className="mkt-primary" disabled={busy}>Сохранить правила расчёта</button>
  </form>;
}

export function ReportImport({ request, busy, onClose }) {
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  async function submit(event) {
    event.preventDefault();
    let body;
    try { body = JSON.parse(text); } catch { setError('Не удалось прочитать JSON. Проверьте формат выгрузки.'); return; }
    const result = await request('/reports/import', { method: 'POST', body, message: 'Выгрузка сохранена. Рассчитайте период заново.' });
    if (result) onClose();
  }
  return <Dialog title="Подтверждённые события и полнота источника" onClose={onClose}><form className="mkt-form" onSubmit={submit}>
    <p>Используйте устойчивые идентификаторы и обезличенные subject_id. Время поступления фиксируется сервером. Рабочая и тестовая среды разделены.</p>
    <details><summary>Формат выгрузки</summary><pre className="mkt-json">{JSON.stringify({ events: [{ id: 'source-event-1', kind: 'registration', subject_id: 'anonymous-1', at: '2025-01-07T12:00:00+05:00', dataset: 'test', source: 'confirmed-export', confirmed: true }], coverage: [{ dataset: 'test', categories: ['registrations'], starts_on: '2024-01-01', ends_on: '2025-02-01', through: '2025-01-31T23:00:00+05:00', history_complete: true, status: 'complete', reference: 'Источник и основание проверки полноты' }] }, null, 2)}</pre><p>coverage подтверждает полноту категории на интервале, включая историю для первых регистраций, оплат и подписок. Отсутствие записи о полноте означает «Нет данных», а не ноль. Не подтверждайте будущие даты или неполную выгрузку.</p></details>
    <Field label="Подтверждённая выгрузка JSON"><textarea rows="10" required value={text} onChange={e => setText(e.target.value)} /></Field>
    <details><summary>Исправление или отзыв события</summary><p>Добавьте corrections с event_id, dataset, reason, expected_version (0 при первом исправлении) и replacement — полным исправленным событием с тем же id и средой. replacement: null отзывает ошибочное событие. Исходная запись сохраняется; зависимые метрики пересчитываются. Дубли одной транзакции исправляются согласованно в одной выгрузке.</p><pre className="mkt-json">{JSON.stringify({ corrections: [{ event_id: 'source-event-1', dataset: 'test', replacement: null, reason: 'Подтверждён отзыв исходной записи', expected_version: 0 }] }, null, 2)}</pre></details>
    {error && <p role="alert">{error}</p>}<button className="mkt-primary" disabled={busy}>Сохранить выгрузку</button>
  </form></Dialog>;
}
