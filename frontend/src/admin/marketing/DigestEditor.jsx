import { Field } from './Widgets.jsx';

export function DigestEditor({ items, onChange, evidence, calendar = false }) {
  const update = (index, changes) => onChange(items.map((item, position) => position === index ? { ...item, ...changes } : item));
  return <div className="mkt-stack">
    <p>{calendar ? 'Добавьте от одного до восьми объявленных событий выбранной недели. Перенос даты относится к тому же событию.' : 'Добавьте от двух до восьми разных событий.'} Каждый выбранный оригинал должен относиться к одному пункту. Даты, эмитенты и ссылки добавятся из оригиналов при сохранении.</p>
    {items.map((item, index) => <fieldset className="mkt-stack" key={index}><legend>Пункт {index + 1}</legend>
      <div className="mkt-checks">{evidence.map(original => <label key={original.id}>
        <input type="checkbox" checked={item.evidence_ids.includes(original.id)} onChange={event => update(index, {
          evidence_ids: event.target.checked ? [...item.evidence_ids, original.id] : item.evidence_ids.filter(id => id !== original.id),
        })} />{original.title}
      </label>)}</div>
      {!evidence.length && <p>Сначала выберите доказательства выше.</p>}
      <Field label={`Текст пункта ${index + 1}`}><textarea value={item.text} onChange={event => update(index, { text: event.target.value })} rows={4} maxLength={3000} required /></Field>
      <button type="button" aria-label={`Удалить пункт ${index + 1}`} onClick={() => onChange(items.filter((_, position) => position !== index))}>Удалить пункт</button>
    </fieldset>)}
    <button type="button" disabled={items.length >= 8} onClick={() => onChange([...items, { evidence_ids: [], text: '' }])}>{calendar ? 'Добавить пункт календаря' : 'Добавить пункт дайджеста'}</button>
  </div>;
}
