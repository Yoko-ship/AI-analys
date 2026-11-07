import {useMemo, useState} from 'react';
import {prepareMarketRows} from '../../lib/marketData.js';
import {marketDisplayPrice} from '../../shared/marketModel.jsx';
import {price, pct, compact} from '../../lib/format.js';
import {sectorLabel} from '../../shared/marketCopy.jsx';
import {buildIssuerTree, industryLabel, industrySource} from '../../lib/companyIndustries.js';
import {safeHref} from '../../lib/safeHref.js';
import './issuerDirectory.css';

function Classification({issuer, language, t}) {
  const statuses = {
    verified: t('Код проверен', 'Code checked', 'Kod tekshirilgan'),
    documented: t('ОКЭД указан в PDF', 'Code provided in PDF', 'Kod PDFda ko‘rsatilgan'),
    inferred: t('Требует проверки', 'Needs verification', 'Tekshirish kerak'),
    conflict: t('Расхождение источников', 'Sources disagree', 'Manbalar farq qiladi'),
    unclassified: t('Не классифицировано', 'Unclassified', 'Tasniflanmagan'),
  };
  return <details className="industry-evidence">
    <summary className={`industry-status industry-status-${issuer.status}`}>
      {statuses[issuer.status]}{issuer.oked ? ` · ${issuer.oked}` : ''}
    </summary>
    <div>
      {issuer.page && <p>{industrySource} · {t('стр.', 'p.', 'bet')} {issuer.page}</p>}
      <p>{industryLabel(issuer.note, language) || (issuer.status === 'documented'
        ? t('Код перенесён из документа; регистрационные данные отдельно не проверены.', 'Code transcribed from the document; registration data has not been independently checked.', 'Kod hujjatdan olingan; ro‘yxatga olish ma’lumotlari alohida tekshirilmagan.')
        : issuer.status === 'unclassified'
          ? t('Компания отсутствует в отраслевом справочнике. Требуется классификация.', 'This issuer is not in the industry registry and needs classification.', 'Emitent tarmoq ma’lumotnomasida yo‘q; tasniflash kerak.')
          : t('Группа определена по профилю деятельности в PDF. Код ОКЭД не подтверждён.', 'Grouped by the business profile in the PDF. The OKED code is unconfirmed.', 'Guruh PDFdagi faoliyatga asoslangan. IFUT kodi tasdiqlanmagan.'))}</p>
      {issuer.evidence?.map(source => <a key={source.url} href={safeHref(source.url)} target="_blank" rel="noopener noreferrer">{source.title}</a>)}
    </div>
  </details>;
}

