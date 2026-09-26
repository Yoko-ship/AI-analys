import { roundedDisplayValue } from "../../lib/format.js";
export function newsPeriod(item, language) {
  if (item.year == null) return "";
  if (item.quarter && item.quarter > 0) {
    return language === "en" ? `Q${item.quarter} ${item.year}` : language === "uz" ? `${item.year} ${item.quarter}-chorak` : `${item.quarter} кв. ${item.year}`;
  }
  return language === "en" ? `FY ${item.year}` : language === "uz" ? `${item.year}-yil` : `${item.year} год`;
}
export function newsHeadline(item, language, tx) {
  const company = item.company || item.ticker || "";
  if (item.type === "listing") {
    const suffix = item.ticker ? ` (${item.ticker})` : "";
    return language === "en" ? `New listing: ${company}${suffix}` : language === "uz" ? `Yangi listing: ${company}${suffix}` : `Новый листинг: ${company}${suffix}`;
  }
  if (item.type === "delisting") {
    return language === "en" ? `${company} drops off active trading` : language === "uz" ? `${company} faol savdodan chiqdi` : `${company}: нет активных торгов`;
  }
  const form = item.report_form && tx.forms[item.report_form] || item.report_form || "";
  const period = newsPeriod(item, language);
  if (language === "en") return `${company} files ${form} report${period ? ` for ${period}` : ""}`.replace(/\s+/g, " ").trim();
  if (language === "uz") return `${company} ${form} hisobotini e'lon qildi${period ? ` (${period})` : ""}`.replace(/\s+/g, " ").trim();
  return `${company}: раскрыт отчёт ${form}${period ? ` за ${period}` : ""}`.replace(/\s+/g, " ").trim();
}
export function newsDek(item, language) {
  if (item.type === "listing") {
    return language === "en" ? "Newly admitted to trading on the exchange." : language === "uz" ? "Birjada savdoga yangi kiritildi." : "Новая бумага допущена к торгам на бирже.";
  }
  if (item.type === "delisting") {
    return language === "en" ? "No recent trades — a possible delisting." : language === "uz" ? "So'nggi savdolar yo'q — delisting ehtimoli." : "Давно нет сделок — возможен делистинг.";
  }
  return language === "en" ? "Financial statements disclosed on the exchange." : language === "uz" ? "Moliyaviy hisobot birjada e'lon qilindi." : "Финансовая отчётность раскрыта на бирже.";
}
export const _TONE_CLS = {
  positive: "pos",
  negative: "neg",
  neutral: "neu"
};
export function feedSentiment(items) {
  const counts = {
    positive: 0,
    neutral: 0,
    negative: 0
  };
  let sum = 0,
    n = 0;
  for (const it of items) {
    if (it.tone && counts[it.tone] != null) counts[it.tone] += 1;
    if (typeof it.tone_score === "number") {
      sum += it.tone_score;
      n += 1;
    }
  }
  const avg = n ? sum / n : 0;
  return {
    avg,
    counts,
    pct: roundedDisplayValue((avg + 1) / 2 * 100),
    cls: avg > 0.15 ? "pos" : avg < -0.15 ? "neg" : "neu"
  };
}
export function edSummary(item, language) {
  if (!item) return "";
  return (item[`summary_${language}`] || "").trim() || (item.summary_ru || "").trim() || (item.lang === language ? (item.snippet || "").trim() : "");
}
export function edDetail(item, language) {
  if (!item) return [];
  const text = (item[`detail_${language}`] || "").trim() || (item.detail_ru || "").trim();
  return text ? text.split(/\n\s*\n/).map(p => p.trim()).filter(Boolean) : [];
}
export function newsAbsTime(dateStr, language) {
  if (!dateStr) return "";
  const raw = String(dateStr).replace(" ", "T");
  const d = new Date(raw);
  if (isNaN(d.getTime())) return String(dateStr);
  const loc = language === "en" ? "en-US" : language === "uz" ? "uz-UZ" : "ru-RU";
  const opts = {
    day: "numeric",
    month: "long",
    year: "numeric"
  };
  if (raw.length > 10) {
    opts.hour = "2-digit";
    opts.minute = "2-digit";
  }
  return d.toLocaleString(loc, opts);
}
export function newsHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
export function newsAddsDetail(snippet, summary) {
  const words = s => new Set((String(s || "").toLowerCase().match(/[\wЀ-ӿ]+/g) || []).filter(w => w.length > 3));
  const lead = words(snippet);
  if (lead.size < 4) return false;
  const ours = words(summary);
  let shared = 0;
  lead.forEach(w => {
    if (ours.has(w)) shared += 1;
  });
  return shared / lead.size < 0.7;
}
export function newsShortDay(dateStr, language) {
  if (!dateStr) return "";
  const d = new Date(String(dateStr).replace(" ", "T"));
  if (isNaN(d.getTime())) return String(dateStr);
  const loc = language === "en" ? "en-US" : language === "uz" ? "uz-UZ" : "ru-RU";
  return d.toLocaleDateString(loc, {
    day: "numeric",
    month: "short"
  });
}
