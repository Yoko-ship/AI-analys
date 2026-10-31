import { trackFeature } from "../../lib/track.js";
import React from 'react';
import { words } from '../../shared/TerminalTables.jsx';
import { safeHref } from '../../lib/safeHref.js';
import { qualityReason } from './financialColumnQuality.js';
import { financialGroup } from './financialColumnGroups.js';
import { FinancialHistoryChart } from './FinancialHistoryChart.jsx';
import { RatioInfo } from '../../shared/RatioInfo.jsx';
import './financialColumns.css';

const FORM_ORDER = ['F2', 'BANK_PL', 'INSURANCE_PL', 'PL', 'ASSETS', 'EQUITY', 'CF', 'DEBT', 'F1', 'BANK_BS', 'INSURANCE_BS', 'BS', 'Equity', 'Notes', 'DERIVED', 'RAT'];
const QUALITY = {
  valid: ['Проверено', 'Tekshirilgan', 'Verified'], warn: ['Проверить', 'Tekshirish kerak', 'Review'],
  blocked: ['Расчёт заблокирован', 'Hisoblash bloklangan', 'Calculation blocked'],
  missing: ['Нет данных', 'Ma’lumot yo‘q', 'Missing'], not_applicable: ['Неприменимо', 'Qo‘llanilmaydi', 'Not applicable'],
};
const VIEWS = [['summary', 'Обзор по стандарту', 'Standart bo‘yicha', 'Overview'],
  ['original', 'Исходные строки форм', 'Asl shakllar', 'Original forms'],
  ['ratios', 'Коэффициенты', 'Koeffitsiyentlar', 'Ratios'], ['owners', 'Акционеры', 'Aksiyadorlar', 'Shareholders']];
const GROUPS = {
  ASSETS: ['Активы', 'Aktivlar', 'Assets'], EQUITY: ['Капитал', 'Kapital', 'Equity'],
  DEBT: ['Обязательства и долговая нагрузка', 'Majburiyatlar va qarz', 'Liabilities and debt'],
  DERIVED: ['Расчётные показатели', 'Hisoblangan ko‘rsatkichlar', 'Calculated indicators'],
  F2: ['Финансовые результаты · НСБУ', 'Moliyaviy natijalar · NSBU', 'Income · NSBU'],
  BANK_PL: ['Финансовые результаты · банковская форма', 'Bank daromadlari', 'Income · bank form'],
  INSURANCE_PL: ['Финансовые результаты · страхование', 'Sug‘urta daromadlari', 'Income · insurance'],
  PL: ['Прибыль и совокупный доход · МСФО', 'Foyda va umumiy daromad · IFRS', 'Profit and comprehensive income · IFRS'],
  F1: ['Активы, обязательства и капитал · НСБУ', 'Aktivlar va kapital · NSBU', 'Assets, liabilities and equity · NSBU'],
  BANK_BS: ['Баланс банка', 'Bank balansi', 'Bank balance sheet'],
  INSURANCE_BS: ['Баланс страховщика', 'Sug‘urta balansi', 'Insurance balance sheet'],
  BS: ['Финансовое положение · МСФО', 'Moliyaviy holat · IFRS', 'Financial position · IFRS'],
  CF: ['Денежные потоки', 'Pul oqimlari', 'Cash flows'], Equity: ['Изменения капитала', 'Kapital o‘zgarishi', 'Changes in equity'],
  Notes: ['Примечания', 'Izohlar', 'Notes'], RAT: ['Расчёт UZStock', 'UZStock hisobi', 'UZStock calculations'],
};

function Status({ value, t }) {
  return <span className={`fc-status fc-status-${value || 'missing'}`}>{t(...(QUALITY[value] || QUALITY.missing))}</span>;
}

