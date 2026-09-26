import { roundedDisplayValue } from "../lib/format.js";
import { useCallback } from "react";
export const lang3 = language => language === "uz" ? 1 : language === "en" ? 2 : 0;
export const useT = language => {
  const i = lang3(language);
  return useCallback((ru, uz, en) => [ru, uz, en][i] ?? ru, [i]);
};
export const DASH = "—";
export function fmtInt(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return Number(value).toLocaleString("ru-RU");
}
export function fmtNum(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return Number(value).toLocaleString("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}
export function fmtShare(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return `${(Number(value) * 100).toLocaleString("ru-RU", {
    minimumFractionDigits: digits,
    maximumFractionDigits: Math.max(digits, 1)
  })}%`;
}
export function fmtUsd(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return DASH;
  return `$${Number(value).toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  })}`;
}
export function fmtDuration(seconds, t) {
  if (seconds === null || seconds === undefined || Number.isNaN(Number(seconds))) return DASH;
  const total = roundedDisplayValue(Number(seconds));
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (!minutes) return t(`${rest} с`, `${rest} s`, `${rest}s`);
  return t(`${minutes} мин ${rest} с`, `${minutes} min ${rest} s`, `${minutes}m ${rest}s`);
}
export function fmtStamp(value, {
  withTime = true
} = {}) {
  if (!value) return DASH;
  const text = String(value).trim().replace(" ", "T");
  const date = new Date(/[Z+]|\d\d:\d\d$/.test(text) ? text : `${text}Z`);
  if (Number.isNaN(date.getTime())) return String(value);
  const opts = withTime ? {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  } : {
    day: "2-digit",
    month: "2-digit",
    year: "numeric"
  };
  return date.toLocaleString("ru-RU", opts).replace(",", " ·");
}
export function fmtAge(hours, t) {
  if (hours === null || hours === undefined) return DASH;
  if (hours < 1) return t("меньше часа назад", "bir soatdan kam", "less than an hour ago");
  if (hours < 48) return t(`${roundedDisplayValue(hours)} ч назад`, `${roundedDisplayValue(hours)} soat oldin`, `${roundedDisplayValue(hours)} h ago`);
  const days = roundedDisplayValue(hours / 24);
  return t(`${days} дн. назад`, `${days} kun oldin`, `${days} d ago`);
}
export function fmtDay(iso) {
  const parts = String(iso || "").split("-");
  return parts.length === 3 ? `${parts[2]}.${parts[1]}` : String(iso || "");
}
export function companyDraftOf(item) {
  if (!item) return null;
  return {
    ticker: String(item.ticker || "").toUpperCase(),
    company_name: item.company_name || "",
    org_id: item.org_id || "",
    isin: item.isin || "",
    sector: item.sector || "other",
    logo_url: item.logo_url || "",
    security_type: item.security_type || "stock",
    share_type: item.share_type || "",
    review_note: item.review_note || "",
    warnings: item.warnings || [],
    can_approve: item.can_approve !== false && Boolean(item.org_id),
    status: item.status || "pending",
    sync_status: item.sync_status || "",
    catalog_visible: item.catalog_visible !== 0
  };
}
export const SEVERITY_TONE = {
  blocking: "err",
  warning: "warn",
  info: "ok"
};
export const SECTIONS = [{
  key: "overview",
  icon: "dashboard",
  title: ["Обзор", "Umumiy", "Overview"]
}, {
  key: "audience",
  icon: "up",
  title: ["Аудитория", "Auditoriya", "Audience"]
}, {
  key: "engagement",
  icon: "chart",
  title: ["Вовлечённость", "Faollik", "Engagement"]
}, {
  key: "analysis",
  icon: "search",
  title: ["AI-анализ", "AI-tahlil", "AI analysis"]
}, {
  key: "users",
  icon: "users",
  title: ["Пользователи", "Foydalanuvchilar", "Users"]
}, {
  key: "feedback",
  icon: "news",
  title: ["Обратная связь", "Fikr-mulohaza", "Feedback"]
}, {
  key: "system",
  icon: "sliders",
  title: ["Система", "Tizim", "System"]
}];
export const SYSTEM_SECTIONS = [
  { key: "quality", title: ["Качество данных", "Ma'lumotlar sifati", "Data quality"] },{
  key: "system",
  title: ["Данные", "Ma'lumotlar", "Data"]
}, {
  key: "railway",
  title: ["Railway", "Railway", "Railway"]
}, {
  key: "companies",
  title: ["Компании", "Kompaniyalar", "Companies"]
}, {
  key: "streams",
  title: ["Сборщики", "Yig'uvchilar", "Collectors"]
}, {
  key: "findings",
  title: ["Аудит", "Audit", "Audit"]
}, {
  key: "intake",
  title: ["Отчёты", "Hisobotlar", "Statements"]
}, {
  key: "issuer",
  title: ["Эмитент", "Emitent", "Issuer"]
}, {
  key: "rules",
  title: ["Правила", "Qoidalar", "Rules"]
}, {
  key: "source",
  title: ["Источник", "Manba", "Source"]
}];
export const SYSTEM_KEYS = SYSTEM_SECTIONS.map(s => s.key);
export const ADMIN_SECTION_KEYS = [...SECTIONS.map(s => s.key), ...SYSTEM_KEYS.filter(k => k !== "system")];
