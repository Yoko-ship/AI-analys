import { roundedDisplayValue } from "../../lib/format.js";
import { changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { avgSharePrice, marketDisplayPrice } from "../../shared/marketModel.jsx";
import { mt } from "../../shared/marketCopy.jsx";
import { finPeriodCoverage, finRowPeriod, marketRowDay } from "../../lib/valuation.js";
export function createMarketExport({
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
}) {
  const exportCsv = () => {
    const ruLocale = lang !== "en";
    const sep = ruLocale ? ";" : ",";
    const cell = v => {
      if (v === null || v === undefined || v === "" || typeof v === "number" && Number.isNaN(v)) return "";
      let s = typeof v === "number" ? ruLocale ? String(v).replace(".", ",") : String(v) : String(v);
      // A quoted field is needed for the delimiter, quotes and newlines — and, once decimals
      // are commas, for every number too when the delimiter is a comma.
      return new RegExp(`["\\n\\r${sep === ";" ? ";" : ","}]`).test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    // Rounded the way the screen rounds: a report states a figure, it does not dump a float.
    const round = (v, digits) => Number.isFinite(v) ? Number(v.toFixed(digits)) : "";
    const money = v => Number.isFinite(v) ? roundedDisplayValue(v) : "";
    const filters = [mt(lang, type === "stock" ? "stocks" : type === "bond" ? "bonds" : type === "preferred" ? "preferredStocks" : type === "ordinary" ? "ordinaryStocks" : "all"),
    // The file states the filters that ACTUALLY shaped it — a suspended sector
    // named in the header would describe a selection the rows never went through.
    activeSector || "", favOnly ? mt(lang, "csvFav") : "",
    // The export states its filters, and «только неактивные» changes what the
    // whole file IS — a sheet of eleven dormant listings that looks like the
    // board would be read as the board.
    inactiveOnly ? lang === "en" ? "inactive only" : lang === "uz" ? "faqat faol emas" : "только неактивные" : "", String(query || "").trim() ? `${mt(lang, "csvSearch")}: ${String(query).trim()}` : ""].filter(Boolean).join(" · ");
    // `last_trade_date` arrives as DD.MM.YYYY from the live feed and YYYY-MM-DD from the
    // listings registry. Normalise both through marketRowDay so one column holds one format.
    const day = d => /^\d{8}$/.test(d || "") ? `${d.slice(6)}.${d.slice(4, 6)}.${d.slice(0, 4)}` : "";
    const session = day(stats.boardDay);

    // Two columns, so the block reads as label/value in a spreadsheet rather than as text
    // spilled across the sheet. A blank row separates it from the table proper.
    const lines = [[mt(lang, "csvTitle"), ""].map(cell).join(sep),
    // Stamped DD.MM.YYYY like every other date in the file. Deliberately not the browser
    // locale's own format: on en-US that prints 7/29/2026 next to a 29.07.2026 trade-date
    // column, and one report should not carry two date conventions.
    [mt(lang, "csvGenerated"), (() => {
      const d = new Date();
      const pad = n => String(n).padStart(2, "0");
      return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    })()].map(cell).join(sep),
    // Over a window there is no ONE session to stamp — `stats.boardDay` is
    // null by design — and a «Торговая сессия» row with nothing after it reads
    // as a missing value rather than as a period export. The period line below
    // takes its place.
    ...(session ? [[mt(lang, "csvSession"), session].map(cell).join(sep)] : []),
    // Which PERIOD the volume columns describe. Without it the file is a set
    // of numbers that look like a session and are a year — the one thing a
    // spreadsheet, unlike the screen, carries no control to reveal.
    ...(windowed ? [[mt(lang, "csvPeriod"), changePeriodLabel(changePeriod, lang, "label")].map(cell).join(sep), [mt(lang, "csvPeriodNote"), ""].map(cell).join(sep)] : []), [mt(lang, "csvFilter"), filters].map(cell).join(sep),
    // The file is the table as it stands on screen, so the row ORDER is part of
    // what is being exported — state it rather than let the reader guess.
    [mt(lang, "csvSort"), sortKeys.length ? sortKeys.map(({
      key,
      dir
    }) => `${SORT_LABEL_OF[key] || key} ${dir === "asc" ? "↑" : "↓"}`).join(" → ") : mt(lang, "csvSortDefault")].map(cell).join(sep), [mt(lang, "csvRows"), visibleRows.length].map(cell).join(sep), [mt(lang, "csvMoneyNote"), ""].map(cell).join(sep), [mt(lang, "csvSources"), ""].map(cell).join(sep), ""];
    const header = [mt(lang, "ticker"), mt(lang, "company"), mt(lang, "isin"), mt(lang, "sector"), mt(lang, "shareType"), mt(lang, "date"), mt(lang, "last"), `${mt(lang, "change")}, %`,
    // Each window change names the session it was measured from — the same
    // statement the cell's tooltip makes, because a percent without its base
    // date is not reproducible from a spreadsheet.
    `${mt(lang, "change")} 1${lang === "en" ? "W" : lang === "uz" ? "H" : "Н"}, %`, lang === "en" ? "1W base" : lang === "uz" ? "1H bazasi" : "База 1Н", `${mt(lang, "change")} 1${lang === "en" ? "M" : lang === "uz" ? "O" : "М"}, %`, lang === "en" ? "1M base" : lang === "uz" ? "1O bazasi" : "База 1М", mt(lang, "open"), mt(lang, "high"), mt(lang, "low"), mt(lang, "volumeCol"), mt(lang, "csvTrades"), mt(lang, "volQty"), mt(lang, "avgSharePrice"), "VWAP", mt(lang, "bigTrade"), mt(lang, "volShare"), mt(lang, "finPeriod"), mt(lang, "finCoverage"), mt(lang, "finRevenue"), mt(lang, "finGross"), mt(lang, "finOperating"), mt(lang, "finNet"), mt(lang, "finCash"), mt(lang, "finLiab"), mt(lang, "mktCap"), mt(lang, "pe"), mt(lang, "pb"), "P/S", mt(lang, "roe"), mt(lang, "roa"), `${mt(lang, "netMargin")}, % (${mt(lang, "netMarginBankNote")})`, `${mt(lang, "equityAssets")}, %`];
    lines.push(header.map(cell).join(sep));
    for (const row of visibleRows) {
      const sec = smap[row.ticker] || {};
      const fin = finOf(row.ticker) || null;
      const period = finRowPeriod(fin);
      const share = stats.boardDay && marketRowDay(row) !== stats.boardDay ? 0 : Number.isFinite(row.stockVolume) && stats.totalVolume > 0 ? row.stockVolume / stats.totalVolume * 100 : "";
      const isPreferred = sec.is_preferred || row.share_type === "preferred";
      lines.push([row.ticker, row.name, row.isin, sec.sector || "", row.type === "bond" || sec.type === "bond" ? mt(lang, "bondOne") : isPreferred ? mt(lang, "preferred") : mt(lang, "ordinary"), day(marketRowDay(row)), round(marketDisplayPrice(row), 2), round(row.changePercent, 2), round(changeOver(row.ticker, "1w")?.pct, 2), day(changeOver(row.ticker, "1w")?.from), round(changeOver(row.ticker, "1m")?.pct, 2), day(changeOver(row.ticker, "1m")?.from), round(row.openPrice, 2), round(row.highPrice, 2), round(row.lowPrice, 2), money(row.stockVolume), row.stockTradeCount, row.stockQuantity, round(Number.isFinite(row.avgPrice) ? row.avgPrice : avgSharePrice(row), 2), round(row.vwap, 2), money(row.ts?.largest_value), round(share, 2), period || "", period ? finPeriodCoverage(period, lang) : "", money(fin?.revenue), money(fin?.gross_profit), money(fin?.operating_income), money(fin?.net_income), money(fin?.cash), money(fin?.total_liabilities), money(mktCapOf(row)), round(peOf(row), 2), round(pbOf(row), 2), round(multipleOf(row, "ps").value, 2), round(multipleOf(row, "roe").value, 2), round(multipleOf(row, "roa").value, 2), round(multipleOf(row, "net_margin").value, 2), round(multipleOf(row, "equity_assets").value, 2)].map(cell).join(sep));
    }

    // CRLF and the BOM: what Excel expects of a CSV on Windows, which is where these open.
    const blob = new Blob(["﻿" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8;"
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `uzse_${type || "all"}_${windowed ? changePeriod : (stats.boardDay || "").slice(0, 8) || "latest"}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };
  return {
    exportCsv
  };
}