function FinancialValue({ cell, open, format, t }) {
  const parts = cell.display_parts || [cell];
  return <div className={cell.display_parts ? 'fc-value-parts' : undefined}>{parts.map((part, i) => <button key={i} type="button" className={`fc-value fc-value-${part.quality}`} title={t(...(QUALITY[part.quality] || QUALITY.missing))} onClick={() => open(part)}>
    {cell.display_parts && <small>{part.source_code || part.raw_label || part.metric_id}: </small>}{format(part.value)}{['warn','blocked'].includes(part.quality) && <span aria-hidden="true"> ⚑</span>}
    {part.annualized && part.value != null && <small>{t('в годовом выражении', 'yillik hisobda', 'annualized')}</small>}
  </button>)}</div>;
}

export function SourcePassport({ item, close, t, format }) {
  const dialog = React.useRef(null);
  React.useEffect(() => { dialog.current?.showModal(); }, []);
  const cell = item.cell;
  const details = [
    [t('Стандарт / периметр', 'Standart / qamrov', 'Standard / scope'), `${cell.standard || item.standard} · ${cell.scope || item.scope}`],
    [t('Период', 'Davr', 'Period'), `${cell.period_start || item.end} — ${cell.period_end || item.end}`],
    [t('Форма / код', 'Shakl / kod', 'Form / code'), `${cell.source_form || item.row.source_form} · ${cell.source_code || item.row.source_code || '—'}`],
    [t('Исходное название', 'Asl nomi', 'Original label'), cell.raw_label || item.row.source_label || item.row.label],
    [t('Исходное значение', 'Asl qiymat', 'Original amount'), cell.raw_value == null ? '—' : String(cell.raw_value)],
    [t('Валюта / масштаб', 'Valyuta / miqyos', 'Currency / source scale'), `${cell.currency || '—'} · ${cell.unit_scale || '—'}`],
    ...(cell.fx ? [[t('Курс / дата', 'Kurs / sana', 'Exchange rate / date'), `${cell.fx.rate ?? '—'} · ${cell.fx.as_of || '—'} · ${cell.fx.effective_date || '—'}`]] : []),
    [t('Страница / лист / строка', 'Sahifa / varaq / qator', 'Page / sheet / row'), [cell.page, cell.sheet, cell.row].filter(v => v != null).join(' · ') || '—'],
    [t('Публикация', 'E’lon qilingan', 'Published'), cell.published_at || '—'],
    [t('Версия источника', 'Manba versiyasi', 'Source version'), cell.source_version || '—'],
  ];
  return <dialog className="fc-passport" ref={dialog} onCancel={close} onClose={close} aria-label={t('Паспорт источника', 'Manba pasporti', 'Source passport')}>
    <header><h3>{t('Паспорт источника', 'Manba pasporti', 'Source passport')}</h3><button type="button" onClick={close}>{t('Закрыть', 'Yopish', 'Close')}</button></header>
    <h4>{item.row.label}</h4><Status value={cell.quality} t={t}/>
    <dl>{details.map(([name, value]) => <React.Fragment key={name}><dt>{name}</dt><dd>{value}</dd></React.Fragment>)}</dl>
    {cell.formula && <p><strong>{t('Формула', 'Formula', 'Formula')}:</strong> {cell.formula}</p>}
    {cell.normalization && <p>{cell.normalization}</p>}
    {cell.reason && <p className="fc-notice">{qualityReason(cell.reason, t)}</p>}
    {cell.components?.length > 0 && <><h4>{t('Входные данные', 'Kirish ma’lumotlari', 'Calculation inputs')}</h4><div className="fc-scroll"><table data-own-export><thead><tr><th>{t('Показатель', 'Ko‘rsatkich', 'Metric')}</th><th>{t('Период', 'Davr', 'Period')}</th><th>{t('Значение', 'Qiymat', 'Amount')}</th></tr></thead><tbody>{cell.components.map((part, i) => <tr key={i}><td>{part.raw_label || part.metric_id || '—'}</td><td>{part.period_start} — {part.period_end}</td><td>{format(part.value)}</td></tr>)}</tbody></table></div></>}
    {cell.raw_line && <pre>{cell.raw_line}</pre>}
    {cell.components?.length > 0 && <ul>{[...new Set(cell.components.flatMap(part => [part.source_url, ...(part.components || []).map(p => p.source_url)]).filter(Boolean))].map(url => <li key={url}><a href={safeHref(url)} target="_blank" rel="noreferrer">{t('Источник расчёта', 'Hisoblash manbasi', 'Calculation source')}</a></li>)}</ul>}
    {cell.source_url && <a href={safeHref(cell.source_url)} target="_blank" rel="noreferrer">{t('Открыть источник', 'Manbani ochish', 'Open source')}</a>}
  </dialog>;
}

