// Unit tests for the browser-translation helper. Run with `npm run test:unit`
// (node's built-in test runner — no extra dependency).
//
// The module is a progressive enhancement over an already-Russian card, so the behaviour
// worth pinning is what it does when it CANNOT translate: every path must resolve to an
// empty string rather than throw, or a foreign headline would render blank instead of
// falling back to the summary the server supplied. Node has no `Translator` global, which
// makes it exactly the environment this has to survive — the same one Safari, Firefox and
// every iOS browser present.
import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";

import {
  availability,
  cachedTranslation,
  downloadAllowed,
  resetTranslationCache,
  supportsTranslation,
  translateHeadline,
} from "../frontend/src/lib/translate.js";

afterEach(() => {
  delete globalThis.Translator;
  delete globalThis.localStorage;
  resetTranslationCache();
});

describe("a browser without the on-device translator", () => {
  it("reports no support", () => {
    assert.equal(supportsTranslation(), false);
  });

  it("resolves to an empty translation instead of throwing", async () => {
    const out = await translateHeadline("Uzbekistan Signs Railway Deal", "en", "ru");
    assert.deepEqual(out, { text: "", status: "unsupported" });
  });

  it("reports 'unsupported' availability", async () => {
    assert.equal(await availability("en", "ru"), "unsupported");
  });

  it("treats an unreadable localStorage as no consent", () => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get() { throw new Error("blocked in private mode"); },
    });
    assert.equal(downloadAllowed(), false);
  });
});

describe("guards that hold whatever the browser supports", () => {
  it("never translates empty text or a missing source language", async () => {
    assert.equal((await translateHeadline("", "en", "ru")).text, "");
    assert.equal((await translateHeadline("Some headline", "", "ru")).text, "");
    assert.equal((await translateHeadline(null, "en", "ru")).text, "");
  });

  it("never translates a language into itself", async () => {
    assert.equal(await availability("ru", "ru"), "unsupported");
  });

  it("reports nothing cached for text it has not translated", () => {
    assert.equal(cachedTranslation("Central Asia Weighs Its Options", "en", "ru"), "");
  });
});

describe("a browser that does have the translator", () => {
  function fakeTranslator({ status, translate }) {
    globalThis.Translator = {
      availability: async () => status,
      create: async () => ({ translate: async (t) => translate(t) }),
    };
  }

  it("translates when the language pack is already installed", async () => {
    fakeTranslator({ status: "available", translate: () => "Узбекистан подписал соглашение" });
    const out = await translateHeadline("Uzbekistan Signs Railway Deal", "en", "ru");
    assert.equal(out.text, "Узбекистан подписал соглашение");
    // ...and serves the same headline from cache afterwards, so the feed, the rail and the
    // related block cost one call between them rather than one each.
    assert.equal(cachedTranslation("Uzbekistan Signs Railway Deal", "en", "ru"),
                 "Узбекистан подписал соглашение");
  });

  it("does NOT download a language pack on the automatic path", async () => {
    let created = false;
    globalThis.Translator = {
      availability: async () => "downloadable",
      create: async () => { created = true; return { translate: async () => "нет" }; },
    };
    const out = await translateHeadline("Central Asia Weighs Its Options", "en", "ru");
    assert.equal(out.text, "");
    assert.equal(out.status, "downloadable");
    assert.equal(created, false, "a pack must only be fetched from an explicit user action");
  });

  it("downloads when the reader explicitly asks", async () => {
    fakeTranslator({ status: "downloadable", translate: () => "Центральная Азия взвешивает варианты" });
    const out = await translateHeadline("Central Asia Weighs Its Options", "en", "ru", { download: true });
    assert.equal(out.text, "Центральная Азия взвешивает варианты");
  });

  it("treats an echoed-back source string as a failed translation", async () => {
    fakeTranslator({ status: "available", translate: (t) => t });
    const out = await translateHeadline("Fitch Affirms Uzbekistan", "en", "ru");
    assert.equal(out.text, "", "an untranslated echo must fall back, not pose as Russian");
  });

  it("survives a translator that throws mid-call", async () => {
    fakeTranslator({ status: "available", translate: () => { throw new Error("model died"); } });
    const out = await translateHeadline("Uzbekistan Signs Deal With China", "en", "ru");
    assert.equal(out.text, "");
  });
});

describe("the target language is the reader's, not a constant", () => {
  it("translates ru->en for the English site", async () => {
    globalThis.Translator = {
      availability: async ({ sourceLanguage, targetLanguage }) =>
        (sourceLanguage === "ru" && targetLanguage === "en" ? "available" : "unavailable"),
      create: async () => ({ translate: async () => "The central bank held the rate" }),
    };
    const out = await translateHeadline("ЦБ сохранил ставку", "ru", "en");
    assert.equal(out.text, "The central bank held the rate");
  });

  // Checked against real Chrome on 2026-07-29: every Uzbek pair reports "unavailable".
  // The Uzbek site therefore has no browser route at all and must fall back to the stored
  // summary_uz — this asserts it degrades quietly instead of throwing or blanking.
  it("gives up quietly on Uzbek, which Chrome cannot do", async () => {
    globalThis.Translator = {
      availability: async ({ targetLanguage }) => (targetLanguage === "uz" ? "unavailable" : "available"),
      create: async () => ({ translate: async () => "should never be reached" }),
    };
    const out = await translateHeadline("ЦБ сохранил ставку", "ru", "uz");
    assert.equal(out.text, "");
    assert.equal(out.status, "unavailable");
  });

  it("caches per direction, so ru->en cannot be served to an Uzbek reader", async () => {
    globalThis.Translator = {
      availability: async () => "available",
      create: async () => ({ translate: async () => "English text" }),
    };
    await translateHeadline("ЦБ сохранил ставку", "ru", "en");
    assert.equal(cachedTranslation("ЦБ сохранил ставку", "ru", "en"), "English text");
    assert.equal(cachedTranslation("ЦБ сохранил ставку", "ru", "uz"), "");
  });
});
