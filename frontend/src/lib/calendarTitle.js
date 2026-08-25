const TITLE_LABELS = {
  ru: {
    general: "Общее собрание акционеров",
    annual: "Годовое общее собрание акционеров",
    extraordinary: "Внеочередное общее собрание акционеров",
    repeated: "Повторное общее собрание акционеров",
  },
  en: {
    general: "General meeting of shareholders",
    annual: "Annual general meeting of shareholders",
    extraordinary: "Extraordinary general meeting of shareholders",
    repeated: "Repeated general meeting of shareholders",
  },
  uz: {
    general: "Aksiyadorlarning umumiy yig‘ilishi",
    annual: "Aksiyadorlarning yillik umumiy yig‘ilishi",
    extraordinary: "Aksiyadorlarning navbatdan tashqari umumiy yig‘ilishi",
    repeated: "Aksiyadorlarning takroriy umumiy yig‘ilishi",
  },
};

// JavaScript's `\b`/`\w` remain ASCII-oriented without the newer `v` mode, so
// Cyrillic words are matched directly rather than with a word-boundary token.
const UZBEK_HINT = /[қғҳў]|(?:aksiyador|yig['‘’`ʻʼ]?ilish|o['‘’`ʻʼ]?tkaz|to['‘’`ʻʼ]?g['‘’`ʻʼ]?risida|navbatdan|tashqari|xabar(?:noma)?|e['‘’`ʻʼ]?lon|акциядор|йиғилиш|йигилиш|ўтказ|утказ|тўғрисида|тугрисида|навбатдан|ташқари|ташкари|хабарнома|эълон)/i;
const RUSSIAN_HINT = /(?:акционер|собрани|проведен|созыв|сообщени|уведомлен|внеочеред|годов|повторн|об[ъь]?явлен)/i;
const ENGLISH_HINT = /\b(?:shareholder|meeting|notice|annual|extraordinary|repeated|convocation)\w*/i;

export function calendarTitleLanguage(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (UZBEK_HINT.test(text)) return "uz";
  if (RUSSIAN_HINT.test(text)) return "ru";
  if (ENGLISH_HINT.test(text)) return "en";
  return "";
}

export function calendarMeetingKind(value) {
  const text = String(value || "");
  if (/повтор|такрор|takror|қайта|qo['‘’`ʻʼ]?shimcha|қўшимча/i.test(text)) return "repeated";
  if (/внеочеред|navbatdan\s+tashqari|навбатдан\s+таш(?:қ|к)ари/i.test(text)) return "extraordinary";
  if (/годов|итогам\s+\d{4}|annual|yillik|йиллик|йил\s+якун/i.test(text)) return "annual";
  return "general";
}

// Openinfo exposes one source-language title for meeting notices. The issuer is
// already printed in its own column, so the useful localized information here
// is the event type. Prefer future server-provided translations when present;
// otherwise preserve a title already written in the selected language or use a
// precise, language-matched meeting label. The source wording remains available
// to the UI as hover metadata for auditability.
export function localizedCalendarTitle(item, language = "ru") {
  const lang = Object.hasOwn(TITLE_LABELS, language) ? language : "ru";
  const row = item && typeof item === "object" ? item : { title: item };
  const explicit = String(row[`title_${lang}`] || "").trim();
  if (explicit) return explicit;

  const raw = String(row.title || "").trim();
  if (!raw) return "";
  if (calendarTitleLanguage(raw) === lang) return raw;
  return TITLE_LABELS[lang][calendarMeetingKind(raw)];
}
