import React from 'react';
import {safeHref} from '../../lib/safeHref.js';
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

export function CompanyShareholders({ticker, lang = 'ru', apiFetch = fetch}) {
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
  const percentage = value => `${new Intl.NumberFormat(locale, {maximumFractionDigits: 2}).format(Number(value))}%`;
  return <section className="company-shareholders" data-testid="company-shareholders" aria-label={t('Акционеры и руководство', 'Aksiyadorlar va rahbariyat', 'Shareholders and management')} aria-busy={!current}>
    {!current && <p className="shareholder-message" role="status">{t('Загрузка сведений об акционерах и руководстве…', 'Aksiyadorlar va rahbariyat ma’lumotlari yuklanmoqda…', 'Loading shareholders and management…')}</p>}
    {current?.error && <div className="shareholder-message" role="alert">
      <p>{t('Не удалось загрузить сведения об акционерах и руководстве.', 'Aksiyadorlar va rahbariyat ma’lumotlarini yuklab bo‘lmadi.', 'Could not load shareholders and management.')}</p>
      <button type="button" onClick={() => setRetry(value => value + 1)}>{t('Повторить', 'Qayta urinish', 'Retry')}</button>
    </div>}
    {ownership && management && <div className="shareholder-grid">
      <section className="shareholder-card" aria-label={t('Акционеры', 'Aksiyadorlar', 'Shareholders')}>
        <header><h2>{t('Акционеры', 'Aksiyadorlar', 'Shareholders')}</h2>
          {ownership.items.length > 0 && <span>{ownership.share_class === 'preferred' ? t('Привилегированные акции', 'Imtiyozli aksiyalar', 'Preferred shares') : ownership.share_class === 'ordinary' ? t('Обыкновенные акции', 'Oddiy aksiyalar', 'Ordinary shares') : t('Доля в капитале', 'Kapitaldagi ulush', 'Ownership interest')}</span>}
        </header>
        {ownership.items.length ? <table className="shareholder-table" aria-label={t('Доли акционеров', 'Aksiyadorlar ulushlari', 'Ownership percentages')}><tbody>
          {ownership.items.map((owner, index) => <tr key={`${owner.name}:${index}`}>
            <th scope="row"><a href={sourceHref(owner.source_url || ownership.source?.url, owner.page || ownership.source?.page)} target="_blank" rel="noreferrer" title={owner.name}>
              {owner.kind === 'aggregate' ? t('Прочие (менее 1% каждый)', 'Boshqalar (har biri 1% dan kam)', 'Others (less than 1% each)') : owner.name}
            </a></th><td>{percentage(owner.share)}</td>
          </tr>)}
        </tbody></table> : <p className="shareholder-empty">{t('Нет проверенных данных о долях акционеров в загруженных раскрытиях.', 'Yuklangan hujjatlarda aksiyadorlar ulushlari haqida tasdiqlangan ma’lumot yo‘q.', 'No verified ownership percentages in the collected disclosures.')}</p>}
        {ownership.status === 'partial' && <p className="shareholder-note">{t('Раскрыта часть акционеров. Доли не пересчитываются до 100%.', 'Aksiyadorlarning bir qismi oshkor etilgan. Ulushlar 100% ga qayta hisoblanmaydi.', 'Only some shareholders are disclosed. Percentages are not rescaled to 100%.')}</p>}
        <SourceNote data={ownership} t={t} locale={locale}/>
      </section>
      <section className="shareholder-card" aria-label={t('Руководство', 'Rahbariyat', 'Management')}>
        <header><h2>{t('Руководство', 'Rahbariyat', 'Management')}</h2></header>
        {management.items.length ? <ul className="shareholder-management">
          {management.items.map((person, index) => <li key={`${person.name}:${index}`}>
            {person.position && <span>{person.position}</span>}
            <a href={sourceHref(person.source_url || management.source?.url)} target="_blank" rel="noreferrer">{person.name}</a>
          </li>)}
        </ul> : <p className="shareholder-empty">{t('Нет проверенных данных о руководстве в загруженных раскрытиях.', 'Yuklangan hujjatlarda rahbariyat haqida tasdiqlangan ma’lumot yo‘q.', 'No verified management information in the collected disclosures.')}</p>}
        {management.status === 'partial' && <p className="shareholder-note">{t('Состав может быть неполным: опубликованы отдельные изменения.', 'Tarkib to‘liq bo‘lmasligi mumkin: alohida o‘zgarishlar e’lon qilingan.', 'The roster may be incomplete: only individual changes were disclosed.')}</p>}
        <SourceNote data={management} t={t} locale={locale}/>
      </section>
    </div>}
  </section>;
}
