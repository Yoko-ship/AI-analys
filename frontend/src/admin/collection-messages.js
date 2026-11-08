// Wording is selected from recorded cause codes; never guess a cause from an exit code.
const CAUSES = {
  table_missing: ["Таблица не найдена в опубликованных данных.", "E’lon qilingan ma’lumotlarda jadval topilmadi.", "The table was not found in the published data."],
  format_changed: ["не удалось прочитать формат таблицы.", "jadval formatini o‘qib bo‘lmadi.", "the table format could not be read."],
  rate_limited: ["Источник временно ограничил количество запросов.", "Manba so‘rovlar sonini vaqtincha chekladi.", "The source temporarily limited the number of requests."],
  access_denied: ["Источник отказал в доступе к данным.", "Manba ma’lumotlarga kirishni rad etdi.", "The source refused access to the data."],
  source_timeout: ["Источник не ответил за отведённое время.", "Manba belgilangan vaqtda javob bermadi.", "The source did not respond in time."],
  source_unavailable: ["Не удалось связаться с источником данных.", "Ma’lumot manbasiga ulanib bo‘lmadi.", "The data source could not be reached."],
  publication_unavailable: ["Не удалось сохранить полученные данные на сайте.", "Olingan ma’lumotlarni saytga saqlab bo‘lmadi.", "The collected data could not be saved to the website."],
  missing_dependency: ["На сервере не хватает компонента для этого сбора.", "Serverda ushbu yig‘ish uchun zarur dasturiy qism yetishmayapti.", "The server is missing a component required for this collection."],
  credentials_missing: ["Для сбора не настроен доступ к данным.", "Yig‘ish uchun ma’lumotlarga kirish sozlanmagan.", "Access credentials for this collection have not been configured."],
  storage_error: ["Сервер не смог записать данные в хранилище.", "Server ma’lumotlarni saqlash joyiga yoza olmadi.", "The server could not write to its data storage."],
  time_limit: ["Сбор занял больше разрешённого времени и был остановлен.", "Yig‘ish ruxsat etilgan vaqtdan oshdi va to‘xtatildi.", "The collection exceeded its allowed time and was stopped."],
  memory_limit: ["Сбор остановлен: серверу не хватило выделенной памяти.", "Yig‘ish to‘xtatildi: ajratilgan xotira yetmadi.", "The collection stopped because it exceeded its memory allowance."],
  interrupted: ["Сбор был прерван извне. Кто его остановил, в этих данных не указано.", "Yig‘ish tashqaridan to‘xtatildi. Kim to‘xtatgani bu ma’lumotlarda ko‘rsatilmagan.", "The collection was interrupted externally. These records do not identify who stopped it."],
  document_missing: ["В раскрытии не найдена ссылка на файл отчёта.", "E’londa hisobot fayliga havola topilmadi.", "The filing has no linked report file."],
  empty_filing: ["В отчёте не найдены пригодные для загрузки финансовые значения.", "Hisobotda yuklash uchun yaroqli moliyaviy qiymatlar topilmadi.", "The report contains no financial values that passed the loading checks."],
  unknown: ["Точная причина не записана в доступном журнале.", "Aniq sabab mavjud jurnalda qayd etilmagan.", "The available log does not record the exact cause."],
};
const DATASETS = {
  npl: ["Проблемные кредиты", "Muammoli kreditlar", "Non-performing loans"],
  main: ["Показатели банков", "Bank ko‘rsatkichlari", "Bank indicators"],
  structure: ["Кредиты и депозиты", "Kreditlar va depozitlar", "Loans and deposits"],
  capital: ["Капитал банков", "Bank kapitali", "Bank capital"],
  liquidity: ["Ликвидность", "Likvidlik", "Liquidity"],
  profitability: ["Доходность банков", "Bank rentabelligi", "Bank profitability"],
  industry: ["Кредиты по отраслям", "Tarmoqlar bo‘yicha kreditlar", "Loans by industry"],
  inflation: ["Инфляция", "Inflyatsiya", "Inflation"],
  rates: ["Процентные ставки", "Foiz stavkalari", "Interest rates"],
  fsi: ["Финансовая устойчивость", "Moliyaviy barqarorlik", "Financial soundness"],
  fx: ["Исторические курсы валют", "Tarixiy valyuta kurslari", "Historical exchange rates"],
};
const FIELDS = {
  cash: ["денежные средства", "pul mablag‘lari", "cash"],
  total_liabilities: ["обязательства", "majburiyatlar", "liabilities"],
  total_equity: ["капитал", "kapital", "equity"],
  total_assets: ["активы", "aktivlar", "assets"],
  revenue: ["выручка", "tushum", "revenue"],
  gross_profit: ["валовая прибыль", "yalpi foyda", "gross profit"],
  operating_income: ["операционная прибыль", "operatsion foyda", "operating profit"],
  net_income: ["чистая прибыль", "sof foyda", "net profit"],
};
const periodText = period => /^\d{4}-\d{2}$/.test(period || "") ? period.slice(5) + "." + period.slice(0, 4) : period || "";
export const datasetNames = (issue, t) => (issue.datasets || []).map(key => t(...(DATASETS[key] || ["Данные источника", "Manba ma’lumotlari", "Source data"])));
export function issueText(issue, t) {
  const names = datasetNames(issue, t);
  const scope = [issue.ticker, periodText(issue.period)].filter(Boolean).join(" · ");
  if (issue.code === "table_missing" && issue.period) return t(
    `Не найдены таблицы за ${periodText(issue.period)}: ${names.length}.`,
    `${periodText(issue.period)} uchun topilmagan jadvallar: ${names.length}.`,
    `Tables not found for ${periodText(issue.period)}: ${names.length}.`);
  if (issue.code === "period_mismatch") return `${scope}: ` + t(
    `отчёт не прошёл проверку периода; дата внутри документа — ${issue.actual_date}.`,
    `hisobot davri tekshiruvdan o‘tmadi; hujjat ichidagi sana — ${issue.actual_date}.`,
    `the report failed the period check; the date inside the document is ${issue.actual_date}.`);
  if (issue.code === "incomplete_values") {
    const fields = (issue.fields || []).map(key => t(...(FIELDS[key] || ["финансовый показатель", "moliyaviy ko‘rsatkich", "financial value"]))).join(", ");
    return `${scope}: ` + t(`новый отчёт не содержит ранее сохранённые значения (${fields}). Замена отклонена.`,
      `yangi hisobotda oldin saqlangan qiymatlar yo‘q (${fields}). Almashtirish rad etildi.`,
      `the new report omits previously saved values (${fields}). The replacement was rejected.`);
  }
  const prefix = issue.code === "format_changed" && names.length ? names.join(", ") : scope;
  return (prefix ? prefix + ": " : "") + t(...(CAUSES[issue.code] || CAUSES.unknown));
}
export function runSummary(run, t) {
  const messages = {
    partial: ["Обновление выполнено частично.", "Yangilash qisman bajarildi.", "The update completed only in part."],
    failed: ["Обновление остановилось с ошибкой.", "Yangilash xato bilan to‘xtadi.", "The update stopped with an error."],
    running: ["Сбор данных выполняется.", "Ma’lumotlar yig‘ilmoqda.", "Data collection is running."],
    no_change: ["Новых данных для обновления нет.", "Yangilash uchun yangi ma’lumot yo‘q.", "There is no new data to update."],
    unknown: ["Результат запуска ещё не получен.", "Ishga tushirish natijasi hali olinmagan.", "No run result has been received yet."],
    completed: run.publication === "acknowledged"
      ? ["Обновление завершено.", "Yangilash tugallandi.", "The update completed."]
      : ["Сбор завершился, но сохранение данных не подтверждено.", "Yig‘ish tugadi, lekin ma’lumotlar saqlangani tasdiqlanmadi.", "Collection finished, but saving the data has not been confirmed."],
  };
  return t(...(messages[run.status] || messages.unknown));
}
export function runIssues(run) {
  return run.diagnosis?.issues || (["failed", "partial"].includes(run.status) ? [{ code: "unknown" }] : []);
}
export function nextAction(run, t) {
  const codes = runIssues(run).map(i => i.code);
  if (!codes.length) return "";
  if (codes.some(c => ["format_changed", "period_mismatch", "incomplete_values", "empty_filing", "document_missing", "missing_dependency", "credentials_missing", "storage_error"].includes(c)))
    return t("Нужна проверка источника или загрузчика разработчиком. Повторный запуск сам по себе может не помочь.",
      "Manba yoki yuklash dasturini dasturchi tekshirishi kerak. Qayta ishga tushirishning o‘zi yordam bermasligi mumkin.",
      "A developer needs to check the source or loader. Running it again may not resolve this.");
  if (codes.every(c => c === "table_missing")) return t(
    "Проверим снова по расписанию. Если таблицы уже есть на сайте источника, нужно проверить их поиск.",
    "Jadval bo‘yicha yana tekshiriladi. Jadvallar manba saytida mavjud bo‘lsa, ularni qidirishni tekshirish kerak.",
    "The next scheduled run will check again. If the tables are already on the source website, their discovery needs checking.");
  if (codes.includes("unknown")) return t("Повторите запуск один раз. Если ошибка повторится, передайте разработчику технические подробности.",
    "Bir marta qayta ishga tushiring. Xato takrorlansa, texnik tafsilotlarni dasturchiga bering.",
    "Retry once. If it fails again, give a developer the technical details.");
  return t("Дождитесь следующего запуска по расписанию или повторите позже. Если ошибка повторяется, нужна проверка разработчиком.",
    "Keyingi rejalashtirilgan ishga tushirishni kuting yoki keyinroq qayta urinib ko‘ring. Xato takrorlansa, dasturchi tekshiruvi kerak.",
    "Wait for the next scheduled run or retry later. Repeated failures need a developer to investigate.");
}
export function scheduleText(schedule, t) {
  return (schedule || "—").replace(/daily/g, t("ежедневно", "har kuni", "daily"))
    .replace(/Mon–Fri/g, t("пн–пт", "du–ju", "Mon–Fri")).replace(/Mon–Sat/g, t("пн–сб", "du–sha", "Mon–Sat"))
    .replace(/hourly/g, t("каждый час", "har soatda", "hourly"));
}
export function requestText(status, t) {
  const text = {
    queued: ["Ожидает запуска. Повторно нажимать кнопку не нужно.", "Ishga tushishni kutmoqda. Tugmani qayta bosish shart emas.", "Waiting to start. There is no need to click again."],
    dispatching: ["Передаём запрос на запуск.", "Ishga tushirish so‘rovi yuborilmoqda.", "Sending the start request."],
    dispatched: ["Запуск принят, ожидаем результат.", "Ishga tushirish qabul qilindi, natija kutilmoqda.", "The start was accepted; waiting for the result."],
    uncertain: ["Не удалось подтвердить запуск. Перед повтором нужно проверить, не выполняется ли сбор.", "Ishga tushgani tasdiqlanmadi. Qayta urinishdan oldin yig‘ish ishlamayotganini tekshiring.", "The start could not be confirmed. Check whether collection is running before retrying."],
    expired: ["Запрос не был выполнен вовремя. Можно отправить его снова.", "So‘rov o‘z vaqtida bajarilmadi. Qayta yuborish mumkin.", "The request was not picked up in time. You can submit it again."],
    failed: ["Не удалось запустить сбор.", "Yig‘ishni ishga tushirib bo‘lmadi.", "The collection could not be started."],
    cleared: ["Запрос снят с очереди.", "So‘rov navbatdan olindi.", "The request was removed from the queue."],
    finished: ["Запуск завершён. Результат указан в истории.", "Ish tugallandi. Natija tarixda ko‘rsatilgan.", "The run finished. Its result is in the history."],
  };
  return t(...(text[status] || text.uncertain));
}
