import { SafeLink, date } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';

export function LinkedInConnection({ platform, account, setup, request, busy }) {
  async function connect() {
    const result = await request(`/accounts/${account.id}/linkedin/start`, {
      method: 'POST', body: { expected_version: account.version }, refresh: false,
    });
    if (!result?.authorization_url) return;
    const url = new URL(result.authorization_url);
    if (url.origin === 'https://www.linkedin.com' && url.pathname === '/oauth/v2/authorization') window.location.assign(url.href);
  }
  const connected = setup?.ready;
  return <section aria-label={`Подключение ${platform.name}`} className="mkt-item">
    <p><strong>{connected ? 'Подключение проверено' : setup?.configured ? 'Нужен вход владельца' : 'Настройка приложения LinkedIn'}</strong></p>
    <p>Вход закрепляет конкретный личный профиль. Режим выпуска, рубрики и срок разрешения задаются в правилах аккаунта.</p>
    {!setup?.configured && <>
      <ol><li><SafeLink href="https://www.linkedin.com/developers/apps">Откройте приложение LinkedIn ↗</SafeLink> и включите продукты «Sign in with LinkedIn using OpenID Connect» и «Share on LinkedIn».</li>
        <li>На сервере задайте приватные параметры приложения и ключ шифрования: {(setup?.required_settings || []).map((name, index) => <span key={name}>{index > 0 ? ', ' : ''}<code>{name}</code></span>)}.</li>
        <li>Зарегистрируйте HTTPS-адрес возврата на этом сайте с путём <code>/admin/ai-marketing</code>. Затем обновите подключения.</li></ol>
      <p className="mkt-muted">Секрет приложения и токен не нужно вводить в эту форму.</p>
    </>}
    {setup?.callback_url && <p>Адрес возврата в настройках LinkedIn: <code>{setup.callback_url}</code></p>}
    {!account ? <p>Сохраните правила аккаунта и отдельно разрешите личный профиль. Для первого входа можно оставить ID пустым и выбрать режим черновиков.</p>
      : !account.personal_profile && <p>В правилах аккаунта отметьте отдельное разрешение личного профиля.</p>}
    {connected && <p><strong>{account.connection_identity?.title}</strong><br /><code>{account.external_id}</code><br />Доступ до {date(setup.expires_at)}. Затем потребуется повторный вход.</p>}
    {!connected && account && setup?.configured && <p>{reasonText(setup.reason)}</p>}
    <p className="mkt-muted">Доступны текст, изображение, карусель изображений и видео. После создания поста откройте его в LinkedIn и подтвердите видимость в разделе контента. При неясном исходе повторная отправка заблокирована.</p>
    <div className="mkt-actions">
      <button className="mkt-primary" disabled={busy || !account?.personal_profile || !setup?.configured} onClick={connect}>{connected ? 'Повторить вход LinkedIn' : 'Войти через LinkedIn'}</button>
      {setup?.has_credential && <button disabled={busy} onClick={() => request(`/accounts/${account.id}/probe`, { method: 'POST', body: { expected_version: account.version }, message: 'Проверка профиля завершена.' })}>Проверить профиль</button>}
      {account && account.connection_status !== 'not_connected' && <button disabled={busy} onClick={() => request(`/accounts/${account.id}/linkedin/disconnect`, { method: 'POST', body: { expected_version: account.version }, message: 'Токен удалён из UZStock. Отозвать доступ приложения в самом LinkedIn можно в настройках LinkedIn.' })}>Отключить LinkedIn</button>}
    </div>
  </section>;
}
