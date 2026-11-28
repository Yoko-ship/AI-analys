import { useState } from 'react';
import { Field } from './Widgets.jsx';
import { FounderSelection } from './FounderFacts.jsx';
import { EvidenceSelection } from './EvidenceSelection.jsx';
import { InstagramLinkField } from './InstagramLinkField.jsx';
import { DigestEditor } from './DigestEditor.jsx';
import { OccasionField, occasionReady } from './OccasionField.jsx';
import { publicationFormats } from './providerFormats.js';

export const contentFormats = { post: 'Текстовый пост', image: 'Изображение', carousel: 'Карусель', video: 'Видео', story: 'Stories' };
const localTime = value => new Date(new Date(value).getTime() + 5 * 3600000).toISOString().slice(0, 16);

export function ContentForm({ item, data, request, error, busy, onDone }) {
  const [selected, setSelected] = useState(item?.evidence_ids || []);
  const [mode, setMode] = useState(item?.mode || 'manual');
  const [problem, setProblem] = useState('');
  const [accountId, setAccountId] = useState(item?.account_id || data.accounts[0]?.id || '');
  const [rubric, setRubric] = useState(item?.rubric || 'news');
  const [digestItems, setDigestItems] = useState(item?.digest_items || []);
  const [occasion, setOccasion] = useState(item?.occasion || null);
  const originals = data.evidence.filter(row => selected.includes(row.id));
  const account = data.accounts.find(value => value.id === accountId);
  const instagram = account?.platform === 'instagram';
  const calendar = rubric === 'calendar';
  const structured = rubric === 'digest' || calendar && (!item || item.digest_items?.length);
  const formats = publicationFormats(data, account, rubric);
  const digestSupported = formats.length > 0;
  async function save(event) {
    event.preventDefault();
    setProblem('');
    const f = new FormData(event.currentTarget);
    if (!occasionReady(occasion, originals)) { setProblem('Выберите текущий подтверждённый оригинал повода с датой события.'); return; }
    if (structured && (digestItems.length < (calendar ? 1 : 2) || digestItems.some(entry => !entry.evidence_ids.length
      || entry.evidence_ids.some(id => !selected.includes(id))) || selected.some(id => !digestItems.some(entry => entry.evidence_ids.includes(id))))) {
      setProblem(calendar ? 'Добавьте минимум одно событие недели и распределите выбранные оригиналы по пунктам.' : 'Добавьте минимум два пункта и распределите выбранные оригиналы по событиям.'); return;
    }
    let calculation;
    try { calculation = f.get('calculation') ? JSON.parse(f.get('calculation')) : null; }
    catch { setProblem('Расчёт должен быть JSON-объектом или пустым полем.'); return; }
    const value = { title: f.get('title'), body: structured ? item?.body || (calendar ? 'Календарь' : 'Дайджест') : f.get('body'),
      digest_items: structured ? digestItems : [], evidence_ids: selected, destination_url: f.get('destination_url'), track_visits: f.has('track_visits'),
      expires_at: `${f.get('expires_at')}:00+05:00`, not_before: f.get('not_before') ? `${f.get('not_before')}:00+05:00` : null,
      calculation, founder_fact_ids: f.getAll('founder_fact_ids'), instagram_link: instagram ? f.get('instagram_link') : 'none', occasion,
      claims: f.getAll('claims').map(value => JSON.parse(value)).filter(claim => selected.includes(claim.evidence_id)),
    };
    let result;
    if (item) result = await request(`/candidates/${item.id}`, { method: 'PATCH', body: { expected_version: item.version, changes: value }, message: 'Новая версия сохранена. Проверка и разрешение нужны заново.' });
    else result = await request('/candidates', { method: 'POST', body: { ...value, publication_type: f.get('publication_type'), event_id: f.get('event_id'), account_id: f.get('account_id'), rubric: f.get('rubric'), language: f.get('language'), format: f.get('format'), entity: f.get('entity'), period: f.get('period'), mode }, message: 'Материал сохранён вместе с доказательствами.' });
    if (result) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>
    {(problem || error) && <p role="alert" className="mkt-error">{problem || error}</p>}
    {!item ? <>
      <Field label="Ключ события" name="event_id" maxLength={200} required help="Повтор одного события в том же аккаунте вернёт существующий материал." />
      <div className="mkt-fields">
        <Field label="Назначение материала" help="Платный креатив проходит фактчекинг здесь, а разрешение рекламного действия — в экспериментах."><select name="publication_type"><option value="organic">Органическая публикация</option><option value="paid">Платный креатив</option></select></Field>
        <Field label="Целевой аккаунт"><select name="account_id" value={accountId} onChange={e => setAccountId(e.target.value)} required>{data.accounts.map(account => <option key={account.id} value={account.id}>{account.label}</option>)}</select></Field>
        <Field label="Режим материала"><select value={mode} onChange={e => setMode(e.target.value)}><option value="draft">Только черновик</option><option value="manual">Проверка и моё решение</option><option value="automatic">Автоматическая финальная проверка</option></select></Field>
        <Field label="Рубрика"><select name="rubric" value={rubric} onChange={event => setRubric(event.target.value)}>{data.rubrics.map(rubric => <option key={rubric.id} value={rubric.id}>{rubric.name}</option>)}</select></Field>
        <Field label="Язык материала"><select name="language"><option value="ru">Русский</option><option value="uz">O‘zbekcha</option><option value="en">English</option></select></Field>
        <Field label="Формат материала"><select key={`${rubric}:${accountId}`} name="format" required>{formats.map(id => <option key={id} value={id}>{contentFormats[id]}</option>)}</select></Field>
        <Field label="Эмитент или тикер" name="entity" maxLength={100} />
        <Field label={calendar ? 'Начало недели · понедельник' : 'Период материала'} name="period" type={calendar ? 'date' : 'text'} required={calendar} placeholder="2026Q3 или дата торгов" maxLength={40} />
      </div>
      {mode === 'automatic' && <p className="mkt-callout">Неудачная финальная проверка завершает этот материал со статусом «Пропущен». Повтор события не возобновляет его. Разрешение аккаунта проверяется отдельно.</p>}
    </> : <p>Событие: {item.event_id} · {data.accounts.find(a => a.id === item.account_id)?.label || item.account_id} · {item.language.toUpperCase()} · версия {item.version}. Правка отменяет прежнюю проверку и одобрение.</p>}
    <Field label="Заголовок материала" name="title" defaultValue={item?.title || ''} maxLength={300} required />
    {structured ? <p className="mkt-callout">{calendar ? 'Календарь собирается из пунктов ниже по датам событий. Объявленная выплата не означает, что деньги уже выплачены.' : 'Текст дайджеста собирается из пунктов ниже.'} Сейчас доступен текстовый пост для Telegram, Facebook или LinkedIn.</p>
      : <Field label="Текст публикации"><textarea name="body" defaultValue={item?.body || ''} rows={7} maxLength={20000} required /></Field>}
    {!digestSupported && <p className="mkt-callout">{structured ? 'Выбранный аккаунт не поддерживает эту текстовую подборку. Выберите аккаунт с разрешёнными текстовыми постами.' : 'Нет разрешённого поддерживаемого формата для этой рубрики. Проверьте правила аккаунта.'}</p>}
    <Field label="Прямая ссылка на UZStock" name="destination_url" type="url" defaultValue={item?.destination_url || ''} required
      help={item?.origin_task ? 'Укажите проверенную точную ссылку на новость, график или разбор. Сохранение фиксирует ваш выбор ссылки; факты и разрешение на выпуск проверяются отдельно.' : 'Ссылка на конкретную новость, график или разбор.'} />
    <label className="mkt-check"><input type="checkbox" name="track_visits" defaultChecked={item ? Boolean(item.track_visits) : true} />Связать переходы с этой публикацией</label>
    <p className="mkt-muted">Метка добавляется в ссылку для отправки. Набор данных берётся из настроек отчёта при сохранении; готовый адрес виден перед утверждением. Переходы учитываются отдельно от кликов площадки.</p>
    {structured && <p className="mkt-muted">Метка учитывает переходы по основной ссылке. Ссылки остальных пунктов остаются прямыми.</p>}
    {instagram && <InstagramLinkField key={accountId} value={item?.instagram_link || 'none'} />}
    <Field label="Актуален до · Ташкент" name="expires_at" type="datetime-local" defaultValue={localTime(item?.expires_at || Date.now() + 86400000)} required />
    <Field label="Публиковать не раньше · Ташкент" name="not_before" type="datetime-local" defaultValue={item?.not_before ? localTime(item.not_before) : ''} help="Оставьте пустым для ближайшего разрешённого окна. Время должно быть раньше срока актуальности. Изменение времени требует повторной проверки и одобрения ручного материала." />
    <EvidenceSelection evidence={data.evidence} selected={selected} onChange={setSelected} claims={item?.claims} />
    <OccasionField value={occasion} onChange={setOccasion} evidence={originals} />
    {structured && <DigestEditor calendar={calendar} items={digestItems} onChange={setDigestItems} evidence={data.evidence.filter(original => selected.includes(original.id))} />}
    <details><summary>Вычисление из оригиналов</summary><Field label="Воспроизводимый расчёт · JSON" help="Для разницы периодов: operation=difference, field, left и right — ID двух оригиналов, value — результат."><textarea name="calculation" spellCheck={false} defaultValue={item?.calculation ? JSON.stringify(item.calculation, null, 2) : ''} /></Field></details>
    <FounderSelection data={data} selected={item?.founder_fact_ids} />
    <button className="mkt-primary" disabled={busy || !digestSupported || (!item && !data.accounts.length) || !occasionReady(occasion, originals)}>Сохранить материал</button>
  </form>;
}
