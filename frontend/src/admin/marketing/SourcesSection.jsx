import { useState } from 'react';
import { Dialog, Panel, SafeLink, Status, date } from './Widgets.jsx';
import { SourceForm, sourceMethods, rightsLabels } from './SourceForm.jsx';
import { MaterialImport } from './MaterialImport.jsx';
import { EvidenceDetail } from './EvidenceDetail.jsx';
import { TrendForm, TrendObservations } from './TrendObservations.jsx';

export function SourcesSection({ data, request, busy, error, onHistory }) {
  const [dialog, setDialog] = useState(null);
  const close = () => setDialog(null);
  const shared = { request, busy, error, onDone: close };
  return <div className="mkt-stack">
    <Panel title="Реестр источников" action={<button onClick={() => setDialog({ kind: 'source', title: 'Новый источник' })}>Добавить источник</button>}>
      <p className="mkt-muted">Мониторинг запускается на сервере после вашего разрешения. Новости UZStock, итоги торгов и готовые разборы читаются из внутренних хранилищ.</p>
      <button disabled={busy} onClick={() => request('/workspace')}>Обновить статусы источников</button>
      {!data.sources.length && <p>Источники ещё не настроены. Добавьте разрешённый ресурс или источник ручных выгрузок.</p>}
      {data.sources.map(source => <article className="mkt-item" key={source.id}>
        <div className="mkt-row mkt-between"><h4>{source.name}</h4><Status value={source.status} /></div>
        <p>{sourceMethods[source.method]} · {source.language.toUpperCase()} · {source.geography}</p>
        <SafeLink href={source.url}>Открыть источник ↗</SafeLink>
        <p className="mkt-muted">{rightsLabels[source.rights]} · ответственный: {source.owner}</p>
        <p>Последнее получение: {source.last_success_at ? date(source.last_success_at) : 'Ещё не было'}{source.last_count != null && ` · материалов: ${source.last_count}`}</p>
        {source.status === 'unavailable' && <p className="mkt-error">Сбор не удался. Сохранённые оригиналы доступны для просмотра; данные не считаются свежими. Проверьте доступ и настройки источника.</p>}
        {source.status === 'reviewing' && <p>Разрешение получено. Ожидается первая проверка фоновым обработчиком.</p>}
        <div className="mkt-actions">
          <button onClick={() => setDialog({ kind: 'source', title: 'Настройки источника', source })}>Изменить источник</button>
          <button onClick={() => setDialog({ kind: 'import', title: 'Импорт оригинала', source })} disabled={!source.may_store || source.rights === 'unknown'}>Импортировать материал</button>
          {source.enabled || source.status === 'connected' ? <button disabled={busy} onClick={() => request(`/sources/${source.id}/permission`, { method: 'POST', body: { expected_version: source.version, enabled: false }, message: 'Источник отключён. Его доказательства больше не допускаются к выпуску.' })}>Отключить источник</button> : source.method !== 'manual' && <button disabled={busy} onClick={() => request(`/sources/${source.id}/permission`, { method: 'POST', body: { expected_version: source.version, enabled: true }, message: 'Мониторинг разрешён. Первый результат появится после фонового сбора.' })}>Разрешить мониторинг</button>}
          <button onClick={() => onHistory('source', source.id, 'История источника')}>История источника</button>
        </div>
      </article>)}
    </Panel>
    <TrendObservations items={data.trends} onHistory={onHistory} onEdit={item => setDialog({ kind: 'trend', title: 'Наблюдение темы', item })} />
    <div className="mkt-columns">
      <Panel title="Оригиналы и доказательства">{!data.evidence.length && <p className="mkt-muted">После сбора или импорта здесь появятся фрагменты, факты, единицы и версии оригиналов.</p>}{data.evidence.map(item => <article className="mkt-item" key={item.id}><h4>{item.title}</h4><p><Status value={item.status} /> · {item.publisher} · {date(item.published_at)}</p><div className="mkt-actions"><button onClick={() => setDialog({ kind: 'evidence', title: item.title, item })}>Открыть доказательство</button><button onClick={() => onHistory('evidence', item.id, 'Версии оригинала')}>Версии оригинала</button></div></article>)}</Panel>
      <Panel title="События и свежие темы"><p className="mkt-muted">Перепечатки с одним ключом объединяются. Свежесть события сама по себе не доказывает рост интереса.</p>{!data.topics.length && <p>Событий пока нет.</p>}{data.topics.map(topic => <article className="mkt-item" key={topic.id}><h4>{topic.title}</h4><p>{topic.classification === 'new_event' ? 'Датированное событие' : 'Редакционная гипотеза'} · {date(topic.event_at)}</p><p>Оригиналов и перепечаток: {topic.evidence_ids.length}. Рост интереса: нет измерения.</p><button onClick={() => onHistory('topic', topic.id, 'История события')}>История события</button></article>)}</Panel>
    </div>
    {dialog && <Dialog title={dialog.title} onClose={close}>{dialog.kind === 'source' && <SourceForm source={dialog.source} {...shared} />}{dialog.kind === 'import' && <MaterialImport source={dialog.source} {...shared} />}{dialog.kind === 'evidence' && <EvidenceDetail item={dialog.item} {...shared} />}{dialog.kind === 'trend' && <TrendForm item={dialog.item} sources={data.sources} {...shared} />}</Dialog>}
  </div>;
}
