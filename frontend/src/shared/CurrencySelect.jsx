import { useId } from 'react';
import * as Select from '@radix-ui/react-select';
import franklin from '../assets/benjamin-franklin.webp';
import emblem from '../assets/uzbekistan-emblem.webp';
import './currencySelect.css';

// Portrait: https://www.loc.gov/item/2004671903/
// Emblem: https://commons.wikimedia.org/wiki/File:Emblem_of_Uzbekistan.svg
const currencies = {
  UZS: { image: emblem, ru: 'Узбекский сум', uz: 'O‘zbek so‘mi', en: 'Uzbek som' },
  USD: { image: franklin, ru: 'Доллар США', uz: 'AQSH dollari', en: 'US dollar' },
};

function CurrencyBadge({ code }) {
  return <img className="currency-badge" data-code={code} src={currencies[code].image} width="36" height="36" alt="" />;
}

export function CurrencySelect({ label, lang, value, onChange }) {
  const id = useId();
  return <div className="currency-select">
    <label htmlFor={id}>{label}</label>
    <Select.Root value={value} onValueChange={onChange}>
      <Select.Trigger id={id} className="currency-trigger">
        <CurrencyBadge code={value} />
        <Select.Value>{value}</Select.Value>
        <Select.Icon className="currency-chevron">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="m3 6 5 5 5-5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="currency-menu" aria-label={label} position="popper" align="start" sideOffset={5} collisionPadding={8}>
          <Select.Viewport>
            {Object.entries(currencies).map(([code, currency]) => {
              const name = currency[lang] || currency.ru;
              return <Select.Item key={code} value={code} textValue={name} className="currency-option">
                <CurrencyBadge code={code} />
                <Select.ItemText>{name}</Select.ItemText>
                <Select.ItemIndicator className="currency-check" aria-hidden="true">✓</Select.ItemIndicator>
              </Select.Item>;
            })}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  </div>;
}
