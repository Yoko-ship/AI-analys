import { useState } from 'react';
import { Field, Panel, SafeLink, date, number } from './Widgets.jsx';

const labels = { new_event: 'Новое событие', recurring_theme: 'Повторяющаяся тема', measured_growth: 'Измеряемый рост интереса', editorial_hypothesis: 'Редакционная гипотеза' };
const signed = value => `${value > 0 ? '+' : ''}${number(value)}`;

export function TrendObservations({ items = [], onEdit, onHistory }) {
  return <Panel title="Наблюдения тем" labelled action={<button onClick={() => onEdit(null)}>Сравнить наблюдения темы</button>}>
    <p className="mkt-muted">Сравниваем два соседних окна одинаковой длины в выбранных источниках. Темы задаются при импорте; перепечатки одного события считаются один раз. Это наблюдения выбранной подборки, а не всего рынка.</p>
    {!items.length && <p>История сравнений пока не создана. Без проверки полноты можно сохранить наблюдение без вывода о росте.</p>}
    {items.map(item => <article className="mkt-item" key={item.id}>
      <h4>{item.theme}</h4>
      {item.review_status === 'stale' ? <p className="mkt-error">Данные изменились после проверки. Сравнение требует пересмотра; ниже сохранённые числа прежней версии.</p> : <p><strong>{labels[item.classification]}</strong> · по состоянию на конец выбранного окна</p>}
      <div className="mkt-table-wrap"><table className="mkt-theme-table"><caption>История упоминаний · {item.theme}</caption><thead><tr><th scope="col">Показатель</th><th scope="col">База<br />{date(item.baseline.starts_on)}<br />до {date(item.baseline.ends_on)}</th><th scope="col">Текущее окно<br />{date(item.current.starts_on)}<br />до {date(item.current.ends_on)}</th></tr></thead><tbody>
        <tr><th scope="row">Упоминания без перепечаток</th><td>{number(item.baseline.mentions)}</td><td>{number(item.current.mentions)}</td></tr>
        <tr><th scope="row">Уникальные источники упоминаний</th><td>{number(item.baseline.source_ids.length)}</td><td>{number(item.current.source_ids.length)}</td></tr>
      </tbody></table></div>
      <p className="mkt-muted">Границы — полночь Ташкента; конец каждого окна не включён. Самое свежее упоминание в текущем окне: {item.current.latest_published_at ? date(item.current.latest_published_at) : 'Нет наблюдений'}.</p>
      {item.growth ? <p><strong>Изменение: {signed(item.growth.absolute)}</strong> · {item.growth.percent == null ? 'Процент не рассчитан: база равна нулю' : `${signed(item.growth.percent)}%`}</p> : <p>Рост интереса не измерен: {item.review_status === 'stale' ? 'нужна повторная проверка.' : 'полнота сопоставимых окон не подтверждена.'}</p>}
      <p><strong>Выбранные источники:</strong> {item.basis.sources.map(source => source.name).join(', ')}</p>
      <p><strong>Связь с аудиторией:</strong> {item.audience_relevance}</p>
      <p><strong>Риск:</strong> {item.risk}</p>
      <p><strong>Формат для проверки:</strong> {item.proposed_format}</p>
      <p className="mkt-muted">Релевантность и формат — редакционные оценки. Вовлечённость аудитории не измерялась.</p>
      <details><summary>Основание и оригиналы</summary>
        <p>Проверка: {date(item.reviewed_at)}. {item.review_reason || 'Полнота не подтверждена.'}</p>
        <p>Ранние оригиналы учитываются, чтобы поздняя перепечатка не стала новым событием. Один ключ события или одна ссылка объединяет материалы; остальные перепечатки нужно сверить при проверке.</p>
        {item.basis.evidence.map(original => <div className="mkt-item" key={original.id}><SafeLink href={original.url}>{original.title} ↗</SafeLink><p>{date(original.published_at)} · версия {original.version}</p><button onClick={() => onHistory('evidence', original.id, 'Версии оригинала')}>Версии оригинала</button></div>)}
      </details>
      <div className="mkt-actions"><button onClick={() => onEdit(item)}>Пересмотреть наблюдение</button><button onClick={() => onHistory('trend', item.id, 'История наблюдения')}>История наблюдения</button></div>
    </article>)}
  </Panel>;
}

export function TrendForm({ item, sources, request, busy, error, onDone }) {
  const [complete, setComplete] = useState(false), [problem, setProblem] = useState('');
  async function save(event) {
    event.preventDefault();
    setProblem('');
    const form = new FormData(event.currentTarget);
    const data = Object.fromEntries(['theme', 'starts_on', 'ends_on', 'review_reason', 'audience_relevance', 'risk', 'proposed_format'].map(key => [key, form.get(key).trim()]));
    data.source_ids = form.getAll('source_ids');
    data.complete = complete;
    if (!data.source_ids.length) { setProblem('Выберите хотя бы один источник.'); return; }
    const days = (Date.parse(data.ends_on) - Date.parse(data.starts_on)) / 86400000;
    if (days < 1 || days > 90) { setProblem('Длина окна — от 1 до 90 полных дней.'); return; }
    if (complete && !data.review_reason) { setProblem('Запишите, как проверены обе полные подборки и перепечатки.'); return; }
    if (await request(`/trends/${item?.id || crypto.randomUUID()}`, { method: 'PUT', body: { data, expected_version: item?.version || 0 }, message: 'Наблюдение сохранено с датами и версиями оригиналов.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>
    {(problem || error) && <p role="alert" className="mkt-error">{problem || error}</p>}
    <Field label="Тема для сравнения" name="theme" required maxLength={100} defaultValue={item?.theme || ''} help="Должна совпадать с темой в импортированных материалах. Регистр не учитывается." />
    <fieldset><legend>Одинаковая подборка источников для обоих окон</legend><div className="mkt-checks">{sources.map(source => <label key={source.id}><input type="checkbox" name="source_ids" value={source.id} defaultChecked={item?.source_ids.includes(source.id)} />{source.name}</label>)}</div></fieldset>
    <div className="mkt-fields">
      <Field label="Начало текущего окна" name="starts_on" type="date" required defaultValue={item?.starts_on || ''} />
      <Field label="Конец окна, не включая" name="ends_on" type="date" required defaultValue={item?.ends_on || ''} />
    </div>
    <p className="mkt-muted">База — непосредственно предыдущее окно той же длины. Только завершённые дни, от 1 до 90 дней в окне. Считаем по дате первой публикации, а не по времени загрузки.</p>
    <label className="mkt-checkbox"><input type="checkbox" checked={complete} onChange={event => setComplete(event.target.checked)} />Оба окна полны, темы и перепечатки проверены</label>
    <p className="mkt-muted">Отметьте только после сверки полных выгрузок всех выбранных источников за оба периода и всех тем материала. Успешный сбор RSS не подтверждает полноту. Без отметки сохранятся только наблюдаемые числа.</p>
    <Field label="Основание проверки полноты"><textarea name="review_reason" required={complete} defaultValue={item?.review_reason || ''} maxLength={2000} /></Field>
    <Field label="Связь с аудиторией"><textarea name="audience_relevance" required defaultValue={item?.audience_relevance || ''} maxLength={2000} /></Field>
    <Field label="Риск интерпретации"><textarea name="risk" required defaultValue={item?.risk || ''} maxLength={2000} /></Field>
    <Field label="Предлагаемый формат" name="proposed_format" required defaultValue={item?.proposed_format || ''} maxLength={500} />
    <button className="mkt-primary" disabled={busy}>Сохранить наблюдение</button>
  </form>;
}
