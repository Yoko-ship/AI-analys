import { useState } from 'react';
import { Dialog, Field, Panel, SafeLink, Status, date } from './Widgets.jsx';

const languages = { ru: 'Русский', uz: 'O‘zbekcha', en: 'English' };
const categories = { role: 'Роль', experience: 'Опыт', achievement: 'Достижение', product: 'Факт о продукте' };

function FactForm({ item, request, busy, error, onDone }) {
  async function submit(event) {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const wordings = Object.fromEntries(Object.keys(languages).map(lang => [lang, String(f.get(lang)).split('\n').map(text => text.trim()).filter(Boolean)]).filter(([, rows]) => rows.length));
    const data = { title: f.get('title'), category: f.get('category'), proof_url: f.get('proof_url'), verification_note: f.get('verification_note'),
      wordings, valid_until: `${f.get('valid_until')}T23:59:00+05:00`, status: f.has('confirmed') ? 'verified' : 'draft' };
    if (await request(`/founder-facts/${item?.id || crypto.randomUUID()}`, { method: 'PUT', body: { data, expected_version: item?.version || 0 }, message: 'Факт и разрешённые формулировки сохранены с новой версией.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={submit}>
    <Field label="Название факта" name="title" defaultValue={item?.title || ''} required maxLength={200} />
    <Field label="Категория факта"><select name="category" defaultValue={item?.category || 'role'}>{Object.entries(categories).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
    <Field label="Подтверждающая ссылка" name="proof_url" type="url" defaultValue={item?.proof_url || ''} required />
    <Field label="Основание подтверждения"><textarea name="verification_note" required maxLength={2000} defaultValue={item?.verification_note || ''} /></Field>
    <p className="mkt-muted">Одна разрешённая фраза на строку. Личные утверждения используются дословно; переводы подтверждаются отдельно. Заполните хотя бы один язык.</p>
    {Object.entries(languages).map(([lang, label]) => <Field key={lang} label={`Разрешённые формулировки · ${label}`}><textarea name={lang} defaultValue={item?.wordings[lang]?.join('\n') || ''} maxLength={20000} /></Field>)}
    <Field label="Факт действителен до" name="valid_until" type="date" defaultValue={item?.valid_until?.slice(0, 10) || new Date(Date.now() + 180 * 86400000).toISOString().slice(0, 10)} required />
    <label className="mkt-checkbox"><input type="checkbox" name="confirmed" defaultChecked={item?.status === 'verified'} />Я проверил факт и разрешаю эти формулировки</label>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <button className="mkt-primary" disabled={busy}>Сохранить факт</button>
  </form>;
}

export function FounderFacts({ data, request, busy, error, onHistory }) {
  const [editing, setEditing] = useState(null);
  const close = () => setEditing(null);
  return <Panel title="Карта фактов основателя" action={<button onClick={() => setEditing({})}>Добавить факт основателя</button>}>
    <p className="mkt-muted">Подтверждённые роли, опыт, достижения и факты о продукте для личного профиля. Отзыв или изменение факта останавливает выпуск ранее проверенной версии.</p>
    {!data.founder_facts.length && <p>Фактов пока нет. Команда не может придумывать личный опыт или цитаты.</p>}
    {data.founder_facts.map(item => <article className="mkt-item" key={item.id}>
      <div className="mkt-row mkt-between"><h4>{item.title}</h4><Status value={item.status} /></div>
      <p>{categories[item.category]} · до {date(item.valid_until)} · версия {item.version}</p>
      {Object.entries(item.wordings).map(([lang, wordings]) => <div key={lang}><strong>{languages[lang]}</strong>{wordings.map((wording, i) => <p key={i}>{wording}</p>)}</div>)}
      <p><SafeLink href={item.proof_url}>Подтверждение ↗</SafeLink> · {item.verification_note}</p>
      <div className="mkt-actions"><button onClick={() => setEditing(item)}>Изменить факт</button>
        {item.status !== 'disabled' && <button disabled={busy} onClick={() => request(`/founder-facts/${item.id}/revoke`, { method: 'POST', body: { expected_version: item.version } })}>Отозвать факт</button>}
        <button onClick={() => onHistory('founder_fact', item.id, 'История факта')}>История факта</button></div>
    </article>)}
    {editing && <Dialog title={editing.id ? 'Изменить факт' : 'Новый факт основателя'} onClose={close}><FactForm item={editing.id ? editing : null} request={request} busy={busy} error={error} onDone={close} /></Dialog>}
  </Panel>;
}

export function FounderSelection({ data, selected = [] }) {
  const facts = data.founder_facts.filter(item => item.status === 'verified' || selected.includes(item.id));
  if (!facts.length) return null;
  return <fieldset><legend>Карта фактов основателя</legend><div className="mkt-checks">{facts.map(item => <div key={item.id}>
    <label><input type="checkbox" name="founder_fact_ids" value={item.id} defaultChecked={selected.includes(item.id)} disabled={item.status !== 'verified'} />{item.title}</label>
    <details><summary>Разрешённые формулировки</summary>{Object.entries(item.wordings).map(([lang, values]) => <p key={lang}>{languages[lang]}: {values.join(' / ')}</p>)}<Status value={item.status} /></details>
  </div>)}</div></fieldset>;
}
