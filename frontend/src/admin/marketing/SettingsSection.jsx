import { useState } from 'react';
import { VersionedEditor } from './VersionedEditor.jsx';
import { Field, Panel, Status } from './Widgets.jsx';
import { FounderFacts } from './FounderFacts.jsx';
import { ChannelConnection, connectionStatus } from './ChannelConnection.jsx';

function AccountForm({ platform, account, rubrics, request, busy }) {
  const [mode, setMode] = useState(account?.mode || 'draft');
  const supported = platform.formats || [];
  async function save(event) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const value = { platform: platform.id, label: fields.get('label'), external_id: fields.get('external_id'), mode,
      rubrics: fields.getAll('rubrics'), formats: fields.getAll('formats'), languages: fields.getAll('languages'),
      valid_until: fields.get('valid_until') ? `${fields.get('valid_until')}T23:59:00+05:00` : null,
      window_start: fields.get('window_start'), window_end: fields.get('window_end'),
      min_interval_minutes: Number(fields.get('min_interval_minutes')), correction_policy: 'manual',
      personal_profile: fields.has('personal_profile'), paused: account?.paused || false,
      news_daily_limit: account?.news_daily_limit || 2, news_publish_times: account?.news_publish_times || [],
      automatic_news: account?.automatic_news || false };
    await request(`/accounts/${account?.id || platform.id}`, { method: 'PUT', body: { data: value, expected_version: account?.version || 0 }, message: 'Правила аккаунта сохранены. Подключение проверяется отдельно.' });
  }
  return <form className="mkt-form" onSubmit={save}>
    <Field label="Название аккаунта" name="label" defaultValue={account?.label || platform.name} required />
    <Field label="ID целевого аккаунта" name="external_id" defaultValue={account?.external_id || ''} required={mode !== 'draft'} help="Только идентификатор канала или профиля. Секреты и токены здесь не сохраняются." />
    <Field label="Режим выпуска"><select value={mode} onChange={e => setMode(e.target.value)}><option value="draft">Только черновики</option><option value="manual">Каждая версия по моему решению</option><option value="automatic">Разрешённая органика автоматически</option></select></Field>
    <fieldset><legend>Разрешённые рубрики</legend><div className="mkt-checks">{rubrics.map(r => <label key={r.id}><input type="checkbox" name="rubrics" value={r.id} defaultChecked={account?.rubrics.includes(r.id)} />{r.name}</label>)}</div></fieldset>
    <fieldset><legend>Форматы</legend><div className="mkt-checks">{[['post', 'Пост'], ['image', 'Изображение'], ['carousel', 'Карусель'], ['video', 'Видео'], ['story', 'Stories']].map(([id, label]) => <label key={id}><input type="checkbox" name="formats" value={id} disabled={!supported.includes(id)} defaultChecked={supported.includes(id) && account?.formats.includes(id)} />{id === 'video' && platform.id === 'facebook' ? 'Видео · общедоступный Reel с отметкой ИИ' : id === 'video' && platform.id === 'instagram' ? 'Видео · Reel с отметкой ИИ' : label}{!supported.includes(id) && ' · недоступно'}</label>)}</div></fieldset>
    <p className="mkt-muted">Здесь доступны форматы, которые поддерживает подключение этой площадки. Вход и разрешения проверяются отдельно.</p>
    {account?.formats.some(format => !supported.includes(format)) && <p className="mkt-callout">В прежних правилах есть неподдерживаемые форматы. Сохранение уберёт их из разрешения; история материалов останется.</p>}
    {platform.id === 'facebook' && <p>Аудитория Reels: все. Видео публикуются на выбранной странице с отметкой об использовании ИИ. Разрешайте формат «Видео» только для таких публикаций. Совместные публикации и отправка на другие страницы не включены.</p>}
    {platform.id === 'instagram' && <p>Видео публикуются как Reels в выбранном Instagram с отметкой об использовании ИИ. Дополнительное размещение в ленте профиля отключено. Видимость и возможность ремиксов зависят от настроек самого Instagram.</p>}
    {platform.id === 'instagram' && <p>Stories доступны только для бизнес-аккаунта: отправляется изображение с текстом и отметкой ИИ. Отдельная подпись и ссылка-стикер не добавляются. После отправки проверяем наличие изображения среди активных Stories.</p>}
    <fieldset><legend>Языки</legend><div className="mkt-checks">{[['ru', 'Русский'], ['uz', 'O‘zbekcha'], ['en', 'English']].map(([id, label]) => <label key={id}><input type="checkbox" name="languages" value={id} defaultChecked={(account?.languages || ['ru']).includes(id)} />{label}</label>)}</div></fieldset>
    <div className="mkt-fields"><Field label="Разрешение действует до" name="valid_until" type="date" defaultValue={account?.valid_until?.slice(0, 10) || ''} required={mode !== 'draft' && !account?.automatic_news} />
      <Field label="Интервал между публикациями · минуты" name="min_interval_minutes" type="number" min="1" max="10080" defaultValue={account?.min_interval_minutes || 60} required />
      <Field label="Начало окна · Ташкент" name="window_start" type="time" defaultValue={account?.window_start?.slice(0, 5) || '09:00'} required />
      <Field label="Конец окна · Ташкент" name="window_end" type="time" defaultValue={account?.window_end?.slice(0, 5) || '21:00'} required /></div>
    {platform.id === 'telegram' && account?.automatic_news && <p className="mkt-muted">Количество автоматических новостей и время каждого поста меняются в «Обзор команды → Telegram → Расписание публикаций».</p>}
    {platform.id === 'linkedin' && <label className="mkt-checkbox"><input type="checkbox" name="personal_profile" defaultChecked={account?.personal_profile} required={mode !== 'draft'} />Разрешаю этот личный профиль отдельно от корпоративных каналов</label>}
    <p className="mkt-muted">Правила относятся только к органическим публикациям в указанном аккаунте. Реклама и личные сообщения требуют отдельного решения.</p>
    <button className="mkt-primary" disabled={busy}>Сохранить правила аккаунта</button>
  </form>;
}

