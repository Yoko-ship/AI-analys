

export function relativeVolume(daily, date, turnover) {
  if (!(turnover > 0)) return null;
  const i = daily.findIndex((p) => p.date === date);
  if (i < 0) return null;
  let sum = 0, n = 0;
  for (let j = i - 1; j >= 0 && n < 20; j--) {
    if (daily[j].turnover > 0) { sum += daily[j].turnover; n += 1; }
  }
  return n >= 3 ? turnover / (sum / n) : null;
}

export function peerVolumeAt(volHist, date) {
  const d = String(date);
  const e = (volHist || []).find((p) => p.date === d);
  if (!e || !(e.turnover > 0)) return null;
  return { turnover: e.turnover, rel: relativeVolume(volHist, d, e.turnover) };
}

export function fmtRelVol(v, lang) {
  return `×${v.toFixed(1).replace(".", lang === "en" ? "." : ",")}`;
}
