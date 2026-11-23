import React from 'react';
import { reportRatioUnit } from '../lib/reportRatioDisplay.js';

export default function OtherFilingValue({ filing, lang }) {
  if (!filing || filing.standard !== 'ifrs' || !['separate','consolidated'].includes(filing.scope)
      || filing.value == null || !/^https:\/\//i.test(filing.source_url || '')) return null;
  const labels = {
    ru: ['МСФО', 'консолидированная', 'отдельная'],
    uz: ['MHXS', 'konsolidatsiyalangan', 'alohida'],
    en: ['IFRS', 'consolidated', 'separate'],
  };
  const [standard, consolidated, separate] = labels[lang] || labels.ru;
  const scope = filing.scope === 'consolidated' ? consolidated : separate;
  const href = Number.isInteger(filing.page) ? filing.source_url+'#page='+filing.page : filing.source_url;
  const period = filing.period_start && filing.period_end ? filing.period_start+' – '+filing.period_end : filing.period_end || filing.period;
  const assurance = filing.audited === false && ({ru:'без аудита',uz:'auditsiz',en:'unaudited'}[lang] || 'без аудита');
  const quote = filing.market_as_of && (({ru:'Котировка',uz:'Kotirovka',en:'Quote'}[lang] || 'Котировка')+' '+filing.market_as_of);
  return <small><a href={href} target="_blank" rel="noreferrer">
    {[standard, scope, assurance, period].filter(Boolean).join(' · ')} · {Number(filing.value).toLocaleString(lang==='en'?'en-US':'ru-RU', { maximumFractionDigits: filing.unit === 'percent' ? 2 : 10 })}{reportRatioUnit(filing.unit,lang)}{quote && ' · '+quote}
  </a></small>;
}
