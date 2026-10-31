const languages = {ru: 'ru-RU', uz: 'uz-Latn-UZ', en: 'en-US'};
const languageKey = lang => Object.hasOwn(languages, lang) ? lang : 'ru';

export function reportDateLabel(value, lang = 'ru') {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return '—';
  const date = new Date(`${value}T00:00:00Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value) return '—';
  // Some browsers lack Uzbek month names and render placeholders such as M09.
  if (lang === 'uz') {
    const months = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun', 'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'];
    return `${date.getUTCDate()}-${months[date.getUTCMonth()]}, ${date.getUTCFullYear()}`;
  }
  return date.toLocaleDateString(languages[languageKey(lang)], {
    day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
  });
}

// Financial overview flows are cumulative from January, not standalone quarters.
export function reportPeriodLabel(value, lang = 'ru', compact = false) {
  const period = String(value || '');
  if (/^\d{4}$/.test(period)) return period;
  const match = /^(\d{4})Q([1-4])$/.exec(period);
  if (!match) return reportDateLabel(period, lang);
  const [, year, quarter] = match, months = Number(quarter) * 3;
  if (months === 12) return year;
  const language = languageKey(lang);
  if (compact) return {
    ru: `${months} мес. ${year}`, uz: `${year} · ${months} oy`, en: `${months} months ${year}`,
  }[language];
  const ranges = {
    ru: ['январь–март', 'январь–июнь', 'январь–сентябрь'],
    uz: ['yanvar–mart', 'yanvar–iyun', 'yanvar–sentabr'],
    en: ['January–March', 'January–June', 'January–September'],
  };
  const range = ranges[language][Number(quarter) - 1];
  return language === 'uz' ? `${year}-yil ${range}` : `${range} ${year}`;
}

export function reportScopeLabel(scope, lang = 'ru') {
  const labels = {
    separate: {ru: 'Отчётность компании', uz: 'Kompaniya hisoboti', en: 'Company financial statements'},
    consolidated: {ru: 'Отчётность группы компаний', uz: 'Kompaniyalar guruhi hisoboti', en: 'Group financial statements'},
    unknown: {ru: 'Состав отчётности не уточнён', uz: 'Hisobot qamrovi aniqlanmagan', en: 'Reporting coverage is unconfirmed'},
  };
  return (Object.hasOwn(labels, scope) ? labels[scope] : labels.unknown)[languageKey(lang)];
}