function OriginalDocuments({ forms, t }) {
  const [selected, setSelected] = React.useState(0);
  const choices = forms.flatMap(f => (f.documents || []).flatMap(d => d.sheets ? d.sheets.map(sheet => ({ ...sheet, period: f.period_end, url: d.source_url })) : [{ ...d, period: f.period_end, url: f.source_url }]));
  const chosen = choices[selected] || choices[0];
  if (!chosen) return null;
  return <details className="fc-documents"><summary>{t('Полная исходная форма', 'To‘liq asl shakl', 'Complete original form')}</summary>
    <select aria-label={t('Исходный документ', 'Asl hujjat', 'Source document')} value={selected} onChange={e => setSelected(Number(e.target.value))}>{choices.map((choice, i) => <option key={i} value={i}>{choice.period} · {choice.sheet || choice.form} {choice.page || ''}</option>)}</select>
    {chosen.url && <a href={safeHref(chosen.url)} target="_blank" rel="noreferrer">{t('Открыть источник', 'Manbani ochish', 'Open source')}</a>}
    {chosen.text ? <pre>{chosen.text}</pre> : <div className="fc-scroll"><table data-own-export><tbody>{(chosen.source_rows || []).map(row => <tr key={row.row}><th>{row.row}</th>{row.cells.map((v, i) => <td key={i}>{v == null ? '' : String(v)}</td>)}</tr>)}</tbody></table></div>}
  </details>;
}

