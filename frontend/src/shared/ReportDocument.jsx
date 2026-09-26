import { t } from "./i18n.jsx";
import { Suspense } from "react";
import { VerifiedReport } from "./VerifiedReport.jsx";

function getSectionTitle(language, key) {
  return t(language, `sections.${key}`) || key.replaceAll("_", " ");
}

// 14 разделов из _analysis_prompt_v2 в analysis_service.py (public-information-v4-bank-aware-2026-05-27).
// Эти разделы выводятся сверху в строго заданном порядке, остальные — под катом «Дополнительно».
const PRIMARY_SECTIONS = [
  "СКОРИНГ",
  "ДОСЬЕ",
  "ЧТО_С_ДЕНЬГАМИ",
  "ТРЕНД",
  "ЭФФЕКТИВНОСТЬ",
  "ТЕХНИЧЕСКИЙ_АНАЛИЗ",
  "ОЦЕНКА_ЦЕНЫ",
  "КАТАЛИЗАТОРЫ",
  "СИЛЬНЫЕ_СТОРОНЫ",
  "СЛАБЫЕ_СТОРОНЫ",
  "РЫНОЧНЫЕ_ДАННЫЕ",
  "ВЕРДИКТ",
  "ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА",
  "ИТОГ",
];

function splitSections(sections) {
  const sourceEntries = sections ? Object.entries(sections) : [];
  const lookup = new Map(sourceEntries);
  const primary = [];
  const seen = new Set();
  for (const key of PRIMARY_SECTIONS) {
    if (lookup.has(key)) {
      primary.push([key, lookup.get(key)]);
      seen.add(key);
    }
  }
  const supplementary = sourceEntries.filter(([key]) => !seen.has(key));
  return { primary, supplementary };
}

const SECTION_LABELS = {
  ru: "РАЗДЕЛ",
  en: "SECTION",
  uz: "BO'LIM",
};

const SUPPLEMENTARY_LABELS = {
  ru: "ПРИЛОЖЕНИЕ",
  en: "APPENDIX",
  uz: "ILOVA",
};

// Subheaders we want to bold: any uppercase phrase (4-60 chars) ending with ":"
// covers RU/EN/UZ ("ЛИКВИДНОСТЬ:", "LIQUIDITY:", "LIKVIDLIK:") in one rule.
const UPPER_SUBHEADER_RE = /^[A-ZА-ЯЁЎҚҒҲ][A-ZА-ЯЁЎҚҒҲ0-9\s,'’\-/()&]{2,58}:\s*$/u;

// KV pair: short label, then value that *starts with a number or sign* — keeps
// real metric lines ("ROE: 15.2%") and rejects normal prose ("Главное: банк…").
const KV_LABEL_MAX = 40;

const KV_VALUE_NUMERIC_RE = /^\s*[+\-−]?\s*[\d(]/;

const TLDR_HEADER_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]?\s*$/i;

const TLDR_INLINE_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]\s*(.+)$/i;

const TLDR_STARTS_RE = /^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\b/i;

const TLDR_STRUCTURED_HINT_RE = /\b(?:Тон|Tone|Плюсы|Минусы|Pluses|Minuses|Strengths|Concerns|Score|Скор|Для\s+тебя|For\s+you|Bu\s+siz)\s*[-:：—]/i;

const TLDR_TONE_LABEL_RE = /^\s*Тон\s*[-:：—]\s*(.+)$/i;

const TLDR_SCORE_LABEL_RE = /^\s*Скор\s*[-:：—]\s*(.+)$/i;

const TLDR_PLUSES_LABEL_RE = /^\s*Плюсы\s*[-:：—]?\s*$/i;

const TLDR_MINUSES_LABEL_RE = /^\s*Минусы\s*[-:：—]?\s*$/i;

const TLDR_FORYOU_LABEL_RE = /^\s*Для\s+тебя\s*[-:：—]\s*(.+)$/i;

const TLDR_BULLET_RE = /^\s*[-•—]\s+(.+)$/;

const TLDR_TONE_KEYS = {
  позитивный: "positive",
  positive: "positive",
  ijobiy: "positive",
  умеренный: "neutral",
  умеренная: "neutral",
  neutral: "neutral",
  mixed: "neutral",
  смешанный: "neutral",
  o_rtacha: "neutral",
  "o'rtacha": "neutral",
  тревожный: "caution",
  тревожная: "caution",
  осторожно: "caution",
  caution: "caution",
  warning: "caution",
  ehtiyot: "caution",
  критичный: "critical",
  критическая: "critical",
  critical: "critical",
  негативный: "critical",
  негативная: "critical",
  tanqidiy: "critical",
  нет_данных: "unknown",
  unknown: "unknown",
  insufficient: "unknown",
  "ma'lumot_yo'q": "unknown",
};

