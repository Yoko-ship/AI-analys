import { normalizeMarketDay } from "../lib/valuation.js";
import { safeNumber } from "../lib/numbers.js";
import sunset from "../assets/bozor-sunset.webp";

const formatNumber = new Intl.NumberFormat("ru-RU", {maximumFractionDigits: 10});
const number = value => formatNumber.format(value).replaceAll("\u00a0", " ");
const dateLabel = day => [day.slice(6), day.slice(4, 6), day.slice(0, 4)].join(".");

export function sessionPoster(stocks, statistics, securities) {
  // The exchange dates each security independently. A stale close or deal count
  // must never enter a newer day's ranking, even when the ticker is present in both.
  const shares = stocks.filter(row => row.ticker && row.type !== "bond");
  const day = shares.reduce((latest, row) => {
    const date = normalizeMarketDay(row.last_trade_date);
    return date > latest ? date : latest;
  }, normalizeMarketDay(statistics.trade_date) || "");
  if (!day || (statistics.validation?.partial && normalizeMarketDay(statistics.validation.trade_date) === day)) return null;
  const rows = [];
  for (const row of shares) {
    const stat = statistics.stats[row.isin];
    const figures = normalizeMarketDay(stat?.trade_date) === day ? stat : null;
    const quote = normalizeMarketDay(row.last_trade_date) === day ? row : null;
    const price = safeNumber(quote?.last_price) ?? safeNumber(figures?.close_price);
    if (!(price > 0)) continue;
    const issuer = securities[row.ticker];
    rows.push({
      ticker: row.ticker, name: issuer?.company_name || row.name || row.ticker,
      logo: issuer?.logo_url, price,
      turnover: safeNumber(figures?.total_value) ?? safeNumber(quote?.volume),
      trades: safeNumber(figures?.trade_count) ?? safeNumber(quote?.trade_count),
    });
  }
  const leaders = metric => rows.filter(row => row[metric] > 0)
    .sort((a, b) => b[metric] - a[metric] || a.ticker.localeCompare(b.ticker)).slice(0, 3);
  const turnover = leaders("turnover"), trades = leaders("trades");
  return turnover.length && trades.length ? {day, turnover, trades} : null;
}

export function posterCaption({day, turnover, trades}, edition) {
  const uz = edition === "uz";
  const [valueLeader] = turnover, [tradeLeader] = trades;
  const lead = uz
    ? `${valueLeader.ticker} savdo aylanmasi bo‘yicha yetakchi — ${number(valueLeader.turnover)} so‘m. Eng ko‘p bitim ${tradeLeader.ticker} aksiyalarida tuzildi — ${number(tradeLeader.trades)} ta.`
    : `${valueLeader.ticker} лидирует по обороту — ${number(valueLeader.turnover)} сум. Больше всего сделок с акциями ${tradeLeader.ticker} — ${number(tradeLeader.trades)}.`;
  return `${uz ? "Bozor sharhi" : "Обзор рынка"} · ${dateLabel(day)}\n\n${lead}\n\nhttps://uzstock.uz/${uz ? "uz/" : ""}market?utm_source=telegram&utm_medium=social&utm_campaign=bozor-sharhi-${day}-${edition}`;
}

async function loadImage(url) {
  const img = new Image();
  img.src = url;
  await img.decode();
  return img;
}

export async function posterAssets(poster) {
  const urls = new Set([...poster.turnover, ...poster.trades].map(row => row.logo).filter(url => url?.startsWith("/logos/")));
  const [background, logos] = await Promise.all([
    loadImage(sunset),
    Promise.all(Array.from(urls, async url => [url, await loadImage(url).catch(() => null)])),
    document.fonts.load('48px "Poster Anton"'),
    document.fonts.load('700 72px "Poster Caveat"'),
    document.fonts.load('700 36px "Poster Manrope"'),
  ]);
  return {background, logos: new Map(logos)};
}

function box(ctx, x, y, w, h, radius, color) {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, radius);
  ctx.fill();
}

