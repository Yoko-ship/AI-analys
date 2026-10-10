import { roundedDisplayValue } from "../../lib/format.js";
import { changePeriodLabel } from "../../shared/marketPeriods.jsx";
import { avgSharePrice, avgTradeValue, marketDisplayPrice } from "../../shared/marketModel.jsx";
import { mt } from "../../shared/marketCopy.jsx";
import { marketRowDay } from "../../lib/valuation.js";
import { marketVolumeShare } from "../../lib/marketVolume.js";
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
  visibleOrder,
  LABEL_OF,
  smap,
  finOf,
  ratioOf,
  parOf,
  priceToPar,
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
    // The file carries exactly the columns the board shows, in the board's order
    // (frozen ones first): ticker and company, which cannot be hidden, then every
    // column the reader left switched on. A column switched off on screen is
    // absent from the file too.
    const EXPORT_OF = {
      last: row => round(marketDisplayPrice(row), 2),
      // Mirrors the cell: «нет сделок» on a 1D board is a blank, never a 0.
      change: row => changePeriod === "1d" ? row.tradedToday ? round(row.changePercent, 2) : "" : round(changeOver(row.ticker, changePeriod)?.pct, 2),
      change1w: row => round(changeOver(row.ticker, "1w")?.pct, 2),
      change1m: row => round(changeOver(row.ticker, "1m")?.pct, 2),
      nominal: row => round(parOf(row), 2),
      priceToPar: row => round(priceToPar(row), 2),
      open: row => round(row.openPrice !== null ? row.openPrice : marketDisplayPrice(row), 2),
      high: row => round(row.highPrice !== null ? row.highPrice : marketDisplayPrice(row), 2),
      low: row => round(row.lowPrice !== null ? row.lowPrice : marketDisplayPrice(row), 2),
      volume: row => money(row.stockVolume),
      volQty: row => row.stockQuantity,
      avgShare: row => round(Number.isFinite(row.avgPrice) ? row.avgPrice : avgSharePrice(row), 2),
      avgTrade: row => money(avgTradeValue(row)),
      bigTrade: row => money(row.ts?.largest_value),
      volShare: row => round(marketVolumeShare(row, stats), 2),
      finRevenue: row => money(finOf(row.ticker)?.revenue),
      finGross: row => money(finOf(row.ticker)?.gross_profit),
      finCash: row => money(finOf(row.ticker)?.cash),
      finLiab: row => money(finOf(row.ticker)?.total_liabilities),
      finNet: row => money(finOf(row.ticker)?.net_income),
      finOperating: row => money(finOf(row.ticker)?.operating_income),
      mktCap: row => money(mktCapOf(row)),
      pe: row => round(peOf(row), 2),
      pb: row => round(pbOf(row), 2),
      ps: row => round(multipleOf(row, "ps").value, 2),
      roe: row => round(multipleOf(row, "roe").value, 2),
      roa: row => round(multipleOf(row, "roa").value, 2),
      netMargin: row => round(multipleOf(row, "net_margin").value, 2),
      eqAssets: row => round(multipleOf(row, "equity_assets").value, 2),
      currentRatio: row => round(ratioOf(row.ticker)?.current_ratio, 2),
      quickRatio: row => round(ratioOf(row.ticker)?.quick_ratio, 2),
      debtAssets: row => round(ratioOf(row.ticker)?.debt_ratio, 1),
      assetTurnover: row => round(ratioOf(row.ticker)?.total_asset_turnover, 2),
      roce: row => round(ratioOf(row.ticker)?.return_to_capital_employed, 2),
      date: row => day(marketRowDay(row)),
      source: row => row.url || ""
    };
    // The screen prints «%» inside the cell; a spreadsheet cell holds the bare number,
    // so the unit moves to the heading.
    const PCT_COLS = new Set(["change", "change1w", "change1m", "volShare", "roe", "roa", "netMargin", "eqAssets", "debtAssets"]);
    const cols = visibleOrder.filter(k => EXPORT_OF[k]);
    const label = k => LABEL_OF[k] || k;
    const header = [mt(lang, "ticker"), mt(lang, "company"), ...cols.map(k => PCT_COLS.has(k) && !label(k).includes("%") ? `${label(k)}, %` : label(k))];
    lines.push(header.map(cell).join(sep));
    for (const row of visibleRows) {
      lines.push([row.ticker, row.name || smap[row.ticker]?.name || "", ...cols.map(k => EXPORT_OF[k](row))].map(cell).join(sep));
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
