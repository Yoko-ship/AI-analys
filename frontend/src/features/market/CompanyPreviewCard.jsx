import React from 'react';
import { CompanyLogo } from '../../shared/CompanyLogo.jsx';
import { marketDisplayPrice } from '../../shared/marketModel.jsx';
import { sectorLabel } from '../../shared/marketCopy.jsx';
import {industryOf} from '../../lib/companyIndustries.js';
import { changePeriodLabel } from '../../shared/marketPeriods.jsx';
import { formatChangePercent, formatCompactNumber } from '../../lib/numberFormat.js';
import { isoDay, priceFormatFor } from '../../charts/lwCore.js';
import { safeHref } from '../../lib/safeHref.js';
import { localizedPath } from '../../lib/languagePath.js';
import { edHeadline, newsArticlePath } from '../news/index.js';
import { usePreviewResource } from './companyPreviewData.js';
import { CompanyPreviewChart } from './CompanyPreviewChart.jsx';

export function CompanyPreviewCard({ item, lang, changePeriod, cache, onClose, onOpenCompany }) {
  const { row, security } = item, ticker = row.ticker;
  const t = (ru, uz, en) => lang === 'en' ? en : lang === 'uz' ? uz : ru;
  const history = usePreviewResource(`/api/price-history/${encodeURIComponent(ticker)}?months=6`, cache);
  const news = usePreviewResource(`/api/news/ticker/${encodeURIComponent(ticker)}?limit=1&days=90`, cache);
  const name = row.name || security.name || ticker;
  const price = marketDisplayPrice(row);
  const quoteDay = isoDay(row.last_trade_date || row.close_date || security.last_trade_date);
  const preferred = security.is_preferred || row.share_type === 'preferred';
  const story = news.data?.items?.[0];
  const sector = industryOf(ticker)?.sector || security.sector || row.sector;
  return <>
    <header className="company-preview-header">
      <CompanyLogo logo={security.logo_url} name="" ticker={ticker} />
      <div className="company-preview-symbol"><strong>{ticker}</strong><time>{quoteDay || '—'}</time></div>
      <div className="company-preview-quote"><strong>{price > 0 ? priceFormatFor(price, lang).formatter(price) : '—'} <small>UZS</small></strong>
        <span className={row.changePercent > 0 ? 'company-preview-up' : row.changePercent < 0 ? 'company-preview-down' : ''}>
          {formatChangePercent(row.changePercent, lang)} <small>· {changePeriodLabel(changePeriod || '1d', lang, 'short')}</small>
        </span>
      </div>
      <button type="button" className="company-preview-close" aria-label={t('Закрыть обзор', 'Yopish', 'Close preview')} onClick={onClose}>×</button>
    </header>
    <div className="company-preview-chart-label"><span>{t('Дневной график', 'Kunlik grafik', 'Daily chart')}</span><span>{t('6 месяцев', '6 oy', '6 months')} · UZS</span></div>
    {history.status === 'loading' ? <div className="company-preview-empty" role="status">{t('Загружаем график…', 'Grafik yuklanmoqda…', 'Loading chart…')}</div>
      : history.status === 'error' ? <div className="company-preview-empty" role="status">{t('Не удалось загрузить график', 'Grafik yuklanmadi', 'Could not load the chart')}</div>
      : <CompanyPreviewChart points={history.data?.points} ticker={ticker} lang={lang} t={t} />}
    {history.data?.adjustments?.length > 0 && <p className="company-preview-adjusted">{t('История скорректирована на корпоративные действия', 'Tarix korporativ harakatlarga moslashtirilgan', 'History adjusted for corporate actions')}</p>}
    <div className="company-preview-details">
      <strong className="company-preview-name">{name}</strong>
      <div className="company-preview-meta">{sector && <span>{sectorLabel(lang, sector)}</span>}
        <span>{preferred ? t('Привилегированные', 'Imtiyozli', 'Preferred shares') : t('Обыкновенные', 'Oddiy', 'Common shares')}</span>
      </div>
      {row.marketCap > 0 && <div className="company-preview-cap">{t('Капитализация выпуска', 'Emissiya kapitallashuvi', 'Share class market cap')} <span>{formatCompactNumber(row.marketCap, lang)} UZS</span></div>}
    </div>
    <div className="company-preview-news">
      {story ? <><div className="company-preview-news-source">{story.source} · {isoDay(story.published_at)}</div>
        <a href={safeHref(newsArticlePath(story, lang))}>{edHeadline(story, lang).text}</a></>
        : <span>{news.status === 'loading' ? t('Загружаем новости…', 'Yangiliklar yuklanmoqda…', 'Loading news…')
          : news.status === 'error' ? t('Новости временно недоступны', 'Yangiliklar vaqtincha mavjud emas', 'News is temporarily unavailable')
          : t('Нет новостей за последние 90 дней', 'Oxirgi 90 kunda yangilik yo‘q', 'No news in the last 90 days')}</span>}
    </div>
    <footer className="company-preview-footer"><a data-preview-primary href={localizedPath(`/company/${encodeURIComponent(ticker)}`, lang)}
      onClick={event => {
        if (onOpenCompany && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button === 0) {
          event.preventDefault(); onClose(); onOpenCompany(ticker);
        }
      }}>{t('Открыть компанию', 'Kompaniyani ochish', 'Open company')} <span aria-hidden="true">↗</span></a>
      <span>{t('Esc — закрыть', 'Esc — yopish', 'Esc to close')}</span>
    </footer>
  </>;
}
