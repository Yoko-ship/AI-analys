import { Status } from './Widgets.jsx';

const timestamp = value => new Date(value).toLocaleString('ru-RU', {
  timeZone: 'Asia/Tashkent', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
});

export function MetricCoverage({ coverage, labels }) {
  if (!coverage) return null;
  return <div className="mkt-metric-coverage"><h5>Окна источников для этого показателя</h5>
    <p>Время Ташкента. Подтверждение должно охватывать всё указанное окно; история проверяется отдельно.</p>
    {Object.entries(coverage).map(([source, basis]) => <div className="mkt-item" key={source}>
      <p><b>{labels[source] || source}</b> · <Status value={basis.status} /></p>
      <p>С {timestamp(basis.starts_at)}<br />до {timestamp(basis.ends_at)} {basis.end_inclusive ? 'включительно' : '(не включая)'}</p>
      <p>{basis.history_required ? 'Нужна история до начала окна.' : 'История до начала окна не требуется.'}</p>
      <p>{basis.confirmation?.reference || 'Нет подтверждения этого окна.'}</p>
    </div>)}
  </div>;
}
