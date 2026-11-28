import { useState } from 'react';
import { Field, Status } from './Widgets.jsx';
import { contentFormats } from './ContentForm.jsx';
import { FounderSelection } from './FounderFacts.jsx';
import { InstagramLinkField } from './InstagramLinkField.jsx';
import { chartChoices } from './chartChoices.js';
import { OccasionField, occasionReady } from './OccasionField.jsx';
import { publicationFormats } from './providerFormats.js';

const languageNames = { ru: 'Русский', uz: 'O‘zbekcha', en: 'English' };

export function ProductionForm({ data, request, busy, assignment = null }) {
  const inputs = assignment?.item.preparation?.inputs || {};
  const saved = inputs.production;
  const preparing = assignment?.prepare;
  const localTime = value => new Date(new Date(value).getTime() + 5 * 3600000).toISOString().slice(0, 16);
  const [selected, setSelected] = useState(saved?.targets.map(target => target.account_id) || []);
  const [mode, setMode] = useState('draft');
  const [rubric, setRubric] = useState(assignment?.item.step.rubric || saved?.rubric || 'news');
  const [evidence, setEvidence] = useState(inputs.evidence_ids || []);
  const [series, setSeries] = useState(saved?.chart ? `${saved.chart.evidence_id}|${saved.chart.field}` : '');
  const [occasion, setOccasion] = useState(saved?.occasion || null);
  const originals = data.evidence.filter(row => evidence.includes(row.id));
  const choices = chartChoices(data.evidence, evidence);
  const chart = choices.find(choice => choice.key === series);
  const formatReady = selected.every(id => publicationFormats(data, data.accounts.find(account => account.id === id), rubric).length);
  const [problem, setProblem] = useState('');
  async function send(event) {
    event.preventDefault();
    setProblem('');
    const form = event.currentTarget;
    const f = new FormData(form);
    const targets = selected.map(id => ({ account_id: id, languages: f.getAll(`${id}:languages`),
      primary_language: f.get(`${id}:primary`), format: f.get(`${id}:format`), instagram_link: f.get(`${id}:instagram_link`) || 'none' }));
    if (!targets.length || !formatReady || targets.some(target => !target.languages.includes(target.primary_language))) {
      setProblem('Выберите аккаунты и включите основной язык в список подготавливаемых языков.'); return;
    }
    if (rubric === 'chart' && !chart) { setProblem('Выберите подтверждённый ряд из оригиналов этого задания.'); return; }
    if (!occasionReady(occasion, originals)) { setProblem('Выберите текущий подтверждённый оригинал повода с датой события.'); return; }
    const production = { event_id: f.get('event_id'), rubric, chart: rubric === 'chart' ? chart.ref : null, entity: f.get('entity'), period: f.get('period'), destination_url: f.get('destination_url') || '',
        expires_at: `${f.get('expires_at')}:00+05:00`, not_before: f.get('not_before') ? `${f.get('not_before')}:00+05:00` : null,
        mode: assignment ? 'draft' : mode, targets, founder_fact_ids: f.getAll('founder_fact_ids'), occasion };
    const body = assignment ? { expected_version: assignment.item.version, data: { evidence_ids: f.getAll('evidence'), production } }
      : { kind: 'content', message: f.get('message'), evidence_ids: f.getAll('evidence'), production };
    const result = await request(assignment ? `/plan-steps/${assignment.item.id}/${preparing ? 'prepare' : 'start'}` : '/tasks', { method: 'POST', body,
      message: preparing ? 'Черновик запланирован. Координатор дождётся даты и принятых результатов зависимостей.' : 'Команда получила задание. Каждый шаг и вариант сохраняется на сервере.' });
    if (result) { if (assignment) assignment.onDone(); else form.querySelector('[name="message"]').value = ''; }
  }
  return <form className="mkt-form" onSubmit={send}>
    {problem && <p role="alert" className="mkt-error">{problem}</p>}
    {assignment ? <p><strong>Ожидаемый результат:</strong> {assignment.item.step.deliverable}</p> : <Field label="Задание команде"><textarea name="message" required maxLength={12000} placeholder="Событие, аудитория, что объяснить и каких утверждений избегать" /></Field>}
    {preparing && <p className="mkt-callout">Автоматический старт готовит только внутренние черновики. Выбранные оригиналы, аккаунты и факты об основателе должны оставаться актуальными до завершения работы.</p>}
    <div className="mkt-fields">
      <Field label="Ключ события" name="event_id" required maxLength={200} defaultValue={saved?.event_id || ''} help="Один ключ для одного события. Повтор не запускает уже завершённый выпуск." />
      {assignment ? <p>Подготовка внутренних черновиков · {data.rubrics.find(row => row.id === assignment.item.step.rubric)?.name || assignment.item.step.rubric}. Публикация рассматривается отдельно.</p> : <><Field label="Режим подготовки"><select value={mode} onChange={e => setMode(e.target.value)}><option value="draft">Подготовить внутренние черновики</option><option value="account">Выпуск по действующим правилам аккаунтов</option></select></Field>
        <Field label="Рубрика задания"><select name="rubric" value={rubric} onChange={e => setRubric(e.target.value)}>{data.rubrics.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></Field></>}
      <Field label="Эмитент или тикер" name="entity" maxLength={100} defaultValue={saved?.entity || ''} />
      <Field label={rubric === 'calendar' ? 'Начало недели · понедельник' : 'Период задания'} name="period" type={rubric === 'calendar' ? 'date' : 'text'} required={rubric === 'calendar'} placeholder="2026Q3 или дата торгов" maxLength={40} defaultValue={saved?.period || ''} />
      <Field label="Точная ссылка для читателя" name="destination_url" type="url" maxLength={2000} defaultValue={saved?.destination_url || ''}
        help="Необязательно, если точная ссылка UZStock уже есть в выбранных оригиналах. Иначе укажите проверенный материал, график или разбор. Команда не может придумать адрес; без основания ссылка не пройдёт финальную проверку." />
      <Field label="Актуальность до · Ташкент" name="expires_at" type="datetime-local" required defaultValue={saved ? localTime(saved.expires_at) : new Date(Date.now() + 29 * 3600000).toISOString().slice(0, 16)} />
      <Field label="Публиковать не раньше · Ташкент" name="not_before" type="datetime-local" defaultValue={saved?.not_before ? localTime(saved.not_before) : ''} help="Необязательно. Команда может подготовить материалы заранее; отправка начнётся после этого времени в разрешённом окне." />
    </div>
    <p className="mkt-muted">Команда готовит отдельные языковые варианты. Основной язык выбирает одну версию для каждого аккаунта. Остальные варианты сохраняются для просмотра и ручного выбора.</p>
    {mode === 'account' && <p className="mkt-callout">После успешной проверки разрешённая органика попадёт в очередь автоматически. Ручные аккаунты ждут вашего решения, закрытые сохраняют черновики.</p>}
    <div className="mkt-fields">{data.accounts.map(account => {
      const formats = publicationFormats(data, account, rubric);
      const preferred = saved?.targets.find(target => target.account_id === account.id)?.format;
      return <fieldset key={account.id}>
      <legend>{account.label}</legend>
      <label className="mkt-checkbox"><input type="checkbox" checked={selected.includes(account.id)} onChange={e => setSelected(previous => e.target.checked ? [...previous, account.id] : previous.filter(id => id !== account.id))} />Подготовить для {account.label}</label>
      {selected.includes(account.id) && <div className="mkt-form">
        <div className="mkt-checks">{account.languages.map(language => <label key={language}><input type="checkbox" name={`${account.id}:languages`} value={language} defaultChecked={saved?.targets.find(target => target.account_id === account.id)?.languages.includes(language) ?? true} />{languageNames[language]}</label>)}</div>
        <Field label={`Основной язык · ${account.label}`}><select name={`${account.id}:primary`} defaultValue={saved?.targets.find(target => target.account_id === account.id)?.primary_language || account.languages[0]}>{account.languages.map(lang => <option key={lang} value={lang}>{languageNames[lang]}</option>)}</select></Field>
        <Field label={`Формат · ${account.label}`}><select name={`${account.id}:format`} key={`${rubric}:${formats.join(',')}`} required defaultValue={formats.includes(preferred) ? preferred : formats[0]}>{formats.map(id => <option key={id} value={id}>{contentFormats[id]}</option>)}</select></Field>
        {!formats.length && <p className="mkt-callout">Для этой рубрики нет разрешённого формата, поддерживаемого площадкой. Проверьте правила аккаунта или выберите другой аккаунт.</p>}
        {account.platform === 'instagram' && <InstagramLinkField name={`${account.id}:instagram_link`} label={`Переход из Instagram · ${account.label}`} value={saved?.targets.find(target => target.account_id === account.id)?.instagram_link || 'none'} />}
      </div>}
    </fieldset>; })}</div>
    {!data.accounts.length && <p>Добавьте аккаунты в настройках, чтобы подготовить версии для площадок.</p>}
    <fieldset><legend>Исходные оригиналы</legend><div className="mkt-checks">{data.evidence.map(item => <div key={item.id}><label><input type="checkbox" name="evidence" value={item.id} checked={evidence.includes(item.id)} onChange={e => {
      setEvidence(previous => e.target.checked ? [...previous, item.id] : previous.filter(id => id !== item.id));
      if (!e.target.checked && chart?.ref.evidence_id === item.id) setSeries('');
    }} />{item.title}</label><Status value={item.status} /></div>)}</div>{!data.evidence.length && <p>Сначала добавьте материалы в разделе «Источники».</p>}</fieldset>
    {rubric === 'chart' && <Field label="Ряд графика" help="Выберите оригинал выше и один ряд дат и значений с единицами. Один и тот же ряд используется во всех языковых версиях; период и выводы проверяются перед выпуском.">
      <select required value={chart?.key || ''} onChange={e => setSeries(e.target.value)}><option value="">Выберите подтверждённый ряд</option>{choices.map(choice => <option key={choice.key} value={choice.key}>{choice.label}</option>)}</select>
    </Field>}
    <OccasionField value={occasion} onChange={setOccasion} evidence={originals} />
    <FounderSelection data={data} selected={saved?.founder_fact_ids || []} />
    <button className="mkt-primary" disabled={busy || !data.accounts.length || !formatReady || rubric === 'chart' && !chart || !occasionReady(occasion, originals)}>{preparing ? 'Сохранить для автоматического старта' : assignment ? 'Назначить задачу' : 'Передать команде'}</button>
  </form>;
}