export function FinancialColumns({ ticker, lang = 'ru', standard = 'NSBU', scope = 'separate', onStandardChange, onScopeChange, fromYear = 2020, onLoad, fallback, showContextControls = true, statement = 'all' }) {
  const t = (...labels) => words(lang, ...labels);
  const [freq, setFreq] = React.useState('annual'), [view, setView] = React.useState('summary'), [representation, setRepresentation] = React.useState('table');
  const [query, setQuery] = React.useState(''), [loaded, setLoaded] = React.useState(null), [retry, setRetry] = React.useState(0), [passport, setPassport] = React.useState(null);
  const [collapsed, setCollapsed] = React.useState({});
  React.useEffect(() => { setPassport(null); }, [statement]);
  const params = new URLSearchParams({ form: standard, scope, freq, view: 'template' });
  const exportParams = new URLSearchParams({ form: standard, scope, freq, view: view === 'summary' ? 'overview' : 'template',
    statement: ['summary', 'original'].includes(view) ? statement : 'all' });
  const url = `/api/company/${encodeURIComponent(ticker)}/financials/columns?${params}`;
  const loadRef = React.useRef(onLoad); loadRef.current = onLoad;
  React.useEffect(() => {
    const controller = new AbortController(), startedAt = performance.now();
    setPassport(null);
    fetch(url, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.ok) throw new Error('Invalid financial response');
      if (!controller.signal.aborted) { setLoaded({ url, data }); loadRef.current?.({ startedAt }); }
    }).catch(error => {
      if (!controller.signal.aborted) { setLoaded({ url, error: error.message }); loadRef.current?.({ startedAt, error: error.message }); }
    });
    return () => controller.abort();
  }, [url, retry]);
  const current = loaded?.url === url ? loaded : null, data = current?.data;
  const format = value => value == null ? '—' : new Intl.NumberFormat(lang === 'en' ? 'en-US' : lang === 'uz' ? 'uz-UZ' : 'ru-RU', { maximumFractionDigits: 2 }).format(Number(value));
  const columns = (data?.columns || []).filter(c => Number(c.end.slice(0,4)) >= fromYear);
  const visibleRows = view === 'ratios' ? data?.ratios : view === 'summary' ? data?.overview_rows ?? data?.rows : data?.rows;
  const rows = (visibleRows || []).filter(r => (['ratios','owners'].includes(view) || statement === 'all' || (r.kind === 'stock') === (statement === 'balance')) && (view !== 'original' || r.source_form !== 'DERIVED') && `${r.label} ${r.display_ref || ''} ${r.source_code || ''} ${r.metric_id || ''}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const groups = [...new Set(rows.map(r => financialGroup(r, view)))];
  if (data?.presentation !== 'template') groups.sort((a,b) => FORM_ORDER.indexOf(a)-FORM_ORDER.indexOf(b));
  const stat = metric => {
    const row = (data?.rows || []).find(r => r.metric_id === metric);
    const column = row && columns.filter(c => row.cells[c.key]?.value != null && ['valid','warn'].includes(row.cells[c.key].quality)).at(-1);
    return { value: format(column ? row.cells[column.key].value : null), period: column?.label || '—' };
  };
  return <section className="financial-columns" data-testid="financial-columns" aria-busy={!current}>
    <div className="fc-toolbar">
      {showContextControls && <><div><span className="fc-label">{t('Стандарт', 'Standart', 'Standard')}</span><div className="fc-segment">{[['NSBU','NSBU'],['MSFO','IFRS']].map(([id,label]) => <button key={id} type="button" data-track-control="finance_standard" data-track-value={id} data-track-ticker={ticker} aria-pressed={standard === id} onClick={() => onStandardChange?.(id)}>{label}</button>)}</div></div>
      <label><span className="fc-label">{t('Периметр', 'Qamrov', 'Scope')}</span><select data-track-control="finance_scope" data-track-ticker={ticker} aria-label={t('Периметр отчётности', 'Hisobot qamrovi', 'Reporting scope')} value={scope} onChange={e => onScopeChange?.(e.target.value)}>{[['separate','Отдельная','Alohida','Separate'],['consolidated','Консолидированная','Konsolidatsiyalangan','Consolidated'],['unknown','Не подтверждён','Tasdiqlanmagan','Unconfirmed']].map(([id,...labels]) => <option key={id} value={id}>{t(...labels)}</option>)}</select></label></>}
      <div><span className="fc-label">{t('Период', 'Davr', 'Period')}</span><div className="fc-segment">{[['annual','Годовые','Yillik','Annual'],['quarter','Кварталы','Choraklar','Quarters'],['interim','6M / 9M','6M / 9M','6M / 9M']].map(([id,...labels]) => <button key={id} type="button" data-track-control="finance_period" data-track-value={id} data-track-ticker={ticker} aria-pressed={freq === id} onClick={() => setFreq(id)}>{t(...labels)}</button>)}</div></div>
      <div><span className="fc-label">{t('Представление', 'Ko‘rinish', 'View')}</span><div className="fc-segment">{[['table','Таблица','Jadval','Table'],['chart','График','Grafik','Chart']].map(([id,...labels]) => <button key={id} type="button" data-track-control="finance_display" data-track-value={id} data-track-ticker={ticker} aria-pressed={representation === id} onClick={() => { if (representation !== id && id === "chart") trackFeature("chart", ticker); setRepresentation(id); }}>{t(...labels)}</button>)}</div></div>
      <div className="fc-exports">{['csv','xlsx'].map(ext => <a key={ext} href={`/api/company/${encodeURIComponent(ticker)}/financials/columns.${ext}?${exportParams}`} download>{ext.toUpperCase()}</a>)}</div>
    </div>
    <div className={`fc-stats${showContextControls ? '' : ' fc-stats-embedded'}`}>{showContextControls && <div><span>{t('Эмитент', 'Emitent', 'Issuer')}</span><strong>{ticker}</strong><small>{data?.issuer_name || ticker} · {standard === 'MSFO' ? 'IFRS' : 'NSBU'}</small></div>}{[['total_assets','Активы','Aktivlar','Assets'],['total_equity','Капитал','Kapital','Equity'],['net_income','Чистая прибыль','Sof foyda','Net profit']].map(([id,...labels]) => <div key={id}><span>{t(...labels)}</span><strong>{stat(id).value}</strong><small>{stat(id).period} · {t('тыс. UZS', 'ming UZS', 'thousands UZS')}</small></div>)}</div>
    <div className="fc-subnav"><div role="tablist" aria-label={t('Финансовые данные', 'Moliyaviy ma’lumotlar', 'Financial data')}>{VIEWS.map(([id,...labels]) => <button key={id} type="button" role="tab" data-track-control="finance_view" data-track-value={id} data-track-ticker={ticker} aria-selected={view === id} onClick={() => { if (view !== id) trackFeature(id === "ratios" ? "ratios" : "financials", ticker); setView(id); }}>{t(...labels)}</button>)}</div><input type="search" aria-label={t('Поиск показателя', 'Ko‘rsatkich qidirish', 'Search metrics')} placeholder={t('Поиск показателя…', 'Ko‘rsatkich qidirish…', 'Search metrics…')} value={query} onChange={e => setQuery(e.target.value)}/><button type="button" onClick={() => {setQuery('');setCollapsed({});}}>{t('Сбросить', 'Tiklash', 'Reset')}</button></div>
    {!current && <p className="fc-empty" role="status">{t('Загрузка отчётности…', 'Hisobot yuklanmoqda…', 'Loading statements…')}</p>}
    {current?.error && <div role="alert" className="fc-empty">{t('Не удалось загрузить отчётность.', 'Hisobotni yuklab bo‘lmadi.', 'Could not load financial statements.')} <button type="button" onClick={() => setRetry(n => n+1)}>{t('Повторить', 'Qayta urinish', 'Retry')}</button></div>}
    {data && <>
      {columns.filter(column => column.notice && statement !== 'balance').map(column => <p key={column.key} className="fc-notice fc-period-notice"><strong>{column.label}:</strong> {qualityReason(column.notice, t)} {column.balance_source === 'comparative' && t('Баланс взят из сравнительной колонки более позднего отчёта.', 'Balans keyingi hisobotning taqqoslash ustunidan olingan.', 'Balance figures come from a comparative column in a later filing.')}</p>)}
      {standard === 'MSFO' && data.coverage?.notes !== 'present' && <p className="fc-notice">{t('Примечания отсутствуют или не проверены.', 'Izohlar yo‘q yoki tekshirilmagan.', 'Notes are missing or have not been verified.')}</p>}
      {!data.rows?.length && <p className="fc-empty">{t('Нет проверенных строк источника в этом периметре.', 'Ushbu qamrovda tekshirilgan manba qatorlari yo‘q.', 'No verified source rows in this accounting scope.')}</p>}
      {view === 'original' && data.presentation !== 'template' && <OriginalDocuments forms={data.source_forms || []} t={t}/>}
      {view === 'owners' ? <div className="fc-empty">{data.shareholders?.length ? data.shareholders.map((owner,i) => <p key={i}>{owner.name} · {format(owner.share)}% · {owner.date} · {owner.scope} · {owner.share_class} {owner.source_url && <a href={safeHref(owner.source_url)} target="_blank" rel="noreferrer">{t('Источник', 'Manba', 'Source')} · {owner.page}</a>}</p>) : t('Проверенные сведения об акционерах не раскрыты или ещё не импортированы.', 'Aksiyadorlar haqida tekshirilgan ma’lumotlar yo‘q.', 'Verified shareholders have not been disclosed or imported.')}</div> : representation === 'chart' ? <FinancialHistoryChart rows={rows} columns={columns} view={view} groupLabel={group => t(...(GROUPS[group] || [group,group,group]))} format={format} lang={lang} t={t}/> : <div className="fc-scroll"><table className="fc-table" data-own-export><thead><tr><th>{t('Показатель', 'Ko‘rsatkich', 'Metric')}</th>{columns.map(column => <th key={column.key}>{column.label}<small>{column.basis === 'as_of' ? t('на дату', 'sana bo‘yicha', 'as of') : column.basis === 'ytd' ? 'YTD' : column.basis === 'quarter' ? t('отдельный квартал', 'alohida chorak', 'standalone quarter') : ''}</small></th>)}</tr></thead><tbody>{groups.map(group => <React.Fragment key={group}><tr className="fc-group"><th colSpan={columns.length+1}><button type="button" aria-expanded={!collapsed[group]} onClick={() => setCollapsed({...collapsed,[group]:!collapsed[group]})}>{collapsed[group] ? '▸' : '▾'} {t(...(GROUPS[group] || [group,group,group]))}</button></th></tr>{!collapsed[group] && rows.filter(r => financialGroup(r, view) === group).map(row => <tr key={row.id} data-metric={row.metric_id || ''}><th scope="row">{row.label}{view === 'ratios' && <RatioInfo metric={row.metric_id} label={row.label} lang={lang} meaning={row[`meaning_${lang}`] || row.meaning_ru} formula={[...new Set(Object.values(row.cells).map(cell => cell.formula).filter(Boolean))].join('\n')}/>}<small>{view === 'summary' && row.display_ref ? row.display_ref : `${row.source_form} ${row.source_code || ''}`}{row.unit === 'UZS_thousand' ? t(' · тыс.', ' · ming', ' · thous.') : row.unit === 'percent' ? ' · %' : row.unit === 'ratio' ? ' · ×' : row.unit === 'UZS_per_share' ? ' · UZS / share' : ''}</small></th>{columns.map(column => {const cell = row.cells[column.key] || {quality:'missing'};return <td key={column.key}><FinancialValue cell={cell} open={part => setPassport({cell:part,row,end:column.end,standard,scope})} format={format} t={t}/></td>;})}</tr>)}</React.Fragment>)}</tbody></table></div>}
      {view === 'ratios' && data.published_ratios?.length > 0 && <section className="fc-published"><h3>OpenInfo · {t('Опубликованные коэффициенты', 'E’lon qilingan koeffitsiyentlar', 'Published ratios')}</h3>{data.published_ratios.map((r,i) => <p key={i}>{r.field}<RatioInfo metric={r.field} label={r.field} lang={lang}/> · {r.period} · {format(r.value)} {r.unit} {r.source_url && <a href={safeHref(r.source_url)} target="_blank" rel="noreferrer">OpenInfo</a>}</p>)}</section>}
      {!data.rows?.length && data.presentation !== 'template' && fallback && <details className="fc-legacy"><summary>{t('Ранее опубликованные показатели', 'Oldin e’lon qilingan ko‘rsatkichlar', 'Previously published indicators')}</summary>{fallback}</details>}
    </>}
    <footer>{t('Нажмите на значение, чтобы открыть источник.', 'Manba uchun qiymatni bosing.', 'Select an amount to inspect its source.')}</footer>
    {passport && <SourcePassport key={`${url}:${passport.row.id}:${passport.end}`} item={passport} close={() => setPassport(null)} t={t} format={format}/>}
  </section>;
}
