export const NEWSCAL_TX = {
  ru: {
    views: {
      events: "Собрания",
      announcements: "Объявления",
      dividends: "Дивиденды"
    },
    viewHint: {
      events: "Объявленные общие собрания акционеров — по дате проведения",
      announcements: "Сообщения о созыве собраний — по дате публикации",
      dividends: "Объявленные дивиденды всего рынка — суммы, проценты и окна выплат"
    },
    weekdays: ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
    loading: "Загружаем календарь…",
    error: "Не удалось загрузить календарь.",
    emptyMonth: "На этот месяц собраний не заявлено.",
    wholeMonth: "Весь месяц",
    mode: {
      month: "Месяц",
      year: "Год"
    },
    searchPh: "Эмитент или тикер…",
    download: "Скачать CSV",
    divTypes: {
      common: "Простые акции",
      preferred: "Привилегированные",
      bond: "Облигации"
    },
    th: {
      issuer: "Эмитент",
      decision: "Дата решения",
      amount: "Сумма, сум",
      window: "Реестр / выплата",
      org: "Организация",
      title: "Название",
      pub: "Дата публикации",
      meeting: "Дата собрания"
    },
    pager: {
      perPage: "Показывать по",
      shown: "Показаны",
      of: "из"
    },
    annEmpty: "Объявлений не найдено.",
    divEmpty: "Данных по дивидендам пока нет.",
    divNote: "Суммы — на одну бумагу по решению собрания; период — окно закрытия реестра и выплаты.",
    source: "Источник: openinfo.uz"
  },
  en: {
    views: {
      events: "Meetings",
      announcements: "Announcements",
      dividends: "Dividends"
    },
    viewHint: {
      events: "Announced general shareholder meetings, by meeting date",
      announcements: "Meeting convocation notices, by publication date",
      dividends: "Declared dividends across the market — amounts, percents and payout windows"
    },
    weekdays: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    loading: "Loading the calendar…",
    error: "Could not load the calendar.",
    emptyMonth: "No meetings announced for this month.",
    wholeMonth: "Whole month",
    mode: {
      month: "Month",
      year: "Year"
    },
    searchPh: "Issuer or ticker…",
    download: "Download CSV",
    divTypes: {
      common: "Ordinary shares",
      preferred: "Preferred",
      bond: "Bonds"
    },
    th: {
      issuer: "Issuer",
      decision: "Decision date",
      amount: "Amount, UZS",
      window: "Record / payment",
      org: "Organization",
      title: "Title",
      pub: "Published",
      meeting: "Meeting date"
    },
    pager: {
      perPage: "Per page",
      shown: "Showing",
      of: "of"
    },
    annEmpty: "No announcements found.",
    divEmpty: "No dividend data yet.",
    divNote: "Amounts are per security, as resolved by the meeting; the window runs from the record date to the end of payment.",
    source: "Source: openinfo.uz"
  },
  uz: {
    views: {
      events: "Yig'ilishlar",
      announcements: "E'lonlar",
      dividends: "Dividendlar"
    },
    viewHint: {
      events: "E'lon qilingan umumiy yig'ilishlar — o'tkazish sanasi bo'yicha",
      announcements: "Yig'ilish chaqiruvi haqidagi xabarlar — e'lon sanasi bo'yicha",
      dividends: "Butun bozor bo'yicha e'lon qilingan dividendlar — summalar, foizlar va to'lov oynalari"
    },
    weekdays: ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"],
    loading: "Taqvim yuklanmoqda…",
    error: "Taqvimni yuklab bo'lmadi.",
    emptyMonth: "Bu oyga yig'ilishlar e'lon qilinmagan.",
    wholeMonth: "Butun oy",
    mode: {
      month: "Oy",
      year: "Yil"
    },
    searchPh: "Emitent yoki tiker…",
    download: "CSV yuklab olish",
    divTypes: {
      common: "Oddiy aksiyalar",
      preferred: "Imtiyozli",
      bond: "Obligatsiyalar"
    },
    th: {
      issuer: "Emitent",
      decision: "Qaror sanasi",
      amount: "Summa, so'm",
      window: "Reyestr / to'lov",
      org: "Tashkilot",
      title: "Nomi",
      pub: "E'lon sanasi",
      meeting: "Yig'ilish sanasi"
    },
    pager: {
      perPage: "Sahifada",
      shown: "Ko'rsatildi",
      of: "/"
    },
    annEmpty: "E'lonlar topilmadi.",
    divEmpty: "Dividendlar bo'yicha ma'lumot hozircha yo'q.",
    divNote: "Summalar — yig'ilish qarori bo'yicha bitta qog'ozga; davr — reyestr yopilishidan to'lov oxirigacha.",
    source: "Manba: openinfo.uz"
  }
};
export const NEWS_CALENDAR_POLL_MS = 5 * 60 * 1000;
export function calendarAnnouncementPath(item) {
  const id = String(item?.announcement_id || "").trim();
  if (!id) return "";
  return `/news/announcement/${encodeURIComponent(id)}`;
}
