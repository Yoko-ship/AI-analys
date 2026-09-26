import { normalizeLanguage } from "../../shared/i18n.jsx";
import { useEffect, useState } from "react";
import { CHANGE_PERIODS, CHANGE_PERIOD_KEY, changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { mt } from "../../shared/marketCopy.jsx";
import { formatRatio } from "../../shared/format.jsx";
import { CompanyInfoPanel } from "./CompanyInfoPanel.jsx";
import { marketColumns } from "./marketColumns.js";
import { useMarketColumns } from "./useMarketColumns.js";
import { useMarketEnrichment } from "./useMarketEnrichment.js";
import { useMarketSorting } from "./useMarketSorting.js";
import { useCompanyPanel } from "./useCompanyPanel.js";
import { useMarketRows } from "./useMarketRows.js";
import { summarizeMarket } from "./marketSummary.js";
import { createMarketCells } from "./MarketCells.jsx";
import { sortMarketRows } from "./marketSorting.js";
import { createMarketExport } from "./marketExport.js";
import { useMarketExport } from "./useMarketExport.js";
import { createMarketHeaders } from "./MarketHeaders.jsx";
import { MarketHeader } from "./MarketHeader.jsx";
import { MarketOverview } from "./MarketOverview.jsx";
import { MarketMovers } from "./MarketMovers.jsx";
import { MarketFilters } from "./MarketFilters.jsx";
import { MarketTable } from "./MarketTable.jsx";
function MarketView({
  rows,
  meta,
  loading,
  message,
  query,
  onQueryChange,
  type,
  onTypeChange,
  onRefresh,
  onAnalyze,
  onOpenCompany,
  onOpenBond,
  onOpenBankFx,
  language,
  companies,
  securitiesMap,
  financials,
  tradeStats,
  favoriteTickers,
  onToggleFavorite,
  viewMode: viewModeProp,
  onViewModeChange,
  isAdmin = false
}) {
  const lang = normalizeLanguage(language);
  const viewMode = viewModeProp || "table";
  const setViewMode = onViewModeChange || (() => {});
  const [marketSector, setMarketSector] = useState(null);
  const [favOnly, setFavOnly] = useState(false);
  const hasFav = t => !!favoriteTickers && favoriteTickers.has(String(t || "").trim().toUpperCase());
  const [segment, setSegment] = useState("main");
  const [changePeriod, setChangePeriod] = useState(() => {
    try {
      const saved = localStorage.getItem(CHANGE_PERIOD_KEY);
      if (CHANGE_PERIODS.some(p => p.code === saved)) return saved;
    } catch (e) {/* ignore */}
    return "1d";
  });
  useEffect(() => {
    try {
      localStorage.setItem(CHANGE_PERIOD_KEY, changePeriod);
    } catch (e) {/* ignore */}
  }, [changePeriod]);
  const [inactiveOnly, setInactiveOnly] = useState(false);
  const {
    COL_GROUPS,
    MARKET_COLS,
    CORE_COLS,
    SORT_LABEL_OF
  } = marketColumns({
    lang,
    changePeriod
  });
  const {
    visibleCols,
    setVisibleCols,
    colsOpen,
    setColsOpen,
    colsBtnRef,
    colsSearch,
    setColsSearch,
    openGroups,
    toggleGroup,
    toggleCol,
    MOVABLE_KEYS,
    dragCol,
    setDragCol,
    dragOverCol,
    setDragOverCol,
    wrapRef,
    moveCol,
    resetColOrder,
    pinnedCols,
    togglePin,
    shownOrder,
    visibleOrder,
    colSpan,
    pinAt,
    pinCls,
    colGroupOf,
    moveColBy,
    colMenu,
    setColMenu,
    closeColMenu
  } = useMarketColumns({
    MARKET_COLS,
    type
  });
  const {
    prepareExport,
    ratios,
    changes,
    multiples,
    multiplesStatus,
    onDemandFinancials,
    marketSummary,
    mapData,
    instruments,
    suppliedFinancials
  } = useMarketEnrichment({
    rows,
    loading,
    viewMode,
    visibleCols,
    financials,
    type
  });
  const {
    sortKeys,
    setSortKeys,
    sortRankOf,
    sortDirOf,
    onSort,
    clearSort,
    longPress,
    startLongPress,
    cancelLongPress,
    sortHintSeen,
    dismissSortHint,
    coarsePointer
  } = useMarketSorting();
  const {
    panelTicker,
    setPanelTicker,
    panelWiki,
    setPanelWiki,
    panelWikiLoading,
    openPanel
  } = useCompanyPanel({
    lang
  });
  const {
    changeOver,
    parOf,
    priceToPar,
    smap,
    finOf,
    negotiatedCount,
    negotiatedAnywhere,
    windowed,
    byClass,
    isDormant,
    dormantCount,
    prepared,
    search,
    rowSector,
    presentSectors,
    sectorWord,
    activeSector,
    sectorMapRows,
    ratioOf,
    mktCapOf,
    multipleOf,
    multiplesOf,
    valuationOf,
    peOf,
    annualisedFin,
    pbOf
  } = useMarketRows({
    changes,
    securitiesMap,
    companies,
    suppliedFinancials,
    financials,
    onDemandFinancials,
    tradeStats,
    rows,
    segment,
    changePeriod,
    type,
    instruments,
    inactiveOnly,
    query,
    lang,
    marketSector,
    ratios,
    multiples,
    multiplesStatus
  });
  const {
    cardSector,
    stats,
    cardStats,
    capPeriodChange,
    sectorDormant,
    periodMovers
  } = summarizeMarket({
    activeSector,
    byClass,
    isDormant,
    windowed,
    rowSector,
    mktCapOf
  });
  const {
    LABEL_OF,
    NUM_COLS,
    CELL_OF
  } = createMarketCells({
    lang,
    finOf,
    ratioOf,
    changeOver,
    MARKET_COLS,
    windowed,
    changePeriod,
    MOVABLE_KEYS,
    parOf,
    priceToPar,
    stats,
    mktCapOf,
    valuationOf,
    multipleOf,
    multiplesOf
  });
  const {
    visibleRows
  } = sortMarketRows({
    changePeriod,
    changeOver,
    parOf,
    priceToPar,
    annualisedFin,
    finOf,
    mktCapOf,
    peOf,
    pbOf,
    multipleOf,
    ratioOf,
    prepared,
    favOnly,
    hasFav,
    activeSector,
    rowSector,
    search,
    sortKeys
  });
  const {
    exportCsv
  } = createMarketExport({
    lang,
    type,
    activeSector,
    favOnly,
    inactiveOnly,
    query,
    stats,
    windowed,
    changePeriod,
    sortKeys,
    SORT_LABEL_OF,
    visibleRows,
    smap,
    finOf,
    changeOver,
    mktCapOf,
    peOf,
    pbOf,
    multipleOf
  });
  const { startExport, exporting, exportError } = useMarketExport({ type, prepareExport, exportCsv });
  const {
    headCells,
    pinTicker,
    pinCompany
  } = createMarketHeaders({
    pinAt,
    sortRankOf,
    sortDirOf,
    sortKeys,
    dragCol,
    dragOverCol,
    colMenu,
    lang,
    longPress,
    onSort,
    startLongPress,
    cancelLongPress,
    setDragCol,
    setDragOverCol,
    moveCol,
    setColMenu,
    visibleOrder,
    LABEL_OF,
    NUM_COLS
  });
  const formatLeader = row => row ? `${row.ticker} ${formatRatio(row.changePercent, 2, lang)}%` : "—";
  return <section className="market-layout">
      <MarketHeader lang={lang} isAdmin={isAdmin} meta={meta} onRefresh={onRefresh} loading={loading} rows={rows} />

      {/* The FX strip and summary cards provide context for the visual map, but
          duplicate information available in the market table. Keep this block
          on the dedicated heatmap page only. */}
      <MarketOverview
        viewMode={viewMode}
        lang={lang}
        onOpenBankFx={onOpenBankFx}
        cardSector={cardSector}
        setMarketSector={setMarketSector}
        cardStats={cardStats}
        formatLeader={formatLeader}
        marketSummary={marketSummary}
        sectorDormant={sectorDormant}
        capPeriodChange={capPeriodChange}
        changePeriod={changePeriod}
        windowed={windowed}
      />

      {/* Three readings of one session: who moved, and who was actually
          tradeable. Ликвидность answers the question the two percent lists
          cannot — a +20 % on one 37 200-сум trade is a move, not a market —
          and it reads off the same «Объём» (turnover in money) the column, the
          turnover card and the charts already mean — in the same compact form
          those use, so the figure is recognisable without a unit spelled out
          beside it (one was tried in the head and the customer had it out). */}
      <MarketMovers
        viewMode={viewMode}
        periodMovers={periodMovers}
        lang={lang}
        changePeriod={changePeriod}
        onOpenCompany={onOpenCompany}
        onAnalyze={onAnalyze}
        smap={smap}
      />

      <article className="panel market-board">
        <div className="market-board-head">
          <div>
            <div className="panel-label">{viewMode === "heatmap" ? lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка" : mt(lang, "tableTitle")}</div>
            <h2>{viewMode === "heatmap" ? lang === "en" ? "Market Map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка" : mt(lang, "tableTitle")}</h2>
          </div>
          <div className="market-board-head-right">
            {(windowed || stats.boardDay) && <span className="market-session-date">
                {windowed ? changePeriodLabel(changePeriod, lang, "label") : `${stats.boardDay.slice(6, 8)}.${stats.boardDay.slice(4, 6)}.${stats.boardDay.slice(0, 4)}`}
              </span>}
            <div className="market-view-toggle">
              <button type="button" className={viewMode === "table" ? "active" : ""} onClick={() => setViewMode("table")} title={lang === "en" ? "Table view" : lang === "uz" ? "Jadval ko'rinishi" : "Таблица"}>
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="2" width="13" height="1.8" rx="0.9" />
                  <rect x="1" y="6.6" width="13" height="1.8" rx="0.9" />
                  <rect x="1" y="11.2" width="13" height="1.8" rx="0.9" />
                </svg>
                <span>{lang === "en" ? "Table" : lang === "uz" ? "Jadval" : "Таблица"}</span>
              </button>
              <button type="button" className={viewMode === "heatmap" ? "active" : ""} onClick={() => setViewMode("heatmap")} title={lang === "en" ? "Market map" : lang === "uz" ? "Bozor xaritasi" : "Карта рынка"}>
                <svg width="15" height="15" viewBox="0 0 15 15" fill="currentColor">
                  <rect x="1" y="1" width="5.8" height="5.8" rx="1.2" />
                  <rect x="8.2" y="1" width="5.8" height="5.8" rx="1.2" />
                  <rect x="1" y="8.2" width="5.8" height="5.8" rx="1.2" />
                  <rect x="8.2" y="8.2" width="5.8" height="5.8" rx="1.2" />
                </svg>
                <span>{lang === "en" ? "Map" : lang === "uz" ? "Xarita" : "Карта"}</span>
              </button>
            </div>
            {viewMode === "table" && <span className="status-badge muted">{mt(lang, "showing")}: {visibleRows.length}/{prepared.length}</span>}
          </div>
        </div>

        {/* Every filter the board has — instrument class, share class, favourites,
            search, the column picker and the sector chips — lives in one block so
            it can stick under the topbar as a unit. Scrolling to row 300 must not
            cost the reader the controls that put those rows on screen. */}
        <MarketFilters
          lang={lang}
          type={type}
          onTypeChange={onTypeChange}
          segment={segment}
          setSegment={setSegment}
          negotiatedCount={negotiatedCount}
          presentSectors={presentSectors}
          activeSector={activeSector}
          setMarketSector={setMarketSector}
          sectorWord={sectorWord}
          viewMode={viewMode}
          favOnly={favOnly}
          setFavOnly={setFavOnly}
          dormantCount={dormantCount}
          inactiveOnly={inactiveOnly}
          setInactiveOnly={setInactiveOnly}
          query={query}
          onQueryChange={onQueryChange}
          exportCsv={startExport}
          exporting={exporting || loading || !rows.length}
          exportError={exportError}
          colsBtnRef={colsBtnRef}
          colsOpen={colsOpen}
          setColsOpen={setColsOpen}
          shownOrder={shownOrder}
          colsSearch={colsSearch}
          setColsSearch={setColsSearch}
          CORE_COLS={CORE_COLS}
          MARKET_COLS={MARKET_COLS}
          COL_GROUPS={COL_GROUPS}
          openGroups={openGroups}
          visibleCols={visibleCols}
          setVisibleCols={setVisibleCols}
          toggleGroup={toggleGroup}
          toggleCol={toggleCol}
          coarsePointer={coarsePointer}
          resetColOrder={resetColOrder}
          changePeriod={changePeriod}
          setChangePeriod={setChangePeriod}
          sortKeys={sortKeys}
          onSort={onSort}
          SORT_LABEL_OF={SORT_LABEL_OF}
          sortHintSeen={sortHintSeen}
          dismissSortHint={dismissSortHint}
          clearSort={clearSort}
        />

        {/* ТЗ Дополнение 1 §А.2: bonds get their own table, not a row in the
            equity board — an issue has a value rather than a capitalisation, and
            no earnings for a multiple to divide by. The «Облигации» segment IS
            the bond section: screener + yield map, a row opens /bond/{T}. */}
        <MarketTable
          viewMode={viewMode}
          type={type}
          lang={lang}
          onOpenBond={onOpenBond}
          onAnalyze={onAnalyze}
          loading={loading}
          rows={rows}
          sectorMapRows={sectorMapRows}
          companies={companies}
          smap={smap}
          onOpenCompany={onOpenCompany}
          mapData={mapData}
          changePeriod={changePeriod}
          inactiveOnly={inactiveOnly}
          segment={segment}
          negotiatedCount={negotiatedCount}
          negotiatedAnywhere={negotiatedAnywhere}
          wrapRef={wrapRef}
          headCells={headCells}
          colSpan={colSpan}
          visibleRows={visibleRows}
          hasFav={hasFav}
          pinCls={pinCls}
          pinTicker={pinTicker}
          onToggleFavorite={onToggleFavorite}
          openPanel={openPanel}
          pinCompany={pinCompany}
          visibleOrder={visibleOrder}
          CELL_OF={CELL_OF}
          pinAt={pinAt}
          favOnly={favOnly}
          colMenu={colMenu}
          colGroupOf={colGroupOf}
          sortDirOf={sortDirOf}
          pinnedCols={pinnedCols}
          setSortKeys={setSortKeys}
          moveColBy={moveColBy}
          togglePin={togglePin}
          toggleCol={toggleCol}
          setColMenu={setColMenu}
          closeColMenu={closeColMenu}
        />
      </article>

      {panelTicker && <CompanyInfoPanel ticker={panelTicker} secInfo={smap[panelTicker]} wikiInfo={panelWiki} language={language} onClose={() => {
      setPanelTicker(null);
      setPanelWiki(null);
    }} loading={panelWikiLoading} />}
    </section>;
}
export { MarketView };
