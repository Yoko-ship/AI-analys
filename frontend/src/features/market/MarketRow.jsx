import React from 'react';
import {mt} from '../../shared/marketCopy.jsx';
import {CompanyPreviewLogo} from './CompanyPreview.jsx';

export const MarketRow = React.memo(function MarketRow({row, sec, lang, isFav, pinCls, pinTicker, pinCompany, visibleOrder, CELL_OF, pinAt, actions}) {
  const isPreferred = sec.is_preferred || row.share_type === "preferred";
  const shareLabel = row.type === 'bond' || sec.type === 'bond' ? mt(lang,'bondOne') : isPreferred ? mt(lang,'preferred') : row.share_type ? mt(lang,row.share_type) : row.type || '—';
  const shortShareLabel = row.type === 'bond' || sec.type === 'bond' ? mt(lang,'bondOne') : isPreferred ? lang === 'en' ? 'Pref.' : lang === 'uz' ? 'Imt.' : 'прив.' : lang === 'en' ? 'Common' : lang === 'uz' ? 'Oddiy' : 'обыкн.';
  return <tr>
          <td className={`market-ticker-cell${pinCls(pinTicker)}`} style={pinTicker ? {
      left: pinTicker.left
    } : undefined}>
            {/* The flex row lives inside the cell: a <td> that is itself
                `display: flex` drops out of table layout and stops
                stretching to its row, which misaligned every row. */}
            <div className="market-ticker-cell-inner">
            <button type="button" data-track-control="market_favorite" data-track-ticker={row.ticker} className={`market-fav-btn ${isFav ? "is-fav" : ""}`} aria-pressed={isFav} title={isFav ? lang === "en" ? "Remove from favorites" : lang === "uz" ? "Tanlanganlardan olib tashlash" : "Убрать из избранного" : lang === "en" ? "Add to favorites" : lang === "uz" ? "Tanlanganlarga qo'shish" : "В избранное"} onClick={e => {
        e.stopPropagation();
        actions.current.onToggleFavorite?.(row.ticker, row.name);
      }}>
              {isFav ? "★" : "☆"}
            </button>
            <CompanyPreviewLogo row={row} security={sec} />
            <div className="market-ticker-info">
              <button type="button" data-track-control="company_open" data-track-ticker={row.ticker} className="market-ticker-btn" onClick={() => actions.current.onOpenCompany ? actions.current.onOpenCompany(row.ticker) : actions.current.onAnalyze?.(row.ticker)}>
                {row.ticker || "—"}
              </button>
              <span className="market-share-class" title={shareLabel} aria-label={shareLabel}>
                <span className="market-share-full">{shareLabel}</span>
                <span className="market-share-short" aria-hidden="true">{shortShareLabel}</span>
              </span>
            </div>
            <button type="button" data-track-control="company_info" data-track-ticker={row.ticker} className="market-info-btn" title={lang === "en" ? "Company info" : lang === "uz" ? "Kompaniya ma'lumoti" : "О компании"} onClick={() => actions.current.openPanel(row.ticker)}>ℹ</button>
            </div>
          </td>
          <td className={pinCls(pinCompany).trim() || undefined} style={pinCompany ? {
      left: pinCompany.left
    } : undefined}>
            <button type="button" data-track-control="company_open" data-track-ticker={row.ticker} className="market-company-name-btn" onClick={() => actions.current.onOpenCompany?.(row.ticker)}>
              {row.name || sec.name || "—"}
            </button>
            <span>{row.isin || "—"}</span>
          </td>
          {visibleOrder.map(k => {
      const cell = CELL_OF[k](row);
      const pin = pinAt(k);
      if (!pin) return React.cloneElement(cell, {
        key: k
      });
      return React.cloneElement(cell, {
        key: k,
        className: `${cell.props.className || ""}${pinCls(pin)}`.trim(),
        style: {
          ...(cell.props.style || {}),
          left: pin.left
        }
      });
    })}
        </tr>;
});
