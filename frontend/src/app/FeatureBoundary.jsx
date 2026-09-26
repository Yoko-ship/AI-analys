import { Component, Suspense } from "react";
import { normalizeLanguage } from "../shared/i18n.jsx";

const COPY = {
  ru: { loading: "Загрузка...", error: "Не удалось открыть страницу. Попробуйте обновить её.", reload: "Обновить страницу" },
  en: { loading: "Loading...", error: "This page could not be opened. Try reloading it.", reload: "Reload page" },
  uz: { loading: "Yuklanmoqda...", error: "Sahifani ochib bo'lmadi. Uni qayta yuklab ko'ring.", reload: "Sahifani yangilash" },
};

// The shell sits outside this boundary, so a failed page download does not
// remove navigation. Reload also recovers a stale asset URL after a release.
export class FeatureBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    const copy = COPY[normalizeLanguage(this.props.language)];
    if (this.state.failed) {
      return <div className="empty-state" role="alert">
        <p>{copy.error}</p>
        <button type="button" className="ghost-btn" onClick={() => window.location.reload()}>{copy.reload}</button>
      </div>;
    }
    return <Suspense fallback={<div className="empty-state" role="status">{copy.loading}</div>}>
      {this.props.children}
    </Suspense>;
  }
}
