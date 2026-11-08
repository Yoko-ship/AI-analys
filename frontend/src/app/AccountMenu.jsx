import * as Popover from '@radix-ui/react-popover';
import { accountInitials } from '../shared/accountIdentity.jsx';
import { normalizeLanguage, t } from '../shared/i18n.jsx';
import { LanguageSelect } from './LanguageSelect.jsx';
import './account-menu.css';

export const accountLabels = {
  ru: { account: 'Аккаунт и настройки', settings: 'Настройки', language: 'Язык', theme: 'Тема', dark: 'Тёмная', light: 'Светлая' },
  uz: { account: 'Akkaunt va sozlamalar', settings: 'Sozlamalar', language: 'Til', theme: 'Mavzu', dark: 'Tungi', light: 'Kunduzgi' },
  en: { account: 'Account and settings', settings: 'Settings', language: 'Language', theme: 'Theme', dark: 'Dark', light: 'Light' },
};

export function GuestAvatar() {
  return <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
    <circle cx="12" cy="8" r="3.5" /><path d="M5 20v-1a7 7 0 0 1 14 0v1" />
  </svg>;
}

export function AccountMenu({ user, language, setLanguage, theme, toggleTheme, open, onOpenChange, onProfile, onLogout, landing }) {
  const copy = accountLabels[normalizeLanguage(language)];
  return <Popover.Root open={open} onOpenChange={onOpenChange}>
    <div className="account-wrap">
      <Popover.Trigger asChild>
        <button className={`account-button account-avatar${user ? '' : ' account-avatar-guest'}`} type="button"
          aria-label={`${copy.account}${user ? `: ${user.full_name || user.email}` : ''}`}>
          {user ? (user.avatar_data_url ? <img src={user.avatar_data_url} alt="" /> : accountInitials(user)) : <GuestAvatar />}
        </button>
      </Popover.Trigger>
    </div>
    <Popover.Portal>
      <Popover.Content className="account-menu account-preferences" align="end" sideOffset={8} collisionPadding={12} aria-label={copy.account}>
        <div className="account-menu-head">
          <strong>{user ? (user.full_name || user.email) : copy.settings}</strong>
          {user?.full_name && <span>{user.email}</span>}
        </div>
        {user && <button className="account-menu-action" type="button" onClick={onProfile}>{t(language, 'nav.profile')}</button>}
        <div className="account-preference-row">
          <span>{copy.language}</span>
          <LanguageSelect language={language} onChange={setLanguage} landing={landing} />
        </div>
        <div className="account-preference-row">
          <span>{copy.theme}</span>
          <button className="theme-toggle" type="button" onClick={toggleTheme}
            aria-label={theme === 'dark' ? t(language, 'theme.light') : t(language, 'theme.dark')}>
            <strong aria-hidden="true">{theme === 'dark' ? '☾' : '☀'}</strong>
            <span>{theme === 'dark' ? copy.dark : copy.light}</span>
          </button>
        </div>
        {user && <div className="account-menu-footer">
          <button className="account-menu-action is-logout" type="button" onClick={onLogout}>{t(language, 'auth.logout')}</button>
        </div>}
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
