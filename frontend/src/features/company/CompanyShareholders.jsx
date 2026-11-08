import React from 'react';
import {safeHref} from '../../lib/safeHref.js';
import {Icons} from '../../shared/Icons.jsx';
import {localizedPath} from '../../lib/languagePath.js';
import './companyShareholders.css';

function sourceHref(source, page) {
  const href = safeHref(source);
  return href && page ? `${href.split('#')[0]}#page=${page}` : href;
}

function SourceNote({data, t, locale}) {
  const date = data.as_of && new Date(`${data.as_of}T00:00:00Z`);
  const sourceName = /^https?:\/\/(?:[\w-]+\.)*openinfo\.uz(?:[/:]|$)/i.test(data.source?.url || '')
    ? 'Openinfo' : t('Источник', 'Manba', 'Source');
  return <footer className="shareholder-source">
    {date && <span>{t('По раскрытию на', 'Oshkor etilgan sana', 'Disclosed as of')} <time dateTime={data.as_of}>{new Intl.DateTimeFormat(locale, {day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'UTC'}).format(date)}</time></span>}
    {data.source?.url && <a href={sourceHref(data.source.url, data.source.page)} target="_blank" rel="noreferrer">
      {sourceName}{data.source.page ? ` · ${t('стр.', 'sah.', 'p.')} ${data.source.page}` : ''} ↗
    </a>}
  </footer>;
}

function EmptyDisclosure({children, ticker, onOpenReports, t, lang}) {
  return <div className="shareholder-empty">
    <span className="shareholder-empty-icon" aria-hidden="true">{Icons.users}</span>
    <h3>{t('Сведения пока недоступны', 'Ma’lumotlar hozircha mavjud emas', 'No verified details yet')}</h3>
    <p>{children}</p>
    {onOpenReports
      ? <button type="button" className="shareholder-reports-link" onClick={onOpenReports}>{t('Смотреть отчёты', 'Hisobotlarni ko‘rish', 'View reports')} <span aria-hidden="true">→</span></button>
      : <a className="shareholder-reports-link" href={localizedPath(`/company/${encodeURIComponent(ticker)}?tab=reports`, lang)}>{t('Смотреть отчёты', 'Hisobotlarni ko‘rish', 'View reports')} <span aria-hidden="true">→</span></a>}
  </div>;
}

function collectionMessage(collection, t) {
  const reason = collection?.reason;
  if (reason === 'MISSING_ISSUER_ID') return t('Компания пока не сопоставлена с эмитентом в Openinfo.', 'Kompaniya Openinfo emitenti bilan hali bog‘lanmagan.', 'This company has not yet been matched to an Openinfo issuer.');
  if (reason === 'NOT_COLLECTED') return t('Раскрытия о руководстве ещё не проверены.', 'Rahbariyat haqidagi ma’lumotlar hali tekshirilmagan.', 'Management disclosures have not been checked yet.');
  if (reason === 'NO_FORM8_DISCLOSURES') return t('В Openinfo не найдены раскрытия об изменениях в органах управления.', 'Openinfo’da boshqaruv organlaridagi o‘zgarishlar haqida ma’lumot topilmadi.', 'No disclosures of changes in governing bodies were found on Openinfo.');
  if (reason === 'NO_EXECUTIVE_ROSTER') return t('В проверенных раскрытиях не найден полный состав исполнительного органа.', 'Tekshirilgan hujjatlarda ijroiya organining to‘liq tarkibi topilmadi.', 'The checked disclosures do not contain a complete executive roster.');
  if (collection?.state === 'partial') return t('Проверена часть архива. Поиск более ранних раскрытий продолжится.', 'Arxivning bir qismi tekshirildi. Oldingi hujjatlarni qidirish davom etadi.', 'Part of the archive has been checked. Earlier disclosures will be checked next.');
  if (reason === 'TIMEOUT') return t('Openinfo не ответил вовремя. Обновление будет повторено.', 'Openinfo o‘z vaqtida javob bermadi. Yangilash takrorlanadi.', 'Openinfo did not respond in time. The update will be retried.');
  if (reason === 'SOURCE_PAUSED' || reason === 'CONNECTION_ERROR' || /^HTTP_(429|5\d\d)$/.test(reason || '')) return t('Openinfo временно недоступен. Обновление будет повторено.', 'Openinfo vaqtincha mavjud emas. Yangilash takrorlanadi.', 'Openinfo is temporarily unavailable. The update will be retried.');
  if (collection?.state === 'failed') return t('Не удалось подтвердить полученное раскрытие. Обновление будет повторено.', 'Olingan hujjatni tasdiqlab bo‘lmadi. Yangilash takrorlanadi.', 'The retrieved disclosure could not be verified. The update will be retried.');
  return null;
}

