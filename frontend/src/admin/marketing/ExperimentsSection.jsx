import { useState } from 'react';
import { Dialog, Field, Panel, SafeLink, Status, date, number } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';
import { EditorialExperiments } from './EditorialExperiments.jsx';

const actions = { create: 'Создать кампанию в кабинете', launch: 'Запустить кампанию', extend: 'Продлить кампанию', increase_limit: 'Повысить лимит', paid_placement: 'Оплатить размещение' };
const localTime = value => new Date(new Date(value).getTime() + 5 * 3600000).toISOString().slice(0, 16);

function ExperimentForm({ item, data, request, error, busy, onDone }) {
  const [platform, setPlatform] = useState(item?.platform || 'telegram');
  const goal = data.active_goal;
  const stamp = Date.now(), today = localTime(stamp).slice(0, 10), tomorrow = localTime(stamp + 86400000).slice(0, 10);
  const creatives = data.candidates.filter(candidate => candidate.publication_type === 'paid' && data.accounts.find(account => account.id === candidate.account_id)?.platform === platform);
  async function save(event) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = Object.fromEntries(['title', 'advertiser_account_id', 'campaign_ref', 'action', 'hypothesis', 'reader_question', 'tested_variable', 'audience', 'comparison', 'measurement', 'evaluation_starts_on', 'evaluation_ends_on', 'currency', 'stop_condition', 'creative_brief', 'policy_reference', 'policy_review'].map(key => [key, form.get(key)]));
    Object.assign(value, { goal_version: goal.version, platform, budget_limit: Number(form.get('budget_limit')), placements: form.get('placements').split('\n').map(value => value.trim()).filter(Boolean),
      starts_at: `${form.get('starts_at')}:00+05:00`, ends_at: `${form.get('ends_at')}:00+05:00`, candidate_ids: form.getAll('candidate_ids'),
      minimum_observations: form.get('minimum_observations') ? Number(form.get('minimum_observations')) : null,
      policy_reviewed_on: form.get('policy_reviewed_on') || null, policy_review_valid_until: form.get('policy_review_valid_until') || null });
    if (await request(item ? `/experiments/${item.id}` : '/experiments', { method: item ? 'PUT' : 'POST', body: { data: value, expected_version: item?.version || 0 }, message: 'Предложение сохранено. Для этой версии нужно отдельное решение о платном действии.' })) onDone();
  }
  const prose = [['hypothesis', 'Гипотеза'], ['reader_question', 'Вопрос читателя'], ['tested_variable', 'Единственная проверяемая переменная'], ['audience', 'Аудитория'], ['comparison', 'Контроль или вариант сравнения'], ['measurement', 'Что и как измеряем'], ['stop_condition', 'Условие остановки'], ['creative_brief', 'Бриф креатива']];
  return <form className="mkt-form" onSubmit={save}>
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <p>Цель: {goal.title} · версия {goal.version}. Предложение не создаёт кампанию в рекламном кабинете и не расходует бюджет.</p>
    {item?.approval && <p className="mkt-callout">Сохранение новой версии отменит прежнее разрешение. Согласованные параметры останутся в истории.</p>}
    <Field label="Название эксперимента" name="title" defaultValue={item?.title || ''} maxLength={300} minLength={3} required />
    <div className="mkt-fields">
      <Field label="Рекламная площадка"><select value={platform} onChange={event => setPlatform(event.target.value)}>{data.platforms.map(value => <option value={value.id} key={value.id}>{value.name}</option>)}</select></Field>
      <Field label="Платное действие"><select name="action" defaultValue={item?.action || 'launch'}>{Object.entries(actions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field>
      <Field label="Рекламный кабинет" name="advertiser_account_id" defaultValue={item?.advertiser_account_id || ''} maxLength={200} required help="Идентификатор кабинета рекламодателя. Права на органические посты его не заменяют." />
      <Field label="Кампания или размещение" name="campaign_ref" defaultValue={item?.campaign_ref || ''} maxLength={200} required />
    </div>
    <Field label="Размещения" help="По одному разрешённому каналу или размещению на строку."><textarea name="placements" defaultValue={item?.placements.join('\n') || ''} rows={2} required /></Field>
    {prose.map(([key, label]) => <Field key={key} label={label}><textarea name={key} defaultValue={item?.[key] || ''} rows={2} minLength={3} maxLength={4000} required /></Field>)}
    <div className="mkt-fields">
      <Field label="Минимум наблюдений" name="minimum_observations" type="number" min="1" step="1" defaultValue={item?.minimum_observations || ''} required help="До этого объёма результат остаётся предварительным." />
      <Field label="Предельный бюджет" name="budget_limit" type="number" min="0.01" step="0.01" defaultValue={item?.budget_limit || ''} required />
      <Field label="Валюта эксперимента"><select name="currency" defaultValue={item?.currency || goal.currency}><option value="UZS">UZS</option><option value="USD">USD</option></select></Field>
      <Field label="Начало кампании · Ташкент" name="starts_at" type="datetime-local" defaultValue={localTime(item?.starts_at || stamp + 3600000)} required />
      <Field label="Конец кампании · Ташкент" name="ends_at" type="datetime-local" defaultValue={localTime(item?.ends_at || stamp + 86400000)} required />
      <Field label="Начало окна оценки" name="evaluation_starts_on" type="date" defaultValue={item?.evaluation_starts_on || today} required />
      <Field label="Конец окна оценки" name="evaluation_ends_on" type="date" defaultValue={item?.evaluation_ends_on || tomorrow} required />
    </div>
    <fieldset><legend>Платные креативы для этой площадки</legend>
      {!creatives.length && <p>Подготовьте платный креатив в разделе «Контент и очередь» и проверьте факты. Предложение можно сохранить до его готовности.</p>}
      {creatives.map(candidate => <div className="mkt-item" key={candidate.id}><label className="mkt-checkbox"><input name="candidate_ids" type="checkbox" value={candidate.id} defaultChecked={item?.candidate_ids.includes(candidate.id)} />{candidate.title}</label><p>Версия {candidate.version} · {candidate.check?.passed ? 'Факты проверены' : 'Нужна проверка фактов'}</p></div>)}
    </fieldset>
    <fieldset><legend>Проверка правил рекламы</legend>
      <p className="mkt-muted">Зафиксируйте проверенный первоисточник и ограничения финансовой рекламы. Согласование не гарантирует модерацию площадки.</p>
      <Field label="Правила площадки · ссылка" name="policy_reference" type="url" defaultValue={item?.policy_reference || ''} />
      <Field label="Результат проверки правил"><textarea name="policy_review" defaultValue={item?.policy_review || ''} maxLength={4000} rows={3} /></Field>
      <div className="mkt-fields"><Field label="Правила проверены" name="policy_reviewed_on" type="date" defaultValue={item?.policy_reviewed_on || today} /><Field label="Проверка правил действительна до" name="policy_review_valid_until" type="date" defaultValue={item?.policy_review_valid_until || tomorrow} /></div>
    </fieldset>
    <button className="mkt-primary" disabled={busy}>Сохранить предложение</button>
  </form>;
}

function RevokeForm({ item, request, busy, error, onDone }) {
  async function save(event) {
    event.preventDefault();
    if (await request(`/experiments/${item.id}/revoke`, { method: 'POST', body: { expected_version: item.version, reason: new FormData(event.currentTarget).get('reason') }, message: 'Разрешение отозвано, его история сохранена.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={save}>{error && <p role="alert" className="mkt-error">{error}</p>}<Field label="Причина отзыва"><textarea name="reason" minLength={3} maxLength={2000} rows={3} required /></Field><button disabled={busy}>Отозвать разрешение</button></form>;
}

function TeamBrief({ data, request, busy, onHistory }) {
  async function send(event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (await request('/tasks', { method: 'POST', body: { kind: 'experiment', message: new FormData(form).get('message') }, message: 'Задание сохранено. Таргетолог, PR и CMO передадут предложения; платные действия требуют отдельного решения.' })) form.reset();
  }
  const tasks = data.tasks.filter(task => task.kind === 'experiment');
  return <Panel title="Предложение команды">
    <form className="mkt-form" onSubmit={send}><Field label="Задание таргетологу" help="Укажите площадку, кабинет, доступные размещения, предел бюджета и что хотите проверить. При нехватке данных команда задаст вопросы."><textarea name="message" minLength={3} maxLength={12000} rows={3} required /></Field><button disabled={busy || !data.active_goal}>Запросить предложение команды</button></form>
    {tasks.map(task => <div className="mkt-item" key={task.id}><div className="mkt-row mkt-between"><strong>{task.title}</strong><Status value={task.status} /></div><p>{reasonText(task.reason)}</p>
      <details><summary>Результаты таргетолога, PR и CMO</summary>{!task.outputs.length && <p>Сохранённых ответов модели пока нет.</p>}{task.outputs.map((output, index) => <div className="mkt-item" key={index}><strong>{data.roles.find(role => role.id === output.role)?.name || output.role}</strong><p>{output.result.summary}</p>{output.result.questions.map((question, i) => <p key={i}>{question}</p>)}</div>)}</details>
      {!!task.experiment_ids?.length && <p>Сохранено предложений: {task.experiment_ids.length}. Они доступны ниже и не имеют разрешения на расходы.</p>}
      <button onClick={() => onHistory('task', task.id, 'История задания таргетологу')}>История задания</button>
    </div>)}
  </Panel>;
}

export function ExperimentsSection({ data, request, busy, error, onHistory }) {
  const [dialog, setDialog] = useState(null);
  const close = () => setDialog(null);
  const items = data.experiments || [];
  const approved = items.filter(item => item.status === 'approved');
  const reserves = ['UZS', 'USD'].map(currency => [currency, approved.filter(item => item.currency === currency).reduce((sum, item) => sum + item.budget_limit, 0)]).filter(([, total]) => total > 0);
  const act = (item, action, message) => request(`/experiments/${item.id}/${action}`, { method: 'POST', body: { expected_version: item.version }, message });
  return <div className="mkt-stack">
    <EditorialExperiments data={data} request={request} busy={busy} error={error} onHistory={onHistory} />
    <p>Гипотезы, контроль, сроки, креативы и предел расходов. Каждое платное действие требует отдельного решения владельца по точной версии.</p>
    <p className="mkt-callout">Подключение рекламных кабинетов ещё не реализовано. Предложения и решения сохраняются; внешние кампании не создаются и расходы не выполняются.</p>
    <div className="mkt-actions"><button className="mkt-primary" disabled={!data.active_goal || busy} onClick={() => setDialog({ kind: 'edit' })}>Новый эксперимент</button><button disabled={busy} onClick={() => request('/workspace')}>Обновить эксперименты</button></div>
    {!data.active_goal && <p>Сначала утвердите цель с бюджетом и периодом.</p>}
    <TeamBrief data={data} request={request} busy={busy} onHistory={onHistory} />
    <Panel title="Лимиты согласованных экспериментов"><p>{reserves.length ? reserves.map(([currency, total]) => `${number(total)} ${currency}`).join(' · ') : 'Нет зарезервированных лимитов'}</p><p className="mkt-muted">Это согласованные пределы, а не фактические расходы. Расходы появятся в отчётах только из подтверждённых данных.</p></Panel>
    <Panel title="Предложения и решения">{!items.length && <p>Эксперименты пока не предложены.</p>}{items.map(item => <article key={item.id} className="mkt-item">
      <div className="mkt-row mkt-between"><h4>{item.title}</h4><Status value={item.status} /></div>
      <p>{actions[item.action]} · {data.platforms.find(value => value.id === item.platform)?.name} · {item.advertiser_account_id} · {item.campaign_ref}</p>
      <p><strong>{number(item.budget_limit)} {item.currency}</strong> · {date(item.starts_at)}–{date(item.ends_at)} · версия {item.version}</p>
      <p>{item.hypothesis}</p><p>Сравнение: {item.comparison}</p><p>Измерение: {item.measurement} · {date(item.evaluation_starts_on)}–{date(item.evaluation_ends_on)}</p><p>Остановка: {item.stop_condition}</p>
      <p>Вопрос читателя: {item.reader_question || 'Не задан'}</p><p>Проверяемая переменная: {item.tested_variable || 'Не задана'} · минимум наблюдений: {number(item.minimum_observations)}</p>
      <details><summary>Аудитория, размещения и креативы</summary><p>{item.audience}</p><p>{item.placements.join(' · ')}</p><p>{item.creative_brief}</p>{item.candidate_ids.map(id => <p key={id}>{data.candidates.find(candidate => candidate.id === id)?.title || id}</p>)}</details>
      <details><summary>Проверка правил площадки</summary><p>{item.policy_review || 'Не проведена'}</p><p>{date(item.policy_reviewed_on)} · действительна до {date(item.policy_review_valid_until)}</p>{item.policy_reference && <SafeLink href={item.policy_reference}>Источник правил ↗</SafeLink>}</details>
      {item.approval && <p className="mkt-callout">Согласована точная версия параметров и креативов. Доступы, актуальность источников и бюджет проверяются снова перед действием.</p>}
      {item.reason && <p>{item.reason}</p>}
      <div className="mkt-actions">
        <button disabled={busy || !data.active_goal} onClick={() => setDialog({ kind: 'edit', item })}>Изменить эксперимент</button>
        {item.status === 'proposed' && <button disabled={busy} onClick={() => act(item, 'approve', 'Платное действие согласовано для показанных параметров и версий креативов.')}>Утвердить платное действие</button>}
        <button disabled={busy} onClick={() => act(item, 'action')}>Запросить платное действие</button>
        {['proposed', 'approved'].includes(item.status) && <button disabled={busy} onClick={() => setDialog({ kind: 'revoke', item })}>Отозвать решение</button>}
        <button onClick={() => onHistory('experiment', item.id, 'История эксперимента')}>История эксперимента</button>
      </div>
    </article>)}</Panel>
    {dialog && <Dialog title={dialog.kind === 'edit' ? 'Параметры эксперимента' : 'Отзыв решения'} onClose={close}>{dialog.kind === 'edit' ? <ExperimentForm item={dialog.item} data={data} request={request} busy={busy} error={error} onDone={close} /> : <RevokeForm item={dialog.item} request={request} busy={busy} error={error} onDone={close} />}</Dialog>}
  </div>;
}