export function IssuerDirectory({language, companies = [], securitiesMap = {}, marketRows = [], tradeStats, onOpenCompany}) {
  const [query, setQuery] = useState('');
  const [sector, setSector] = useState('');
  const [group, setGroup] = useState('');
  const t = (ru, en, uz) => language === 'en' ? en : language === 'uz' ? uz : ru;
  const quotes = useMemo(() => Object.fromEntries(prepareMarketRows(marketRows, tradeStats).map(r => [r.ticker, r])), [marketRows, tradeStats]);
  const all = useMemo(() => buildIssuerTree({companies, securitiesMap}), [companies, securitiesMap]);
  const tree = useMemo(() => buildIssuerTree({companies, securitiesMap, query, sector, group}), [companies, securitiesMap, query, sector, group]);
  const count = tree.reduce((total, section) => total + section.groups.reduce((n, g) => n + g.issuers.length, 0), 0);
  const subgroupLabel = g => industryLabel(g.label, language) || t('Без подотрасли', 'Unclassified subgroup', 'Quyi tarmoq belgilanmagan');
  const subgroupOptions = new Map(all.filter(s => !sector || s.sector === sector).flatMap(s => s.groups.map(g => [g.id, g])));
  const columnNames = [t('Бумага', 'Security', 'Qimmatli qog‘oz'), 'ISIN', t('Цена, сум', 'Price, UZS', 'Narx, so‘m'), t('Изменение', 'Change', 'O‘zgarish'), t('Объём', 'Turnover', 'Hajm')];
  return <div className="issuer-directory">
    <header className="concept-page-heading"><div>
      <span className="hd-eyebrow">{t('РЫНОК · ЭМИТЕНТЫ', 'MARKET · ISSUERS', 'BOZOR · EMITENTLAR')}</span>
      <h1>{t('Каталог компаний', 'Company directory', 'Kompaniyalar katalogi')}</h1>
      <p>{t('Отрасль → подотрасль → компания → классы акций', 'Sector → subgroup → company → share classes', 'Tarmoq → quyi tarmoq → kompaniya → aksiya turlari')}</p>
    </div></header>
    <section className="concept-card industry-controls" aria-label={t('Поиск и фильтры', 'Search and filters', 'Qidirish va filtrlar')}>
      <div className="hd-toolbar">
        <input type="search" aria-label={t('Поиск эмитентов', 'Search issuers', 'Emitentlarni qidirish')} placeholder={t('Компания, тикер или ISIN', 'Company, ticker or ISIN', 'Kompaniya, tiker yoki ISIN')} value={query} onChange={e => setQuery(e.target.value)}/>
        <select aria-label={t('Отрасль', 'Sector', 'Tarmoq')} value={sector} onChange={e => {setSector(e.target.value); setGroup('');}}>
          <option value="">{t('Все отрасли', 'All sectors', 'Barcha tarmoqlar')}</option>
          {all.map(s => <option key={s.sector} value={s.sector}>{s.code ? `${s.code} · ` : ''}{industryLabel(s.label, language) || sectorLabel(language, s.sector)}</option>)}
        </select>
        <select aria-label={t('Подотрасль', 'Subgroup', 'Quyi tarmoq')} value={group} onChange={e => setGroup(e.target.value)}>
          <option value="">{t('Все подотрасли', 'All subgroups', 'Barcha quyi tarmoqlar')}</option>
          {[...subgroupOptions.values()].map(g => <option key={g.id} value={g.id}>{subgroupLabel(g)}</option>)}
        </select>
      </div>
      <p className="industry-help">{t('По дереву ОКЭД UZStock. Подотрасли — группы для навигации; неподтверждённые назначения отмечены.', 'Based on the UZStock OKED tree. Subgroups are navigation categories; unconfirmed assignments are marked.', 'UZStock IFUT daraxti asosida. Quyi tarmoqlar — navigatsiya guruhlari; tasdiqlanmagan tasniflar belgilangan.')}</p>
      <p className="industry-count" role="status">{t('Компаний', 'Companies', 'Kompaniyalar')}: {count}</p>
    </section>
    {tree.map(section => <section className="industry-section" data-sector={section.sector} key={section.sector} aria-labelledby={`industry-${section.sector}`}>
      <h2 id={`industry-${section.sector}`}>{section.code && <span>{section.code}</span>}{industryLabel(section.label, language) || sectorLabel(language, section.sector)}<small>{section.groups.reduce((n, g) => n + g.issuers.length, 0)}</small></h2>
      {section.groups.map(subgroup => <details key={`${subgroup.id}-${query}`} className="industry-group concept-card" data-group={subgroup.id} open>
        <summary><h3>{subgroupLabel(subgroup)}</h3><span>{subgroup.issuers.length}</span></summary>
        <div className="concept-table-scroll" role="region" aria-label={subgroupLabel(subgroup)} tabIndex={0}>
          <table className="concept-table industry-table">
            <thead><tr>{columnNames.map(h => <th key={h} scope="col">{h}</th>)}</tr></thead>
            {subgroup.issuers.map(issuer => <tbody key={issuer.id} data-issuer={issuer.id}>
              <tr className="industry-issuer"><th colSpan={5} scope="rowgroup"><div className="industry-issuer-heading"><strong>{issuer.name}</strong><Classification issuer={issuer} language={language} t={t}/></div></th></tr>
              {issuer.securities.map(s => {
                const quote = quotes[s.ticker];
                const preferred = s.is_preferred === true || s.share_type === 'preferred';
                return <tr key={s.ticker} data-ticker={s.ticker}>
                  <th scope="row"><button className="industry-security" onClick={() => onOpenCompany(s.ticker)}>{s.ticker}</button><small>{preferred ? t('Привилегированная', 'Preferred', 'Imtiyozli') : t('Обыкновенная', 'Ordinary', 'Oddiy')}</small></th>
                  <td>{s.isin || '—'}</td>
                  <td>{price(quote ? marketDisplayPrice(quote) : null, language)}</td>
                  <td>{Number.isFinite(quote?.changePercent) ? pct(quote.changePercent, language, 2) : '—'}</td>
                  <td>{compact(quote?.stockVolume, language)}</td>
                </tr>;
              })}
            </tbody>)}
          </table>
        </div>
      </details>)}
    </section>)}
    {!count && <p className="industry-empty">{t('Совпадений нет.', 'No matching issuers.', 'Mos emitentlar yo‘q.')}</p>}
  </div>;
}
