// The header, settings and value tooltip share one definition per metric.
export const TECHNICAL_TERMS = {
  ...Object.fromEntries([20, 50, 200].map(n => [`sma${n}`, {
    ru: {term:`SMA${n} — простая скользящая средняя (Simple Moving Average)`, def:`Среднее закрытие за последние ${n} сохранённых сессий сглаживает колебания и помогает оценить тренд. В колонке показано отклонение последнего закрытия от этой средней в процентах: плюс — выше средней, минус — ниже. Нужны все ${n} закрытий.`},
    uz: {term:`SMA${n} — oddiy sirg‘aluvchi o‘rtacha (Simple Moving Average)`, def:`Oxirgi ${n} saqlangan sessiyaning o‘rtacha yopilish narxi tebranishlarni yumshatib, trendni baholashga yordam beradi. Ustunda oxirgi yopilishning o‘rtachadan foizdagi farqi ko‘rsatiladi: musbat — yuqorida, manfiy — pastda. Barcha ${n} yopilish kerak.`},
    en: {term:`SMA${n} — Simple Moving Average`, def:`The average close over the last ${n} stored sessions smooths price swings to help identify the trend. This column shows the latest close's percentage distance from that average: positive means above it, negative means below. All ${n} closes are required.`},
  }])),
  high52w: {
    ru: {term:'52W High — максимум за 52 недели', def:'Самая высокая цена за последние 52 недели. Колонка показывает, на сколько процентов последнее закрытие отличается от этого максимума: −10% означает на 10% ниже него. Помогает оценить близость к годовому пику. Нужна полная история периода.'},
    uz: {term:'52W High — 52 haftalik maksimum', def:'Oxirgi 52 haftadagi eng yuqori narx. Ustun oxirgi yopilishning shu maksimumdan foizdagi farqini ko‘rsatadi: −10% undan 10% past degani. Yillik cho‘qqiga yaqinlikni baholashga yordam beradi. To‘liq davr tarixi kerak.'},
    en: {term:'52W High — 52-week high', def:'The highest price in the last 52 weeks. This column shows the latest close’s percentage distance from that high: −10% means 10% below it. It helps show how close the price is to its annual peak. Full period coverage is required.'},
  },
  low52w: {
    ru: {term:'52W Low — минимум за 52 недели', def:'Самая низкая цена за последние 52 недели. Колонка показывает, на сколько процентов последнее закрытие отличается от этого минимума: +30% означает на 30% выше него. Помогает оценить положение цены относительно годового дна. Нужна полная история периода.'},
    uz: {term:'52W Low — 52 haftalik minimum', def:'Oxirgi 52 haftadagi eng past narx. Ustun oxirgi yopilishning shu minimumdan foizdagi farqini ko‘rsatadi: +30% undan 30% yuqori degani. Narxning yillik minimumga nisbatan holatini ko‘rsatadi. To‘liq davr tarixi kerak.'},
    en: {term:'52W Low — 52-week low', def:'The lowest price in the last 52 weeks. This column shows the latest close’s percentage distance from that low: +30% means 30% above it. It helps locate the price relative to its annual bottom. Full period coverage is required.'},
  },
  rsi14: {
    ru: {term:'RSI (14) — индекс относительной силы (Relative Strength Index)', def:'Сравнивает сглаженную величину роста и снижения закрытий по методу Уайлдера с периодом 14 сессий. Шкала от 0 до 100: высокое значение означает преобладание роста, низкое — снижения. Помогает оценить импульс движения цены; это не сравнение с рыночным индексом.'},
    uz: {term:'RSI (14) — nisbiy kuch indeksi (Relative Strength Index)', def:'14 sessiyalik Wilder usuli bilan yopilish narxlarining silliqlangan ko‘tarilish va pasayish miqdorini solishtiradi. Shkala 0 dan 100 gacha: yuqori qiymat o‘sish, past qiymat pasayish ustunligini bildiradi. Narx harakati kuchini baholaydi; bozor indeksi bilan taqqoslash emas.'},
    en: {term:'RSI (14) — Relative Strength Index', def:'Compares smoothed close-to-close gains and losses using Wilder’s 14-session method. Its scale is 0–100: high values mean gains dominate, low values mean losses dominate. It helps assess price momentum; it does not compare the stock with a market index.'},
  },
  atr14: {
    ru: {term:'ATR (14) — средний истинный диапазон (Average True Range)', def:'Средняя амплитуда колебаний по методу Уайлдера за 14 сессий, с учётом разрывов относительно предыдущего закрытия. Измеряется в узбекских сумах (UZS): ATR 3,5 означает диапазон 3,5 сума. Показывает волатильность, а не направление движения.'},
    uz: {term:'ATR (14) — o‘rtacha haqiqiy diapazon (Average True Range)', def:'14 sessiyalik Wilder usulida narx tebranishlarining o‘rtacha diapazoni; oldingi yopilishga nisbatan uzilishlarni ham hisobga oladi. O‘zbekiston so‘mida (UZS) o‘lchanadi: ATR 3,5 — 3,5 so‘mlik diapazon. Harakat yo‘nalishini emas, o‘zgaruvchanlikni ko‘rsatadi.'},
    en: {term:'ATR (14) — Average True Range', def:'Wilder’s average trading range over 14 sessions, including gaps from the previous close. Measured in Uzbek soum (UZS): ATR 3.5 means a range of 3.5 soum. It measures volatility, not the direction of price movement.'},
  },
  beta: {
    ru: {term:'Beta — коэффициент чувствительности к рынку', def:'Оценивает, как доходность акции исторически реагировала на изменение рыночного индекса. Используется для сравнения рыночного риска. Сейчас значение недоступно: нет проверенной истории индекса для расчёта.'},
    uz: {term:'Beta — bozorga sezuvchanlik koeffitsiyenti', def:'Aksiya daromadliligi tarixan bozor indeksi o‘zgarishiga qanday javob berganini baholaydi. Bozor xatarini solishtirish uchun ishlatiladi. Hisoblash uchun tasdiqlangan indeks tarixi yo‘qligi sababli hozir qiymat mavjud emas.'},
    en: {term:'Beta — market sensitivity coefficient', def:'Estimates how the stock’s returns have historically responded to changes in a market index. It is used to compare market risk. Currently unavailable because verified benchmark-index history is missing.'},
  },
  dayChange: {
    ru: {term:'Изм. за сессию — изменение цены за сессию', def:'Последнее закрытие / предыдущее сохранённое закрытие − 1, в процентах. Показывает рост или снижение между двумя сессиями. В Technical всегда относится к последней сохранённой сессии, независимо от выбранного периода таблицы.'},
    uz: {term:'Sessiya o‘zgarishi — sessiyalik narx o‘zgarishi', def:'Oxirgi yopilish / oldingi saqlangan yopilish − 1, foizda. Ikki sessiya orasidagi o‘sish yoki pasayishni ko‘rsatadi. Technical uchun jadval davridan qat’i nazar, oxirgi saqlangan sessiya olinadi.'},
    en: {term:'Session change — close-to-close price change', def:'Latest close / previous stored close − 1, in percent. Shows the rise or fall between sessions. In Technical it always describes the latest stored session, regardless of the table’s selected period.'},
  },
  changeOpen: {
    ru: {term:'От открытия — изменение от цены открытия', def:'Последнее закрытие / открытие той же сессии − 1, в процентах. Показывает, выросла или снизилась цена внутри сессии, отдельно от разрыва на открытии.'},
    uz: {term:'Ochilishdan — ochilish narxidan o‘zgarish', def:'Oxirgi yopilish / shu sessiya ochilishi − 1, foizda. Ochilishdagi uzilishdan alohida, sessiya ichida narx ko‘tarilgan yoki pasayganini ko‘rsatadi.'},
    en: {term:'Change from open — price movement within the session', def:'Latest close / same-session open − 1, in percent. Shows whether the price rose or fell during the session, separately from the opening gap.'},
  },
  gap: {
    ru: {term:'Gap — ценовой разрыв на открытии', def:'Открытие / предыдущее сохранённое закрытие − 1, в процентах. Плюс означает открытие выше предыдущего закрытия, минус — ниже. Помогает отделить движение между сессиями от движения внутри дня.'},
    uz: {term:'Gap — ochilishdagi narx uzilishi', def:'Ochilish / oldingi saqlangan yopilish − 1, foizda. Musbat qiymat oldingi yopilishdan yuqori, manfiy qiymat past ochilganini bildiradi. Sessiyalar orasidagi harakatni kun ichidagi harakatdan ajratadi.'},
    en: {term:'Gap — opening price gap', def:'Open / previous stored close − 1, in percent. Positive means the session opened above the previous close; negative means below. It separates movement between sessions from movement during the day.'},
  },
  dayVolume: {
    ru: {term:'Объём, шт. — объём торгов в акциях', def:'Количество акций, проданных в последней сохранённой сессии. Показывает торговую активность в штуках, а не денежный оборот. Отсутствующее значение — «—», подтверждённый ноль — 0.'},
    uz: {term:'Hajm, dona — sotilgan aksiyalar soni', def:'Oxirgi saqlangan sessiyada sotilgan aksiyalar miqdori. Savdo faolligini pul aylanmasida emas, donalarda ko‘rsatadi. Ma’lumot yo‘q bo‘lsa — «—», tasdiqlangan nol bo‘lsa — 0.'},
    en: {term:'Volume, shares — number of shares traded', def:'The number of shares traded in the latest stored session. It measures trading activity in shares, not monetary turnover. Missing data is “—”; a confirmed zero is 0.'},
  },
};
