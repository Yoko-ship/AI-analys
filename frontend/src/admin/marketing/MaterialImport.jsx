import { useState } from 'react';
import { Field } from './Widgets.jsx';

export function MaterialImport({ source, request, busy, error, onDone }) {
  const [problem, setProblem] = useState('');
  async function save(event) {
    event.preventDefault();
    setProblem('');
    const f = new FormData(event.currentTarget);
    let data, units;
    try {
      data = JSON.parse(f.get('data') || '{}'); units = JSON.parse(f.get('units') || '{}');
      if (!data || Array.isArray(data) || typeof data !== 'object' || !units || Array.isArray(units) || typeof units !== 'object' || Object.values(units).some(v => typeof v !== 'string')) throw new Error();
    } catch { setProblem('Факты и единицы должны быть JSON-объектами. Единицы задаются текстом.'); return; }
    const material = Object.fromEntries(['title', 'url', 'publisher', 'entity', 'canonical_event_id', 'excerpt', 'period', 'standard', 'scope', 'currency', 'destination_url'].map(key => [key, f.get(key)]));
    material.source_item_id = f.get('source_item_id') || f.get('url');
    material.themes = String(f.get('themes')).split(',').map(value => value.trim()).filter(Boolean);
    material.published_at = `${f.get('published_at')}:00+05:00`;
    material.event_at = f.get('event_at') ? `${f.get('event_at')}:00+05:00` : null;
    Object.assign(material, { data, units, rights: source.rights });
    if (await request(`/sources/${source.id}/import`, { method: 'POST', body: { materials: [material] }, message: 'Оригинал сохранён. Проверка фактов выполняется отдельно.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>
    <p>Источник: <strong>{source.name}</strong>. Повторный ID обновляет версию оригинала; ключ события объединяет перепечатки.</p>
    {(problem || error) && <p role="alert" className="mkt-error">{problem || error}</p>}
    <Field label="Название материала" name="title" maxLength={500} required />
    <Field label="Ссылка на оригинал" name="url" type="url" required />
    <Field label="ID материала в источнике" name="source_item_id" maxLength={200} help="Можно оставить пустым: будет использована ссылка." />
    <div className="mkt-fields">
      <Field label="Издатель" name="publisher" required maxLength={200} />
      <Field label="Эмитент или тикер" name="entity" maxLength={100} />
      <Field label="Дата публикации оригинала" name="published_at" type="datetime-local" required help="Время Ташкента" />
      <Field label="Дата самого события" name="event_at" type="datetime-local" help="Если известна; время Ташкента" />
    </div>
    <Field label="Ключ события" name="canonical_event_id" required maxLength={200} help="Один ключ для одного решения или события во всех источниках." />
    <Field label="Темы материала" name="themes" maxLength={1000} help="До 10 тем через запятую, например: дивиденды, банки. Эти метки связывают материал с историей наблюдений." />
    <Field label="Оригинальный фрагмент"><textarea name="excerpt" maxLength={20000} required rows={5} /></Field>
    <div className="mkt-fields">
      <Field label="Факты в JSON" help={'Например: {"dividend":120}'}><textarea name="data" defaultValue="{}" spellCheck={false} /></Field>
      <Field label="Единицы в JSON" help={'Например: {"dividend":"UZS/share"}'}><textarea name="units" defaultValue="{}" spellCheck={false} /></Field>
      <Field label="Период данных" name="period" placeholder="2026-09-30" />
      <Field label="Стандарт отчётности" name="standard" placeholder="nsbu / ifrs" />
      <Field label="Периметр отчёта" name="scope" placeholder="separate / consolidated" />
      <Field label="Валюта данных" name="currency" defaultValue="UZS" />
    </div>
    <Field label="Связанный материал на UZStock" name="destination_url" type="url" placeholder="https://uzstock.uz/news/…" />
    <button className="mkt-primary" disabled={busy}>Импортировать</button>
  </form>;
}
