import { number, Panel, Status } from './Widgets.jsx';

export function PublicationAttribution({ value, channel, days }) {
  if (!value) return null;
  const rows = value.rows.filter(row => !channel || row.channel === channel);
  return <Panel labelled title="Переходы из публикаций">
    <p>Наблюдаемые открытия ссылок на сайте не добавляются к кликам площадки. Повторное открытие — новый переход; это не число уникальных читателей.</p>
    <p>Регистрации отнесены к последнему известному непрямому переходу за {days} дн. до регистрации. Дата регистрации определяет отчётный период. <Status value={value.status} /></p>
    {value.status !== 'complete' && <p className="mkt-callout">Показаны полученные наблюдения. Пропуски сбора и истории переходов могут изменить атрибуцию; ноль в строке не подтверждает отсутствие других переходов или регистраций.</p>}
    {rows.length ? <div className="mkt-table-wrap"><table><caption>Наблюдаемые переходы и атрибуция</caption><thead><tr><th>Публикация</th><th>Канал / тип</th><th>Переходы в периоде</th><th>Регистрации в периоде</th></tr></thead><tbody>{rows.map(row => <tr key={`${row.publication_id}:${row.channel}:${row.promotion}`}><td>{row.publication_id}</td><td>{row.channel} / {row.promotion === 'paid' ? 'Реклама' : 'Органика'}</td><td>{number(row.observed_arrivals)}</td><td>{number(row.attributed_registrations)}</td></tr>)}</tbody></table></div> : <p>Нет связанных наблюдений за выбранный период и канал.</p>}
    <p>Регистрации без установленной связи с публикацией за весь период: {number(value.unattributed_registrations)}.</p>
    {value.unresolved_registrations > 0 && <p>Регистраций с неуточнённым источником или публикацией: {number(value.unresolved_registrations)}.</p>}
  </Panel>;
}
