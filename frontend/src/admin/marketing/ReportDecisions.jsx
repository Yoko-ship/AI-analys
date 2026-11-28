import { Status, date, number } from './Widgets.jsx';

const actions = { continue: 'Продолжить', change: 'Изменить', stop: 'Остановить' };
const priorities = { high: 'Высокий', normal: 'Обычный', low: 'Низкий' };
const kinds = { organic: 'Органический тест', measurement: 'Проверка измерений', paid_proposal: 'Предложение платного теста' };

export function ReportDecisions({ review, roles = [] }) {
  if (!review) return null;
  const { basis, decisions, hypotheses } = review;
  const roleName = key => key === 'owner' ? 'Владелец' : roles.find(role => role.id === key)?.name || key;
  const metricNames = keys => keys.map(key => basis.metrics[key]?.title || key).join(', ');
  return <section className="mkt-report-decisions" aria-label="Решения CMO">
    <h4>Решения CMO</h4>
    <p>Предложения не меняют цель, срок, бюджет или разрешения. Следующий тест ещё не выполнен; его эффект предстоит измерить.</p>
    {basis.dataset === 'test' && <p className="mkt-callout">Тестовые данные · эти результаты не описывают реальных клиентов.</p>}
    <p className="mkt-muted">Основание: {date(basis.period.starts_on)} — {date(basis.period.ends_on)} (конец не включён). Срез: {new Date(basis.period.cutoff).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' })} · Ташкент.</p>
    <div className="mkt-table-wrap"><table><caption>Основания решений</caption><thead><tr><th>Показатель</th><th>Значение</th><th>Полнота</th><th>Источники</th></tr></thead>
      <tbody>{Object.entries(basis.metrics).map(([key, value]) => <tr key={key}><th scope="row">{value.title}</th><td>{number(value.value)} {value.currency || (value.unit === 'percent' ? '%' : '')}{value.estimate && <small> · Расчётная оценка</small>}</td><td><Status value={value.status} /></td><td>{value.source_ids?.join(', ') || 'Нет применимых наблюдений'}</td></tr>)}</tbody>
    </table></div>
    {decisions.map(row => <article className="mkt-item" key={row.id} aria-label={row.subject}>
      <h5>{actions[row.action]} · {row.subject}</h5>
      <p>{row.reason}</p>
      <p className="mkt-muted">Основания: {metricNames(row.metric_ids)}</p>
      <dl className="mkt-details"><dt>Следующее действие</dt><dd>{row.next_action}</dd><dt>Ответственный</dt><dd>{roleName(row.owner)}</dd><dt>Проверить результат</dt><dd>{date(row.check_on)}</dd>
        <dt>Гипотезы для проверки</dt><dd>{row.hypothesis_ids.map(id => hypotheses.find(value => value.id === id)?.statement).join(' ')}</dd></dl>
    </article>)}
    <div role="group" aria-label="Дерево гипотез"><h4>Дерево гипотез</h4><p className="mkt-muted">Предположения и предлагаемые проверки; связь с показателем не доказывает причину изменения.</p>
      {hypotheses.map(row => <article className="mkt-item" key={row.id} aria-label={row.statement}>
        <h5>{row.statement}</h5>
        {row.parent_id && <p>Развивает гипотезу: {hypotheses.find(value => value.id === row.parent_id)?.statement}</p>}
        <p>{kinds[row.kind]} · Приоритет: {priorities[row.priority]}</p>
        {row.kind === 'paid_proposal' && <p className="mkt-callout">Платный тест требует отдельного решения владельца по точным параметрам. Это предложение не разрешает запуск или расход.</p>}
        <p>Проверка: {row.test_plan}</p><p>Предлагаемый критерий: {row.success_criterion}</p>
        <dl className="mkt-details"><dt>Показатель теста</dt><dd>{metricNames([row.success_metric])}</dd><dt>Ответственный</dt><dd>{roleName(row.owner)}</dd><dt>Проверить результат</dt><dd>{date(row.check_on)}</dd></dl>
      </article>)}
    </div>
  </section>;
}
