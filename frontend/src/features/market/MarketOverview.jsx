import { changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { formatCompactVolume, tradeCountLabel } from "../../shared/marketModel.jsx";
import { mt, sectorLabel } from "../../shared/marketCopy.jsx";
import { formatRatio } from "../../shared/format.jsx";
import { FxRatesBar } from "../currency/index.js";
import { MarketBreadthCard, MarketStatCard } from "./Statistics.jsx";
export function MarketOverview({
  viewMode,
  lang,
  onOpenBankFx,
  cardSector,
  setMarketSector,
  cardStats,
  formatLeader,
  marketSummary,
  sectorDormant,
  capPeriodChange,
  changePeriod,
  windowed
}) {
  return <>{viewMode === "heatmap" && <>
          <FxRatesBar language={lang} onOpenBanks={onOpenBankFx} />

          {/* The sector control that scopes these four cards is further down the
              page, in the filter bar — so the row has to say for itself which
              sector it is answering for, and offer the way back. Without this the
              numbers change under a control the reader cannot see from here. */}
          {cardSector && <div className="market-stats-scope">
              <span className="market-stats-scope-label">
                {lang === "en" ? "Sector" : lang === "uz" ? "Tarmoq" : "Категория"}:
              </span>
              <button type="button" className="market-stats-scope-chip" onClick={() => setMarketSector(null)}>
                {sectorLabel(lang, cardSector)}
                <span aria-hidden="true">×</span>
              </button>
            </div>}

          <div className="market-stats-grid">
        {/* Инструментов / Сделки сегодня / Без изменений were removed at the
            customer's request (2026-08-12) — the row keeps only the counters
            that name a mover or a sum of money. Up and down belong to one market
            breadth reading, so they share a card and a proportional rail. */}
        <MarketBreadthCard
          language={lang}
          advancers={cardStats.advancers}
          decliners={cardStats.decliners}
          topGrowth={formatLeader(cardStats.topGrowth)}
          topDrop={formatLeader(cardStats.topDrop)}
        />
        {/* ТЗ §8: the market's capitalisation is its ACTIVE SHARES. The client
            sum counted bonds, which carry no ownership, and dormant listings —
            23 of them, 29 088 bn — inside a figure labelled "the market". The
            server now answers with the total and with what it left out. */}
        {(() => {
          // Whole board: the server's own figure, because only it can say what it
          // left out. Under a sector chip there is no server answer to ask for, so
          // the sum comes from that sector's active rows — the same pool the three
          // counters beside it use — and the note counts what it left out of THEM.
          const server = cardSector ? null : marketSummary?.market_cap;
          const value = server?.value ?? cardStats.totalMarketCap;
          if (!(value > 0)) return null;
          let sub = "UZS";
          if (server) {
            const ex = server.excluded || {};
            const excludedNote = [ex.bonds?.instruments ? `${lang === "ru" ? "облигации" : lang === "uz" ? "obligatsiyalar" : "bonds"} — ${ex.bonds.instruments}` : null, ex.inactive_listings?.instruments ? `${lang === "ru" ? "неактивные" : lang === "uz" ? "faol emas" : "inactive"} — ${ex.inactive_listings.instruments}` : null].filter(Boolean).join(", ");
            if (excludedNote) sub = `UZS · ${lang === "ru" ? "исключено" : lang === "uz" ? "hisobdan chiqarilgan" : "excluded"}: ${excludedNote}`;
          } else if (sectorDormant) {
            // Its own sentence, not the market note's list with one item left in
            // it: «без облигации: 17, неактивные: 10» works as an enumeration
            // after «без», «без неактивные: 10» on its own does not.
            sub = `UZS · ${lang === "ru" ? "без неактивных" : lang === "uz" ? "faol emaslarsiz" : "excl. inactive"}: ${sectorDormant}`;
          }
          if (Number.isFinite(capPeriodChange)) {
            // The period the reader chose, spelled out beside its own number:
            // the card is read without the period control in view.
            sub = `${sub} · ${changePeriodLabel(changePeriod, lang, "short")}: ${capPeriodChange > 0 ? "+" : ""}${formatRatio(capPeriodChange, 2, lang)}%`;
          }
          return <MarketStatCard label={mt(lang, "marketCap")} value={formatCompactVolume(value, lang)} sub={sub} kind="capitalization" />;
        })()}
        {/* The day's turnover is the sum of the rows below it, not a separate
            feed's idea of the day: the mirror's /trades snapshot covers a fixed
            44 securities and called 31.07 "120,7 млн over ~900 trades" while the
            board it sits above listed 1,56 млрд over 6 507 — and it cannot
            answer per tab, so the shares view was quoting bond turnover too. */}
        {cardStats.totalVolume > 0 && <MarketStatCard
          label={windowed ? `${mt(lang, "volume")} · ${changePeriodLabel(changePeriod, lang, "short")}` : mt(lang, "volume")}
          termId="volume"
          lang={lang}
          value={formatCompactVolume(cardStats.totalVolume, lang)}
          sub={cardStats.totalTrades ? `${formatRatio(cardStats.totalTrades, 0, lang)} ${tradeCountLabel(cardStats.totalTrades, lang)}` : null}
          kind="turnover"
        />}
          </div>
        </>}</>;
}
