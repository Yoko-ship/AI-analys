// One reading of an API response for the pages that show its error to a reader.
//
// Two failures used to reach the reader raw: a proxy's HTML error page (a
// timeout or a restart) made `response.json()` throw «Unexpected token <», and
// the rate limiter's 429 arrived as English text whatever the interface
// language. Both are worded here from the status and Retry-After alone, so the
// message does not depend on which server text happened to come back.

function russianSeconds(n) {
  if (n % 10 === 1 && n % 100 !== 11) return "секунду";
  if ([2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100)) return "секунды";
  return "секунд";
}

export function rateLimitMessage(retryAfterSeconds, language) {
  const seconds = Number(retryAfterSeconds);
  if (Number.isFinite(seconds) && seconds > 3600) {
    return {
      ru: "Дневной лимит запросов исчерпан. Попробуйте завтра.",
      uz: "Kunlik so‘rovlar chegarasi tugadi. Ertaga qayta urinib ko‘ring.",
      en: "The daily request limit is reached. Try again tomorrow.",
    }[language] || "Дневной лимит запросов исчерпан. Попробуйте завтра.";
  }
  const n = Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : 60;
  return {
    ru: `Превышен лимит запросов. Попробуйте через ${n} ${russianSeconds(n)}.`,
    uz: `So‘rovlar chegarasidan oshildi. ${n} soniyadan so‘ng qayta urinib ko‘ring.`,
    en: `Request limit exceeded. Try again in ${n} seconds.`,
  }[language] || `Превышен лимит запросов. Попробуйте через ${n} ${russianSeconds(n)}.`;
}

export function unavailableMessage(status, language) {
  const code = status ? ` (${status})` : "";
  return {
    ru: `Сервер временно не ответил${code}. Повторите запрос через минуту.`,
    uz: `Server vaqtincha javob bermadi${code}. Bir daqiqadan so‘ng qayta urinib ko‘ring.`,
    en: `The server did not respond${code}. Please retry in a minute.`,
  }[language] || `Сервер временно не ответил${code}. Повторите запрос через минуту.`;
}

/** Parse a response body as JSON without throwing on an HTML error page. */
export async function readApiResponse(response) {
  const text = await response.text();
  if (!text) return { data: null, json: false };
  try {
    return { data: JSON.parse(text), json: true };
  } catch {
    return { data: null, json: false };
  }
}

/** The message to show for a failed response, in the interface language. */
export function apiErrorMessage(response, data, language, fallback = "") {
  const status = response?.status;
  if (status === 429) {
    return rateLimitMessage(response.headers?.get?.("Retry-After"), language);
  }
  if (status >= 500 && data?.error_id) {
    // The opaque 500 (server/hardening.py) says only "Internal server error"
    // in English; the id is what support needs.
    return {
      ru: `Внутренняя ошибка сервера. Код ошибки: ${data.error_id}.`,
      uz: `Serverning ichki xatosi. Xato kodi: ${data.error_id}.`,
      en: `Internal server error. Error id: ${data.error_id}.`,
    }[language] || `Внутренняя ошибка сервера. Код ошибки: ${data.error_id}.`;
  }
  const detail = data && typeof data.detail === "string" ? data.detail : "";
  if (detail) return detail;
  if (!data || (status && status >= 500)) return unavailableMessage(status, language);
  return fallback || unavailableMessage(status, language);
}