function label(ctx, text, x, y, font, color, align = "left", maxWidth) {
  ctx.font = font;
  ctx.fillStyle = color;
  ctx.textAlign = align;
  if (maxWidth && ctx.measureText(text).width > maxWidth) {
    let trimmed = text;
    while (trimmed && ctx.measureText(trimmed + "…").width > maxWidth) trimmed = trimmed.slice(0, -1);
    text = trimmed.trimEnd() + "…";
  }
  ctx.fillText(text, x, y);
}

function rankingPanel(ctx, y, rows, metric, uz, logos) {
  const byValue = metric === "turnover";
  const name = byValue ? (uz ? "Savdo aylanmasi" : "Оборот торгов") : (uz ? "Bitimlar soni" : "Количество сделок");
  const suffix = byValue ? (uz ? "so‘m" : "сум") : (uz ? "ta" : "");
  box(ctx, 56, y, 968, 402, 32, "rgba(24, 13, 37, 0.90)");
  label(ctx, name, 96, y + 68, '43px "Poster Anton"', "#fff6ee");
  label(ctx, "TOP " + rows.length, 982, y + 66, '700 27px "Poster Manrope"', "#ffa6c6", "right");
  rows.forEach((row, index) => {
    const top = y + 97 + index * 97;
    ctx.fillStyle = "rgba(255,231,243,.17)";
    ctx.fillRect(96, top - 9, 888, 1.5);
    box(ctx, 96, top + 5, 66, 66, 15, "#fff8f3");
    const logo = logos.get(row.logo);
    if (logo) {
      const scale = 50 / Math.max(logo.naturalWidth, logo.naturalHeight);
      const w = logo.naturalWidth * scale, h = logo.naturalHeight * scale;
      ctx.drawImage(logo, 129 - w / 2, top + 38 - h / 2, w, h);
    } else label(ctx, row.ticker.slice(0, 2), 129, top + 49, '31px "Poster Anton"', "#4c2048", "center");
    label(ctx, row.name, 183, top + 34, '700 33px "Poster Manrope"', "#fff8f2", "left", 442);
    label(ctx, row.ticker, 185, top + 68, '700 24px "Poster Manrope"', "#e4b6cf");
    label(ctx, (number(row[metric]) + " " + suffix).trim(), 983, top + 36, '34px "Poster Anton"', "#fff6ed", "right");
    label(ctx, (uz ? "Narx" : "Цена") + " · " + number(row.price) + " UZS", 983, top + 69,
      '700 23px "Poster Manrope"', "#e4b6cf", "right");
  });
}

export function drawPoster(canvas, poster, {background, logos}, edition) {
  const ctx = canvas.getContext("2d"), uz = edition === "uz";
  ctx.drawImage(background, 0, 0, 1080, 1350);
  ctx.fillStyle = "rgba(23,5,38,.18)";
  ctx.fillRect(0, 0, 1080, 1350);
  label(ctx, "UZStock", 60, 93, '52px "Poster Anton"', "#fff5ec");
  label(ctx, dateLabel(poster.day), 1018, 87, '700 35px "Poster Manrope"', "#fff5ec", "right");
  ctx.font = '137px "Poster Anton"';
  ctx.textAlign = "center";
  ctx.lineJoin = "round";
  ctx.lineWidth = 10;
  ctx.strokeStyle = "#211025";
  ctx.strokeText("BOZOR SHARHI", 540, 277);
  ctx.fillStyle = "#fff2de";
  ctx.fillText("BOZOR SHARHI", 540, 277);
  ctx.save();
  ctx.translate(540, 340);
  ctx.rotate(-0.04);
  ctx.shadowColor = "#200923";
  ctx.shadowBlur = 7;
  ctx.shadowOffsetY = 4;
  label(ctx, uz ? "Kunlik bozor sharhi" : "Ежедневный обзор рынка", 0, 0, '700 75px "Poster Caveat"', "#ff91be", "center");
  ctx.restore();
  rankingPanel(ctx, 405, poster.turnover, "turnover", uz, logos);
  rankingPanel(ctx, 836, poster.trades, "trades", uz, logos);
  box(ctx, 414, 1272, 252, 47, 23, "rgba(24,13,37,.85)");
  label(ctx, "uzstock.uz/market", 540, 1305, '700 24px "Poster Manrope"', "#fff5ef", "center");
}
