import { formatRatio, safeNumber } from "./format.jsx";
import { normalizeLanguage } from "./i18n.jsx";

const SCORE_EXPLANATION_TEXTS = {
  ru: {
    ranges: {
      A: "сильный диапазон 80-100",
      B: "хороший диапазон 60-79",
      C: "средний диапазон 40-59",
      D: "слабый диапазон ниже 40",
    },
    inputs: "Влияют",
    trend: "тренд",
    momentum: "импульс",
    dcf: "DCF",
    industry: "отрасль",
    liquidity: "ликвидность",
    noFactors: "Недостаточно сильных сигналов, чтобы поднять компанию выше текущего класса",
    advice: {
      A: "Финансовое состояние выглядит сильным.",
      B: "До A нужны еще более устойчивые рост и прибыльность.",
      C: "До B нужны сильнее рост, прибыльность и устойчивость баланса.",
      D: "Нужны заметное улучшение прибыли, ликвидности и долговой нагрузки.",
    },
    signals: { bullish: "положительный", neutral: "нейтральный", bearish: "негативный" },
  },
  en: {
    ranges: {
      A: "strong 80-100 range",
      B: "good 60-79 range",
      C: "middle 40-59 range",
      D: "weak range below 40",
    },
    inputs: "Drivers",
    trend: "trend",
    momentum: "momentum",
    dcf: "DCF",
    industry: "industry",
    liquidity: "liquidity",
    noFactors: "There are not enough strong signals to lift the company above this class",
    advice: {
      A: "Financial condition looks strong.",
      B: "A needs more consistent growth and profitability.",
      C: "B needs stronger growth, profitability, and balance-sheet stability.",
      D: "Profit, liquidity, and debt load need clear improvement.",
    },
    signals: { bullish: "positive", neutral: "neutral", bearish: "negative" },
  },
  uz: {
    ranges: {
      A: "kuchli 80-100 oralig'i",
      B: "yaxshi 60-79 oralig'i",
      C: "o'rtacha 40-59 oralig'i",
      D: "40 dan past zaif oralig'i",
    },
    inputs: "Ta'sir qilganlar",
    trend: "trend",
    momentum: "impuls",
    dcf: "DCF",
    industry: "sektor",
    liquidity: "likvidlik",
    noFactors: "Kompaniyani hozirgi sinfdan yuqoriga olib chiqadigan kuchli signallar yetarli emas",
    advice: {
      A: "Moliyaviy holat kuchli ko'rinadi.",
      B: "A uchun o'sish va rentabellik yanada barqaror bo'lishi kerak.",
      C: "B uchun o'sish, rentabellik va balans barqarorligi kuchliroq bo'lishi kerak.",
      D: "Foyda, likvidlik va qarz yuki aniq yaxshilanishi kerak.",
    },
    signals: { bullish: "ijobiy", neutral: "neytral", bearish: "salbiy" },
  },
};

function scoreGradeCode(score) {
  const value = safeNumber(score);
  if (value === null) return null;
  if (value >= 80) return "A";
  if (value >= 60) return "B";
  if (value >= 40) return "C";
  return "D";
}

function buildScoreExplanation(total = {}, metrics = {}, language = "ru") {
  const lang = normalizeLanguage(language);
  const text = SCORE_EXPLANATION_TEXTS[lang] || SCORE_EXPLANATION_TEXTS.ru;
  const score = safeNumber(total?.score);
  const code = scoreGradeCode(score) || String(total?.grade || "").trim().slice(0, 1).toUpperCase();
  if (!["A", "B", "C", "D"].includes(code)) return "";
  const gradeCode = code;
  const factors = [];

  const trends = metrics?.trends || {};
  const trendScore = safeNumber(trends.overall_score);
  if (trendScore !== null) factors.push(`${text.trend} ${formatRatio(trendScore, 0, lang)}/12`);

  const momentum = metrics?.momentum || {};
  const momentumScore = safeNumber(momentum.overall_score);
  if (momentumScore !== null) {
    factors.push(`${text.momentum} ${formatRatio(momentumScore, 0, lang)}`);
  } else if (momentum.css) {
    factors.push(`${text.momentum} ${text.signals[momentum.css] || momentum.css}`);
  }

  const dcfSignal = metrics?.dcf?.signal;
  if (dcfSignal) factors.push(`${text.dcf} ${text.signals[dcfSignal] || dcfSignal}`);

  const industry = metrics?.industry || {};
  if (industry.good_count !== undefined || industry.weak_count !== undefined) {
    factors.push(`${text.industry} +${industry.good_count ?? 0}/-${industry.weak_count ?? 0}`);
  }

  const liquidityDays = metrics?.market_liquidity?.trade_days;
  if (liquidityDays !== undefined && liquidityDays !== null) {
    factors.push(`${text.liquidity} ${liquidityDays}/30`);
  }

  const range = text.ranges[gradeCode] || text.ranges.C;
  const factorText = factors.length ? `${text.inputs}: ${factors.slice(0, 3).join("; ")}.` : `${text.noFactors}.`;
  return `${gradeCode}: ${range}. ${factorText} ${text.advice[gradeCode] || text.advice.C}`;
}

export {  };
