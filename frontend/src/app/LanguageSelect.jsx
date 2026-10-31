import * as Select from '@radix-ui/react-select';
import { normalizeLanguage } from '../shared/i18n.jsx';
import './language-select.css';

const languages = [
  { value: 'ru', name: 'Русский' },
  { value: 'uz', name: 'O‘zbekcha' },
  { value: 'en', name: 'English' },
];
const labels = {
  ru: { field: 'Язык', title: 'Язык интерфейса' },
  uz: { field: 'Til', title: 'Interfeys tili' },
  en: { field: 'Language', title: 'Interface language' },
};

export function LanguageSelect({ language, onChange, landing, onOpen }) {
  const value = normalizeLanguage(language);
  const copy = labels[value];
  return <div className="topbar-language">
    <Select.Root value={value} onValueChange={onChange} onOpenChange={open => { if (open) onOpen(); }}>
      <Select.Trigger id="languageSelect" className="language-trigger" aria-label={copy.field}>
        <svg className="language-globe" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" /><path d="M3 12h18" />
        </svg>
        <Select.Value>{value.toUpperCase()}</Select.Value>
        <Select.Icon className="language-chevron">
          <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="m4 6 4 4 4-4" /></svg>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="language-menu" data-landing={landing} position="popper" side="bottom" align="end" sideOffset={8} collisionPadding={12}>
          <Select.Viewport>
            <Select.Group>
              <Select.Label className="language-menu-label">{copy.title}</Select.Label>
              {languages.map(item => <Select.Item className="language-option" key={item.value} value={item.value} textValue={item.name}>
                <Select.ItemIndicator className="language-check">
                  <svg width="16" height="16" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75" aria-hidden="true"><path d="m4 10 4 4 8-8" /></svg>
                </Select.ItemIndicator>
                <Select.ItemText><span lang={item.value}>{item.name}</span></Select.ItemText>
              </Select.Item>)}
            </Select.Group>
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  </div>;
}
