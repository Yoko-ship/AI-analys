import { Field, Panel, Status } from './Widgets.jsx';

export function TelegramNews({ data, request, busy, navigate }) {
  const account = data.accounts.find(item => item.platform === 'telegram');
  const connected = account && data.channel_setup[account.id]?.ready;
  const active = connected && account.automatic_news;
  const configured = data.provider_setup?.telegram?.configured;
  const tasks = data.tasks.filter(task => task.editorial?.kind === 'telegram');
  const latest = tasks[0];
  async function connect(event) {
    event.preventDefault();
    await request('/telegram/connect', { method: 'POST', body: {
      channel: new FormData(event.currentTarget).get('channel'), account_id: account?.id || null,
      expected_version: account?.version || 0,
    }, message: 'Проверка подключения завершена.' });
  }
  async function pause() {
    await request(`/telegram/${account.id}/pause`, { method: 'POST', body: {
      expected_version: account.version, paused: !account.paused,
    } });
  }
  return <Panel title="Telegram" labelled>
    {active ? <div className="mkt-stack">
      <div className="mkt-row mkt-between"><strong>Канал подключён · {account.connection_identity?.title || account.label}</strong>
        <Status value={account.paused ? 'paused' : 'connected'} /></div>
      <p>Новости UZStock подбираются автоматически. ИИ сверяет источник, готовит текст и проверяет его перед выпуском.</p>
      <p>{account.mode === 'automatic' ? 'Проверенные посты публикуются автоматически.' : account.mode === 'manual'
        ? 'Готовые посты ждут вашего решения перед публикацией.' : 'Готовые посты сохраняются как внутренние черновики.'} До {data.telegram_news?.max_daily || 2} постов в день.</p>
      {data.pause.processing && <p role="status">Обработка материалов на общей паузе. Возобновите её в настройках.</p>}
      {!data.model.configured && <p role="status">Подключение ИИ на сервере недоступно. Канал сохранён.</p>}
      {latest ? <p><Status value={latest.status} /> {latest.title}</p> : <p className="mkt-muted">Ожидаем свежую новость. Открытая вкладка и включённый компьютер не нужны.</p>}
      <div className="mkt-actions"><button onClick={() => navigate('content')}>Открыть посты</button>
        <button disabled={busy} onClick={pause}>{account.paused ? 'Возобновить Telegram' : 'Приостановить Telegram'}</button></div>
    </div> : <form className="mkt-form" onSubmit={connect}>
      <p>Подключите канал один раз. Источники, задания и проверка новостей работают автоматически.</p>
      {!configured && <p role="status">Сначала сохраните токен бота на сервере. После этого здесь понадобится только канал.</p>}
      {account?.connection_status === 'error' && <p role="alert" className="mkt-error">Проверьте ID канала и право бота публиковать сообщения. Подключение не подтверждено.</p>}
      <Field label="Канал Telegram" name="channel" required pattern="-100[0-9]+" defaultValue={account?.external_id || ''}
        placeholder="-100…" help="ID канала. Бот должен быть администратором с правом публикации." />
      <p className="mkt-muted">{!account || account.mode === 'automatic' ? 'Проверенные новости будут публиковаться автоматически, до двух постов в день.'
        : 'Сохраняется выбранный режим выпуска канала.'} Работает до отключения; цель и стратегия не требуются.</p>
      <button className="mkt-primary" disabled={busy || !configured}>Подключить канал</button>
    </form>}
  </Panel>;
}
