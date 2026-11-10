import React from 'react';
import * as Popover from '@radix-ui/react-popover';
import { CompanyLogo } from '../../shared/CompanyLogo.jsx';
import { formatMarketNumber } from '../../shared/format.jsx';
import { marketDisplayPrice } from '../../shared/marketModel.jsx';
import { changePeriodLabel } from '../../shared/marketPeriods.jsx';
import { buildSparkline } from '../../shared/chartModel.jsx';
import { safeNumber } from '../../lib/numberFormat.js';
import { isoDay } from '../../charts/lwCore.js';
import { edHeadline, newsArticlePath } from '../news/index.js';
import { safeHref } from '../../lib/safeHref.js';
import { usePreviewResource } from './companyPreviewData.js';
import { formatMapMetric, mapMetricCoverage } from './HeatmapMetrics.jsx';
import './heatmapPreview.css';

export function useHeatmapHover() {
  const [hover, setHover] = React.useState(null);
  const timer = React.useRef(null), panel = React.useRef(null), cache = React.useRef(new Map());
  const trigger = React.useRef(null), suppressFocus = React.useRef(false);
  const id = React.useId();
  const keep = React.useCallback(() => clearTimeout(timer.current), []);
  const close = React.useCallback((restoreFocus = false) => {
    keep(); setHover(null);
    if (restoreFocus && trigger.current?.isConnected) {
      suppressFocus.current = true;
      trigger.current.focus({preventScroll: true});
      suppressFocus.current = false;
    }
  }, [keep]);
  React.useEffect(() => {
    const entries = cache.current;
    return () => { keep(); entries.forEach(entry => entry.controller.abort()); };
  }, [keep]);
  React.useEffect(() => {
    if (!hover) return undefined;
    const onScroll = event => {
      if (panel.current?.contains(event.target)) return;
      const box = hover.element.getBoundingClientRect();
      if (box.bottom <= 0 || box.top >= window.innerHeight || box.right <= 0 || box.left >= window.innerWidth) close();
    };
    window.addEventListener('scroll', onScroll, true);
    return () => window.removeEventListener('scroll', onScroll, true);
  }, [hover, close]);
  const show = (event, row, immediate = false) => {
    keep();
    if (suppressFocus.current) return;
    const element = event.currentTarget;
    // A pointer anchor keeps the card close even on a very large tile. Keyboard
    // users anchor to the tile itself. Radix handles flipping and screen edges.
    const box = element.getBoundingClientRect();
    const offset = { x: event.clientX - box.left, y: event.clientY - box.top };
    const anchor = immediate ? element : { getBoundingClientRect: () => {
      const current = element.getBoundingClientRect();
      return new DOMRect(current.left + offset.x, current.top + offset.y, 1, 1);
    } };
    const open = () => { trigger.current = element; setHover({ ticker: row.ticker, element, anchor }); };
    if (immediate) open();
    else timer.current = setTimeout(open, 160);
  };
  const leave = () => { keep(); timer.current = setTimeout(() => {
    if (!panel.current?.contains(document.activeElement) && document.activeElement !== trigger.current) setHover(null);
  }, 180); };
  return { hover, show, leave, keep, close, panel, cache: cache.current, id };
}

function HistorySparkline({ ticker, cache, t }) {
  const history = usePreviewResource(`/api/price-history/${encodeURIComponent(ticker)}?months=6`, cache);
  const byDate = new Map();
  for (const point of history.data?.points || []) {
    const date = isoDay(point.date), close = safeNumber(point.close);
    if (/^\d{4}-\d{2}-\d{2}$/.test(date) && Number.isFinite(Date.parse(date)) && close > 0) byDate.set(date, close);
  }
  const values = [...byDate].sort(([a], [b]) => a.localeCompare(b)).map(([, value]) => value);
  const chart = values.length >= 2 ? buildSparkline(values, 100, 42) : null;
  if (!chart) return <span className="heatmap-preview-no-history" title={history.status === 'loading'
    ? t('Загружаем историю', 'Tarix yuklanmoqda', 'Loading history')
    : t('Нет истории', 'Tarix yo‘q', 'No history')}>{history.status === 'loading' ? '…' : '—'}</span>;
  return <svg viewBox="0 0 100 42" role="img" aria-label={`${ticker} · ${t('История за 6 месяцев', '6 oylik tarix', '6-month history')}`}
    className={values.at(-1) > values[0] ? 'tone-good' : values.at(-1) < values[0] ? 'tone-danger' : 'tone-neutral'}>
    <path d={chart.path} fill="none" stroke="currentColor" strokeWidth="1.5" />
  </svg>;
}

function LatestNews({ ticker, cache, lang }) {
  const news = usePreviewResource(`/api/news/ticker/${encodeURIComponent(ticker)}?limit=1&days=90`, cache);
  const story = news.data?.items?.[0];
  if (!story) return null;
  return <div className="heatmap-preview-news"><small>{story.source} · {isoDay(story.published_at)}</small>
    <a href={safeHref(newsArticlePath(story, lang))}>{edHeadline(story, lang).text}</a></div>;
}