export function CompanyShareholders({ticker, lang = 'ru', apiFetch = fetch, onOpenReports}) {
  const t = (ru, uz, en) => lang === 'en' ? en : lang === 'uz' ? uz : ru;
  const locale = lang === 'en' ? 'en-GB' : lang === 'uz' ? 'uz-UZ' : 'ru-RU';
  const [loaded, setLoaded] = React.useState(null);
  const [retry, setRetry] = React.useState(0);
  React.useEffect(() => {
    const controller = new AbortController();
    let alive = true;
    apiFetch(`/api/company/${encodeURIComponent(ticker)}/shareholders`, {signal: controller.signal})
      .then(async response => {
        if (!response.ok) throw new Error('Disclosure request failed');
        const data = await response.json();
        if (!data?.ok || !Array.isArray(data.ownership?.items) || !Array.isArray(data.management?.items)) throw new Error('Invalid disclosure response');
        if (alive) setLoaded({ticker, retry, data});
      })
      .catch(() => {if (alive) setLoaded({ticker, retry, error: true});});
    return () => {alive = false; controller.abort();};
  }, [ticker, retry, apiFetch]);
  const current = loaded?.ticker === ticker && loaded.retry === retry ? loaded : null;
  const ownership = current?.data?.ownership, management = current?.data?.management;
  const collectionNote = collectionMessage(management?.collection, t);
  const bodyLabel = {
    executive: t('Исполнительный орган', 'Ijroiya organi', 'Executive management'),
    supervisory: t('Наблюдательный совет', 'Kuzatuv kengashi', 'Supervisory board'),
    audit: t('Ревизионная комиссия', 'Taftish komissiyasi', 'Audit commission'),
    unspecified: t('Орган управления не уточнён', 'Boshqaruv organi aniqlashtirilmagan', 'Governing body not specified'),
  }[management?.body] || t('По раскрытиям компании', 'Kompaniya ma’lumotlari bo‘yicha', 'Company disclosures');
  const percentage = value => `${new Intl.NumberFormat(locale, {maximumFractionDigits: 2}).format(Number(value))}%`;
  return <section className="company-shareholders" data-testid="company-shareholders" aria-label={t('Акционеры и руководство', 'Aksiyadorlar va rahbariyat', 'Shareholders and management')} aria-busy={!current}>
    {!current && <p className="shareholder-message" role="status">{t('Загрузка сведений об акционерах и руководстве…', 'Aksiyadorlar va rahbariyat ma’lumotlari yuklanmoqda…', 'Loading shareholders and management…')}</p>}
    {current?.error && <div className="shareholder-message" role="alert">
      <p>{t('Не удалось загрузить сведения об акционерах и руководстве.', 'Aksiyadorlar va rahbariyat ma’lumotlarini yuklab bo‘lmadi.', 'Could not load shareholders and management.')}</p>
      <button type="button" onClick={() => setRetry(value => value + 1)}>{t('Повторить', 'Qayta urinish', 'Retry')}</button>
    </div>}
    {ownership && management && <div className={`shareholder-grid${!ownership.items.length && management.items.length ? ' shareholder-grid--management' : ''}`}>
      <section className="shareholder-card" aria-label={t('Акционеры', 'Aksiyadorlar', 'Shareholders')}>
        <header><h2>{t('Акционеры', 'Aksiyadorlar', 'Shareholders')}</h2>
          {ownership.items.length > 0 && <span>{ownership.share_class === 'preferred' ? t('Привилегированные акции', 'Imtiyozli aksiyalar', 'Preferred shares') : ownership.share_class === 'ordinary' ? t('Обыкновенные акции', 'Oddiy aksiyalar', 'Ordinary shares') : t('Доля в капитале', 'Kapitaldagi ulush', 'Ownership interest')}</span>}
        </header>
        {ownership.items.length ? <div className="shareholder-table-wrap"><table className="shareholder-table" aria-label={t('Доли акционеров', 'Aksiyadorlar ulushlari', 'Ownership percentages')}>
          <thead><tr><th scope="col">{t('Акционер', 'Aksiyador', 'Shareholder')}</th><th scope="col">{t('Доля', 'Ulush', 'Holding')}</th></tr></thead><tbody>
          {ownership.items.map((owner, index) => <tr key={`${owner.name}:${index}`}>
            <th scope="row"><a href={sourceHref(owner.source_url || ownership.source?.url, owner.page || ownership.source?.page)} target="_blank" rel="noreferrer" title={owner.name}>
              {owner.kind === 'aggregate' ? t('Прочие (менее 1% каждый)', 'Boshqalar (har biri 1% dan kam)', 'Others (less than 1% each)') : owner.name}
            </a></th><td><strong>{percentage(owner.share)}</strong><span className="shareholder-share-track" aria-hidden="true"><span style={{width: `${Number(owner.share)}%`}}/></span></td>
          </tr>)}
        </tbody></table></div> : <EmptyDisclosure ticker={ticker} onOpenReports={onOpenReports} t={t} lang={lang}>{t('Нет проверенных данных о долях акционеров в загруженных раскрытиях.', 'Yuklangan hujjatlarda aksiyadorlar ulushlari haqida tasdiqlangan ma’lumot yo‘q.', 'No verified ownership percentages in the collected disclosures.')}</EmptyDisclosure>}
        {ownership.status === 'partial' && <p className="shareholder-note">{t('Раскрыта часть акционеров. Доли не пересчитываются до 100%.', 'Aksiyadorlarning bir qismi oshkor etilgan. Ulushlar 100% ga qayta hisoblanmaydi.', 'Only some shareholders are disclosed. Percentages are not rescaled to 100%.')}</p>}
        <SourceNote data={ownership} t={t} locale={locale}/>
      </section>
      <section className="shareholder-card" aria-label={t('Руководство', 'Rahbariyat', 'Management')}>
        <header><h2>{t('Руководство', 'Rahbariyat', 'Management')}</h2><span>{bodyLabel}</span></header>
        {management.items.length ? <ul className="shareholder-management">
          {management.items.map((person, index) => <li key={`${person.name}:${index}`}>
            {person.position && <span>{person.position}</span>}
            <a href={sourceHref(person.source_url || management.source?.url)} target="_blank" rel="noreferrer">{person.name}</a>
            {management.body !== 'executive' && person.work_place && <span className="shareholder-employer">{person.work_place}</span>}
          </li>)}
        </ul> : <EmptyDisclosure ticker={ticker} onOpenReports={onOpenReports} t={t} lang={lang}>{collectionNote || t('Нет проверенных данных о руководстве в загруженных раскрытиях.', 'Yuklangan hujjatlarda rahbariyat haqida tasdiqlangan ma’lumot yo‘q.', 'No verified management information in the collected disclosures.')}</EmptyDisclosure>}
        {management.items.length > 0 && collectionNote && <p className="shareholder-note">{collectionNote}{management.collection?.state === 'failed' && ` ${t('Показаны ранее полученные сведения.', 'Oldin olingan ma’lumotlar ko‘rsatilgan.', 'Previously collected details are shown.')}`}</p>}
        {management.status === 'partial' && <p className="shareholder-note">{t('Состав может быть неполным: опубликованы отдельные изменения.', 'Tarkib to‘liq bo‘lmasligi mumkin: alohida o‘zgarishlar e’lon qilingan.', 'The roster may be incomplete: only individual changes were disclosed.')}</p>}
        <SourceNote data={management} t={t} locale={locale}/>
      </section>
    </div>}
  </section>;
}
