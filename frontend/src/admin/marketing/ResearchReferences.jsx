import { Field, SafeLink, Status, date } from './Widgets.jsx';

const decisions = { adapt: 'Адаптировать приём', original: 'Сделать свой формат', reject: 'Не брать' };
const rights = { link_and_excerpt: 'ссылка и выдержка', owned: 'собственный материал', licensed: 'лицензия', unknown: 'не подтверждены' };

export function ResearchForm({ data, request, busy }) {
  async function submit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const result = await request('/tasks', { method: 'POST', body: { kind: values.get('kind'), message: values.get('question'),
      evidence_ids: values.getAll('references'), trend_ids: values.getAll('trends') }, message: 'Исследование сохранено. Результаты появятся в передачах между ролями.' });
    if (result) form.reset();
  }
  return <details><summary>Новое исследование</summary><form className="mkt-form" onSubmit={submit}>
    <p>Аналитики работают с выбранными материалами. Отдельно покажут наблюдение, возможный приём и следующий тест. Если подходящего примера нет, предложат свой формат.</p>
    <Field label="Тип исследования"><select name="kind" defaultValue="research"><option value="research">Форматы и референсы</option><option value="competitors">Сравнение конкурентов и ориентиров</option></select></Field>
    <Field label="Вопрос исследования"><textarea name="question" required maxLength={12000} placeholder="Аудитория, площадка, задача и ограничения" /></Field>
    <fieldset><legend>Материалы для исследования</legend><div className="mkt-checks">{data.evidence.map(item => <div key={item.id}>
      <label><input type="checkbox" name="references" value={item.id} />Референс · {item.title}</label><Status value={item.status} />
    </div>)}</div><p>Можно отправить задачу без источников для разработки собственного формата. Неполученное видео не считается просмотренным.</p></fieldset>
    {!!data.trends?.length && <fieldset><legend>История наблюдений для команды</legend><div className="mkt-checks">{data.trends.map(item => <div key={item.id}>
      <label><input type="checkbox" name="trends" value={item.id} disabled={item.review_status !== 'current'} />Наблюдение · {item.theme}</label>
      <small>{date(item.starts_on)}–{date(item.ends_on)} · {item.review_status !== 'current' ? 'Сначала пересмотрите изменившиеся данные в источниках' : item.complete ? 'Полнота проверена владельцем' : 'Неполные окна: без вывода о росте'}</small>
    </div>)}</div><p>До 10 наблюдений. Версии и даты сохраняются в задаче; изменение исходных данных останавливает новый результат роли.</p></fieldset>}
    <button className="mkt-primary" disabled={busy}>Передать исследователям</button>
  </form></details>;
}

export function ResearchReferences({ cards }) {
  if (!cards?.length) return null;
  return <div className="mkt-stack">{cards.map((card, index) => <article className="mkt-item" key={index} aria-label={decisions[card.recommendation]}>
    <h4>{decisions[card.recommendation]}</h4>
    {card.source ? <>
      <SafeLink href={card.source.url}>{card.source.title}</SafeLink>
      <p className="mkt-muted">{card.source.publisher} · версия {card.source.version} · опубликовано {date(card.source.published_at)} · получено {date(card.source.retrieved_at)}</p>
      <p>{card.source.access === 'excerpt' ? 'Только выдержка · исходное медиа не просмотрено' : 'Материал недоступен для анализа'}</p>
      <p>Права: {rights[card.source.rights]}. Разбор приёма не даёт права копировать исходный визуал.</p>
    </> : <p>Источник не использован · предложение собственного формата.</p>}
    {card.observed_excerpt && <div className="mkt-post-preview"><strong>Наблюдаемая выдержка</strong><p>{card.observed_excerpt}</p></div>}
    <p><strong>Приём:</strong> {card.technique}</p>
    <p><strong>Почему предложен:</strong> {card.rationale}</p>
    <p><strong>Следующий тест:</strong> {card.test_plan}</p>
    <small>Приём и рекомендация — вывод команды, а не факт о результативности чужой публикации.</small>
  </article>)}</div>;
}
