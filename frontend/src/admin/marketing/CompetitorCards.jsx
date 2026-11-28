import { SafeLink, date } from './Widgets.jsx';

const relationships = { direct: 'Прямой конкурент', inspiration: 'Ориентир для вдохновения', adjacent: 'Смежный продукт' };
const fields = { purpose: 'Назначение', audience: 'Аудитория', features: 'Функции', pricing: 'Видимый тариф', communication: 'Коммуникация',
  revenue: 'Выручка', conversion: 'Конверсия', audience_size: 'Размер аудитории' };

export function CompetitorCards({ cards }) {
  if (!cards?.length) return null;
  return <div className="mkt-stack">{cards.map((card, index) => <article className="mkt-item" key={index} aria-label={card.product}>
    <h4>{card.product}</h4><p><strong>{relationships[card.relationship]}</strong> · {card.relationship_reason}</p>
    <p className="mkt-muted">Это датированные наблюдения из выбранных материалов. Сохранённый тариф не подтверждает цену на другую дату.</p>
    <div className="mkt-table-wrap"><table className="mkt-competitor-facts"><caption>Наблюдения · {card.product}</caption><thead><tr><th>Параметр</th><th>Наблюдение и источник</th></tr></thead><tbody>
      {card.facts.map(fact => <tr key={fact.field}><th scope="row">{fields[fact.field]}</th><td>
        <p>{fact.observed_excerpt || (fact.source?.access === 'unavailable' ? 'Нет доступного подтверждения' : 'Не раскрыто в выбранных материалах')}</p>
        {fact.source && <><SafeLink href={fact.source.url}>{fact.source.title}</SafeLink><p className="mkt-muted">Дата получения: {date(fact.source.retrieved_at)} · публикация: {date(fact.source.published_at)} · версия {fact.source.version}</p></>}
      </td></tr>)}
    </tbody></table></div>
    <p><strong>Гипотеза отличия UZStock:</strong> {card.difference_hypothesis}</p>
  </article>)}</div>;
}