export function SettingsSection({ data, busy, request, error, onHistory }) {
  const [open, setOpen] = useState(null);
  return <div className="mkt-stack"><div className="mkt-actions"><button disabled={busy} onClick={() => request('/workspace')}>Обновить подключения</button></div><Panel title="Остановка работы"><div className="mkt-fields">
    <div><h4>Публикации</h4><p>Пауза запрещает новые отправки. Уже начатые отправки сохраняют свой статус.</p><button disabled={busy || (data.pause.publications && data.recovery?.status === 'requires_reconciliation')} onClick={() => request('/pause', { method: 'PUT', body: { publications: !data.pause.publications } })}>{data.pause.publications ? 'Возобновить публикации' : 'Приостановить публикации'}</button></div>
    <div><h4>Обработка материалов</h4><p>Независимая пауза подготовки. История и сохранённые результаты остаются доступны.</p><button disabled={busy} onClick={() => request('/pause', { method: 'PUT', body: { processing: !data.pause.processing } })}>{data.pause.processing ? 'Возобновить обработку' : 'Приостановить обработку'}</button></div>
  </div></Panel><div className="mkt-columns">{data.platforms.map(platform => {
    const account = data.accounts.find(a => a.platform === platform.id);
    return <Panel key={platform.id} title={platform.name} action={<Status value={connectionStatus(data, account)} />}>
      <p>{platform.login}</p><p className="mkt-muted">{account ? `Правила сохранены · версия ${account.version}` : 'Публикация закрыта. Аккаунт ещё не настроен.'}</p>
      <button type="button" aria-expanded={open === platform.id} aria-controls={`account-${platform.id}`} onClick={() => setOpen(open === platform.id ? null : platform.id)}>Настроить {platform.name}</button>
      {open === platform.id && <div id={`account-${platform.id}`}><VersionedEditor value={account} request={request}>{(saved, save) => <AccountForm platform={platform} account={saved} request={save} busy={busy} rubrics={data.rubrics} />}</VersionedEditor></div>}
      <ChannelConnection platform={platform} account={account} data={data} request={request} busy={busy} />
    </Panel>;
  })}</div><FounderFacts data={data} request={request} busy={busy} error={error} onHistory={onHistory} /></div>;
}
