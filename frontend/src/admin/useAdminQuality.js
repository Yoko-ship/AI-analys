import "./admin.css";
import { useCallback, useEffect, useState } from "react";

export function useAdminQuality({ readJson, alive, setError, t, onSectionChange, previewCompany }) {
const [quality, setQuality] = useState(null);

const [qualityCorrections, setQualityCorrections] = useState(null);

const [qualityBusy, setQualityBusy] = useState("");

const [qualityDraft, setQualityDraft] = useState(null);

const [qualityTicker, setQualityTicker] = useState("");

const [qualitySelectedTicker, setQualitySelectedTicker] = useState("");

const [qualitySuggestions, setQualitySuggestions] = useState([]);

const [qualitySuggestionsOpen, setQualitySuggestionsOpen] = useState(false);

const [qualitySearchLoading, setQualitySearchLoading] = useState(false);

const [qualityNotice, setQualityNotice] = useState("");

const loadQuality = useCallback(async () => {
    const [issues, corrections] = await Promise.all([
      readJson("/api/admin/data-quality/issues"),
      readJson("/api/admin/data-quality/corrections"),
    ]);
    if (alive.current) { setQuality(issues); setQualityCorrections(corrections); }
  }, [readJson, alive]);

const scanQualityCompany = useCallback(async (ticker) => {
    const normalized = String(ticker || "").trim().toUpperCase();
    if (!normalized) { setError(t("Введите тикер компании.", "Kompaniya tikerini kiriting.", "Enter a company ticker.")); return; }
    const busyKey = `analysis:${normalized}`;
    setQualityBusy(busyKey); setError("");
    try {
      await readJson(`/api/admin/data-quality/analysis/${encodeURIComponent(normalized)}/scan`, { method: "POST" });
      setQualityTicker(normalized);
      setQualitySelectedTicker(normalized);
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [alive, setError, loadQuality, readJson, t]);

const refreshQualityCompanyReporting = useCallback(async (ticker) => {
    const normalized = String(ticker || "").trim().toUpperCase();
    if (!normalized) { setError(t("Выберите компанию.", "Kompaniyani tanlang.", "Choose a company.")); return; }
    const busyKey = `refresh:${normalized}`;
    setQualityBusy(busyKey); setQualityNotice(""); setError("");
    try {
      const data = await readJson(`/api/admin/data-quality/companies/${encodeURIComponent(normalized)}/refresh`, { method: "POST" });
      setQualityTicker(normalized);
      setQualitySelectedTicker(normalized);
      const period = data.latest_period || t("последний доступный период", "mavjud so'nggi davr", "the latest available period");
      setQualityNotice(t(
        `Официальные отчёты ${normalized} обновлены. Актуальный период: ${period}. Обновлено записей: ${data.financials_updated || 0}; закрыто проверок: ${data.resolved_issues || 0}.`,
        `${normalized} rasmiy hisobotlari yangilandi. Joriy davr: ${period}. Yangilangan yozuvlar: ${data.financials_updated || 0}; yopilgan tekshiruvlar: ${data.resolved_issues || 0}.`,
        `${normalized} official reports were refreshed. Current period: ${period}. Updated records: ${data.financials_updated || 0}; resolved checks: ${data.resolved_issues || 0}.`,
      ));
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [alive, setError, loadQuality, readJson, t]);

useEffect(() => {
    const query = qualityTicker.trim();
    if (!query) {
      setQualitySuggestions([]);
      setQualitySuggestionsOpen(false);
      setQualitySearchLoading(false);
      return undefined;
    }
    let active = true;
    const timer = window.setTimeout(() => {
      setQualitySearchLoading(true);
      readJson(`/api/admin/companies/search?q=${encodeURIComponent(query)}&limit=12`)
        .then((data) => {
          if (!active) return;
          setQualitySuggestions(data.items || []);
          if (!qualitySelectedTicker) setQualitySuggestionsOpen(true);
        })
        .catch(() => { if (active) setQualitySuggestions([]); })
        .finally(() => { if (active) setQualitySearchLoading(false); });
    }, 180);
    return () => { active = false; window.clearTimeout(timer); };
  }, [qualityTicker, qualitySelectedTicker, readJson]);

const submitQualityCorrection = useCallback(async (event) => {
    event.preventDefault();
    if (!qualityDraft) return;
    setQualityBusy("create"); setError("");
    try {
      const { suggestion, alternatives, evidenceMissing, ...correction } = qualityDraft;
      const data = await readJson("/api/admin/data-quality/corrections/apply", {
        method: "POST", body: JSON.stringify({
          ...correction,
          year: Number(correction.year), quarter: Number(correction.quarter || 0),
          value_thousands_uzs: Number(correction.value_thousands_uzs),
        }),
      });
      setQualityDraft(null);
      await loadQuality();
      return data;
    } catch (e) { setError(String(e.message || e)); return null; }
    finally { if (alive.current) setQualityBusy(""); }
  }, [alive, setError, loadQuality, qualityDraft, readJson]);

const reviewQualityCorrection = useCallback(async (id, status) => {
    setQualityBusy(id); setError("");
    try {
      await readJson(`/api/admin/data-quality/corrections/${encodeURIComponent(id)}/review`, {
        method: "POST", body: JSON.stringify({ status }),
      });
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [alive, setError, loadQuality, readJson]);

const autoApplyQualityIssue = useCallback(async (issue) => {
    const busyKey = `apply:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      await readJson(`/api/admin/data-quality/issues/${encodeURIComponent(issue.id)}/apply`, { method: "POST" });
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [alive, setError, loadQuality, readJson]);

const autoApplyUnitScale = useCallback(async (issue) => {
    const busyKey = `scale:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      await readJson(`/api/admin/data-quality/issues/${encodeURIComponent(issue.id)}/apply-unit-scale`, { method: "POST" });
      await loadQuality();
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [alive, setError, loadQuality, readJson]);

const fixIssuerMapping = useCallback(async (issue) => {
    const ticker = String(issue?.ticker || "").trim().toUpperCase();
    if (!ticker) return;
    const busyKey = `issuer:${issue.id}`;
    setQualityBusy(busyKey); setError("");
    try {
      onSectionChange?.("companies");
      await previewCompany(ticker, true);
    } catch (e) { setError(String(e.message || e)); }
    finally { if (alive.current) setQualityBusy(""); }
  }, [alive, setError, onSectionChange, previewCompany]);
return { quality, qualityCorrections, qualityBusy, setQualityBusy, qualityDraft, setQualityDraft, qualityTicker, setQualityTicker, qualitySelectedTicker, setQualitySelectedTicker, qualitySuggestions, qualitySuggestionsOpen, setQualitySuggestionsOpen, qualitySearchLoading, qualityNotice, loadQuality, scanQualityCompany, refreshQualityCompanyReporting, submitQualityCorrection, reviewQualityCorrection, autoApplyQualityIssue, autoApplyUnitScale, fixIssuerMapping };
}
