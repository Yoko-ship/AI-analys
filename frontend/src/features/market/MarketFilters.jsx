import { CHANGE_PERIODS, changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { mt, sectorLabel } from "../../shared/marketCopy.jsx";
import { TermInfo } from "../../shared/TermInfo.jsx";
import { MarketColsPopover } from "./TableOverlays.jsx";
export function MarketFilters({
  lang,
  type,
  onTypeChange,
  segment,
  setSegment,
  negotiatedCount,
  presentSectors,
  activeSector,
  setMarketSector,
  sectorWord,
  viewMode,
  favOnly,
  setFavOnly,
  dormantCount,
  inactiveOnly,
  setInactiveOnly,
  query,
  onQueryChange,
  exportCsv,
  exporting,
  exportError,
  colsBtnRef,
  colsOpen,
  setColsOpen,
  shownOrder,
  colsSearch,
  setColsSearch,
  CORE_COLS,
  MARKET_COLS,
  COL_GROUPS,
  openGroups,
  visibleCols,
  setVisibleCols,
  toggleGroup,
  toggleCol,
  coarsePointer,
  resetColOrder,
  changePeriod,
  setChangePeriod,
  sortKeys,
  onSort,
  SORT_LABEL_OF,
  sortHintSeen,
  dismissSortHint,
  clearSort
}) {
  return <div className="market-filterbar">
        <div className="market-controls">
          {/* Level 1: instrument class — stocks vs bonds are not comparable
              (price/capitalisation vs coupon/maturity), so they never share a table. */}
          <div className="market-type-levels">
            <div className="segmented-control market-type-control">
              {[["stock", mt(lang, "stocks")], ["bond", mt(lang, "bonds")]].map(([value, label]) => {
            const active = value === "bond" ? type === "bond" : type !== "bond";
            return <button key={value} type="button" className={active ? "active" : ""} onClick={() => onTypeChange(value)}>
                    {label}
                  </button>;
          })}
            </div>
            {/* MAIN | NEGO — the exchange's own two boards, side by side with the
                instrument class because that is the same kind of choice: which
                market you are looking at, not which slice of one. The count says
                how many lines had a negotiated deal, so an empty NEGO board
                reads as «none today» rather than as a broken page. */}
            <div className="segmented-control market-segment-control" role="group" aria-label={lang === "en" ? "Market board" : lang === "uz" ? "Bozor" : "Рынок"}>
              {[["main", lang === "en" ? "Main" : lang === "uz" ? "Asosiy" : "Основной"], ["nego", lang === "en" ? "Negotiated" : lang === "uz" ? "Kelishilgan" : "Переговорный"]].map(([value, label]) => <button
                key={value}
                type="button"
                className={segment === value ? "active" : ""}
                aria-pressed={segment === value}
                onClick={() => setSegment(value)}
                title={value === "main" ? lang === "en" ? "The auction session (board G1)" : lang === "uz" ? "Auksion sessiyasi (G1)" : "Аукционная сессия (борд G1)" : lang === "en" ? "Negotiated deals, struck bilaterally (board T1)" : lang === "uz" ? "Kelishilgan bitimlar (T1)" : "Переговорные сделки, вне сессии (борд T1)"}
              >
                    {label}
                    {value === "nego" && negotiatedCount > 0 ? ` (${negotiatedCount})` : ""}
                  </button>)}
            </div>
            {/* Level 2: share class — only meaningful inside stocks. */}
            {type !== "bond" && <div className="segmented-control market-subtype-control">
                {[["stock", mt(lang, "all")], ["ordinary", mt(lang, "ordinaryStocks")], ["preferred", mt(lang, "preferredStocks")]].map(([value, label]) => <button key={value} type="button" className={type === value ? "active" : ""} onClick={() => onTypeChange(value)}>
                    {label}
                  </button>)}
              </div>}
          </div>
          {/* Отрасль. A dropdown rather than the row of chips this used to be:
              eleven chips took a band of the pinned bar to themselves, wrapped
              onto two lines on a laptop, and — because the band was drawn for
              the table only — the map had no sector control at all. One list,
              one answer, both views. */}
          {presentSectors.length > 1 && <label className="market-sector-select">
              <select
                value={activeSector || ""}
                data-all={activeSector ? undefined : "1"}
                onChange={event => setMarketSector(event.target.value || null)}
                aria-label={sectorWord}
                title={lang === "en" ? "Show one sector only" : lang === "uz" ? "Faqat bitta sohani ko'rsatish" : "Показать только одну отрасль"}
              >
                <option value="">{`${sectorWord}: ${sectorLabel(lang, "all").toLowerCase()}`}</option>
                {presentSectors.map(s => <option key={s} value={s}>{sectorLabel(lang, s)}</option>)}
              </select>
            </label>}
          {viewMode === "table" && <button
            type="button"
            className={`market-fav-filter ${favOnly ? "active" : ""}`}
            aria-pressed={favOnly}
            onClick={() => setFavOnly(v => !v)}
            title={lang === "en" ? "Show favorites only" : lang === "uz" ? "Faqat tanlanganlar" : "Только избранное"}
          >
              <span className="fav-star">{favOnly ? "★" : "☆"}</span>
              <span className="market-btn-label">{lang === "en" ? "Favorites" : lang === "uz" ? "Tanlanganlar" : "Избранное"}</span>
            </button>}
          {/* ТЗ §4: dormant listings are hidden, not dropped — the count says
              how many, so their absence is a stated fact rather than a silence,
              and the chip shows exactly those rows. Table only: the map has
              nothing to draw for a security with no session (see `mapRows`), so
              offering the switch there would be offering eleven empty squares. */}
          {viewMode === "table" && dormantCount > 0 && <button
            type="button"
            className={`market-fav-filter market-dormant-filter ${inactiveOnly ? "active" : ""}`}
            aria-pressed={inactiveOnly}
            onClick={() => setInactiveOnly(v => !v)}
            title={inactiveOnly ? lang === "en" ? "Back to the traded board" : lang === "uz" ? "Savdodagi ro'yxatga qaytish" : "Вернуться к торгуемым" : lang === "en" ? `Show the ${dormantCount} listings with no trades for 90 days` : lang === "uz" ? `90 kun bitimsiz ${dormantCount} qog'ozni ko'rsatish` : `Показать ${dormantCount} бумаг без сделок более 90 дней`}
          >
              <span className="market-btn-label">
                {lang === "en" ? "Inactive" : lang === "uz" ? "Faol emas" : "Неактивные"}
                {` (${dormantCount})`}
              </span>
            </button>}
          {viewMode === "table" && <label className="market-search">
              <input value={query} onChange={event => onQueryChange(event.target.value)} placeholder={mt(lang, "search")} />
            </label>}
          {viewMode === "table" && <button type="button" className="market-fav-filter market-export-btn" onClick={exportCsv} disabled={exporting} aria-busy={exporting} title={mt(lang, "exportCsv")}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></svg>
              <span className="market-btn-label">{exporting ? lang === "en" ? "Preparing CSV…" : lang === "uz" ? "CSV tayyorlanmoqda…" : "Подготовка CSV…" : mt(lang, "exportCsv")}</span>
            </button>}
          {viewMode === "table" && <div className="market-cols-wrap">
              <button
                type="button"
                ref={colsBtnRef}
                className={`market-cols-btn ${colsOpen ? "active" : ""}`}
                aria-haspopup="true"
                aria-expanded={colsOpen}
                onClick={() => setColsOpen(o => !o)}
                title={lang === "en" ? "Choose which columns the table shows" : lang === "uz" ? "Jadval ustunlarini tanlash" : "Выбрать колонки таблицы"}
              >
                <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
                {/* Named, like every other button in this bar. A bare gear beside
                    «Избранное», «Неактивные» and «Экспорт CSV» read as an
                    afterthought and was the one control a reader had to guess at —
                    which is how a board with fifteen hidden columns looks like a
                    board that has none. The count says how many are on. */}
                <span className="market-btn-label">
                  {lang === "en" ? "Columns" : lang === "uz" ? "Ustunlar" : "Колонки"}
                  <span className="market-cols-count">{shownOrder.length}</span>
                </span>
              </button>
              {colsOpen && <MarketColsPopover anchorRef={colsBtnRef} onClose={() => setColsOpen(false)} title={lang === "en" ? "Columns" : lang === "uz" ? "Ustunlar" : "Колонки"} closeLabel={lang === "en" ? "Close" : lang === "uz" ? "Yopish" : "Закрыть"}>
                  <>
                    <div className="market-cols-search">
                      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>
                      <input type="text" value={colsSearch} onChange={e => setColsSearch(e.target.value)} placeholder={lang === "en" ? "Search" : lang === "uz" ? "Qidirish" : "Поиск"} />
                    </div>
                    {/* Its own scrollport: the groups scroll here, the search box
                        and the reset footer stay put, and `overscroll-behavior`
                        (CSS) stops the page behind from taking over the gesture. */}
                    <div className="market-cols-body">
                    {(() => {
                const q = colsSearch.trim().toLowerCase();
                const matches = label => !q || label.toLowerCase().includes(q);
                const anyMatch = CORE_COLS.some(([, l]) => matches(l)) || MARKET_COLS.some(([, l]) => matches(l));
                if (!anyMatch) {
                  return <div className="market-cols-empty">{lang === "en" ? "Nothing found" : lang === "uz" ? "Hech narsa topilmadi" : "Ничего не найдено"}</div>;
                }
                return <>
                          {!q && <div className="market-cols-group">
                              <div className="market-cols-group-body">
                                {CORE_COLS.map(([k, label]) => <label key={k} className="market-cols-row market-cols-row-locked">
                                    <input type="checkbox" checked disabled readOnly />
                                    <span>{label}</span>
                                    {/* Same ⓘ as the column header: this panel is where a
                                        reader decides whether a column is worth its width,
                                        which is exactly when they need to know what it
                                        means — before it is on screen to be hovered. */}
                                    <TermInfo termId={k} lang={lang} label={label} />
                                  </label>)}
                              </div>
                            </div>}
                          {COL_GROUPS.map(group => {
                    const cols = group.cols.filter(([, label]) => matches(label));
                    if (!cols.length) return null;
                    const open = q ? true : openGroups.has(group.key);
                    const allOn = group.cols.every(([k]) => visibleCols.has(k));
                    const someOn = group.cols.some(([k]) => visibleCols.has(k));
                    const shownInGroup = group.cols.filter(([k]) => visibleCols.has(k)).length;
                    const setGroupAll = () => setVisibleCols(prev => {
                      const n = new Set(prev);
                      group.cols.forEach(([k]) => {
                        if (allOn) n.delete(k);else n.add(k);
                      });
                      return n;
                    });
                    return <div className="market-cols-group" key={group.key}>
                                <button type="button" className="market-cols-group-head" onClick={() => toggleGroup(group.key)} aria-expanded={open}>
                                  <span className="market-cols-group-title">{group.title}</span>
                                  <span className="market-cols-group-meta">
                                    <span className="market-cols-group-badge">{shownInGroup}</span>
                                    <span className={`market-cols-group-chevron${open ? " open" : ""}`}>›</span>
                                  </span>
                                </button>
                                {open && <div className="market-cols-group-body">
                                    {!q && <label className="market-cols-row market-cols-all">
                                        <input type="checkbox" checked={allOn} ref={el => {
                            if (el) el.indeterminate = someOn && !allOn;
                          }} onChange={setGroupAll} />
                                        <span>{lang === "en" ? "All" : lang === "uz" ? "Hammasi" : "Все"}</span>
                                      </label>}
                                    {cols.map(([k, label]) => <label key={k} className="market-cols-row">
                                        <input type="checkbox" checked={visibleCols.has(k)} onChange={() => toggleCol(k)} />
                                        <span>{label}</span>
                                        {/* The picker's column key IS the glossary id, so the
                                            row asks for its own definition. A column that is
                                            not an economic term (Источник) renders no marker.
                                            The ⓘ is a <button>: per the HTML spec a label does
                                            not activate for events aimed at interactive
                                            descendants, so asking what P/E means does not
                                            toggle the P/E column. */}
                                        <TermInfo termId={k} lang={lang} label={label} />
                                      </label>)}
                                  </div>}
                              </div>;
                  })}
                        </>;
              })()}
                    </div>
                    <div className="market-cols-footer">
                      {/* The two things the headers do that a header does not look
                          like it does. This panel is where a reader comes looking
                          for table controls, so both are stated here as well. */}
                      <span className="market-cols-hint">
                        <span>{lang === "en" ? "Drag column headers to reorder" : lang === "uz" ? "Tartib uchun sarlavhalarni torting" : "Перетаскивайте заголовки для порядка"}</span>
                        <span>{coarsePointer ? lang === "en" ? "Press and hold a header to sort by two columns" : lang === "uz" ? "Ikki ustun bo‘yicha saralash — sarlavhani uzoq bosing" : "Долгое нажатие — сортировка по двум колонкам" : lang === "en" ? "Shift + click to sort by two columns" : lang === "uz" ? "Shift + bosish — ikki ustun bo‘yicha saralash" : "Shift + клик — сортировка по двум колонкам"}</span>
                      </span>
                      <button type="button" className="market-cols-reset" onClick={resetColOrder}>
                        {lang === "en" ? "Reset order" : lang === "uz" ? "Tartibni tiklash" : "Сбросить порядок"}
                      </button>
                    </div>
                  </>
                </MarketColsPopover>}
            </div>}
        </div>

          {/* The period every «изменение» on this screen is measured over. It
            moves the «Изм.» column, the movers strip and the map together —
            one question, one answer. The two fixed 1Н/1М columns stay where
            they are; a reader can still have all three on screen. */}
        {exportError && <p role="alert" className="market-export-error">{lang === "en" ? "Could not prepare CSV. Please try exporting again." : lang === "uz" ? "CSV tayyorlab bo‘lmadi. Eksportni qayta urinib ko‘ring." : "Не удалось подготовить CSV. Попробуйте экспорт ещё раз."}</p>}
        <div className="market-period-row">
        <span className="market-period-label">
          {lang === "en" ? "Change over" : lang === "uz" ? "O'zgarish davri" : "Изменение за"}
        </span>
        <div className="segmented-control market-period-control" role="group" aria-label={lang === "en" ? "Change period" : lang === "uz" ? "O'zgarish davri" : "Период изменения"}>
          {CHANGE_PERIODS.map(p => <button
            key={p.code}
            type="button"
            className={changePeriod === p.code ? "active" : ""}
            aria-pressed={changePeriod === p.code}
            onClick={() => setChangePeriod(p.code)}
            title={lang === "en" ? `Change over ${changePeriodLabel(p.code, lang)}` : lang === "uz" ? `${changePeriodLabel(p.code, lang)} o'zgarishi` : `Изменение за ${changePeriodLabel(p.code, lang).toLowerCase()}`}
          >
              {p.code === "1d" ? lang === "en" ? "Session" : lang === "uz" ? "Sessiya" : "Сессия" : p.code === "ytd" ? "YTD" : changePeriodLabel(p.code, lang)}
            </button>)}
        </div>
        </div>

        {/* A sort built from two headers is invisible once you scroll — the carets
            are off in the columns that made it. Spell the chain out, in order, with
            one control back to the board's default order.
              It shows from the FIRST sorted column, not the second, for two reasons:
            until now a header click could never be undone (there was no way back to
            "latest session first"), and one sorted column is exactly the moment the
            reader is ready to be told a second one can be added. */}
        {viewMode === "table" && sortKeys.length > 0 && <div className="market-sort-chain">
            <span className="market-sort-chain-label">
              {lang === "en" ? "Sorted by" : lang === "uz" ? "Saralash" : "Сортировка"}:
            </span>
            {sortKeys.map(({
        key,
        dir
      }, i) => <button
        key={key}
        type="button"
        className="market-sort-chain-chip"
        onClick={() => onSort(key, true)}
        title={lang === "en" ? "Click to flip, again to remove" : lang === "uz" ? "Yoʻnalishni almashtirish uchun bosing, olib tashlash uchun yana bosing" : "Клик — сменить направление, ещё раз — убрать"}
      >
                {sortKeys.length > 1 && <span className="market-sort-chain-rank">{i + 1}</span>}
                <span>{SORT_LABEL_OF[key] || key}</span>
                <span className="market-sort-caret">{dir === "asc" ? "▲" : "▼"}</span>
              </button>)}
            {sortKeys.length === 1 && !sortHintSeen && <span className="market-sort-teach">
                {coarsePointer ? lang === "en" ? <>press and hold another column to sort by <b>two</b></> : lang === "uz" ? <>ikkinchi kalit uchun boshqa ustunni <b>uzoq bosing</b></> : <>удерживайте другую колонку, чтобы сортировать по <b>двум</b></> : lang === "en" ? <><kbd>Shift</kbd> + click another column to sort by <b>two</b></> : lang === "uz" ? <><kbd>Shift</kbd> + boshqa ustunni bosing — <b>ikkita</b> kalit</> : <><kbd>Shift</kbd> + клик по другой колонке — сортировка по <b>двум</b></>}
                <button
                  type="button"
                  className="market-sort-teach-close"
                  onClick={dismissSortHint}
                  aria-label={lang === "en" ? "Got it" : lang === "uz" ? "Tushunarli" : "Понятно"}
                  title={lang === "en" ? "Got it" : lang === "uz" ? "Tushunarli" : "Понятно"}
                >×</button>
              </span>}
            <button type="button" className="market-sort-chain-reset" onClick={clearSort}>
              {lang === "en" ? "Reset" : lang === "uz" ? "Tiklash" : "Сбросить"}
            </button>
          </div>}
        </div>;
}
