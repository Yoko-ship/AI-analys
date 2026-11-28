import { useState } from 'react';
import { Field, Panel, date } from './Widgets.jsx';
import { ReportImport, ReportSetup } from './ReportSetup.jsx';
import { ReportComparison, ReportResults } from './ReportResults.jsx';
import { ReportReview } from './ReportReview.jsx';
import { WebsiteSource } from './WebsiteSource.jsx';
import { VersionedEditor } from './VersionedEditor.jsx';

export function ReportsSection({ data, busy, request, downloadFile }) {
  const [period, setPeriod] = useState(data.report_period);
  const [report, setReport] = useState(null);
  const [snapshotId, setSnapshotId] = useState('');
  const [baseline, setBaseline] = useState(data.snapshots[0]?.id || '');
  const [comparison, setComparison] = useState(null);
  const [name, setName] = useState('');
  const [reason, setReason] = useState('');
  const [dialog, setDialog] = useState(null);
  const selected = data.snapshots.find(item => item.id === snapshotId);
  function showSnapshot(id) {
    setSnapshotId(id); setComparison(null);
    const item = data.snapshots.find(s => s.id === id);
    if (item) setReport(item.report); else setReport(null);
  }
  async function calculate(event) {
    event.preventDefault();
    const result = await request('/reports/calculate', { method: 'POST', body: period, refresh: false });
    if (result) { setReport(result.report); setSnapshotId(''); setComparison(null); }
  }
  async function freeze(event) {
    event.preventDefault();
    const { starts_on, ends_on, cutoff } = report.period;
    const result = await request('/reports/snapshots', { method: 'POST', body: { name, period: { starts_on, ends_on, cutoff }, expected_settings_version: report.settings_version } });
    if (result) { setSnapshotId(result.item.id); setReport(result.item.report); setBaseline(old => old || result.item.id); setComparison(null); }
  }
  async function recompute(event) {
    event.preventDefault();
    const result = await request(`/reports/snapshots/${snapshotId}/recompute`, { method: 'POST', body: { reason } });
    if (result) { setSnapshotId(result.item.id); setReport(result.item.report); setComparison(null); setReason(''); }
  }
  async function compare() {
    const { starts_on, ends_on, cutoff } = report.period;
    const result = await request('/reports/compare', { method: 'POST', refresh: false, body: { first_id: baseline, ...(snapshotId ? { second_id: snapshotId } : { period: { starts_on, ends_on, cutoff } }) } });
    if (result) setComparison(result);
  }
  async function refresh() {
    const body = { starts_on: report.period.starts_on, ends_on: report.period.ends_on };
    const result = await request('/reports/calculate', { method: 'POST', body, refresh: false });
    if (result) { setReport(result.report); setSnapshotId(''); setComparison(null); }
  }
  return <div className="mkt-stack mkt-reports">
    <VersionedEditor value={data.website?.settings} request={request}>{(saved, save) => <WebsiteSource source={data.website ? { ...data.website, settings: saved } : null} period={period} reportDataset={data.analytics_settings.data.dataset} paused={data.pause.processing} busy={busy} request={save} />}</VersionedEditor>
    <Panel title="Период и база отчёта" action={<div className="mkt-actions"><button onClick={() => setDialog('settings')}>Настроить расчёты</button><button onClick={() => setDialog('import')}>Импортировать события</button></div>}>
      <form onSubmit={calculate} className="mkt-form"><div className="mkt-fields"><Field label="Начало отчёта" type="date" required value={period.starts_on} onChange={e => setPeriod(p => ({ ...p, starts_on: e.target.value }))} /><Field label="Конец отчёта, не включая" type="date" required value={period.ends_on} onChange={e => setPeriod(p => ({ ...p, ends_on: e.target.value }))} /></div><div><button disabled={busy} className="mkt-primary">Рассчитать период</button></div></form>
      <p className="mkt-muted">Asia/Tashkent · Полнота источника подтверждается отдельно. Данные без подтверждения не превращаются в ноль.</p>
      <Field label="Показать снимок"><select value={snapshotId} onChange={e => showSnapshot(e.target.value)}><option value="">Текущий расчёт</option>{data.snapshots.map(item => <option key={item.id} value={item.id}>{item.name} · {date(item.report.period.cutoff)}</option>)}</select></Field>
    </Panel>
    {!report && <Panel title="Недельный отчёт"><p>Выберите период и рассчитайте показатели либо откройте сохранённый снимок.</p></Panel>}
    {report && <>
      <Panel title={selected?.name || 'Текущий расчёт'}><p>{date(report.period.starts_on)} — {date(report.period.ends_on)} (конец не включён) · Правила v{report.settings_version} · Формулы v{report.method.formula_version}</p>
        {selected && <p>Неизменяемый снимок{selected.recomputed_from ? ' · создан пересчётом предыдущего снимка' : ''}. {selected.reason}</p>}
        {data.analytics_settings.version !== report.settings_version && <p className="mkt-callout">Правила изменились. Этот отчёт сохраняет прежнюю версию; новый расчёт применит актуальные правила.</p>}
        {!snapshotId ? <form className="mkt-form" onSubmit={freeze}><Field label="Название снимка" required maxLength="150" value={name} onChange={e => setName(e.target.value)} /><button disabled={busy || data.analytics_settings.version !== report.settings_version}>Зафиксировать неделю</button></form> : <><div className="mkt-actions"><button disabled={busy} onClick={() => downloadFile(`/reports/snapshots/${snapshotId}/export`, 'marketing-report.json')}>Скачать JSON</button><button disabled={busy} onClick={() => downloadFile(`/reports/snapshots/${snapshotId}/export?format=csv`, 'marketing-report.csv')}>Скачать CSV</button></div><form className="mkt-form" onSubmit={recompute}><Field label="Причина пересчёта" required maxLength="2000" value={reason} onChange={e => setReason(e.target.value)} /><button disabled={busy}>Создать пересчитанный снимок</button></form></>}
      </Panel>
      <Panel title="Сопоставление"><Field label="Базовый снимок"><select value={baseline} onChange={e => { setBaseline(e.target.value); setComparison(null); }}><option value="">Выберите снимок</option>{data.snapshots.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></Field><p>База сравнивается с открытым отчётом. Изменение правил, валюты или полноты источников исключает расчёт разницы.</p><button disabled={busy || !baseline} onClick={compare}>Сравнить отчёты</button></Panel>
      <ReportComparison comparison={comparison} metrics={report.metrics} />
      <ReportReview key={`${report.period.starts_on}:${report.period.ends_on}:${report.review.version}:${snapshotId}`} report={report} frozen={Boolean(snapshotId)} request={request} busy={busy} refresh={refresh} roles={data.roles} />
      <ReportResults report={report} />
    </>}
    {dialog === 'settings' && <ReportSetup saved={data.analytics_settings} request={request} busy={busy} onClose={() => setDialog(null)} />}
    {dialog === 'import' && <ReportImport request={request} busy={busy} onClose={() => setDialog(null)} />}
  </div>;
}
