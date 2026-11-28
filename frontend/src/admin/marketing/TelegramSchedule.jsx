import { useState } from 'react';
import { Field } from './Widgets.jsx';
import { VersionedEditor } from './VersionedEditor.jsx';

function suggestedTimes(count, account) {
  const minutes = value => Number(value.slice(0, 2)) * 60 + Number(value.slice(3, 5));
  const start = minutes(account.window_start || '09:00'), end = minutes(account.window_end || '21:00');
  return Array.from({ length: count }, (_, i) => {
    const at = start + Math.floor((end - start) * i / count);
    return `${String(Math.floor(at / 60)).padStart(2, '0')}:${String(at % 60).padStart(2, '0')}`;
  });
}

function ScheduleForm({ account, request, busy }) {
  const [count, setCount] = useState(account.news_daily_limit || 2);
  const [mode, setMode] = useState(account.news_publish_times?.length ? 'times' : 'ready');
  const [times, setTimes] = useState(account.news_publish_times?.length
    ? account.news_publish_times.map(time => time.slice(0, 5)) : suggestedTimes(count, account));
  function changeCount(value) {
    setCount(value);
    const size = Math.max(0, Math.min(24, Number(value) || 0));
    const suggested = suggestedTimes(size, account);
    setTimes(previous => suggested.map((time, i) => previous[i] || time));
  }
  async function save(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    await request(`/telegram/${account.id}/schedule`, { method: 'PUT', body: {
      expected_version: account.version,
      data: { news_daily_limit: Number(count), news_publish_times: mode === 'times' ? times : [],
        window_start: fields.get('window_start'), window_end: fields.get('window_end'),
        min_interval_minutes: Number(fields.get('min_interval_minutes')) },
    }, message: 'Расписание сохранено. Оно повторяется каждый день по времени Ташкента.' });
  }
  return <form className="mkt-form" onSubmit={save} aria-label="Расписание Telegram" aria-busy={busy}>
    <fieldset><legend>Расписание публикаций</legend>
      <div className="mkt-fields">
        <Field label="Постов в день" name="news_daily_limit" type="number" min="1" max="24" step="1"
          value={count} onChange={e => changeCount(e.target.value)} required help="Дневной максимум: от 1 до 24 автоматических новостей." />
        <Field label="Когда публиковать"><select value={mode} onChange={e => setMode(e.target.value)}>
          <option value="ready">По готовности</option><option value="times">В выбранное время</option>
        </select></Field>
      </div>
      {mode === 'times' && <div className="mkt-fields">{times.map((time, i) => <Field key={i}
        label={`Время поста ${i + 1}`} name={`news_time_${i}`} type="time" step="60" required value={time}
        aria-invalid={times.filter(value => value === time).length > 1 || undefined}
        onChange={e => setTimes(previous => previous.map((value, index) => index === i ? e.target.value : value))}
        help={times.filter(value => value === time).length > 1 ? 'Это время повторяется. Выберите отдельное время по Ташкенту.' : 'Ташкент · UTC+5'} />)}</div>}
      <p className="mkt-muted">{mode === 'times'
        ? 'Расписание повторяется ежедневно по Ташкенту. Подготовка начинается заранее. Допустима задержка до 15 минут; пропущенные посты не накапливаются.'
        : 'Публикуем проверенные новости по мере готовности в разрешённое время, до указанного дневного лимита.'} Если подходящих новостей нет, постов будет меньше.</p>
      <details><summary>Окно публикаций и минимальный интервал</summary><div className="mkt-fields">
        <Field label="Начало окна · Ташкент" name="window_start" type="time" defaultValue={account.window_start?.slice(0, 5) || '09:00'} required />
        <Field label="Конец окна · Ташкент" name="window_end" type="time" defaultValue={account.window_end?.slice(0, 5) || '21:00'} required />
        <Field label="Интервал между публикациями · минуты" name="min_interval_minutes" type="number" min="1" max="10080"
          defaultValue={account.min_interval_minutes || 60} required />
      </div><p className="mkt-muted">Каждое время должно быть внутри окна, до его конца. Между постами сохраняется минимальный интервал.</p></details>
    </fieldset>
    <button className="mkt-primary" disabled={busy}>Сохранить расписание</button>
  </form>;
}

export function TelegramSchedule({ account, request, busy }) {
  return <VersionedEditor value={account} request={request}>{(saved, save) =>
    <ScheduleForm account={saved} request={save} busy={busy} />}</VersionedEditor>;
}