export function HeatmapPreview({ interaction, row, peers, industry, name, security, lang, period, type,
  statusOf, formatPct, metrics, values, onOpen }) {
  const { hover, close, keep, leave, panel, cache, id } = interaction;
  const t = (ru, uz, en) => lang === 'en' ? en : lang === 'uz' ? uz : ru;
  const price = marketDisplayPrice(row);
  const quoteDate = isoDay(row.last_trade_date || row.close_date || security?.last_trade_date);
  const change = item => statusOf(item) === 'ok' ? formatPct(item.changePercent) : '—';
  const tone = item => statusOf(item) !== 'ok' ? 'neutral' : item.changePercent > 0 ? 'good' : item.changePercent < 0 ? 'danger' : 'neutral';
  // Keep requests bounded for large industries; always include the hovered issue.
  const shown = [row, ...peers.filter(peer => peer.ticker !== row.ticker)].slice(0, 12);
  return <Popover.Root open onOpenChange={open => { if (!open) close(panel.current?.contains(document.activeElement)); }}>
    <Popover.Anchor virtualRef={{ current: hover.anchor }} />
    <Popover.Portal>
      <Popover.Content ref={panel} id={id} className="heatmap-preview" side={window.innerWidth < 768 ? 'bottom' : 'right'} align="start" sideOffset={12}
        collisionPadding={8} sticky="always" aria-label={`${t('Обзор компании', 'Kompaniya haqida', 'Company preview')} ${row.ticker}`}
        onOpenAutoFocus={event => event.preventDefault()} onCloseAutoFocus={event => event.preventDefault()}
        onEscapeKeyDown={event => { event.preventDefault(); close(true); }}
        onPointerEnter={keep} onPointerLeave={leave} onFocus={keep}
        onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== hover.element) leave(); }}>
        <header className="heatmap-preview-industry"><span>{industry}</span>
          <Popover.Close aria-label={t('Закрыть обзор', 'Yopish', 'Close preview')}>×</Popover.Close>
        </header>
        <div className="heatmap-preview-identity">
          <CompanyLogo logo={security?.logo_url || row.logo_url} ticker={row.ticker} name={name} />
          <div><strong>{row.ticker}</strong><time>{quoteDate || '—'}</time></div>
          <div className="heatmap-preview-quote"><strong className="heatmap-preview-price">{price != null ? formatMarketNumber(price, lang) : '—'} <small>UZS</small></strong>
            <span className={`heatmap-preview-change tone-${tone(row)}`}>{change(row)} <small>· {changePeriodLabel(period, lang, 'short')}</small></span>
          </div>
        </div>
        <p className="heatmap-preview-name">{name}</p>
        {type !== 'bond' && <LatestNews key={row.ticker} ticker={row.ticker} cache={cache} lang={lang} />}
        <div className="heatmap-preview-columns"><span>{t('Бумага', 'Qog‘oz', 'Security')}</span>
          <span>{t('6 мес.', '6 oy', '6 mo')}</span><span>{t('Цена', 'Narx', 'Price')} · UZS</span>
          <span>{changePeriodLabel(period, lang, 'short')}</span></div>
        <div className="heatmap-preview-peers">
          {shown.map(peer => { const peerPrice = marketDisplayPrice(peer); return <button type="button" key={peer.ticker}
            data-peer={peer.ticker} className={peer.ticker === row.ticker ? 'is-current' : ''} onClick={() => onOpen(peer.ticker)}>
            <strong>{peer.ticker}</strong>
            {type === 'bond' ? <span>—</span> : <HistorySparkline ticker={peer.ticker} cache={cache} t={t} />}
            <span>{peerPrice != null ? formatMarketNumber(peerPrice, lang) : '—'}</span><b className={`tone-${tone(peer)}`}>{change(peer)}</b>
          </button>; })}
        </div>
        {peers.length > shown.length && <p className="heatmap-preview-count">{t('Показано', 'Ko‘rsatilgan', 'Showing')} {shown.length} / {peers.length}</p>}
        {metrics.length > 0 && <dl className="heatmap-preview-metrics">{metrics.map(({key, label}) => <div key={key}>
          <dt>{label}</dt><dd>{formatMapMetric(key, values[key], lang)}</dd>
          {period !== '1d' && mapMetricCoverage(row, key, lang) && <small>{mapMetricCoverage(row, key, lang)}</small>}
        </div>)}</dl>}
        <footer><button type="button" onClick={() => onOpen(row.ticker)}>{type === 'bond'
          ? t('Открыть выпуск', 'Chiqarilishni ochish', 'Open bond')
          : t('Открыть компанию', 'Kompaniyani ochish', 'Open company')} ↗</button><span>Esc</span></footer>
      </Popover.Content>
    </Popover.Portal>
  </Popover.Root>;
}
