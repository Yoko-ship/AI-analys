import { Panel, date, number, experimentActions as actions } from './Widgets.jsx';

export function ReportExperiments({ value }) {
  if (!value?.items?.length) return null;
  return <Panel title="Оценки тестов рубрик" labelled>
    <p>Последние сохранённые оценки, известные на дату среза, для тестов с пересекающимся окном. Эти же данные получает CMO. Подробности и новые решения доступны в разделе «Эксперименты».</p>
    {value.truncated && <p>Показаны 10 последних из {value.total} тестов. Остальные доступны в разделе «Эксперименты».</p>}
    {value.items.map(item => <article key={item.experiment_id} className="mkt-item">
      <h4>{item.title}</h4>
      <p>{item.result.status === 'preliminary' ? 'Предварительный результат' : 'Наблюдаемое сравнение'} · {item.design.timing === 'retrospective' ? 'ретроспективный дизайн' : 'дизайн до начала набора'} · {item.result.dataset === 'test' ? 'тестовые данные' : 'рабочие данные'}</p>
      <p>Набор: {date(item.design.starts_on)}–{date(item.design.ends_on)} (конец не включён) · наблюдение {item.design.followup_days} дн. Срез оценки: {new Date(item.result.cutoff).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' })} · Ташкент.</p>
      <p>Контроль: {number(item.result.arms.control.outcomes)} / {number(item.result.arms.control.readers)} читателей. Новый вариант: {number(item.result.arms.variant.outcomes)} / {number(item.result.arms.variant.readers)}. Минимум: {number(item.design.minimum_observations)} в каждом варианте.</p>
      <p className="mkt-muted">Переход и последующее действие связаны по читателю; сравнение не доказывает причину изменения.</p>
      {item.owner_decision && <p>Решение владельца: {actions[item.owner_decision.action]} · {item.owner_decision.reason}{!item.decision_uses_this_evaluation && ' Решение относится к другой сохранённой оценке.'}</p>}
    </article>)}
  </Panel>;
}
