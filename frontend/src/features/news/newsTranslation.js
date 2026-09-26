import { edHeadline } from "./editorial.jsx";
import React from "react";
import { allowDownloads, cachedTranslation, onTranslation, translateHeadline } from "../../lib/translate.js";
export function useBrowserHeadline(item, language) {
  const source = item && item.translatable && item.lang && item.lang !== language ? item.lang : "";
  const text = source ? item.title || "" : "";
  const [machine, setMachine] = React.useState(() => text ? cachedTranslation(text, source, language) : "");
  const [offer, setOffer] = React.useState(false);
  React.useEffect(() => {
    let alive = true;
    setMachine(text ? cachedTranslation(text, source, language) : "");
    setOffer(false);
    if (!text) return undefined;
    translateHeadline(text, source, language).then(({
      text: out,
      status
    }) => {
      if (!alive) return;
      if (out) setMachine(out);else setOffer(status === "downloadable" || status === "downloading");
    });
    return () => {
      alive = false;
    };
  }, [text, source, language]);

  // Called from a click, which is what lets Chrome fetch the language pack at all.
  const request = React.useCallback(() => {
    if (!text) return;
    allowDownloads();
    setOffer(false);
    translateHeadline(text, source, language, {
      download: true
    }).then(({
      text: out
    }) => {
      if (out) setMachine(out);
    });
  }, [text, source, language]);
  return {
    machine,
    offer,
    request
  };
}
export function edHeadlineCached(item, language) {
  const machine = item && item.translatable && item.lang && item.lang !== language ? cachedTranslation(item.title || "", item.lang, language) : "";
  return edHeadline(item, language, machine);
}
export function useTranslationTick() {
  const [, bump] = React.useReducer(n => n + 1, 0);
  React.useEffect(() => onTranslation(bump), []);
}
