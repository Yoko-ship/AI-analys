import { localizedPath } from '../../lib/languagePath.js';

export function reportRequest(search, language) {
  const selected = new URLSearchParams(search);
  const mapping = { standard: 'report_standard', scope: 'report_scope', period: 'report_period', lang: 'report_lang', version: 'report_version' };
  const values = { standard: 'nsbu', scope: 'separate', lang: language };
  for (const [name, param] of Object.entries(mapping)) {
    if (selected.getAll(param).length > 1) return null;
    if (selected.has(param)) values[name] = selected.get(param);
  }
  if (!['nsbu', 'ifrs'].includes(values.standard) || !['separate', 'consolidated'].includes(values.scope)
      || !['ru', 'uz', 'en'].includes(values.lang) || ('period' in values && !/^\d{4}(Q[1-4])?$/.test(values.period))
      || ('version' in values && !/^[A-Za-z0-9_-]{1,200}$/.test(values.version))) return null;
  return new URLSearchParams(values).toString();
}

export function reportLink(ticker, language, report) {
  const lang = report?.language || language;
  const params = new URLSearchParams({ report: 'ai' });
  if (report?.standard) params.set('report_standard', report.standard);
  if (report?.standard) params.set('report_scope', report.scope || 'separate');
  if (report?.period) params.set('report_period', report.period);
  params.set('report_lang', lang);
  if (report?.version) params.set('report_version', report.version);
  return `${localizedPath(`/company/${encodeURIComponent(ticker)}`, lang)}?${params}`;
}

export async function readReport(response) {
  const body = await response.json().catch(() => null);
  if (!response.ok || !body?.ok || !body?.headline) {
    const error = new Error('Company insight unavailable');
    error.code = body?.detail?.code;
    throw error;
  }
  return body;
}
