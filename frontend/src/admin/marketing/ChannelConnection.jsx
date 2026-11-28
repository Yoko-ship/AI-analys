import { SafeLink } from './Widgets.jsx';
import { reasonText } from './reasonCopy.js';
import { LinkedInConnection } from './LinkedInConnection.jsx';
import { MetaConnection } from './MetaConnection.jsx';

export function connectionStatus(data, account) {
  if (account && data.channel_setup?.[account.id]?.ready) return 'connected';
  return account?.connection_status === 'error' ? 'error' : 'not_connected';
}

export function ChannelConnection({ platform, account, data, request, busy }) {
  const setup = (account && data.channel_setup?.[account.id]) || data.provider_setup?.[platform.id];
  if (platform.id === 'linkedin') return <LinkedInConnection {...{ platform, account, setup, request, busy }} />;
  if (['facebook', 'instagram'].includes(platform.id)) return <MetaConnection {...{ platform, account, setup, request, busy }} />;
  const label = !setup?.implemented ? 'Интеграция готовится' : setup.ready ? 'Подключение проверено' : setup.configured ? 'Нужна проверка' : 'Не настроено';
  return <section aria-label={`Подключение ${platform.name}`} className="mkt-item">
    <p><strong>{label}</strong></p>
    {setup?.implemented ? <>
      <p>Отдельный бот с правом публикации в конкретном канале. Проверка сверяет ID канала и права бота.</p>
      <ol><li><SafeLink href="https://t.me/BotFather">Создайте бота через BotFather ↗</SafeLink> и добавьте его администратором канала с правом публикации.</li>
        <li>Сохраните токен на сервере в приватной переменной <code>{setup.credential_setting}</code> и перезапустите сервис с обновлённым окружением.</li>
        <li>В правилах аккаунта укажите числовой ID канала вида <code>-100…</code>, затем проверьте подключение.</li></ol>
      <p className="mkt-muted">Токен не передаётся в эту форму. Текст, изображения, альбомы и видео поддерживаются; Stories канала пока недоступны.</p>
      {!account && <p>Сначала сохраните правила целевого аккаунта.</p>}
      {account?.connection_reason && <p>{reasonText(account.connection_reason)}</p>}
      {account?.connection_checked_at && <p className="mkt-muted">Последняя проверка: {new Date(account.connection_checked_at).toLocaleString('ru-RU', { timeZone: 'Asia/Tashkent' })}</p>}
      <button disabled={busy || !account || !setup.configured} onClick={() => request(`/accounts/${account.id}/probe`, { method: 'POST', body: { expected_version: account.version }, message: 'Проверка завершена. Результат показан у аккаунта.' })}>Проверить подключение</button>
    </> : <p className="mkt-muted">Подключение и отправка через эту площадку ещё не реализованы. Правила и черновики можно подготовить заранее.</p>}
  </section>;
}
