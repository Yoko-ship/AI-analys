import { useState } from 'react';
import { Dialog, Field, Panel, Status, date } from './Widgets.jsx';
import { FounderSelection } from './FounderFacts.jsx';
import { InstagramLinkField } from './InstagramLinkField.jsx';
import { contentFormats } from './ContentForm.jsx';
import { reasonText } from './reasonCopy.js';
import { publicationFormats } from './providerFormats.js';

const fields = ['title', 'strategy_id', 'strategy_version', 'source_ids', 'target', 'rubric', 'chart_field', 'digest_time', 'calendar_day', 'calendar_time', 'starts_on', 'ends_on', 'max_daily', 'max_age_hours', 'mode', 'priority', 'enabled', 'founder_fact_ids'];
const ruleData = rule => Object.fromEntries(fields.map(key => [key, rule[key]]));
const languageNames = { ru: 'Русский', uz: 'O‘zbekcha', en: 'English' };
const weekdays = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье'];

function RuleForm({ item, data, request, busy, error, onDone }) {
  const strategies = data.strategies.filter(value => value.status === 'approved' || value.id === item?.strategy_id);
  const [strategyId, setStrategy] = useState(item?.strategy_id || strategies[0]?.id || '');
  const [accountId, setAccount] = useState(item?.target.account_id || data.accounts[0]?.id || '');
  const [selectedPriority, setPriority] = useState(item?.priority || 'normal');
  const [selectedRubric, setRubric] = useState(item?.rubric || 'news');
  const [problem, setProblem] = useState('');
  const strategy = strategies.find(value => value.id === strategyId);
  const account = data.accounts.find(value => value.id === accountId);
  const rubrics = (data.editorial_rubrics || []).filter(value => strategy?.rubrics.includes(value.id) && account?.rubrics.includes(value.id));
  const rubric = rubrics.some(value => value.id === selectedRubric) ? selectedRubric : rubrics[0]?.id || '';
  const priority = rubric === 'news' ? selectedPriority : 'normal';
  const formats = publicationFormats(data, account, rubric);
  const savedTarget = item?.target.account_id === accountId ? item.target : null;
  async function submit(event) {
    event.preventDefault();
    setProblem('');
    const values = new FormData(event.currentTarget);
    const languages = values.getAll('languages'), primary = values.get('primary');
    if (!values.getAll('sources').length || !languages.includes(primary)) {
      setProblem('Выберите источники и включите основной язык в список языков подготовки.'); return;
    }
    const payload = { title: values.get('title'), strategy_id: strategyId, strategy_version: strategy.version,
      target: { account_id: accountId, languages, primary_language: primary, format: values.get('format'), instagram_link: values.get('instagram_link') || 'none' },
      source_ids: values.getAll('sources'), rubric: values.get('rubric'), starts_on: values.get('starts_on'), ends_on: values.get('ends_on'),
      digest_time: rubric === 'digest' ? values.get('digest_time') : '',
      calendar_time: rubric === 'calendar' ? values.get('calendar_time') : '',
      calendar_day: rubric === 'calendar' ? Number(values.get('calendar_day')) : 6,
      chart_field: rubric === 'chart' ? values.get('chart_field') : '',
      max_daily: Number(values.get('max_daily')), max_age_hours: rubric === 'calendar' ? item?.max_age_hours || 24 : Number(values.get('max_age_hours')), mode: values.get('mode'), priority,
      enabled: values.has('enabled'), founder_fact_ids: values.getAll('founder_fact_ids') };
    if (await request(`/editorial-rules/${item?.id || crypto.randomUUID()}`, { method: 'PUT', body: { data: payload, expected_version: item?.version || 0 },
      message: 'Правило сохранено. Координатор использует только проверенные события в заданных границах.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={submit}>
    <p>Выберите источники, рубрику и аккаунт. Координатор создаёт задания по новым проверенным событиям без открытого браузера. Дубликаты и перепечатки объединяются.</p>
    <Field label="Название правила" name="title" required maxLength={200} defaultValue={item?.title || ''} />
    <Field label="Утверждённая стратегия"><select required value={strategyId} onChange={event => setStrategy(event.target.value)}>
      <option value="" disabled>Сначала утвердите стратегию</option>{strategies.map(value => <option key={value.id} value={value.id}>{value.title} · версия {value.version}</option>)}
    </select></Field>
    <Field label="Аккаунт"><select required value={accountId} onChange={event => setAccount(event.target.value)}>
      <option value="" disabled>Сначала добавьте аккаунт</option>{data.accounts.map(value => <option key={value.id} value={value.id}>{value.label}</option>)}
    </select></Field>
    <Field label="Рубрика"><select name="rubric" required value={rubric} onChange={event => { setRubric(event.target.value); setPriority('normal'); }}>
      {rubrics.map(value => <option key={value.id} value={value.id}>{value.name}</option>)}
    </select></Field>
    {rubric === 'chart' && <Field label="Поле ряда в оригинале" name="chart_field" required maxLength={200} defaultValue={item?.chart_field || ''} placeholder="close"
      help="Укажите точное поле данных источника, например close. Нужны ряд дат и значений, единицы и ссылка на график UZStock. При конфликте оригиналов, пропущенных единицах или будущих наблюдениях событие не назначается." />}
    {account && <fieldset key={accountId}><legend>Версия для аккаунта</legend><div className="mkt-checks">
      {account.languages.map(language => <label key={language}><input type="checkbox" name="languages" value={language} defaultChecked={savedTarget ? savedTarget.languages.includes(language) : language === account.languages[0]} />{languageNames[language]}</label>)}
    </div><Field label="Основной язык"><select name="primary" defaultValue={savedTarget?.primary_language || account.languages[0]}>{account.languages.map(language => <option key={language} value={language}>{languageNames[language]}</option>)}</select></Field>
      <Field label="Формат"><select name="format" required key={rubric} defaultValue={formats.includes(savedTarget?.format) ? savedTarget.format : formats[0]}>{formats.map(format => <option key={format} value={format}>{contentFormats[format]}</option>)}</select></Field>
      {!formats.length && <p className="mkt-callout">{rubric === 'chart' ? 'Для графика нужен аккаунт с разрешённым медиаформатом.' : 'Для подборки нужен аккаунт с текстовыми постами. Выберите Telegram, Facebook или LinkedIn с разрешённым форматом.'}</p>}
      {account.platform === 'instagram' && <InstagramLinkField value={savedTarget?.instagram_link} />}
    </fieldset>}
    <fieldset><legend>Разрешённые источники</legend><div className="mkt-checks">{data.sources.map(source => <div key={source.id}>
      <label><input type="checkbox" name="sources" value={source.id} defaultChecked={item?.source_ids.includes(source.id)} />{source.name}</label><Status value={source.status} />
    </div>)}</div>{!data.sources.length && <p>Добавьте источник и получите первый материал в разделе источников.</p>}</fieldset>
    <div className="mkt-grid"><Field label="Начало периода" type="date" name="starts_on" required defaultValue={item?.starts_on || data.active_goal?.starts_on || ''} />
      <Field label="Конец периода" type="date" name="ends_on" required defaultValue={item?.ends_on || data.active_goal?.deadline || ''} /></div>
    {rubric === 'digest' && <Field label="Время подбора дайджеста · Ташкент" name="digest_time" type="time" required defaultValue={item?.digest_time || '18:00'}
      help="После этого времени координатор подбирает минимум два разных проверенных события за указанное число часов до среза. События, уже назначенные этому аккаунту, исключаются. Один выпуск на срез; если событий мало, выпуск пропускается." />}
    {rubric === 'calendar' && <>
      <Field label="День подбора календаря"><select name="calendar_day" defaultValue={item?.calendar_day ?? 6}>{weekdays.map((name, day) => <option key={day} value={day}>{name}</option>)}</select></Field>
      <Field label="Время подбора календаря · Ташкент" name="calendar_time" type="time" required defaultValue={item?.calendar_time || '18:00'}
        help="В воскресенье — события следующей недели; в остальные дни — оставшиеся события текущей. Один выпуск по правилу на неделю, до восьми событий. Пустая неделя не заполняется выдумками. Перенос остаётся тем же событием." />
      <p className="mkt-muted">Дата публикации объявления может быть старой: нужны действующий оригинал и будущая дата события внутри недели.</p>
      {item && !item.calendar_time && <p className="mkt-callout">Сохранение переведёт это правило отдельных событий на недельную подборку.</p>}
    </>}
    <Field label="Заданий за день" name="max_daily" type="number" required min={1} max={10} defaultValue={item?.max_daily || 1} help="Лимит новых заданий по этому правилу. День считается по времени Ташкента; изменения правила не обнуляют счётчик." />
    <Field label="Приоритет"><select value={priority} onChange={event => setPriority(event.target.value)}><option value="normal">Обычный</option>{rubric === 'news' && <option value="urgent">Срочная подтверждённая новость</option>}</select></Field>
    {rubric !== 'calendar' && <Field label="Возраст события, часов" name="max_age_hours" type="number" required min={1} max={priority === 'urgent' ? 24 : 168} defaultValue={item?.max_age_hours || 24}
      help={rubric === 'digest' ? 'Глубина подборки до времени среза. Используется самая ранняя известная дата оригинала или события; поздняя перепечатка не делает событие новым.' : rubric === 'quarterly' ? 'Возраст первого опубликованного разбора этого квартала. Повторная генерация не обновляет возраст. Даты исходной отчётности сохраняются отдельно; само раскрытие ещё не запускает подготовку.' : 'Для срочных — только новости до 24 часов. Возраст считается по самому раннему известному оригиналу; перепечатка его не обновляет.'} />}
    <Field label="Результат работы"><select name="mode" defaultValue={item?.mode || 'draft'}><option value="draft">Только черновики</option><option value="account">По текущим правилам аккаунта</option></select></Field>
    <p className="mkt-muted">Для выпуска действуют отдельные разрешения аккаунта, финальная проверка, окно и интервал публикаций. Непроверенный материал не отправляется. Срочность меняет только порядок.</p>
    <FounderSelection data={data} selected={item?.founder_fact_ids} />
    <label className="mkt-checkbox"><input type="checkbox" name="enabled" defaultChecked={item?.enabled || false} />Включить автоматический выбор</label>
    {item && <p>Изменение или отключение правила останавливает ещё не выпущенные задания прежней версии. История и терминальные пропуски сохраняются.</p>}
    {(problem || error) && <p role="alert" className="mkt-error">{problem || error}</p>}
    <button className="mkt-primary" disabled={busy || !strategy || !account || !formats.length}>Сохранить правило</button>
  </form>;
}

export function EditorialRules({ data, request, busy, error, onHistory, onInspectTask }) {
  const [editing, setEditing] = useState(null);
  const close = () => setEditing(null);
  return <Panel title="Автоматический выбор событий" action={<button onClick={() => setEditing({})}>Добавить редакционное правило</button>}>
    <p className="mkt-muted">Выбор новостей, итогов торгов, дивидендных решений, объявленных дат, готовых квартальных разборов UZStock, графиков по подтверждённым рядам и дайджестов к заданному времени. Правило связывает утверждённую стратегию, источники и один аккаунт. Начните с черновиков; включайте выпуск после проверки пилота и разрешений площадки.</p>
    {data.pause.processing && <p className="mkt-callout">Обработка остановлена: новые события не назначаются.</p>}
    {!(data.editorial_rules || []).length && <p>Правил пока нет. Автоматический выбор событий отключён.</p>}
    {(data.editorial_rules || []).map(item => {
      const tasks = data.tasks.filter(task => task.editorial?.rule_id === item.id);
      const strategy = data.strategies.find(value => value.id === item.strategy_id);
      return <article className="mkt-item" key={item.id} aria-label={item.title}>
        <div className="mkt-row mkt-between"><h4>{item.title}</h4><Status value={item.readiness.status} /></div>
        <p>{data.accounts.find(value => value.id === item.target.account_id)?.label || item.target.account_id} · {data.rubrics.find(value => value.id === item.rubric)?.name || item.rubric} · {item.mode === 'draft' ? 'Только черновики' : 'По правилам аккаунта'}</p>
        <p>{strategy?.title || 'Стратегия'} · версия {item.strategy_version} · {date(item.starts_on)}–{date(item.ends_on)}</p>
        <p>{item.priority === 'urgent' ? 'Срочная подтверждённая новость' : 'Обычный приоритет'} · лимит в день: {item.max_daily}{!item.calendar_time && ` · возраст до ${item.max_age_hours} ч`}</p>
        {item.rubric === 'digest' && <p>Срез дайджеста · {item.digest_time} · Ташкент</p>}
        {item.calendar_time && <p>Еженедельный календарь · {weekdays[item.calendar_day]} · {item.calendar_time} · Ташкент</p>}
        {item.rubric === 'chart' && <p>Поле ряда · {item.chart_field}</p>}
        <p>Источники: {item.source_ids.map(id => data.sources.find(source => source.id === id)?.name || id).join(', ')}</p>
        {item.readiness.reason && <p>{reasonText(item.readiness.reason)}</p>}
        {item.runtime && <p>{reasonText(item.runtime.reason)} · {date(item.runtime.checked_at)}</p>}
        <div className="mkt-actions"><button disabled={busy} onClick={() => setEditing(item)}>Изменить правило</button>
          {item.enabled && <button disabled={busy} onClick={() => request(`/editorial-rules/${item.id}`, { method: 'PUT', body: { data: { ...ruleData(item), enabled: false }, expected_version: item.version }, message: 'Правило отключено; незавершённые назначения остановятся.' })}>Отключить правило</button>}
          <button onClick={() => onHistory('editorial_rule', item.id, 'История правила')}>История правила</button></div>
        {!!tasks.length && <details open><summary>Выбранные события · {tasks.length}</summary><ul className="mkt-history">{tasks.map(task => <li key={task.id}>
          <strong>{task.title}</strong> <Status value={task.status} /><p>{reasonText(task.reason)}</p>
          <small>Правило · версия {task.editorial.rule_version} · событие {date(task.editorial.event_at)}</small>
          <p><button onClick={() => onInspectTask(task)}>Передачи выбранного события</button></p>
        </li>)}</ul></details>}
      </article>;
    })}
    {editing && <Dialog title={editing.id ? 'Изменить редакционное правило' : 'Новое редакционное правило'} onClose={close}>
      <RuleForm item={editing.id ? editing : null} {...{ data, request, busy, error }} onDone={close} />
    </Dialog>}
  </Panel>;
}
