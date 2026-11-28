import { useState } from 'react';
import { Dialog, Field, Panel, date, number, experimentActions as decisions } from './Widgets.jsx';

const kpis = { news_open: 'Открытие новости', report_open: 'Открытие полного AI-разбора', chart_open: 'Открытие графика', issuer_open: 'Открытие эмитента', favorite: 'Добавление в избранное', registration: 'Завершённая регистрация' };
const reasons = { open_window: 'Окно набора или наблюдения ещё не завершено.', incomplete_coverage: 'Полнота нужных данных не подтверждена.', small_sample: 'Недостаточно читателей хотя бы в одном варианте.', creative_changed: 'Содержание выбранной публикации изменилось после фиксации дизайна.', account_changed: 'Аккаунт назначения изменился после фиксации дизайна.' };
const localDay = stamp => new Date(stamp + 5 * 3600000).toISOString().slice(0, 10);

function DesignForm({ data, request, busy, error, onDone }) {
  const [kpi, setKpi] = useState('news_open');
  const candidates = data.candidates.filter(item => item.publication_type === 'organic' && item.track_visits);
  async function save(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = Object.fromEntries(['title', 'hypothesis', 'segment', 'reader_question', 'tested_variable', 'comparison', 'stop_condition', 'starts_on', 'ends_on'].map(key => [key, form.get(key)]));
    Object.assign(value, { goal_version: data.active_goal.version, kpi, outcome_object_id: kpi === 'registration' ? '' : form.get('outcome_object_id'),
      minimum_observations: Number(form.get('minimum_observations')), followup_days: Number(form.get('followup_days')),
      control_ids: form.getAll('control_ids'), variant_ids: form.getAll('variant_ids') });
    if (await request('/editorial-experiments', { method: 'POST', body: { data: value }, message: 'Дизайн зафиксирован. Публикации и цель сохраняют свои отдельные правила.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <p>Цель: {data.active_goal.title} · версия {data.active_goal.version}. Дизайн сохраняется навсегда; для изменения условий создайте новый тест. Набор в прошлом будет отмечен как ретроспективный.</p>
    <Field label="Название теста" name="title" minLength={3} maxLength={2000} required />
    {[['hypothesis', 'Гипотеза'], ['segment', 'Сегмент читателей'], ['reader_question', 'Вопрос читателя'], ['tested_variable', 'Единственная переменная'], ['comparison', 'Условия сравнения'], ['stop_condition', 'Условие прекращения']].map(([key, label]) =>
      <Field key={key} label={label}><textarea name={key} minLength={3} maxLength={2000} rows={2} required /></Field>)}
    <p className="mkt-muted">Выберите разные публикации одного аккаунта и языка с включённым учётом переходов. Читатели обоих вариантов исключаются из сравнения.</p>
    {!candidates.length && <p>Подготовьте две органические публикации и включите учёт переходов в редакторе контента.</p>}
    <div className="mkt-fields">
      {[['control_ids', 'Контроль · публикации'], ['variant_ids', 'Новый вариант · публикации']].map(([name, label]) => <Field key={name} label={label}><select name={name} multiple size={4} required>{candidates.map(item => <option key={item.id} value={item.id}>{item.title} · {data.accounts.find(account => account.id === item.account_id)?.label} · {item.language}</option>)}</select></Field>)}
      <Field label="Целевое действие"><select value={kpi} onChange={event => setKpi(event.target.value)}>{Object.entries(kpis).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
      {kpi !== 'registration' && <Field label="Объект целевого действия" name="outcome_object_id" maxLength={200} required help="Точный ID объекта в подтверждённых событиях продукта: новости, отчёта, эмитента или графика. Действия с другими объектами не учитываются." />}
      <Field label="Начало набора" name="starts_on" type="date" defaultValue={localDay(Date.now())} required />
      <Field label="Конец набора, не включая" name="ends_on" type="date" defaultValue={localDay(Date.now()+7*86400000)} required />
      <Field label="Дней наблюдения после перехода" name="followup_days" type="number" min={1} max={30} step={1} defaultValue={7} required />
      <Field label="Минимум читателей в каждом варианте" name="minimum_observations" type="number" min={1} max={1000000} step={1} defaultValue={30} required />
    </div>
    <p>Условие прекращения проверяется владельцем. Фиксация дизайна не запускает и не останавливает публикации.</p>
    <button className="mkt-primary" disabled={busy || candidates.length < 2}>Зафиксировать дизайн</button>
  </form>;
}

function Evaluation({ item, evaluation, request, busy }) {
  const result = evaluation.result;
  async function decide(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    await request(`/editorial-experiments/${item.id}/decide`, { method: 'POST', body: { expected_version: item.version, evaluation_id: evaluation.id, action: form.get('action'), reason: form.get('reason') }, message: 'Решение сохранено с выбранной оценкой. Цель и бюджет не изменены.' });
  }
  return <div className="mkt-stack mkt-experiment-result">
    <h5>{result.status === 'preliminary' ? 'Предварительный результат' : 'Наблюдаемое сравнение'}</h5>
    <p>{result.dataset === 'test' ? 'Тестовые данные' : 'Рабочие данные'} · срез {new Date(result.cutoff).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' })} · Ташкент</p>
    <p>Это наблюдение за перешедшими читателями, без случайного распределения. Разница не доказывает причину и не измеряет конверсию всех увидевших пост.</p>
    {!!result.reasons.length && <ul>{result.reasons.map(key => <li key={key}>{reasons[key] || key}</li>)}</ul>}
    <div className="mkt-table-wrap" tabIndex={0} role="region" aria-label="Результаты: прокрутка по горизонтали"><table className="mkt-table" aria-label="Измеренные результаты"><thead><tr><th>Вариант</th><th>Читатели</th><th>Целевое действие</th><th>Доля, %</th></tr></thead><tbody>{[['control', 'Контроль'], ['variant', 'Новый вариант']].map(([key, label]) => <tr key={key}><th scope="row">{label}</th><td>{number(result.arms[key].readers)}</td><td>{number(result.arms[key].outcomes)}</td><td>{number(result.arms[key].rate)}</td></tr>)}</tbody></table></div>
    <p>Разница, п. п.: {result.difference_pp == null ? 'Не оценивается' : number(result.difference_pp)}. Один читатель и его целевое действие учитываются по одному разу.</p>
    <p>Исключены из обоих вариантов: {number(result.excluded_overlap)}. Уже зарегистрированы до перехода: {number(result.excluded_existing)}.</p>
    <details><summary>Данные и правила расчёта</summary><p>Формула: {result.formula_version}. Полное окно наблюдения: до {new Date(result.mature_at).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' })} · Ташкент.</p><p>Источники: {result.sources.join(' · ') || 'Нет подтверждённых событий'}</p>{Object.entries(result.coverage).map(([key, value]) => <p key={key}>{key === 'visits' ? 'Переходы' : key === 'activity' ? 'Действия продукта' : 'История регистраций'}: {value.status === 'complete' ? 'Полнота подтверждена' : 'Полнота не подтверждена'} · {value.confirmation?.reference || 'Нет подтверждения'}</p>)}</details>
    <form className="mkt-form" onSubmit={decide}>
      <Field label="Решение по формату"><select name="action" defaultValue="change">{Object.entries(decisions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
      <Field label="Обоснование решения"><textarea name="reason" minLength={3} maxLength={2000} rows={2} required /></Field>
      <p className="mkt-muted">Решение относится к выбранной оценке. Повтор или изменение требуют нового дизайна; остановка фиксирует решение и не управляет внешними публикациями.</p>
      <button disabled={busy}>Сохранить решение по оценке</button>
    </form>
  </div>;
}

function ExperimentCard({ item, evaluations, request, busy, onHistory }) {
  const [selected, setSelected] = useState('');
  const design = item.design;
  const evaluation = evaluations.find(row => row.id === selected) || evaluations[0];
  const decisionEvaluation = evaluations.find(row => row.id === item.decision?.evaluation_id);
  return <article className="mkt-item" aria-label={item.title}>
    <h4>{item.title}</h4><p className="mkt-muted">ID: {item.id}</p>
    <p>{design.timing === 'retrospective' ? 'Ретроспективное сравнение' : 'Дизайн зафиксирован до начала набора'} · {item.status === 'stopped' ? 'Принято решение остановить' : 'Дизайн зарегистрирован'}</p>
    <p>{design.hypothesis}</p><p>{date(design.starts_on)}–{date(design.ends_on)} (конец не включён) · наблюдение {design.followup_days} дн. · минимум {design.minimum_observations} читателей в каждом варианте.</p>
    <p>Целевое действие: {kpis[design.kpi]}{design.outcome_object_id && ` · ${design.outcome_object_id}`}.</p>
    <details><summary>Зафиксированный дизайн</summary><p>Сегмент: {design.segment}</p><p>Вопрос: {design.reader_question}</p><p>Переменная: {design.tested_variable}</p><p>Сравнение: {design.comparison}</p><p>Условие прекращения: {design.stop_condition}</p>{[['control', 'Контроль'], ['variant', 'Новый вариант']].map(([key, label]) => <p key={key}>{label}: {design[key+'_ids'].map(id => `${design.creatives[id].title} · v${design.creatives[id].version}`).join('; ')}</p>)}<p>Цель: {design.goal.title} · версия {design.goal.version}. Настройки и результаты теста не меняют её.</p></details>
    <div className="mkt-actions"><button disabled={busy} onClick={async () => { if (await request(`/editorial-experiments/${item.id}/evaluate`, { method: 'POST', body: { expected_version: item.version }, message: 'Новая оценка сохранена; предыдущие срезы остаются в истории.' })) setSelected(''); }}>Рассчитать и сохранить оценку</button><button onClick={() => onHistory('editorial_experiment', item.id, 'История решений по тесту')}>История решений</button></div>
    {item.decision && <div className="mkt-callout"><p>Сохранённое решение: {decisions[item.decision.action]} · оценка {date(decisionEvaluation?.result.cutoff)}</p><p>{item.decision.reason}</p>{evaluation?.id !== item.decision.evaluation_id && <p>Решение относится к другому сохранённому срезу.</p>}</div>}
    {!!evaluations.length && <Field label="Сохранённая оценка"><select value={evaluation.id} onChange={event => setSelected(event.target.value)}>{evaluations.map((row, index) => <option key={row.id} value={row.id}>Срез {evaluations.length-index} · {new Date(row.result.cutoff).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' })}</option>)}</select></Field>}
    {evaluation && <Evaluation key={evaluation.id} item={item} evaluation={evaluation} request={request} busy={busy} />}
  </article>;
}

export function EditorialExperiments({ data, request, busy, error, onHistory }) {
  const [open, setOpen] = useState(false);
  return <Panel title="Тесты рубрик" labelled>
    <p>Сравните две подачи по подтверждённым переходам и последующему действию. Сохраните условия до начала набора; поздняя регистрация дизайна явно отмечается.</p>
    <button disabled={!data.active_goal || busy} onClick={() => setOpen(true)}>Новый тест рубрики</button>
    {!data.active_goal && <p>Сначала утвердите цель.</p>}
    {(data.editorial_experiments || []).map(item => <ExperimentCard key={item.id} item={item} evaluations={(data.experiment_evaluations || []).filter(row => row.experiment_id === item.id).sort((a, b) => b.result.cutoff.localeCompare(a.result.cutoff))} request={request} busy={busy} onHistory={onHistory} />)}
    {open && <Dialog title="Дизайн теста рубрики" onClose={() => setOpen(false)}><DesignForm data={data} request={request} busy={busy} error={error} onDone={() => setOpen(false)} /></Dialog>}
  </Panel>;
}
