import { useCallback, useState } from "react";
import { companyDraftOf } from "./adminModel.js";
export function useCompanyImports({
  readJson,
  alive,
  setError,
  t
}) {
  const [companyImports, setCompanyImports] = useState(null);
  const [companyLookup, setCompanyLookup] = useState("");
  const [companyFilter, setCompanyFilter] = useState("pending");
  const [companyDraft, setCompanyDraft] = useState(null);
  const [companyNotice, setCompanyNotice] = useState("");
  const [companyBusy, setCompanyBusy] = useState("");
  const loadCompanyImports = useCallback(async (status = companyFilter) => {
    const suffix = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "";
    const data = await readJson(`/api/admin/companies${suffix}`);
    if (alive.current) setCompanyImports(data);
  }, [companyFilter, readJson, alive]);
  const discoverCompanies = useCallback(async () => {
    setCompanyBusy("discover");
    setCompanyNotice("");
    setError("");
    try {
      const data = await readJson("/api/admin/companies/discover", {
        method: "POST"
      });
      if (alive.current) {
        setCompanyImports(companyFilter === "all" ? data : {
          ...data,
          items: (data.items || []).filter(item => item.status === companyFilter)
        });
        setCompanyNotice(t(`Проверено бумаг: ${data.seen ?? data.discovered ?? 0}`, `Tekshirilgan qog'ozlar: ${data.seen ?? data.discovered ?? 0}`, `Securities checked: ${data.seen ?? data.discovered ?? 0}`));
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyFilter, readJson, t, setError, alive]);
  const previewCompany = useCallback(async (ticker, refresh = true) => {
    const one = String(ticker || "").trim().toUpperCase();
    if (!one) return;
    setCompanyBusy(`preview:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      const data = await readJson(`/api/admin/companies/${encodeURIComponent(one)}/preview?refresh=${refresh ? "true" : "false"}`);
      if (alive.current) {
        setCompanyLookup(one);
        setCompanyDraft(companyDraftOf(data.company));
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [readJson, setError, alive]);
  const approveCompany = useCallback(async () => {
    if (!companyDraft) return;
    setCompanyBusy(`approve:${companyDraft.ticker}`);
    setCompanyNotice("");
    setError("");
    try {
      const body = {
        company_name: companyDraft.company_name,
        org_id: companyDraft.org_id,
        isin: companyDraft.isin || null,
        sector: companyDraft.sector,
        logo_url: companyDraft.logo_url || null,
        security_type: companyDraft.security_type,
        share_type: companyDraft.share_type || null,
        review_note: companyDraft.review_note || null,
        sync: true
      };
      const data = await readJson(`/api/admin/companies/${encodeURIComponent(companyDraft.ticker)}/approve`, {
        method: "POST",
        body: JSON.stringify(body)
      });
      if (alive.current) {
        setCompanyDraft(companyDraftOf(data.company));
        setCompanyNotice(data.sync_started ? t("Компания опубликована, синхронизация запущена.", "Kompaniya e'lon qilindi, sinxronlash boshlandi.", "Company published; synchronization started.") : t("Компания опубликована.", "Kompaniya e'lon qilindi.", "Company published."));
        await loadCompanyImports(companyFilter);
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyDraft, companyFilter, loadCompanyImports, readJson, t, setError, alive]);
  const rejectCompany = useCallback(async item => {
    const one = String(item?.ticker || companyDraft?.ticker || "").toUpperCase();
    if (!one) return;
    setCompanyBusy(`reject:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      await readJson(`/api/admin/companies/${encodeURIComponent(one)}/reject`, {
        method: "POST",
        body: JSON.stringify({
          note: item?.review_note || companyDraft?.review_note || null
        })
      });
      if (companyDraft?.ticker === one) setCompanyDraft(null);
      await loadCompanyImports(companyFilter);
      setCompanyNotice(t("Кандидат отклонён.", "Nomzod rad etildi.", "Candidate rejected."));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyDraft, companyFilter, loadCompanyImports, readJson, t, setError, alive]);
  const syncCompany = useCallback(async ticker => {
    const one = String(ticker || "").toUpperCase();
    setCompanyBusy(`sync:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      const data = await readJson(`/api/admin/companies/${encodeURIComponent(one)}/sync`, {
        method: "POST"
      });
      setCompanyNotice(data.started ? t("Синхронизация запущена.", "Sinxronlash boshlandi.", "Synchronization started.") : t("Синхронизация уже идёт.", "Sinxronlash davom etmoqda.", "Synchronization is already running."));
      await loadCompanyImports(companyFilter);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyFilter, loadCompanyImports, readJson, t, setError, alive]);
  const setCompanyVisibility = useCallback(async (item, visible) => {
    const one = String(item?.ticker || "").toUpperCase();
    if (!one) return;
    setCompanyBusy(`visibility:${one}`);
    setCompanyNotice("");
    setError("");
    try {
      await readJson(`/api/admin/companies/${encodeURIComponent(one)}/visibility`, {
        method: "PATCH",
        body: JSON.stringify({
          visible
        })
      });
      await loadCompanyImports(companyFilter);
      setCompanyNotice(visible ? t("Компания возвращена в каталог.", "Kompaniya katalogga qaytarildi.", "Company restored to the catalog.") : t("Компания скрыта из каталога.", "Kompaniya katalogdan yashirildi.", "Company hidden from the catalog."));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      if (alive.current) setCompanyBusy("");
    }
  }, [companyFilter, loadCompanyImports, readJson, t, setError, alive]);
  return {
    companyImports,
    companyLookup,
    setCompanyLookup,
    companyFilter,
    setCompanyFilter,
    companyDraft,
    setCompanyDraft,
    companyNotice,
    companyBusy,
    loadCompanyImports,
    discoverCompanies,
    previewCompany,
    approveCompany,
    rejectCompany,
    syncCompany,
    setCompanyVisibility
  };
}
