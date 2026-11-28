import { useState } from 'react';
import { Field, SafeLink, date } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';

function AccountChoice({ selection, account, request, busy }) {
  const [target, setTarget] = useState('');
  async function select(event) {
    event.preventDefault();
    if (!target) return;
    await request(`/accounts/${account.id}/meta/select`, { method: 'POST', body: {
      expected_version: account.version, selection_id: selection.selection_id, target_id: target,
    }, message: 'Аккаунт Meta подключён. Правила выпуска сохранили прежние разрешения.' });
  }
  return <form className="mkt-form" onSubmit={select}><fieldset><legend>Выбор аккаунта Meta</legend>
    <p>Выберите получателя из аккаунтов, доступных после входа. Подключение сохраняет текущий режим выпуска.</p>
    <Field label="Аккаунт для подключения"><select value={target} onChange={event => setTarget(event.target.value)} required>
      <option value="">Выберите аккаунт</option>
      {selection.choices.map(choice => <option key={choice.target_id} value={choice.target_id}>{choice.title} · {choice.target_id}</option>)}
    </select></Field>
    {target && <p className="mkt-muted">Страница Facebook: {selection.choices.find(choice => choice.target_id === target)?.page_title}</p>}
    <p className="mkt-muted">Выбор доступен до {new Date(selection.expires_at).toLocaleTimeString('ru-RU', { timeZone: 'Asia/Tashkent' })} · Ташкент. Затем повторите вход.</p>
    <button className="mkt-primary" disabled={busy || !target}>Подключить выбранный аккаунт</button>
  </fieldset></form>;
}

export function MetaConnection({ platform, account, setup, request, busy }) {
  async function connect() {
    const result = await request(`/accounts/${account.id}/meta/start`, { method: 'POST',
      body: { expected_version: account.version }, refresh: false });
    if (!result?.authorization_url) return;
    const url = new URL(result.authorization_url);
    if (url.origin === 'https://www.facebook.com' && /^\/v[0-9]+\.0\/dialog\/oauth$/.test(url.pathname)) window.location.assign(url.href);
  }
  return <section aria-label={`Подключение ${platform.name}`} className="mkt-item">
    <p><strong>{setup?.ready ? 'Подключение проверено' : setup?.selection ? 'Выберите аккаунт после входа' : setup?.configured ? 'Нужен вход владельца' : 'Настройка приложения Meta'}</strong></p>
    <p>{platform.id === 'instagram' ? 'Профессиональный Instagram должен быть связан со страницей Facebook, для которой у вас есть право создавать контент.' : 'Публикации предназначены для выбранной страницы Facebook. Личный профиль Facebook не используется.'}</p>
    {!setup?.configured && <ol>
      <li><SafeLink href="https://developers.facebook.com/apps/">Откройте приложение Meta ↗</SafeLink> и настройте Facebook Login for Business с конфигурацией токена пользователя для этой площадки.</li>
      <li>Задайте на сервере приватные параметры: {(setup?.required_settings || []).map((name, index) => <span key={name}>{index > 0 ? ', ' : ''}<code>{name}</code></span>)}.</li>
      <li>Добавьте HTTPS-адрес возврата с путём <code>/admin/ai-marketing</code>, затем обновите подключения.</li>
    </ol>}
    {setup?.callback_url && <p>Адрес возврата: <code>{setup.callback_url}</code></p>}
    {!account && <p>Сохраните правила аккаунта в режиме черновиков. Для первого входа можно оставить ID пустым и выбрать аккаунт после входа.</p>}
    {setup?.ready && <p><strong>{account.connection_identity?.title}</strong><br /><code>{account.external_id}</code><br />Доступ до {date(setup.expires_at)}. Права повторно проверяются при проверке подключения.</p>}
    {account && setup?.configured && !setup.ready && !setup.selection && <p>{reasonText(setup.reason)}</p>}
    {setup?.selection && account && <AccountChoice key={setup.selection.selection_id} selection={setup.selection} account={account} request={request} busy={busy} />}
    <p className="mkt-muted">Секреты сохраняются на сервере. Подключение органического аккаунта не разрешает рекламу.</p>
    <p>{platform.id === 'facebook' ? 'Доступны текстовые посты, фото, подборки фотографий и общедоступные Reels с отметкой ИИ. После отправки проверяются страница, текст и медиа. Лимит Reels — 30 выпусков за последние 24 часа на страницу. Stories ещё готовятся.' : 'Доступны изображения JPEG, карусели из 2–10 изображений, Reels и Stories с отметкой ИИ. Дополнительное размещение Reels в ленте профиля отключено. Stories отправляются как изображение с текстом и доступны только бизнес-аккаунтам. После отправки проверяем публикацию в выбранном аккаунте; для Story — наличие среди активных Stories. Лимит публикаций запрашивается у Instagram.'}</p>
    <div className="mkt-actions">
      <button className="mkt-primary" disabled={busy || !account || !setup?.configured} onClick={connect}>{setup?.ready ? 'Повторить вход Meta' : 'Войти через Meta'}</button>
      {setup?.has_credential && <button disabled={busy} onClick={() => request(`/accounts/${account.id}/probe`, { method: 'POST', body: { expected_version: account.version }, message: 'Проверка аккаунта Meta завершена.' })}>Проверить аккаунт Meta</button>}
      {account && (setup?.selection || account.connection_status !== 'not_connected') && <button disabled={busy} onClick={() => request(`/accounts/${account.id}/meta/disconnect`, { method: 'POST', body: { expected_version: account.version }, message: 'Токены удалены из UZStock. Доступ приложения в Meta можно отозвать в настройках бизнес-интеграций Meta.' })}>Отключить Meta</button>}
    </div>
  </section>;
}
