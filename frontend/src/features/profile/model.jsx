import { safeNumber } from "../../shared/format.jsx";

function profileScoreTone(score) {
  const value = safeNumber(score);
  if (value === null) return "neutral";
  if (value >= 70) return "positive";
  if (value < 50) return "negative";
  return "neutral";
}

function buildActivitySeries(entries, language) {
  const items = Array.isArray(entries) ? entries : [];
  const locale = language === "en" ? "en-US" : language === "uz" ? "uz-Latn-UZ" : "ru-RU";
  const dayMap = new Map();
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const keyFor = (date) =>
    [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");

  for (let offset = 13; offset >= 0; offset -= 1) {
    const date = new Date(now);
    date.setDate(now.getDate() - offset);
    const key = keyFor(date);
    dayMap.set(key, {
      key,
      label: new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(date),
      shortLabel: new Intl.DateTimeFormat(locale, { weekday: "short" }).format(date),
      count: 0,
      cached: 0,
      scoreTotal: 0,
      scoreCount: 0,
      avgScore: null,
    });
  }

  for (const item of items) {
    const createdAt = item?.created_at;
    if (!createdAt) continue;
    const date = new Date(createdAt);
    if (Number.isNaN(date.getTime())) continue;
    date.setHours(0, 0, 0, 0);
    const key = keyFor(date);
    const bucket = dayMap.get(key);
    if (!bucket) continue;
    bucket.count += 1;
    if (item?.from_cache) bucket.cached += 1;
    const score = safeNumber(item?.score ?? item?.summary?.score ?? item?.result?.summary?.score);
    if (score !== null) {
      bucket.scoreTotal += score;
      bucket.scoreCount += 1;
    }
  }

  const days = Array.from(dayMap.values()).map((day) => ({
    ...day,
    avgScore: day.scoreCount ? day.scoreTotal / day.scoreCount : null,
  }));
  const maxCount = Math.max(1, ...days.map((day) => day.count || 0));
  const maxCached = Math.max(1, ...days.map((day) => day.cached || 0));
  const total = days.reduce((sum, day) => sum + (day.count || 0), 0);
  const cachedTotal = days.reduce((sum, day) => sum + (day.cached || 0), 0);
  const scoreDays = days.filter((day) => day.avgScore !== null);
  const avgScore = scoreDays.length ? scoreDays.reduce((sum, day) => sum + day.avgScore, 0) / scoreDays.length : null;
  const peak = days.reduce((best, day) => (day.count > (best?.count || 0) ? day : best), days[0] || null);

  return { days, maxCount, maxCached, total, cachedTotal, avgScore, peak };
}

export { buildActivitySeries, profileScoreTone };
