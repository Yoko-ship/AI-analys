// The browser's own on-device translator, used to put a foreign news headline into Russian
// without a key, a bill, a server round-trip or a third party ever seeing the text.
//
// Chrome and Edge 138+ expose `Translator` as a global: the model runs locally, so this is
// free at any volume and works offline once its language pack is present. Nothing else
// exposes it — Safari, Firefox and every browser on iOS get `undefined` here — which is
// exactly why this file is a PROGRESSIVE ENHANCEMENT and never a dependency. Every caller
// already has a Russian headline to show (`title_ru`, our stored summary); a translation
// that never arrives simply leaves that in place, and no user ever sees an empty card.
//
// Three rules this module keeps:
//
//   1. **Never translate what the publisher did not write.** The server marks each item
//      `translatable`, and Moody's / Fitch are false there because their headline is a URL
//      slug: machine translation turns "fitch affirms uzbekistan at bb outlook stable" into
//      "подтвердило ПРОГНОЗ … на уровне bb", which says Fitch affirmed the outlook when it
//      affirmed the rating. Callers must pass only items the server allowed.
//   2. **Never download a language pack behind the user's back.** First use of a pair costs
//      a real download, and Chrome requires a user gesture for it. So the automatic path
//      only ever uses a pack that is already on the machine; the download is offered as an
//      explicit action and remembered afterwards.
//   3. **Never throw.** Every entry point resolves to a value; a browser that half-supports
//      the API is treated as one that does not support it.

// The target is the language the reader is looking at, not a constant: the Russian site
// needs en->ru, the English site ru->en. Uzbek is deliberately not special-cased — real
// Chrome simply reports every uz pair "unavailable" (checked 2026-07-29), so the Uzbek
// site falls through to the stored summary_uz on its own, with no code path of its own.
const CONSENT_KEY = "news.translate.download";

// text → translation, for the life of the page. The same headline appears in the feed, in
// the "latest" rail and in related-story blocks; it should cost one call, not four.
const _done = new Map();
// One Translator instance per source language, created lazily and shared.
const _instances = new Map();
// Notified whenever a headline finishes translating. The same story appears as a card, as a
// line in the "latest" rail and as a related link; without this the card would repaint with
// the translation and the other two would keep the summary, showing two different Russian
// texts for one story in a single viewport.
const _listeners = new Set();

/** Subscribe to "a translation just landed". Returns an unsubscribe function. */
export function onTranslation(fn) {
  _listeners.add(fn);
  return () => _listeners.delete(fn);
}

function announce() {
  _listeners.forEach((fn) => {
    try {
      fn();
    } catch {
      /* one bad subscriber must not stop the others */
    }
  });
}

function api() {
  try {
    // `globalThis`, not `self`: this module is also exercised by the node test runner, where
    // `self` does not exist and the whole file would silently report "unsupported".
    return typeof globalThis !== "undefined" && typeof globalThis.Translator !== "undefined"
      ? globalThis.Translator : null;
  } catch {
    return null;
  }
}

/** Drop the cached translations and translator instances. Exists for the tests, which swap
 *  the `Translator` global between cases; harmless anywhere else. */
export function resetTranslationCache() {
  _done.clear();
  _instances.clear();
}

/** True when this browser has the on-device translator at all. */
export function supportsTranslation() {
  return Boolean(api());
}

function key(text, source, target) {
  // '|' cannot occur in a BCP-47 language code, so it separates the parts without any
  // chance of two different (source, target, text) triples colliding on one key.
  return `${source}|${target}|${text}`;
}

/** A translation already computed this session, or "" — lets a re-render paint instantly. */
export function cachedTranslation(text, source, target) {
  return _done.get(key(text, source, target)) || "";
}

/**
 * Has the user already agreed to download a language pack? Stored, because the download is
 * a one-off cost and asking again on every visit would be worse than not offering it.
 */
export function downloadAllowed() {
  try {
    return window.localStorage.getItem(CONSENT_KEY) === "1";
  } catch {
    return false;
  }
}

export function allowDownloads() {
  try {
    window.localStorage.setItem(CONSENT_KEY, "1");
  } catch {
    /* private mode — the consent just does not persist past this page */
  }
}

/**
 * "unavailable" | "downloadable" | "downloading" | "available" | "unsupported".
 * "unsupported" is ours, for a browser with no API at all.
 */
export async function availability(source, target) {
  const Translator = api();
  if (!Translator || !source || !target || source === target) return "unsupported";
  try {
    const status = await Translator.availability({ sourceLanguage: source, targetLanguage: target });
    return status || "unavailable";
  } catch {
    return "unavailable";
  }
}

async function instance(source, target) {
  const pair = `${source}|${target}`;
  if (!_instances.has(pair)) {
    const Translator = api();
    _instances.set(pair, Translator.create({ sourceLanguage: source, targetLanguage: target })
      .catch(() => {
        // Do not cache a rejection: a failed create is usually a missing user gesture, and
        // the next attempt comes from a click that has one.
        _instances.delete(pair);
        return null;
      }));
  }
  return _instances.get(pair);
}

/**
 * Translate one headline into Russian. Resolves to `{ text, status }`, where `text` is ""
 * whenever the browser could not (or should not yet) do it and the caller must keep what it
 * already had.
 *
 * With `download: false` (the automatic path) this only uses a language pack that is already
 * installed, so it never costs the visitor a surprise download. Pass `download: true` from a
 * click to fetch the pack and translate.
 */
export async function translateHeadline(text, source, target, { download = false } = {}) {
  const clean = String(text || "").trim();
  if (!clean || !source || !target || source === target) return { text: "", status: "unsupported" };
  const hit = _done.get(key(clean, source, target));
  if (hit) return { text: hit, status: "available" };

  const status = await availability(source, target);
  if (status === "unsupported" || status === "unavailable") return { text: "", status };
  // "downloadable" means the pack is not here yet. Only a user action may fetch it.
  if (status !== "available" && !(download || downloadAllowed())) return { text: "", status };

  const translator = await instance(source, target);
  if (!translator) return { text: "", status };
  try {
    const out = String((await translator.translate(clean)) || "").trim();
    if (!out || out === clean) return { text: "", status: "unavailable" };
    _done.set(key(clean, source, target), out);
    announce();
    return { text: out, status: "available" };
  } catch {
    return { text: "", status: "unavailable" };
  }
}