function normalizeToneKey(raw) {
  if (!raw) return "unknown";
  const clean = String(raw)
    .toLowerCase()
    .replace(/[.,;!?].*$/, "")
    .replace(/\s+/g, "_")
    .trim();
  return TLDR_TONE_KEYS[clean] || TLDR_TONE_KEYS[clean.replace(/_.*$/, "")] || "neutral";
}

function splitInlineBullets(text) {
  if (!text) return [];
  const cleaned = text.replace(/^[-•—]\s*/, "");
  return cleaned
    .split(/\s+[-•—]\s+/)
    .map((s) => s.replace(/[\s.;,]+$/, "").trim())
    .filter(Boolean);
}

function parseInlineTldr(rawText) {
  if (!rawText) return null;
  const text = rawText.replace(/^\s*(?:>\s*)?(?:TL;?DR|КРАТКО|Кратко|Brief|Qisqacha)\s*[-:：—]?\s*/i, "").trim();
  if (!text) return null;

  const tldr = {
    tone: "neutral",
    toneRaw: null,
    score: null,
    pluses: [],
    minuses: [],
    forYou: null,
    summary: null,
  };

  const labelOrder = [
    { key: "tone", re: /Тон\s*[-:：—]\s*/i },
    { key: "score", re: /Скор\s*[-:：—]\s*/i },
    { key: "pluses", re: /Плюсы\s*[-:：—]\s*/i },
    { key: "minuses", re: /Минусы\s*[-:：—]\s*/i },
    { key: "forYou", re: /Для\s+тебя\s*[-:：—]\s*/i },
  ];

  const matches = [];
  for (const { key, re } of labelOrder) {
    const m = text.match(re);
    if (m && m.index !== undefined) {
      matches.push({ key, start: m.index, valueStart: m.index + m[0].length });
    }
  }
  if (!matches.length) {
    tldr.summary = text;
    return tldr;
  }
  matches.sort((a, b) => a.start - b.start);

  if (matches[0].start > 0) {
    const head = text.slice(0, matches[0].start).trim();
    if (head) tldr.summary = head;
  }

  for (let i = 0; i < matches.length; i++) {
    const current = matches[i];
    const end = i + 1 < matches.length ? matches[i + 1].start : text.length;
    const value = text.slice(current.valueStart, end).trim();
    if (!value) continue;
    if (current.key === "tone") {
      tldr.toneRaw = value;
      tldr.tone = normalizeToneKey(value);
    } else if (current.key === "score") {
      tldr.score = value;
    } else if (current.key === "pluses") {
      tldr.pluses = splitInlineBullets(value);
    } else if (current.key === "minuses") {
      tldr.minuses = splitInlineBullets(value);
    } else if (current.key === "forYou") {
      // The "Для тебя" value is the LAST inline label, so when the model crams
      // an entire section onto one line it greedily swallows the trailing hero
      // paragraph ("Статус: ... Причина — ..."). Cut it off so "Для тебя" stays
      // a short phrase and the rest renders as normal section text.
      const heroCut = value.search(/(?:Статус|Вывод|Итог|Резюме|Заключение)\s*[:：]/i);
      if (heroCut > 0) {
        tldr.forYou = value.slice(0, heroCut).trim();
        tldr.trailing = value.slice(heroCut).trim();
      } else {
        tldr.forYou = value;
      }
    }
  }

  return tldr;
}

