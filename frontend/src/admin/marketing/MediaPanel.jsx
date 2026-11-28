import { useEffect, useState } from 'react';
import { Field, SafeLink, Status } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';
import { chartChoices } from './chartChoices.js';

function Preview({ asset, readFile, downloadFile, busy }) {
  const fileType = { 'image/jpeg': ['JPEG', 'jpg'], 'image/png': ['PNG', 'png'], 'video/mp4': ['видео без звука, титры встроены в кадры', 'mp4'] }[asset.mime] || [asset.mime, 'bin'];
  const [file, setFile] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    let url;
    readFile(`/assets/${asset.id}/file`).then(blob => {
      if (!active) return;
      url = URL.createObjectURL(blob);
      setFile(url);
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [asset.id, asset.sha256, readFile]);
  return <figure className="mkt-media">
    {error ? <p role="alert" className="mkt-error">{error}</p> : !file ? <p role="status">Загрузка файла…</p> : asset.mime === 'video/mp4'
      ? <video controls playsInline src={file} aria-label={asset.alt_text} />
      : <img src={file} alt={asset.alt_text} width={asset.width} height={asset.height} />}
    <figcaption><p>{asset.alt_text}</p><p className="mkt-muted">{asset.width} × {asset.height} · {fileType[0]}</p></figcaption>
    <div className="mkt-actions">{file && <a className="mkt-download" href={file} download={`${asset.id}.${fileType[1]}`}>Скачать файл</a>}
      {asset.chart && <button disabled={busy} onClick={() => downloadFile(`/assets/${asset.id}/data`, `${asset.id}.csv`)}>Скачать данные CSV</button>}
    </div>
    {asset.chart && <details><summary>Данные и шкала графика</summary><p>Единица: {asset.chart.unit}. Шкала: {asset.chart.axis_min} — {asset.chart.axis_max}.</p>
      <div className="mkt-table-wrap mkt-chart-data"><table><caption>Исходный ряд</caption><thead><tr><th scope="col">Дата</th><th scope="col">Значение · {asset.chart.unit}</th></tr></thead><tbody>{asset.chart.series.map(point => <tr key={point.date}><th scope="row">{point.date}</th><td>{point.value}</td></tr>)}</tbody></table></div>
    </details>}
  </figure>;
}

export function MediaFiles({ item, data, ...props }) {
  const assets = (item.assets || []).map(ref => data.assets.find(asset => asset.id === ref.id)).filter(Boolean);
  return <div className="mkt-stack">{assets.length ? assets.map(asset => <Preview key={`${asset.id}-${asset.sha256}`} asset={asset} {...props} />) : <p>Готовых файлов пока нет.</p>}
    <details><summary>Оригиналы и версии для медиа</summary>{assets.map(asset => <div key={asset.id}>{Object.entries(asset.source_versions).map(([id, version]) => {
      const evidence = data.evidence.find(value => value.id === id);
      return <p key={id}><SafeLink href={evidence?.url}>{evidence?.title || id}</SafeLink> · версия {version}{evidence?.version !== version ? ' · оригинал изменился, нужна новая проверка' : ''}</p>;
    })}</div>)}</details>
  </div>;
}

export function RenderJobs({ jobs, request, busy, onHistory }) {
  if (!jobs.length) return null;
  return <div className="mkt-render-jobs" aria-label="Рендер медиа">{jobs.map(job => <div className="mkt-item" key={job.id}>
    <div className="mkt-row"><strong>Медиа</strong><Status value={job.status} /></div><p>{reasonText(job.reason)}</p>
    <div className="mkt-actions">{job.status === 'error' && job.attempts < 3 && <button disabled={busy} onClick={() => request(`/renders/${job.id}/retry`, { method: 'POST', body: { expected_version: job.version } })}>Повторить рендер</button>}
      <button onClick={() => onHistory('render', job.id, 'История медиа')}>История рендера</button></div>
  </div>)}</div>;
}

export function RenderForm({ item, data, request, busy, error, onDone }) {
  const [series, setSeries] = useState('');
  const choices = chartChoices(data.evidence, item.evidence_ids);
  async function submit(event) {
    event.preventDefault();
    const body = { expected_version: item.version, chart: choices.find(choice => choice.key === series)?.ref || null };
    if (await request(`/candidates/${item.id}/render`, { method: 'POST', body, message: 'Рендер поставлен в очередь. Обновите материалы после работы обработчика.' })) onDone();
  }
  return <form className="mkt-form" onSubmit={submit}>
    <p>Файл будет создан из сохранённого текста и проверенных фактов. После рендера материал снова проходит проверку.</p>
    <Field label="Данные графика"><select value={series} onChange={event => setSeries(event.target.value)} required={item.rubric === 'chart'}>
      <option value="">{item.rubric === 'chart' ? 'Выберите подтверждённый ряд' : 'Карточка фактов без графика'}</option>
      {choices.map(choice => <option key={choice.key} value={choice.key}>{choice.label}</option>)}
    </select></Field>
    {item.rubric === 'chart' && !choices.length && <p className="mkt-callout">В выбранных оригиналах нет ряда дат и значений. Добавьте подтверждённые данные и единицу измерения.</p>}
    {item.format === 'video' && <p>Будет создан короткий MP4 с титрами и источником, без озвучки и музыки.</p>}
    {error && <p role="alert" className="mkt-error">{error}</p>}
    <button disabled={busy || (item.rubric === 'chart' && !choices.length)} className="mkt-primary">Начать рендер</button>
  </form>;
}
