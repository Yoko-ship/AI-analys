import React from "react";
import { mt } from "../../shared/marketCopy.jsx";
import { CompanyLogo } from "../../shared/CompanyLogo.jsx";
import { MarketColMenu, MarketFloatScroll, MarketStickyHead } from "./TableOverlays.jsx";
import { BondsView } from "../bonds/index.js";
import { blocksMarketContent } from "../../lib/marketLoading.js";
import { MarketHeatmap } from "./Heatmap.jsx";
export function MarketTable({
  viewMode,
  type,
  lang,
  onOpenBond,
  onAnalyze,
  loading,
  rows,
  sectorMapRows,
  companies,
  smap,
  onOpenCompany,
  mapData,
  changePeriod,
  inactiveOnly,
  segment,
  negotiatedCount,
  negotiatedAnywhere,
  wrapRef,
  headCells,
  colSpan,
  visibleRows,
  hasFav,
  pinCls,
  pinTicker,
  onToggleFavorite,
  openPanel,
  pinCompany,
  visibleOrder,
  CELL_OF,
  pinAt,
  favOnly,
  colMenu,
  colGroupOf,
  sortDirOf,
  pinnedCols,
  setSortKeys,
  moveColBy,
  togglePin,
  toggleCol,
  setColMenu,
  closeColMenu
}) {
  return <>{viewMode === "table" && type === "bond" ? <BondsView language={lang} onOpenBond={onOpenBond || onAnalyze} embedded /> : viewMode === "heatmap" ? blocksMarketContent(loading, rows.length) ? <p className="market-empty-cell">{mt(lang, "loading")}</p> : <MarketHeatmap
    rows={sectorMapRows}
    companies={companies}
    securitiesMap={smap}
    language={lang}
    onAnalyze={onAnalyze}
    onOpenCompany={onOpenCompany}
    type={type}
    mapData={mapData}
    period={changePeriod}
  /> : <>
          {/* What the reader is now looking at, and why these rows do not
              behave like the rest of the board: the price is a close from
              months ago carried forward, the day's change is nil because there
              was no day, and the server leaves them out of the market's
              capitalisation. Without this the eleven rows look like eleven
              securities that all happened to close flat. */}
          {inactiveOnly && <p className="market-dormant-note">
              {lang === "en" ? "Listings with no trades for over 90 days. The price is their last settled close, carried forward — there is no day's move, and the market capitalisation above leaves them out." : lang === "uz" ? "90 kundan ortiq bitimsiz qog'ozlar. Narx — ularning oxirgi yopilishi, oldinga ko'chirilgan; kunlik o'zgarish yo'q va yuqoridagi kapitalizatsiya ularni hisobga olmaydi." : "Бумаги без сделок более 90 дней. Цена — их последнее закрытие, перенесённое вперёд: дневного изменения нет, и в капитализацию рынка выше они не входят."}
            </p>}
          {/* The NEGO board's own contract, stated where it is read: which
              columns are negotiated figures, which are still the session's, and
              why the two are never added together. */}
          {segment === "nego" && <p className="market-dormant-note">
              {lang === "en" ? "Negotiated deals (exchange board T1) — struck bilaterally at an agreed price, outside the auction. Turnover, quantity, trades and the average price are the negotiated ones; the quote, the day's change and the OHLC remain the auction session's, because a negotiated price is not a quote. The exchange's own bulletin excludes these deals from the session, and so does the Main board." : lang === "uz" ? "Kelishilgan bitimlar (T1 bordi) — auksiondan tashqari, kelishilgan narxda. Aylanma, hajm, bitimlar soni va o'rtacha narx — kelishilgan; kotirovka, kunlik o'zgarish va OHLC — auksion sessiyasining, chunki kelishilgan narx kotirovka emas." : "Переговорные сделки (борд T1) — заключены двусторонне по согласованной цене, вне аукциона. Оборот, количество, число сделок и средняя цена — переговорные; котировка, дневное изменение и OHLC остаются аукционными, потому что переговорная цена не является котировкой. Бюллетень биржи не включает эти сделки в сессию — и «Основной» рынок здесь тоже."}
            </p>}
          {segment === "nego" && negotiatedCount === 0 && !loading && <p className="market-dormant-note">
              {lang === "en" ? `No negotiated deals on record for the securities on this board.${negotiatedAnywhere ? ` The exchange's statistics hold ${negotiatedAnywhere} for other instruments — most of them bonds, which have their own section.` : ""}` : lang === "uz" ? `Bu ro'yxatdagi qog'ozlar bo'yicha kelishilgan bitimlar yo'q.${negotiatedAnywhere ? ` Boshqa instrumentlar bo'yicha — ${negotiatedAnywhere}, asosan obligatsiyalar.` : ""}` : `По бумагам этого раздела переговорных сделок не зафиксировано.${negotiatedAnywhere ? ` В статистике биржи их ${negotiatedAnywhere} по другим инструментам — в основном по облигациям, у которых свой раздел.` : ""}`}
            </p>}
          <div className="market-table-wrap" ref={wrapRef}>
            <table className="market-table">
              <thead>
                <tr>{headCells}</tr>
              </thead>
              <tbody>
                {blocksMarketContent(loading, rows.length) ? <tr><td colSpan={colSpan} className="market-empty-cell">{mt(lang, "loading")}</td></tr> : visibleRows.length ? visibleRows.map(row => {
              const sec = smap[row.ticker] || {};
              const logo = sec.logo_url;
              const isPreferred = sec.is_preferred || row.share_type === "preferred";
              const isFav = hasFav(row.ticker);
              return <tr key={`${row.ticker}-${row.isin}`}>
                      <td className={`market-ticker-cell${pinCls(pinTicker)}`} style={pinTicker ? {
                  left: pinTicker.left
                } : undefined}>
                        <button type="button" className={`market-fav-btn ${isFav ? "is-fav" : ""}`} aria-pressed={isFav} title={isFav ? lang === "en" ? "Remove from favorites" : lang === "uz" ? "Tanlanganlardan olib tashlash" : "Убрать из избранного" : lang === "en" ? "Add to favorites" : lang === "uz" ? "Tanlanganlarga qo'shish" : "В избранное"} onClick={e => {
                    e.stopPropagation();
                    onToggleFavorite && onToggleFavorite(row.ticker, row.name);
                  }}>
                          {isFav ? "★" : "☆"}
                        </button>
                        <CompanyLogo logo={logo} name={row.name || row.ticker} ticker={row.ticker} />
                        <div className="market-ticker-info">
                          <button type="button" className="market-ticker-btn" onClick={() => onOpenCompany ? onOpenCompany(row.ticker) : onAnalyze(row.ticker)}>
                            {row.ticker || "—"}
                          </button>
                          <span>{row.type === "bond" || sec.type === "bond" ? mt(lang, "bondOne") : isPreferred ? mt(lang, "preferred") : row.share_type ? mt(lang, row.share_type) : row.type || "—"}</span>
                        </div>
                        <button type="button" className="market-info-btn" title={lang === "en" ? "Company info" : lang === "uz" ? "Kompaniya ma'lumoti" : "О компании"} onClick={() => openPanel(row.ticker)}>ℹ</button>
                      </td>
                      <td className={pinCls(pinCompany).trim() || undefined} style={pinCompany ? {
                  left: pinCompany.left
                } : undefined}>
                        <button type="button" className="market-company-name-btn" onClick={() => onOpenCompany && onOpenCompany(row.ticker)}>
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
            }) : <tr><td colSpan={colSpan} className="market-empty-cell">{favOnly ? lang === "en" ? "No favorites yet — tap ☆ next to a company to track it." : lang === "uz" ? "Hali tanlanganlar yo'q — kuzatish uchun kompaniya yonidagi ☆ ni bosing." : "Пока нет избранного — нажмите ☆ рядом с компанией, чтобы следить за ней." : inactiveOnly ? lang === "en" ? "No dormant listing matches the current filters." : lang === "uz" ? "Joriy filtrlarga mos keladigan faol bo'lmagan qog'oz yo'q." : "Под текущие фильтры не попала ни одна неактивная бумага." : mt(lang, "empty")}</td></tr>}
              </tbody>
            </table>
          </div>
          <MarketStickyHead wrapRef={wrapRef} cells={headCells} colSignature={visibleOrder.join("|")} rowCount={visibleRows.length} loading={loading} />
          <MarketFloatScroll wrapRef={wrapRef} colSignature={visibleOrder.join("|")} rowCount={visibleRows.length} loading={loading} />
          {colMenu && visibleOrder.includes(colMenu.key) && (() => {
        const key = colMenu.key;
        const group = colGroupOf(key);
        const i = group.indexOf(key);
        return <MarketColMenu colKey={key} fromSticky={colMenu.fromSticky} lang={lang} state={{
          dir: sortDirOf(key),
          pinned: pinnedCols.has(key),
          canLeft: i > 0,
          canRight: i >= 0 && i < group.length - 1,
          // "Последняя" is a core column: the picker keeps it locked too.
          canHide: key !== "last"
        }} actions={{
          sort: dir => setSortKeys([{
            key,
            dir
          }]),
          move: step => moveColBy(key, step),
          pin: () => togglePin(key),
          hide: () => {
            toggleCol(key);
            setColMenu(null);
          }
        }} onClose={closeColMenu} />;
      })()}
          </>}</>;
}
