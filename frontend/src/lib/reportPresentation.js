const COPY = {
  ru: {
    forms: { NSBU: "НСБУ", MSFO: "МСФО", Audition: "Аудиторское заключение" },
    periods: { annual: "Годовой", quarter: "Квартальный" },
    msfoTitle: "Финансовая отчётность по МСФО",
    auditTitle: "Аудиторское заключение",
    msfoDescription: "Комплект финансовой отчётности. Заключение независимого аудитора может находиться в начале того же PDF.",
    auditDescription: "Отдельное заключение аудитора, а не комплект финансовой отчётности МСФО.",
  },
  uz: {
    forms: { NSBU: "NSBU", MSFO: "MHXS", Audition: "Auditor xulosasi" },
    periods: { annual: "Yillik", quarter: "Choraklik" },
    msfoTitle: "MHXS bo‘yicha moliyaviy hisobot",
    auditTitle: "Auditor xulosasi",
    msfoDescription: "Moliyaviy hisobotlar to‘plami. Mustaqil auditor xulosasi shu PDF boshida bo‘lishi mumkin.",
    auditDescription: "Bu MHXS moliyaviy hisobotlar to‘plami emas, alohida auditor xulosasi.",
  },
  en: {
    forms: { NSBU: "NAS", MSFO: "IFRS", Audition: "Auditor's report" },
    periods: { annual: "Annual", quarter: "Quarterly" },
    msfoTitle: "IFRS financial statements",
    auditTitle: "Auditor's report",
    msfoDescription: "A financial-statement package. The independent auditor's report may appear at the beginning of the same PDF.",
    auditDescription: "A standalone auditor's report, not a set of IFRS financial statements.",
  },
};

function languageCopy(language) {
  return COPY[language] || COPY.ru;
}

export function reportFormLabel(form, language = "ru") {
  return languageCopy(language).forms[form] || form || "";
}

export function companyReportPresentation(report, language = "ru") {
  const copy = languageCopy(language);
  const form = report?.report_form;
  const year = report?.year || "";
  const quarter = Number(report?.quarter || 0);
  const period = `${year}${quarter ? ` Q${quarter}` : ""}`.trim();
  const periodType = copy.periods[report?.period_type] || report?.period_type || "";

  if (form === "MSFO") {
    return {
      title: `${copy.msfoTitle}${period ? ` · ${period}` : ""}`,
      description: copy.msfoDescription,
      formLabel: copy.forms.MSFO,
      periodType,
    };
  }
  if (form === "Audition") {
    return {
      title: `${copy.auditTitle}${period ? ` · ${period}` : ""}`,
      description: copy.auditDescription,
      formLabel: copy.forms.Audition,
      periodType,
    };
  }
  return {
    title: report?.title || `${copy.forms.NSBU}${period ? ` · ${period}` : ""}`,
    description: null,
    formLabel: reportFormLabel(form, language),
    periodType,
  };
}
