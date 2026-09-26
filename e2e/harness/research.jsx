import React, { Suspense, useState } from "react";
import { createRoot } from "react-dom/client";
import { useResearch } from "../../frontend/src/features/research/useResearch.jsx";
import "../../frontend/src/styles.css";
import "../../frontend/src/theme.css";
import "../../frontend/src/mobile.css";
import "../../frontend/src/landing.css";
import "../../frontend/src/market.css";
import "../../frontend/src/profile.css";
import "../../frontend/src/auth.css";

const companies = [
  { ticker: "AGBA", company_name: "AGBA Bank", sector: "Banks" },
  { ticker: "ALKB", company_name: "Aloqabank", sector: "Banks" },
  { ticker: "KVTS", company_name: "Kvarts", sector: "Industry" },
];
const apiFetch = (url, options) => fetch(url, options);
const loadProfile = async () => {};
function ResearchHarness() {
  const [activeView, setActiveView] = useState("analysis");
  const [token, setToken] = useState("local-test-session");
  const [toasts, setToasts] = useState([]);
  const research = useResearch({
    session: { token, apiFetch, loadProfile, hasProAccess: Boolean(token), favoriteTickers: new Set() },
    toasts: { addToast: text => setToasts(items => [...items, text]) },
    preferences: { language: "ru" }, navigation: { activeView, setActiveView },
    market: { companies, resolveTicker: value => value }, favorites: { handleToggleFavorite: () => {} },
  });
  return <main style={{ maxWidth: 1400, padding: 16, margin: "auto" }}>
    <nav aria-label="Test navigation">
      <button onClick={() => setActiveView("analysis")}>QA Analysis</button>
      <button onClick={() => setActiveView("compare")}>QA Compare</button>
      <button onClick={() => setToken(null)}>QA Logout</button>
    </nav>
    <div data-testid="qa-toasts">{toasts.map((text, index) => <p key={index}>{text}</p>)}</div>
    <Suspense fallback={<p>Loading research…</p>}>{research.view}</Suspense>
  </main>;
}
createRoot(document.getElementById("root")).render(<ResearchHarness />);
