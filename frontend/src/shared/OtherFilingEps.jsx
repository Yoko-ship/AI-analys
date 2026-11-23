import React from 'react';
import { reportRatioUnit } from '../lib/reportRatioDisplay.js';

export default function OtherFilingEps({ filing, lang }) {
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
  const period = filing.period_start && filing.period_end ? filing.period_start+' – '+filing.period_end : filing.period;
  return <small><a href={href} target="_blank" rel="noreferrer">
    {standard} · {scope} · {period} · {Number(filing.value).toLocaleString(lang==='en'?'en-US':'ru-RU', { maximumFractionDigits: 10 })}{reportRatioUnit(filing.unit,lang)}
  </a></small>;
}
