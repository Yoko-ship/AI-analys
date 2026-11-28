import { Field, SafeLink, Status, date } from './Widgets.jsx';
import { rightsLabels } from './SourceForm.jsx';

function originalLines(item) {
  if (!item.analysis_version) return [];
  try {
    const lines = JSON.parse(item.excerpt).extracted_original_lines;
    return Array.isArray(lines) && lines.every(line => line && typeof line.line === 'string' && typeof line.field === 'string') ? lines : [];
  } catch { return []; }
}

export function EvidenceDetail({ item, busy, request, error, onDone }) {
  const lines = originalLines(item);
  const labels = Object.fromEntries(lines.map(line => [line.field, line.line]));
  const facts = Object.entries(item.data).filter(([key]) => key !== 'analysis_ready');
  async function verify(event) {
    event.preventDefault();
    if (await request(`/evidence/${item.id}/verify`, { method: 'POST', body: { expected_version: item.version, reason: new FormData(event.currentTarget).get('reason') }, message: 'Проверка оригинала сохранена в истории.' })) onDone();
  }
  return <div className="mkt-stack">
    <p><Status value={item.status} /> · версия {item.version} · {item.publisher} {item.entity && `· ${item.entity}`}</p>
    <SafeLink href={item.url}>Открыть оригинал ↗</SafeLink>
    <dl className="mkt-details"><dt>Опубликован</dt><dd>{date(item.published_at)}</dd><dt>Событие</dt><dd>{date(item.event_at)}</dd><dt>Получен</dt><dd>{date(item.retrieved_at)}</dd><dt>Свежесть до</dt><dd>{date(item.expires_at)}</dd><dt>Права</dt><dd>{rightsLabels[item.rights]}</dd>{item.period_start && <><dt>Начало периода</dt><dd>{item.period_start}</dd></>}{item.period && <><dt>Период</dt><dd>{item.period} · {item.standard} · {item.scope}</dd></>}</dl>
    <blockquote className="mkt-original">{lines.length ? lines.map(line => `${line.line}: ${typeof line.value === 'object' ? JSON.stringify(line.value) : String(line.value)} ${line.unit || ''}`.trim()).join('\n') : item.excerpt}</blockquote>
    {!!facts.length && <div className="mkt-table-wrap"><table><caption>Извлечённые факты</caption><thead><tr><th scope="col">Поле</th><th scope="col">Значение</th><th scope="col">Единица</th></tr></thead><tbody>{facts.map(([key, value]) => <tr key={key}><th scope="row" title={key}>{labels[key] || key}</th><td>{typeof value === 'object' ? JSON.stringify(value) : String(value)}</td><td>{item.units[key] || 'Не указана'}</td></tr>)}</tbody></table></div>}
    {!!lines.length && <details><summary>Исходная запись</summary><pre className="mkt-original">{item.excerpt}</pre></details>}
    {item.verification_reason && <p>Основание проверки: {item.verification_reason}</p>}
    {item.status === 'candidate' && <form className="mkt-form" onSubmit={verify}>
      {error && <p role="alert" className="mkt-error">{error}</p>}
      <Field label="Как проверен оригинал" help="Укажите, какие значения, даты, единицы и эмитента вы сверили."><textarea name="reason" maxLength={2000} required /></Field>
      <button disabled={busy}>Подтвердить факты</button>
    </form>}
    {['disabled', 'unavailable'].includes(item.status) && <p className="mkt-callout">Использование в публикации заблокировано: проверьте доступность, права и текущую конфигурацию источника.</p>}
  </div>;
}
