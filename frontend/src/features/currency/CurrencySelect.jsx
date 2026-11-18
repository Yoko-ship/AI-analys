import { useId } from 'react';
import * as Select from '@radix-ui/react-select';
import './currency-select.css';

const names = {
  UZS: { ru: 'Узбекский сум', en: 'Uzbek som', uz: 'O‘zbek so‘mi' },
  USD: { ru: 'Доллар США', en: 'US dollar', uz: 'AQSH dollari' },
  EUR: { ru: 'Евро', en: 'Euro', uz: 'Yevro' },
  RUB: { ru: 'Российский рубль', en: 'Russian ruble', uz: 'Rossiya rubli' },
  CNY: { ru: 'Китайский юань', en: 'Chinese yuan', uz: 'Xitoy yuani' },
};
const symbols = { EUR: '€', RUB: '₽', CNY: '¥', GBP: '£', JPY: '¥', CHF: 'Fr' };

function currencyName(code, language, rates) {
  if (names[code]?.[language]) return names[code][language];
  const published = rates.find(rate => rate.ccy === code)?.[`name_${language}`];
  if (published) return published;
  try { return new Intl.DisplayNames([language], { type: 'currency' }).of(code); }
  catch { return code; }
}

function CurrencyEmblem({ code }) {
  return <span className={`currency-select-emblem currency-select-emblem-${code.toLowerCase()}`} aria-hidden="true">
    {code === 'USD' || code === 'UZS'
      ? <img src={`/currency-icons/${code.toLowerCase()}.svg`} alt="" />
      : <span>{symbols[code] || code}</span>}
  </span>;
}

export function CurrencySelect({ value, onChange, options, language, label, rates = [] }) {
  const id = useId();
  return <div className="currency-select-field">
    <label className="currency-select-label" htmlFor={id}>
      {language === 'en' ? 'Currency' : language === 'uz' ? 'Valyuta' : 'Валюта'}
    </label>
    <Select.Root value={value} onValueChange={onChange}>
      <Select.Trigger id={id} className="currency-select-trigger" aria-label={label}>
        <CurrencyEmblem code={value} />
        <Select.Value>{value}</Select.Value>
        <Select.Icon className="currency-select-chevron">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="m5 9 7 7 7-7" /></svg>
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className="currency-select-menu" position="popper" side="bottom" align="start" sideOffset={6} collisionPadding={12}>
          <Select.ScrollUpButton className="currency-select-scroll" aria-hidden="true">⌃</Select.ScrollUpButton>
          <Select.Viewport>
            {options.map(code => <Select.Item className="currency-select-option" key={code} value={code} textValue={currencyName(code, language, rates)}>
              <CurrencyEmblem code={code} />
              <Select.ItemText>{currencyName(code, language, rates)}</Select.ItemText>
              <Select.ItemIndicator className="currency-select-check">
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true"><path d="m5 12 4 4 10-10" /></svg>
              </Select.ItemIndicator>
            </Select.Item>)}
          </Select.Viewport>
          <Select.ScrollDownButton className="currency-select-scroll" aria-hidden="true">⌄</Select.ScrollDownButton>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  </div>;
}