function parseTldrBlock(body) {
  if (!body) return { tldr: null, rest: body };
  const lines = body.split("\n");

  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (!trimmed) continue;
    if (!TLDR_STARTS_RE.test(trimmed)) return { tldr: null, rest: body };
    start = i;
    break;
  }
  if (start === -1) return { tldr: null, rest: body };

  const firstLine = lines[start].trim();
  const firstLineHasStructuredHint = TLDR_STRUCTURED_HINT_RE.test(firstLine);

  // CASE A: LLM emitted TL;DR as a single dense line with inline labels
  // ("TL;DR Тон: ... Плюсы: - ... Минусы: - ... Для тебя: ...").
  // Consume the whole TL;DR header line and parse it inline.
  if (firstLineHasStructuredHint) {
    const tldr = parseInlineTldr(firstLine);
    if (tldr && (tldr.pluses.length || tldr.minuses.length || tldr.forYou || tldr.toneRaw || tldr.summary)) {
      let rest = lines.slice(0, start).concat(lines.slice(start + 1)).join("\n").replace(/^\s+|\s+$/g, "");
      if (tldr.trailing) {
        rest = `${tldr.trailing}\n\n${rest}`.replace(/^\s+|\s+$/g, "");
        delete tldr.trailing;
      }
      return { tldr, rest };
    }
  }

  // CASE B: classic multiline structured block.
  let headerLines = 1;
  let inlineSummary = null;
  const inlineMatch = firstLine.match(TLDR_INLINE_RE);
  if (inlineMatch) {
    inlineSummary = inlineMatch[1].trim();
  }

  const tldr = {
    tone: "neutral",
    toneRaw: null,
    score: null,
    pluses: [],
    minuses: [],
    forYou: null,
    summary: inlineSummary,
  };

  let cursor = start + headerLines;
  let activeList = null;
  let consumed = cursor;

  while (cursor < lines.length) {
    const trimmed = lines[cursor].trim();
    if (!trimmed) {
      cursor += 1;
      consumed = cursor;
      continue;
    }

    let matched = false;

    const tone = trimmed.match(TLDR_TONE_LABEL_RE);
    if (tone) {
      tldr.toneRaw = tone[1].trim();
      tldr.tone = normalizeToneKey(tone[1]);
      activeList = null;
      matched = true;
    }

    const score = !matched && trimmed.match(TLDR_SCORE_LABEL_RE);
    if (score) {
      tldr.score = score[1].trim();
      activeList = null;
      matched = true;
    }

    if (!matched && TLDR_PLUSES_LABEL_RE.test(trimmed)) {
      activeList = "pluses";
      matched = true;
    }
    if (!matched && TLDR_MINUSES_LABEL_RE.test(trimmed)) {
      activeList = "minuses";
      matched = true;
    }

    const forYou = !matched && trimmed.match(TLDR_FORYOU_LABEL_RE);
    if (forYou) {
      tldr.forYou = forYou[1].trim();
      activeList = null;
      matched = true;
    }

    const bullet = !matched && trimmed.match(TLDR_BULLET_RE);
    if (bullet && activeList) {
      tldr[activeList].push(bullet[1].trim());
      matched = true;
    }

    if (!matched) break;

    cursor += 1;
    consumed = cursor;
  }

  if (!tldr.pluses.length && !tldr.minuses.length && !tldr.forYou && !tldr.toneRaw && !tldr.summary) {
    // Last-resort: parse the first paragraph as inline.
    const fallback = parseInlineTldr(firstLine);
    if (fallback) {
      let rest = lines.slice(0, start).concat(lines.slice(start + 1)).join("\n").replace(/^\s+|\s+$/g, "");
      if (fallback.trailing) {
        rest = `${fallback.trailing}\n\n${rest}`.replace(/^\s+|\s+$/g, "");
        delete fallback.trailing;
      }
      return { tldr: fallback, rest };
    }
    return { tldr: null, rest: body };
  }

  const rest = lines.slice(0, start).concat(lines.slice(consumed)).join("\n").replace(/^\s+|\s+$/g, "");
  return { tldr, rest };
}

function tldrCardTitle(language, tone) {
  const dict = {
    ru: {
      positive: "Сильная сторона",
      neutral: "Смешанная картина",
      caution: "Требует внимания",
      critical: "Повышенный риск",
      unknown: "Недостаточно данных",
    },
    en: {
      positive: "Strong signal",
      neutral: "Mixed picture",
      caution: "Watch closely",
      critical: "Elevated risk",
      unknown: "Insufficient data",
    },
    uz: {
      positive: "Kuchli tomon",
      neutral: "Aralash holat",
      caution: "Diqqat talab qiladi",
      critical: "Yuqori xavf",
      unknown: "Ma'lumot yetarli emas",
    },
  };
  return dict[language]?.[tone] || dict.ru[tone] || dict.ru.neutral;
}

const TONE_ICONS = {
  positive: "✓",
  neutral: "~",
  caution: "⚠",
  critical: "✗",
  unknown: "?",
};

function TldrCard({ tldr, language = "ru", variant = "default" }) {
  if (!tldr) return null;
  const hasPluses = tldr.pluses?.length > 0;
  const hasMinuses = tldr.minuses?.length > 0;
  const labels = {
    ru: { pluses: "Плюсы", minuses: "Минусы", forYou: "Что это значит для тебя" },
    en: { pluses: "Strengths", minuses: "Concerns", forYou: "What this means for you" },
    uz: { pluses: "Kuchli tomonlar", minuses: "Zaif tomonlar", forYou: "Bu siz uchun nimani anglatadi" },
  }[language] || {
    ru: { pluses: "Плюсы", minuses: "Минусы", forYou: "Что это значит для тебя" },
  }.ru;

  return (
    <div className={`tldr-card tldr-card--${tldr.tone} tldr-card--${variant}`}>
      <div className="tldr-card__head">
        <span className="tldr-card__tone-icon" aria-hidden="true">{TONE_ICONS[tldr.tone] || "~"}</span>
        <span className="tldr-card__tone-label">{tldrCardTitle(language, tldr.tone)}</span>
        {/* Numeric score removed for ТЗ compliance (2026-07-09). */}
      </div>
      {tldr.summary && <p className="tldr-card__summary">{tldr.summary}</p>}
      <div className="tldr-card__body">
        {hasPluses && (
          <div className="tldr-card__col tldr-card__col--pos">
            <div className="tldr-card__col-label">{labels.pluses}</div>
            <ul>
              {tldr.pluses.map((item, idx) => <li key={`p-${idx}`}>{item}</li>)}
            </ul>
          </div>
        )}
        {hasMinuses && (
          <div className="tldr-card__col tldr-card__col--neg">
            <div className="tldr-card__col-label">{labels.minuses}</div>
            <ul>
              {tldr.minuses.map((item, idx) => <li key={`m-${idx}`}>{item}</li>)}
            </ul>
          </div>
        )}
      </div>
      {tldr.forYou && (
        <div className="tldr-card__foryou">
          <span className="tldr-card__foryou-label">{labels.forYou}:</span>
          <span className="tldr-card__foryou-text">{tldr.forYou}</span>
        </div>
      )}
    </div>
  );
}

