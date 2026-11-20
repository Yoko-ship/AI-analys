import React from "react";
import { mt } from "../../shared/marketCopy.jsx";
import { CompanyPreviewProvider } from "./CompanyPreview.jsx";
import { MarketRow } from "./MarketRow.jsx";
const EMPTY_SECURITY = {};
import { MarketColMenu, MarketFloatScroll, MarketStickyHead } from "./TableOverlays.jsx";
import { BondsView } from "../bonds/index.js";
import { blocksMarketContent } from "../../lib/marketLoading.js";
import { MarketHeatmap, HeatmapLayout } from "./Heatmap.jsx";
export function MarketTable({
  heatmapFilters,
  heatmapViewControl,
  mapPresentation,
  isAdmin = false,
  stats,
  windowed,
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
  wrapRef,
  headCells,
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
  closeColMenu,
  filtered,
  onResetFilters
}) {
  // Event handlers must see the current session/navigation without invalidating
  // unchanged quote rows whenever the shell or a column control renders.
  const rowActions = React.useRef({onOpenCompany, onAnalyze, onToggleFavorite, openPanel});
  React.useLayoutEffect(() => {
    rowActions.current = {onOpenCompany, onAnalyze, onToggleFavorite, openPanel};
  }, [onOpenCompany, onAnalyze, onToggleFavorite, openPanel]);
  return <CompanyPreviewProvider enabled={isAdmin} lang={lang} changePeriod={changePeriod} onOpenCompany={onOpenCompany || onAnalyze}>{viewMode === "table" && type === "bond" ? <BondsView language={lang} onOpenBond={onOpenBond || onAnalyze} embedded /> : viewMode === "heatmap" ? blocksMarketContent(loading, rows.length) ? <HeatmapLayout lang={lang} filters={heatmapFilters} viewControl={heatmapViewControl}><p className="market-empty-cell">{mt(lang, "loading")}</p></HeatmapLayout> : <MarketHeatmap
    filters={heatmapFilters}
    viewControl={heatmapViewControl}
    presentation={mapPresentation}
    isAdmin={isAdmin}
    rows={sectorMapRows}
    emptyFiltered={filtered && rows.length > 0}
    onResetFilters={onResetFilters}
    companies={companies}
    securitiesMap={smap}
    language={lang}
    onAnalyze={onAnalyze}
    onOpenCompany={type === "bond" ? onOpenBond || onOpenCompany : onOpenCompany}
    type={type}
    mapData={mapData}
    period={windowed ? changePeriod : "1d"}
    stats={stats}
  /> : <>
          {inactiveOnly && <p className="market-dormant-note">
              {lang === "en" ? "These securities last traded over 90 days ago. Prices and daily changes refer to each security’s last trading session. The market capitalisation above excludes these securities." : lang === "uz" ? "Bu qimmatli qog‘ozlar oxirgi marta 90 kundan ko‘proq vaqt oldin sotilgan. Narx va kunlik o‘zgarish har bir qog‘ozning oxirgi savdo sessiyasiga tegishli. Yuqoridagi bozor kapitallashuviga ular kiritilmagan." : "Эти бумаги торговались более 90 дней назад. Цена и дневное изменение указаны за последнюю сессию каждой бумаги. Капитализация рынка выше рассчитана без этих бумаг."}
            </p>}
          <div className="market-table-wrap" ref={wrapRef}>
            <table className="market-table">
              <thead>
                <tr>{headCells}</tr>
              </thead>
              <tbody>
                {blocksMarketContent(loading, rows.length) ? null : visibleRows.map(row => (
                  <MarketRow key={`${row.ticker}-${row.isin}`} row={row} sec={smap[row.ticker] || EMPTY_SECURITY}
                    lang={lang} isFav={hasFav(row.ticker)} pinCls={pinCls} pinTicker={pinTicker} pinCompany={pinCompany}
                    visibleOrder={visibleOrder} CELL_OF={CELL_OF} pinAt={pinAt} actions={rowActions}/>
                ))}
              </tbody>
            </table>
          </div>
          {(blocksMarketContent(loading, rows.length) || !visibleRows.length) && <div className="market-empty-cell" role="status">
            <p>{blocksMarketContent(loading, rows.length) ? mt(lang,'loading') : favOnly ? lang === "en" ? "No favorites yet — tap ☆ next to a company to track it." : lang === "uz" ? "Hali tanlanganlar yo'q — kuzatish uchun kompaniya yonidagi ☆ ni bosing." : "Пока нет избранного — нажмите ☆ рядом с компанией, чтобы следить за ней." : inactiveOnly ? lang === "en" ? "No dormant listing matches the current filters." : lang === "uz" ? "Joriy filtrlarga mos keladigan faol bo'lmagan qog'oz yo'q." : "Под текущие фильтры не попала ни одна неактивная бумага." : mt(lang,'empty')}</p>
            {!blocksMarketContent(loading,rows.length) && filtered && <button type="button" className="ghost-btn" onClick={onResetFilters}>{lang === 'en' ? 'Reset filters' : lang === 'uz' ? 'Filtrlarni tozalash' : 'Сбросить фильтры'}</button>}
          </div>}
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
          </>}</CompanyPreviewProvider>;
}
