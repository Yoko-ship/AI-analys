import { t } from "../../shared/i18n.jsx";

export function useFavorites({ session: sessionModule, toasts: toastsModule, preferences: preferencesModule, navigation: navigationModule }) {
  const { token, apiFetch, loadProfile } = sessionModule;
  const { addToast } = toastsModule;
  const { language } = preferencesModule;
  const { setActiveView } = navigationModule;
  const handleToggleFavorite = async (ticker, companyName = "") => {
    if (!token) {
      addToast(t(language, "auth.messages.authRequired"), "error");
      setActiveView("auth");
      return;
    }
    const normalized = String(ticker || "").trim();
    if (!normalized) return;
    try {
      const res = await apiFetch("/api/favorites/toggle", {
        method: "POST",
        body: JSON.stringify({ ticker: normalized, company_name: companyName || undefined }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Could not update favorites");
      addToast(`${normalized} ${data.favorited ? "saved" : "removed"}`, "success");
      await loadProfile();
    } catch (error) {
      addToast(error.message, "error");
    }
  };
  return { handleToggleFavorite };
}