function pickFirstParagraph(text) {
  if (!text) return null;
  const blocks = text.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
  if (!blocks.length) return null;
  return blocks[0]
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .join(" ");
}

function HeroVerdictBlock({ analysisResult, language = "ru" }) {
  if (!analysisResult?.sections) return null;
  const scoringRaw = analysisResult.sections["СКОРИНГ"];
  const summaryRaw =
    analysisResult.sections["ИТОГ"] ||
    analysisResult.sections["ВЕРДИКТ"] ||
    null;
  if (!scoringRaw && !summaryRaw) return null;

  const { tldr: scoringTldr } = parseTldrBlock(scoringRaw || "");
  const { tldr: summaryTldr, rest: summaryRest } = parseTldrBlock(summaryRaw || "");
  const heroParagraph = pickFirstParagraph(summaryRest);

  const tone = scoringTldr?.tone || summaryTldr?.tone || "neutral";
  const score = scoringTldr?.score || null;
  const verdictTitle = tldrCardTitle(language, tone);
  const pluses = scoringTldr?.pluses?.length ? scoringTldr.pluses : summaryTldr?.pluses || [];
  const minuses = scoringTldr?.minuses?.length ? scoringTldr.minuses : summaryTldr?.minuses || [];
  const forYou = summaryTldr?.forYou || scoringTldr?.forYou || null;

  const headline = {
    ru: { lead: "Что показывает отчётность", pluses: "Главные плюсы", minuses: "Главные минусы", paragraph: "Простыми словами" },
    en: { lead: "What the report shows", pluses: "Key positives", minuses: "Key concerns", paragraph: "In plain language" },
    uz: { lead: "Hisobotda nima ko'rinmoqda", pluses: "Asosiy ijobiy tomonlar", minuses: "Asosiy salbiy tomonlar", paragraph: "Sodda til bilan" },
  }[language] || {
    lead: "Что показывает отчётность", pluses: "Главные плюсы", minuses: "Главные минусы", paragraph: "Простыми словами",
  };

  return (
    <article className={`hero-verdict hero-verdict--${tone}`}>
      <div className="hero-verdict__crown">
        <span className="hero-verdict__crown-label">{headline.lead}</span>
        {/* Composite attractiveness score removed for ТЗ compliance (2026-07-09). */}
      </div>
      <div className="hero-verdict__headline">
        <span className="hero-verdict__icon" aria-hidden="true">{TONE_ICONS[tone] || "~"}</span>
        <h2 className="hero-verdict__title">{verdictTitle}</h2>
      </div>
      {(pluses.length > 0 || minuses.length > 0) && (
        <div className="hero-verdict__grid">
          {pluses.length > 0 && (
            <div className="hero-verdict__col hero-verdict__col--pos">
              <div className="hero-verdict__col-label">{headline.pluses}</div>
              <ul>
                {pluses.slice(0, 3).map((item, idx) => <li key={`hp-${idx}`}>{item}</li>)}
              </ul>
            </div>
          )}
          {minuses.length > 0 && (
            <div className="hero-verdict__col hero-verdict__col--neg">
              <div className="hero-verdict__col-label">{headline.minuses}</div>
              <ul>
                {minuses.slice(0, 3).map((item, idx) => <li key={`hm-${idx}`}>{item}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
      {heroParagraph && (
        <div className="hero-verdict__paragraph">
          <div className="hero-verdict__paragraph-label">{headline.paragraph}</div>
          <p>{heroParagraph}</p>
        </div>
      )}
      {!heroParagraph && forYou && (
        <div className="hero-verdict__paragraph">
          <div className="hero-verdict__paragraph-label">{headline.paragraph}</div>
          <p>{forYou}</p>
        </div>
      )}
    </article>
  );
}

function renderAnalysisContent(text, { keyPrefix = "analysis" } = {}) {
  if (!text) return null;
  const lines = text.split('\n');
  const elements = [];
  let tableBuffer = [];
  let inTable = false;
  let proseBuffer = [];

  const tableCaptionRe = /^(?:таблица|table|jadval)\b/i;

  const flushProse = () => {
    if (!proseBuffer.length) return;
    elements.push(
      <section key={`${keyPrefix}-detail-${elements.length}`} className="analysis-sector analysis-sector--detail">
        {proseBuffer.map(({ key, text: paragraph }) => (
          <p key={key} className="analysis-para">{paragraph}</p>
        ))}
      </section>
    );
    proseBuffer = [];
  };

  const popTableCaption = () => {
    if (!proseBuffer.length) return null;
    const last = proseBuffer[proseBuffer.length - 1].text.trim();
    if (!tableCaptionRe.test(last)) return null;
    proseBuffer = proseBuffer.slice(0, -1);
    return last;
  };

  const flushTable = () => {
    if (tableBuffer.length > 0) {
      const caption = popTableCaption();
      flushProse();
      const headers = tableBuffer[0].split('|').filter(c => c.trim()).map(c => c.trim());
      const rows = tableBuffer.slice(2).filter(row => !row.match(/^\|[-\s|]+\|$/));
      elements.push(
        <section key={`${keyPrefix}-table-${elements.length}`} className="analysis-sector analysis-sector--table">
          {caption && <div className="analysis-sector__caption">{caption}</div>}
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead>
                <tr>{headers.map((h, i) => <th key={i}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri} className={row.includes('ИТОГО') || row.includes('Итого') ? 'total-row' : ''}>
                    {row.split('|').filter(c => c.trim()).map((cell, ci) => {
                      const val = cell.trim();
                      const isNeg = val.startsWith('-') || val.startsWith('−');
                      const isPos = val.startsWith('+');
                      return <td key={ci} className={`${ci > 0 ? 'num' : ''} ${isNeg ? 'neg' : ''} ${isPos ? 'pos' : ''}`}>{val}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      );
      tableBuffer = [];
    }
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
      inTable = true;
      tableBuffer.push(trimmed);
      continue;
    } else if (inTable) {
      flushTable();
      inTable = false;
    }

    if (!trimmed) {
      continue;
    } else if (trimmed.match(/^[0-9]+\.[0-9]+\.\s+/)) {
      flushProse();
      elements.push(<h3 key={`${keyPrefix}-subsec-${i}`} className="analysis-subsection">{trimmed}</h3>);
    } else if (UPPER_SUBHEADER_RE.test(trimmed)) {
      flushProse();
      elements.push(<h4 key={`${keyPrefix}-h4-${i}`} className="analysis-subheader">{trimmed}</h4>);
    } else if (trimmed.match(/^(Формула|Formula|Formula):/i) || trimmed.match(/^Формула:\s*.+=.+/i) || (trimmed.includes('=') && trimmed.match(/^\•?\s*[\w\s()]+\s*[=:]\s*.*[0-9]/))) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-formula-${i}`} className="formula-box">{trimmed}</div>);
    } else if (trimmed.startsWith('•') || trimmed.startsWith('—') || trimmed.startsWith('-')) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-bullet-${i}`} className="analysis-bullet">{trimmed}</div>);
    } else if (trimmed.match(/^[0-9]+\./)) {
      flushProse();
      elements.push(<div key={`${keyPrefix}-num-${i}`} className="analysis-numbered">{trimmed}</div>);
    } else if (trimmed.match(/^(✓|✗|🟢|🟡|🟠|🔴)/)) {
      const isGood = trimmed.startsWith('✓') || trimmed.startsWith('🟢');
      const isBad = trimmed.startsWith('✗') || trimmed.startsWith('🔴');
      flushProse();
      elements.push(<div key={`${keyPrefix}-check-${i}`} className={`analysis-check ${isGood ? 'good' : ''} ${isBad ? 'bad' : ''}`}>{trimmed}</div>);
    } else if (
      trimmed.includes(':') &&
      trimmed.split(':')[0].length < KV_LABEL_MAX &&
      !trimmed.startsWith('http') &&
      KV_VALUE_NUMERIC_RE.test(trimmed.split(':').slice(1).join(':').trim())
    ) {
      flushProse();
      const [label, ...rest] = trimmed.split(':');
      const value = rest.join(':').trim();
      elements.push(
        <div key={`${keyPrefix}-kv-${i}`} className="analysis-kv">
          <span className="analysis-kv-label">{label}:</span>
          <span className="analysis-kv-value">{value}</span>
        </div>
      );
    } else {
      proseBuffer.push({ key: `${keyPrefix}-p-${i}`, text: trimmed });
    }
  }

  flushTable();
  flushProse();
  return elements;
}

function SectionCard({ title, body, index, open = false, language = "ru" }) {
  const sectionLabel = SECTION_LABELS[language] || SECTION_LABELS.ru;
  const { tldr, rest } = parseTldrBlock(body);
  const summaryHint = tldr?.summary || tldr?.forYou || null;

  return (
    <details className={`section-card fade-in${tldr ? ` section-card--tone-${tldr.tone}` : ""}`} open={open}>
      <summary>
        <span className="section-number">{sectionLabel} {String(index + 1).padStart(2, "0")}</span>
        <span className="section-title-text">{title}</span>
        {summaryHint && <span className="section-tldr-inline">{summaryHint}</span>}
      </summary>
      <div className="section-content">
        {tldr && <TldrCard tldr={tldr} language={language} />}
        {renderAnalysisContent(rest, { keyPrefix: `section-${index}` })}
      </div>
    </details>
  );
}

const ARTICLE_SECTION_ORDER = [
  "ДОСЬЕ",
  "ЧТО_С_ДЕНЬГАМИ",
  "ТРЕНД",
  "ЭФФЕКТИВНОСТЬ",
  "ОЦЕНКА_ЦЕНЫ",
  "РЫНОЧНЫЕ_ДАННЫЕ",
  "ВЕРДИКТ",
  "ИТОГ",
];

const ARTICLE_SECTION_TITLES = {
  ru: {
    ДОСЬЕ: "Общие сведения об эмитенте и методология анализа",
    ЧТО_С_ДЕНЬГАМИ: "Горизонтальный и вертикальный анализ отчётности",
    ТРЕНД: "Анализ динамики показателей",
    ЭФФЕКТИВНОСТЬ: "Коэффициентный анализ",
    ОЦЕНКА_ЦЕНЫ: "Оценка стоимости и качества цены",
    РЫНОЧНЫЕ_ДАННЫЕ: "Публичные рыночные данные",
    ВЕРДИКТ: "Итоговая оценка качества отчётности",
    ИТОГ: "Заключение для частного инвестора",
  },
  en: {
    ДОСЬЕ: "Issuer overview and analysis method",
    ЧТО_С_ДЕНЬГАМИ: "Horizontal and vertical financial analysis",
    ТРЕНД: "Performance trend analysis",
    ЭФФЕКТИВНОСТЬ: "Ratio analysis",
    ОЦЕНКА_ЦЕНЫ: "Valuation and price quality",
    РЫНОЧНЫЕ_ДАННЫЕ: "Public market data",
    ВЕРДИКТ: "Final reporting-quality assessment",
    ИТОГ: "Conclusion for a private investor",
  },
  uz: {
    ДОСЬЕ: "Emitent haqida umumiy ma'lumot va tahlil usuli",
    ЧТО_С_ДЕНЬГАМИ: "Hisobotning gorizontal va vertikal tahlili",
    ТРЕНД: "Ko'rsatkichlar dinamikasi tahlili",
    ЭФФЕКТИВНОСТЬ: "Koeffitsiyentlar tahlili",
    ОЦЕНКА_ЦЕНЫ: "Qiymat va narx sifati",
    РЫНОЧНЫЕ_ДАННЫЕ: "Ochiq bozor ma'lumotlari",
    ВЕРДИКТ: "Hisobot sifati bo'yicha yakuniy baho",
    ИТОГ: "Xususiy investor uchun xulosa",
  },
};

function countReportTables(reportTables) {
  if (!reportTables || typeof reportTables !== "object") return 0;
  return Object.values(reportTables).reduce((sum, tables) => sum + (Array.isArray(tables) ? tables.length : 0), 0);
}

function articleTableCellClass(cell, columnIndex) {
  const value = String(cell ?? "").trim();
  const classes = [];
  if (columnIndex > 0) classes.push("num");
  if (value.startsWith("-") || value.startsWith("\u2212")) classes.push("neg");
  if (value.startsWith("+")) classes.push("pos");
  return classes.join(" ");
}

function isArticleTotalRow(row) {
  const label = String(Array.isArray(row) ? row[0] ?? "" : "").toLowerCase();
  return label.includes("итого") || label.includes("total") || label.includes("jami");
}

function StructuredReportBlocks({ blocks = [], keyPrefix = "article" }) {
  return blocks.map((block, index) => {
    if (block?.type === "subheading" && block.text) {
      return (
        <section key={`${keyPrefix}-subheading-${index}`} className="analysis-sector analysis-sector--subheading">
          <h4 className="article-subheading">{block.text}</h4>
        </section>
      );
    }
    if (block?.type === "rating") {
      return (
        <section key={`${keyPrefix}-rating-${index}`} className={`analysis-sector analysis-sector--rating tone-${block.tone || "neutral"}`}>
          <div className={`article-rating tone-${block.tone || "neutral"}`}>
            {block.label && <span className="article-rating__label">{block.label}</span>}
            <strong className="article-rating__value">{block.value ?? "—"}</strong>
            {block.text && <p>{block.text}</p>}
          </div>
        </section>
      );
    }
    if (block?.type === "kpi_grid") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-kpi-${index}`} className="analysis-sector analysis-sector--kpi-grid">
          <div className="article-kpi-grid">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-kpi-card tone-${item.tone || "neutral"}`}>
                <span className="article-kpi-card__label">{item.label}</span>
                <strong className="article-kpi-card__value">{item.value ?? "—"}</strong>
                {item.hint && <p className="article-kpi-card__hint">{item.hint}</p>}
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "formula") {
      return (
        <section key={`${keyPrefix}-formula-${index}`} className={`analysis-sector analysis-sector--formula tone-${block.tone || "neutral"}`}>
          <div className={`article-formula tone-${block.tone || "neutral"}`}>
            {block.title && <div className="article-formula__title">{block.title}</div>}
            <div className="article-formula__body">
              <code>{block.formula}</code>
              <strong>{block.result ?? "—"}</strong>
            </div>
            {block.description && <p>{block.description}</p>}
          </div>
        </section>
      );
    }
    if (block?.type === "verdict_summary") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-verdict-summary-${index}`} className="analysis-sector analysis-sector--verdict-summary">
          <div className="article-verdict-summary">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-verdict-summary-card tone-${item.tone || "neutral"}`}>
                <span className="article-verdict-summary-card__label">{item.label}</span>
                {item.value && <strong className="article-verdict-summary-card__value">{item.value}</strong>}
                {item.text && <p className="article-verdict-summary-card__text">{item.text}</p>}
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "verdict_list") {
      const items = Array.isArray(block.items) ? block.items : [];
      if (!items.length) return null;
      return (
        <section key={`${keyPrefix}-verdict-${index}`} className="analysis-sector analysis-sector--verdict-list">
          <div className="article-verdict-list">
            {items.map((item, itemIndex) => (
              <div key={`${item.label || itemIndex}-${itemIndex}`} className={`article-verdict-item tone-${item.tone || "neutral"}`}>
                <span>{item.label}</span>
                <p>{item.text}</p>
              </div>
            ))}
          </div>
        </section>
      );
    }
    if (block?.type === "table") {
      const headers = Array.isArray(block.headers) ? block.headers : [];
      const rows = Array.isArray(block.rows) ? block.rows : [];
      if (!headers.length || !rows.length) return null;
      return (
        <section key={`${keyPrefix}-table-${block.id || index}`} className="analysis-sector analysis-sector--table">
          {block.caption && <div className="analysis-sector__caption">{block.caption}</div>}
          {block.note && <div className="analysis-sector__note">{block.note}</div>}
          <div className="analysis-table-wrap">
            <table className="analysis-table">
              <thead>
                <tr>{headers.map((header, headerIndex) => <th key={headerIndex}>{header}</th>)}</tr>
              </thead>
              <tbody>
                {rows.map((row, rowIndex) => {
                  const cells = Array.isArray(row) ? row : [];
                  return (
                    <tr key={rowIndex} className={isArticleTotalRow(cells) ? "total-row" : ""}>
                      {cells.map((cell, cellIndex) => (
                        <td key={cellIndex} className={articleTableCellClass(cell, cellIndex)}>
                          {cell ?? "—"}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      );
    }
    if (block?.type === "paragraph" && block.text) {
      return (
        <section key={`${keyPrefix}-paragraph-${index}`} className="analysis-sector analysis-sector--detail">
          <p className="analysis-para">{block.text}</p>
        </section>
      );
    }
    return null;
  });
}

function ReportArticleView({ analysisResult, language = "ru" }) {
  if (analysisResult?.sector_report) {
    return <article className="panel"><Suspense fallback={null}><VerifiedReport report={analysisResult.sector_report} lang={language} narrative /></Suspense></article>;
  }
  const articleReport = analysisResult?.article_report?.sections?.length ? analysisResult.article_report : null;
  const sections = analysisResult?.sections || {};
  const ordered = ARTICLE_SECTION_ORDER
    .filter((key) => sections[key])
    .map((key) => [key, sections[key]]);
  const fallback = Object.entries(sections).filter(([key]) => !ARTICLE_SECTION_ORDER.includes(key));
  const entries = ordered.length ? ordered : fallback;
  if (!articleReport && !entries.length) return null;

  const dict = {
    ru: {
      desk: "UZ STOCK ANALYZER",
      title: "Анализ финансовой отчётности",
      subtitle: "Структурированный отчёт с таблицами и подробным разбором",
      annotation: "Аннотация",
      company: "Эмитент",
      ticker: "Тикер",
      annual: "Годовой период",
      quarterly: "Квартальный период",
      analysisPeriod: "Период анализа",
      comparison: "Сравнение",
      tables: "Таблиц",
      source: "Источник",
      fresh: "Свежий расчёт",
      cache: "Из кэша",
    },
    en: {
      desk: "UZ STOCK ANALYZER",
      title: "Financial Statement Analysis",
      subtitle: "Structured report with tables and detailed commentary",
      annotation: "Abstract",
      company: "Issuer",
      ticker: "Ticker",
      annual: "Annual period",
      quarterly: "Quarterly period",
      analysisPeriod: "Analysis period",
      comparison: "Comparison",
      tables: "Tables",
      source: "Source",
      fresh: "Fresh run",
      cache: "Cached",
    },
    uz: {
      desk: "UZ STOCK ANALYZER",
      title: "Moliyaviy hisobot tahlili",
      subtitle: "Jadvallar va batafsil izohlar bilan tuzilgan hisobot",
      annotation: "Annotatsiya",
      company: "Emitent",
      ticker: "Tiker",
      annual: "Yillik davr",
      quarterly: "Chorak davr",
      analysisPeriod: "Tahlil davri",
      comparison: "Taqqoslash",
      tables: "Jadval",
      source: "Manba",
      fresh: "Yangi hisob",
      cache: "Keshdan",
    },
  }[language] || {
    desk: "UZ STOCK ANALYZER",
    title: "Анализ финансовой отчётности",
    subtitle: "Структурированный отчёт с таблицами и подробным разбором",
    annotation: "Аннотация",
    company: "Эмитент",
    ticker: "Тикер",
    annual: "Годовой период",
    quarterly: "Квартальный период",
    analysisPeriod: "Период анализа",
    comparison: "Сравнение",
    tables: "Таблиц",
    source: "Источник",
    fresh: "Свежий расчёт",
    cache: "Из кэша",
  };

  const reportMeta = articleReport?.meta || {};
  const company = reportMeta.company || analysisResult.company_name || analysisResult.input || "—";
  const ticker = reportMeta.ticker || analysisResult.ticker || "—";
  const tableCount = reportMeta.table_count ?? countReportTables(analysisResult.report_tables);
  const selectedComparison = reportMeta.report_comparison?.label || analysisResult.report_comparison?.label || "";
  const summaryRaw = sections["ИТОГ"] || sections["ВЕРДИКТ"] || entries[0]?.[1] || "";
  const { rest: summaryRest } = parseTldrBlock(summaryRaw);
  const abstractText = articleReport?.abstract || pickFirstParagraph(summaryRest) || tldrCardTitle(language, "neutral");
  const sectionTitles = ARTICLE_SECTION_TITLES[language] || ARTICLE_SECTION_TITLES.ru;
  const articleSections = articleReport?.sections || [];

  return (
    <article className="report-article-panel">
      <div className="report-article">
        <header className="report-article__masthead">
          <div className="report-article__desk">{dict.desk}</div>
          <h2>{dict.title}</h2>
          <div className="report-article__subtitle">{dict.subtitle}</div>
          <div className="report-article__rule" aria-hidden="true"><span /><em>DATA REPORT</em><span /></div>
        </header>

        <div className="report-article__meta">
          {[
            [dict.company, company],
            [dict.ticker, ticker],
            [dict.annual, reportMeta.annual_period || analysisResult.annual_period || "—"],
            [dict.quarterly, reportMeta.quarterly_period || analysisResult.quarterly_period || "—"],
            [dict.analysisPeriod, reportMeta.analysis_period || reportMeta.analysis_comparison || "—"],
            ...(selectedComparison ? [[dict.comparison, selectedComparison]] : []),
            [dict.tables, tableCount || "—"],
            [dict.source, analysisResult.from_cache ? dict.cache : dict.fresh],
          ].map(([label, value]) => (
            <div className="report-article__meta-item" key={label}>
              <div className="report-article__meta-label">{label}</div>
              <div className="report-article__meta-value">{value}</div>
            </div>
          ))}
        </div>

        {abstractText && (
          <section className="report-article__abstract">
            <div className="report-article__abstract-label">{dict.annotation}</div>
            <p>{abstractText}</p>
          </section>
        )}

        <div className="report-article__body">
          {articleReport ? articleSections.map((section, index) => (
            <section className="report-article__section" key={section.id || index}>
              <span className="report-article__section-number">{section.number || String(index + 1).padStart(2, "0")}</span>
              <h3>{section.title || `${dict.tables} ${String(index + 1).padStart(2, "0")}`}</h3>
              <div className="report-article__section-content">
                <StructuredReportBlocks blocks={section.blocks || []} keyPrefix={`article-structured-${section.id || index}`} />
              </div>
            </section>
          )) : entries.map(([key, value], index) => {
            const { rest } = parseTldrBlock(value || "");
            if (!rest) return null;
            return (
              <section className="report-article__section" key={key}>
                <span className="report-article__section-number">{String(index + 1).padStart(2, "0")}</span>
                <h3>{sectionTitles[key] || getSectionTitle(language, key)}</h3>
                <div className="report-article__section-content">
                  {renderAnalysisContent(rest, { keyPrefix: `article-${index}-${key}` })}
                </div>
              </section>
            );
          })}
        </div>
      </div>
    </article>
  );
}

export { HeroVerdictBlock, ReportArticleView, SUPPLEMENTARY_LABELS, SectionCard, StructuredReportBlocks, getSectionTitle, splitSections };
