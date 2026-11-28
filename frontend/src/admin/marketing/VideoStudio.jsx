import { useEffect, useState } from 'react';
import { Field, Panel } from './Widgets.jsx';

const labels = { queued_script: 'Сценарий в очереди', writing_script: 'Агент пишет сценарий', queued_render: 'Ожидает видеоворкер на ПК',
  rendering: 'Создание видео', complete: 'Готово к скачиванию', error: 'Нужна повторная попытка', cancelled: 'Отменён' };
const stages = { narration: 'Озвучка Qwen', capturing: 'Запись сайта', encoding: 'Монтаж и субтитры', uploading: 'Загрузка MP4' };

function VideoProject({ item, busy, request, readFile, downloadFile }) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  const file = `/videos/${item.id}/file`;
  async function showPreview() {
    setLoading(true); setError('');
    try { setPreview(URL.createObjectURL(await readFile(file))); }
    catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }
  const active = ['queued_script', 'writing_script', 'queued_render', 'rendering'].includes(item.status);
  return <article className="mkt-panel mkt-video-project">
    <div className="mkt-row mkt-between"><h3>{item.storyboard?.title || item.brief}</h3><span className="mkt-status">{labels[item.status]}</span></div>
    {item.storyboard && <p className="mkt-muted">{item.brief}</p>}
    {item.status === 'rendering' && <p role="status">{stages[item.stage] || 'Создание видео'}</p>}
    {item.reason && <p className="mkt-error">{item.reason}</p>}
    {item.storyboard && <details><summary>Сценарий · {item.storyboard.scenes.length} сцены</summary><ol className="mkt-video-scenes">
      {item.storyboard.scenes.map((scene, i) => <li key={i}><strong>{scene.headline}</strong><p>{scene.narration}</p></li>)}
    </ol></details>}
    {preview && <video className="mkt-video-preview" src={preview} controls preload="metadata" aria-label={item.storyboard?.title} />}
    {error && <p role="alert">{error}</p>}
    <div className="mkt-actions">
      {item.status === 'complete' && <><button disabled={busy} onClick={() => downloadFile(file, `${item.id}.mp4`)}>Скачать MP4</button>
        {!preview && <button disabled={loading} onClick={showPreview}>{loading ? 'Загрузка…' : 'Посмотреть видео'}</button>}
        <span className="mkt-muted">1080 × 1920 · 30 кадров/с · с озвучкой</span></>}
      {active && <button disabled={busy} onClick={() => request(`/videos/${item.id}/cancel`, { method: 'POST', body: { expected_version: item.version }, message: 'Видеопроект отменён' })}>Отменить</button>}
      {['error', 'cancelled'].includes(item.status) && <button disabled={busy} onClick={() => request(`/videos/${item.id}/retry`, { method: 'POST', body: { expected_version: item.version }, message: 'Видеопроект возвращён в очередь' })}>Повторить</button>}
    </div>
  </article>;
}

export function VideoStudio(props) {
  const { data, busy, request } = props;
  const [brief, setBrief] = useState('');
  async function create(event) {
    event.preventDefault();
    const result = await request('/videos', { method: 'POST', body: { brief }, message: 'Видеопроект создан' });
    if (result) setBrief('');
  }
  return <div className="mkt-stack">
    <Panel title="От идеи до ролика" labelled>
      <p>PR и знакомство с UZStock: сценарий, мужской голос Qwen, реальные кадры сайта и субтитры. Готовый MP4 можно использовать на разных площадках.</p>
      <form onSubmit={create} className="mkt-stack">
        <Field label="О чём ролик?" help="Например: покажи, как найти новости на UZStock, и пригласи зрителя на сайт.">
          <textarea required minLength={10} maxLength={2000} rows={3} value={brief} onChange={event => setBrief(event.target.value)} />
        </Field>
        <div className="mkt-row mkt-between"><button disabled={busy || brief.trim().length < 10}>Создать видео</button><span className="mkt-muted">Вертикальный формат · русский язык</span></div>
      </form>
    </Panel>
    <aside className="mkt-callout" aria-label="Видеоворкер">
      <strong>{data.video_worker?.online ? 'Видеоворкер на ПК подключён' : 'Видеоворкер на ПК не в сети'}</strong>
      <p>{data.video_worker?.online ? 'Оставьте ПК включённым до завершения озвучки и монтажа.' : 'Сценарий создаётся на сервере. Озвучка и монтаж начнутся, когда видеоворкер на ПК подключится.'} Создание видео не публикует его в соцсетях.</p>
    </aside>
    {(data.video_projects || []).map(item => <VideoProject key={item.id} {...props} item={item} />)}
    {!data.video_projects?.length && <p className="mkt-muted">Здесь появятся сценарии и готовые видео.</p>}
  </div>;
}
