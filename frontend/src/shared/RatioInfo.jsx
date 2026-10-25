import React from 'react';
import {TermInfo} from './TermInfo.jsx';
import {termFor} from '../lib/glossary.js';

const TERMS={current_ratio:'currentRatio',quick_ratio:'quickRatio',debt_ratio:'debtAssets',
  liabilities_to_assets:'debtAssets',debt_to_equity:'debtEq',liabilities_to_equity:'debtEq',de:'debtEq',
  asset_turnover:'assetTurnover',total_asset_turnover:'assetTurnover',return_to_capital_employed:'roce',
  net_margin:'netMargin',net_profit_margin:'netMargin'};

// Prefer the filing's own explanation and formula; glossary definitions fill
// only the gaps. No formula is inferred from the numerical value.
export function RatioInfo({metric,lang,label,meaning,formula}) {
  const entry=termFor(TERMS[metric]||metric,lang);
  const description=[meaning||entry?.def,formula].filter(Boolean).join('\n\n');
  return <TermInfo termId={TERMS[metric]||metric} label={label} lang={lang} description={description}/>;
}
