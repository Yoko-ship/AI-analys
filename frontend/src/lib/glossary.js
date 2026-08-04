/**
 * One glossary for the whole site (ТЗ §3.2).
 *
 * It backs the ⓘ marker beside every economic label in the interface. A term
 * defined twice drifts, so it is defined once here and looked up by id.
 *
 * These definitions outlived the /reference «Термины» page (deleted in f8d1132).
 * That page asked the reader to go somewhere else and remember; the marker answers
 * where the question is actually asked, which is the better place for them.
 *
 * Where a term has a textbook meaning AND a specific meaning on this site, the
 * definition states OURS — which filing the number comes from, which convention
 * the exchange uses, what the cell does when the data is missing. A reader who
 * wanted the textbook line already has one; what they cannot get anywhere else is
 * what the number in front of them actually counts.
 *
 * `id` matches the market board's column key wherever one exists, so a header can
 * ask for its own definition without a second mapping to keep in step.
 */

export const TERMS = {
  // ── Котировки и торги: the market board's own columns ─────────────────────
  ticker: {
    ru: { term: "Тикер", def: "Короткий буквенный код бумаги на бирже. Например, Hamkorbank — HMKB, его привилегированные акции — HMKBP: буква P на конце почти всегда означает преф." },
    en: { term: "Ticker", def: "The exchange's short letter code for a security. Hamkorbank is HMKB; its preferred shares are HMKBP — a trailing P nearly always marks a preferred class." },
    uz: { term: "Ticker", def: "Qimmatli qog‘ozning birjadagi qisqa harfli kodi. Masalan, Hamkorbank — HMKB, uning imtiyozli aksiyalari — HMKBP: oxiridagi P harfi deyarli har doim imtiyozli sinfni bildiradi." },
  },
  last: {
    ru: { term: "Последняя цена", def: "Цена последней исполненной сделки. Если в этот день сделок не было, биржа переносит цену предыдущей сессии — поэтому дата сделки рядом важнее самой цены." },
    en: { term: "Last price", def: "The price of the most recent executed trade. On a day with no trades the exchange carries the previous session's price forward, which is why the trade date beside it matters more than the price itself." },
    uz: { term: "Oxirgi narx", def: "Oxirgi bajarilgan bitim narxi. Agar o‘sha kuni bitim bo‘lmasa, birja oldingi sessiya narxini ko‘chiradi — shu sababli yonidagi bitim sanasi narxning o‘zidan muhimroq." },
  },
  change: {
    ru: { term: "Изменение (Изм.)", def: "Изменение цены закрытия к закрытию предыдущей торговой сессии — та же формула, что в официальном бюллетене биржи. Это НЕ отклонение от средней цены дня." },
    en: { term: "Change", def: "Close against the previous session's close — the exchange's own daily-bulletin convention. It is not the move against the day's average price." },
    uz: { term: "O‘zgarish", def: "Yopilish narxining oldingi sessiya yopilishiga nisbatan o‘zgarishi — birjaning kunlik byulletenidagi formulaning o‘zi. Bu kunlik o‘rtacha narxdan chetlanish EMAS." },
  },
  open: {
    ru: { term: "Открытие", def: "Цена первой сделки торговой сессии. На бирже с редкими сделками открытие часто совпадает с максимумом и минимумом — это значит, что за день прошла одна сделка." },
    en: { term: "Open", def: "The session's first trade price. On a thin market the open often equals the high and the low, which simply means the day held a single trade." },
    uz: { term: "Ochilish", def: "Sessiyaning birinchi bitim narxi. Bitimlari kam bozorda ochilish ko‘pincha maksimum va minimum bilan bir xil bo‘ladi — bu kun davomida bitta bitim bo‘lganini bildiradi." },
  },
  high: {
    ru: { term: "Максимум", def: "Наибольшая цена сделки за торговую сессию." },
    en: { term: "High", def: "The highest trade price of the session." },
    uz: { term: "Maksimum", def: "Sessiyadagi eng yuqori bitim narxi." },
  },
  low: {
    ru: { term: "Минимум", def: "Наименьшая цена сделки за торговую сессию." },
    en: { term: "Low", def: "The lowest trade price of the session." },
    uz: { term: "Minimum", def: "Sessiyadagi eng past bitim narxi." },
  },
  date: {
    ru: { term: "Дата сделки", def: "Сессия, к которой относится цена в строке. Подпись «закр.» под датой — сессия, чьё закрытие взято базой для расчёта изменения. Если дата старая, цена не устарела «по ошибке»: по этой бумаге просто давно не было сделок." },
    en: { term: "Trade date", def: "The session the row's price belongs to. The «close» line beneath it is the session whose close the change is measured against. An old date is not a stale number by mistake — it means the security simply has not traded since." },
    uz: { term: "Bitim sanasi", def: "Qatordagi narx tegishli bo‘lgan sessiya. Sana ostidagi «yop.» — o‘zgarish hisoblanadigan baza sessiya yopilishi. Eski sana xato emas: bu qog‘oz bo‘yicha shundan beri bitim bo‘lmagan." },
  },
  volume: {
    ru: { term: "Объём", def: "Оборот по бумаге за сессию в сумах — сумма всех сделок, а не количество бумаг. Считается по протоколу сделок биржи; под числом указано, из скольких сделок он сложился." },
    en: { term: "Turnover", def: "The session's turnover in soum — the value of all trades, not the number of shares. Computed from the exchange's own trade log; the line beneath says how many trades make it up." },
    uz: { term: "Aylanma", def: "Sessiya davomida qog‘oz bo‘yicha so‘mdagi aylanma — barcha bitimlar summasi, qog‘ozlar soni emas. Birjaning bitimlar bayonnomasi bo‘yicha hisoblanadi; ostida nechta bitimdan tashkil topgani ko‘rsatilgan." },
  },
  volQty: {
    ru: { term: "Объём (шт)", def: "Сколько бумаг перешло из рук в руки за сессию. В паре с оборотом в сумах показывает, крупными или мелкими лотами шла торговля." },
    en: { term: "Volume (shares)", def: "How many securities changed hands during the session. Read together with the soum turnover it says whether trading came in large or small lots." },
    uz: { term: "Hajm (dona)", def: "Sessiya davomida qo‘ldan qo‘lga o‘tgan qog‘ozlar soni. So‘mdagi aylanma bilan birga o‘qilsa, savdo yirik yoki mayda lotlarda ketganini ko‘rsatadi." },
  },
  avgShare: {
    ru: { term: "Средняя цена акции", def: "Оборот, делённый на количество бумаг: средневзвешенная по объёму цена сессии (VWAP). Отличается от цены закрытия — показывает, по какой цене реально прошла основная масса бумаг." },
    en: { term: "Average share price", def: "Turnover divided by shares traded: the session's volume-weighted average price (VWAP). It differs from the close and shows the price at which the bulk of the shares actually changed hands." },
    uz: { term: "O‘rtacha aksiya narxi", def: "Aylanmaning qog‘ozlar soniga nisbati: sessiyaning hajm bo‘yicha o‘rtacha og‘irlangan narxi (VWAP). Yopilish narxidan farq qiladi va qog‘ozlarning asosiy qismi qaysi narxda o‘tganini ko‘rsatadi." },
  },
  avgTrade: {
    ru: { term: "Средняя сумма сделки", def: "Оборот, делённый на число сделок, — средний чек одной сделки в сумах. Большое значение говорит о присутствии крупных участников, малое — о рознице." },
    en: { term: "Average trade size", def: "Turnover divided by the number of trades — the average ticket in soum. A large figure points to institutional participants, a small one to retail." },
    uz: { term: "O‘rtacha bitim summasi", def: "Aylanmaning bitimlar soniga nisbati — bitta bitimning so‘mdagi o‘rtacha summasi. Katta qiymat yirik ishtirokchilar borligini, kichigi chakana savdoni bildiradi." },
  },
  bigTrade: {
    ru: { term: "Крупнейшая сделка", def: "Самая большая по сумме сделка сессии. Если она сопоставима со всем оборотом дня, весь «объём» — это одна сделка, а не активный рынок." },
    en: { term: "Largest trade", def: "The session's single biggest trade by value. When it is close to the whole day's turnover, that turnover is one deal rather than an active market." },
    uz: { term: "Eng yirik bitim", def: "Sessiyaning summasi bo‘yicha eng katta bitimi. Agar u kunlik aylanmaga yaqin bo‘lsa, bu «hajm» faol bozor emas, bitta bitimdir." },
  },
  volShare: {
    ru: { term: "% объёма", def: "Доля бумаги в обороте всей биржи за эту сессию. Считается только по последней сессии: бумага, торговавшаяся в другой день, получает 0." },
    en: { term: "% of turnover", def: "The security's share of the whole exchange's turnover for this session. It counts the latest session only — a security that traded on another day gets 0." },
    uz: { term: "Aylanma ulushi, %", def: "Qog‘ozning shu sessiyadagi butun birja aylanmasidagi ulushi. Faqat oxirgi sessiya bo‘yicha hisoblanadi: boshqa kuni savdolangan qog‘oz 0 oladi." },
  },

  // ── Рыночные термины ──────────────────────────────────────────────────────
  bid: {
    ru: { term: "Bid", def: "Цена, по которой покупатель готов купить бумагу прямо сейчас." },
    en: { term: "Bid", def: "The price at which a buyer is ready to buy right now." },
    uz: { term: "Bid", def: "Xaridor hozirning o‘zida sotib olishga tayyor bo‘lgan narx." },
  },
  ask: {
    ru: { term: "Ask", def: "Цена, по которой продавец готов продать бумагу прямо сейчас." },
    en: { term: "Ask", def: "The price at which a seller is ready to sell right now." },
    uz: { term: "Ask", def: "Sotuvchi hozirning o‘zida sotishga tayyor bo‘lgan narx." },
  },
  spread: {
    ru: { term: "Спред bid/ask", def: "Разница между Ask и Bid. Чем уже спред, тем выше ликвидность; широкий спред означает, что войти и выйти дорого." },
    en: { term: "Bid/ask spread", def: "The gap between ask and bid. A narrow spread means high liquidity; a wide one means entering and exiting is expensive." },
    uz: { term: "Bid/ask spredi", def: "Ask va Bid o‘rtasidagi farq. Spred qanchalik tor bo‘lsa, likvidlik shunchalik yuqori; keng spred kirish va chiqish qimmatligini bildiradi." },
  },
  vwap: {
    ru: { term: "VWAP", def: "Средневзвешенная по объёму цена за период. Учитывает, сколько бумаг куплено по каждой цене, — профессиональный ориентир «справедливой» цены дня." },
    en: { term: "VWAP", def: "Volume-weighted average price over a period. It accounts for how many shares traded at each price — the professional benchmark for a fair price of the day." },
    uz: { term: "VWAP", def: "Davr uchun hajm bo‘yicha o‘rtacha og‘irlangan narx. Har bir narxda nechta qog‘oz sotib olinganini hisobga oladi — kunning «adolatli» narxi uchun professional mo‘ljal." },
  },
  freeFloat: {
    ru: { term: "Free-float", def: "Доля акций, реально торгующихся на бирже. Чем ниже free-float, тем ниже ликвидность и тем легче сдвинуть цену." },
    en: { term: "Free float", def: "The share of stock that actually trades on the exchange. The lower the float, the lower the liquidity and the easier the price is to move." },
    uz: { term: "Free-float", def: "Birjada haqiqatan savdolanadigan aksiyalar ulushi. Free-float qancha past bo‘lsa, likvidlik shuncha past va narxni siljitish shuncha oson." },
  },
  ownership: {
    ru: { term: "Концентрация владения", def: "Насколько акции сосредоточены у небольшого числа акционеров. Высокая концентрация — риск резкого движения цены при выходе крупного держателя." },
    en: { term: "Ownership concentration", def: "How far the shares are held by a small number of holders. High concentration means the price can move sharply when a large holder exits." },
    uz: { term: "Egalik konsentratsiyasi", def: "Aksiyalarning kichik sondagi aksiyadorlarda to‘planganlik darajasi. Yuqori konsentratsiya — yirik egasi chiqqanda narx keskin o‘zgarishi xavfi." },
  },
  liquidity: {
    ru: { term: "Ликвидность", def: "Свойство бумаги быть быстро купленной или проданной по цене, близкой к рыночной, без существенных потерь и при узком спреде." },
    en: { term: "Liquidity", def: "How readily a security can be bought or sold near its market price, without material loss and on a narrow spread." },
    uz: { term: "Likvidlik", def: "Qog‘ozning bozor narxiga yaqin narxda, sezilarli yo‘qotishsiz va tor spredda tez sotib olinishi yoki sotilishi xususiyati." },
  },
  volatility: {
    ru: { term: "Волатильность", def: "Насколько резко и быстро меняется цена. Высокая — цена скачет, низкая — движется плавно." },
    en: { term: "Volatility", def: "How sharply and quickly the price moves. High volatility jumps; low volatility drifts." },
    uz: { term: "Volatillik", def: "Narxning qanchalik keskin va tez o‘zgarishi. Yuqori bo‘lsa narx sakraydi, past bo‘lsa silliq harakatlanadi." },
  },

  // ── Периоды и сравнения ───────────────────────────────────────────────────
  qoq: {
    ru: { term: "QoQ (Quarter over Quarter)", def: "Изменение показателя относительно предыдущего квартала." },
    en: { term: "QoQ (quarter over quarter)", def: "The change in a figure against the previous quarter." },
    uz: { term: "QoQ (chorakma-chorak)", def: "Ko‘rsatkichning oldingi chorakka nisbatan o‘zgarishi." },
  },
  yoy: {
    ru: { term: "YoY (Year over Year)", def: "Изменение относительно того же периода прошлого года. Устраняет сезонный эффект." },
    en: { term: "YoY (year over year)", def: "The change against the same period a year earlier. It removes the seasonal effect." },
    uz: { term: "YoY (yildan yilga)", def: "O‘tgan yilning shu davriga nisbatan o‘zgarish. Mavsumiy ta’sirni yo‘qotadi." },
  },
  ytd: {
    ru: { term: "YTD (Year to Date)", def: "Изменение с начала текущего года по сегодняшний день." },
    en: { term: "YTD (year to date)", def: "The change from the start of the current year to today." },
    uz: { term: "YTD (yil boshidan)", def: "Joriy yil boshidan bugungi kungacha bo‘lgan o‘zgarish." },
  },
  movingAverage: {
    ru: { term: "Скользящее среднее", def: "Среднее значение за последние N периодов, пересчитываемое каждый день." },
    en: { term: "Moving average", def: "The average of the last N periods, recomputed every day." },
    uz: { term: "Siljuvchi o‘rtacha", def: "Oxirgi N davr uchun o‘rtacha qiymat, har kuni qayta hisoblanadi." },
  },

  // ── Финансовые показатели ─────────────────────────────────────────────────
  finRevenue: {
    ru: { term: "Выручка", def: "Все деньги от продажи товаров и услуг за период, до вычета расходов, — первая строка отчёта о прибылях. Берётся из раскрытия эмитента на openinfo.uz; период подписан под числом, потому что у разных эмитентов это может быть квартал, полугодие или год." },
    en: { term: "Revenue", def: "All money from sales of goods and services in the period, before any costs — the top line of the income statement. Taken from the issuer's own filing on openinfo.uz; the period is printed under the figure because across issuers it may be a quarter, a half-year or a full year." },
    uz: { term: "Tushum", def: "Davr davomida tovar va xizmatlar sotuvidan olingan barcha mablag‘, xarajatlar chegirilgunga qadar — foyda hisobotining birinchi qatori. Emitentning openinfo.uz’dagi oshkor qilinishidan olinadi; davr son ostida yozilgan, chunki emitentlarda u chorak, yarim yil yoki yil bo‘lishi mumkin." },
  },
  finGross: {
    ru: { term: "Валовая прибыль", def: "Выручка минус себестоимость проданного, до операционных и прочих расходов. У банков и финансовых компаний этой строки в отчётности нет — там стоит «н/д», а не ноль." },
    en: { term: "Gross profit", def: "Revenue less cost of sales, before operating and other expenses. Banks and financial companies do not report this line at all — those cells read «n/a», not zero." },
    uz: { term: "Yalpi foyda", def: "Tushumdan sotilgan mahsulot tannarxi ayirilgani, operatsion va boshqa xarajatlargacha. Banklar va moliya kompaniyalarida bu qator hisobotda yo‘q — u yerda nol emas, «ma’lumot yo‘q» turadi." },
  },
  finOperating: {
    ru: { term: "Операционный доход", def: "Прибыль от основной деятельности: валовая прибыль минус коммерческие и административные расходы, без учёта процентов и налогов." },
    en: { term: "Operating income", def: "Profit from the core business: gross profit less selling and administrative expenses, before interest and tax." },
    uz: { term: "Operatsion daromad", def: "Asosiy faoliyatdan olingan foyda: yalpi foydadan tijorat va ma’muriy xarajatlar ayirilgani, foizlar va soliqlarsiz." },
  },
  finNet: {
    ru: { term: "Чистая прибыль", def: "То, что осталось после всех расходов, процентов и налогов, — итоговая строка отчёта. Убыток показывается отрицательным числом; ноль означает именно ноль, а не отсутствие данных." },
    en: { term: "Net income", def: "What remains after all costs, interest and tax — the bottom line. A loss is shown as a negative number; a zero means zero, not missing data." },
    uz: { term: "Sof foyda", def: "Barcha xarajatlar, foizlar va soliqlardan keyin qolgan mablag‘ — hisobotning yakuniy qatori. Zarar manfiy son bilan ko‘rsatiladi; nol — bu aynan nol, ma’lumot yo‘qligi emas." },
  },
  totalAssets: {
    ru: { term: "Активы", def: "Всё, чем компания владеет на отчётную дату: деньги, запасы, оборудование, здания, дебиторская задолженность. Активы всегда равны сумме обязательств и собственного капитала — это и есть балансовое равенство." },
    en: { term: "Total assets", def: "Everything the company owns at the reporting date: cash, inventory, equipment, buildings, receivables. Assets always equal liabilities plus equity — that is the balance-sheet identity." },
    uz: { term: "Aktivlar", def: "Kompaniya hisobot sanasida egalik qiladigan hamma narsa: pul, zaxiralar, uskuna, binolar, debitorlik qarzi. Aktivlar doimo majburiyatlar va o‘z kapitali yig‘indisiga teng — bu balans tengligi." },
  },
  equity: {
    ru: { term: "Собственный капитал", def: "Активы минус обязательства — доля владельцев в компании. Отрицательный капитал означает, что долгов больше, чем имущества." },
    en: { term: "Equity", def: "Assets less liabilities — the owners' stake in the company. Negative equity means the debts exceed what the company owns." },
    uz: { term: "O‘z kapitali", def: "Aktivlardan majburiyatlar ayirilgani — egalarning kompaniyadagi ulushi. Manfiy kapital qarzlar mol-mulkdan ko‘pligini bildiradi." },
  },
  finCash: {
    ru: { term: "Наличность в кассе", def: "Денежные средства и их эквиваленты на отчётную дату. Это положение на дату, а не результат за период, — поэтому величину нельзя сравнивать с выручкой напрямую." },
    en: { term: "Cash", def: "Cash and equivalents at the reporting date. It is a position on a date, not a result over a period, so it does not compare directly with revenue." },
    uz: { term: "Kassadagi naqd pul", def: "Hisobot sanasidagi pul mablag‘lari va ularning ekvivalentlari. Bu davr natijasi emas, sanadagi holat — shu sababli uni tushum bilan to‘g‘ridan-to‘g‘ri solishtirib bo‘lmaydi." },
  },
  finLiab: {
    ru: { term: "Общие обязательства", def: "Всё, что компания должна на отчётную дату: кредиты, займы, кредиторская задолженность, налоги к уплате. Тоже положение на дату, а не поток за период." },
    en: { term: "Total liabilities", def: "Everything the company owes at the reporting date: loans, borrowings, payables, taxes due. Also a position on a date rather than a flow over a period." },
    uz: { term: "Umumiy majburiyatlar", def: "Kompaniyaning hisobot sanasidagi barcha qarzlari: kreditlar, qarzlar, kreditorlik qarzi, to‘lanishi kerak bo‘lgan soliqlar. Bu ham davr oqimi emas, sanadagi holat." },
  },
  ebitda: {
    ru: { term: "EBITDA", def: "Прибыль до вычета процентов, налогов и амортизации. Показывает, сколько компания зарабатывает операционной деятельностью, вне структуры долга и учётной политики." },
    en: { term: "EBITDA", def: "Earnings before interest, tax, depreciation and amortisation. It shows what the operating business earns, apart from how it is financed and how it depreciates." },
    uz: { term: "EBITDA", def: "Foizlar, soliqlar va amortizatsiya chegirilgunga qadar foyda. Kompaniya operatsion faoliyatidan qancha topayotganini, qarz tuzilmasi va hisob siyosatidan qat’i nazar ko‘rsatadi." },
  },
  netMargin: {
    ru: { term: "Чистая маржа", def: "Доля чистой прибыли в выручке: сколько прибыли остаётся с каждого заработанного сума. У эмитента с нулевой выручкой маржа не определена — в ячейке стоит пояснение, а не прочерк." },
    en: { term: "Net margin", def: "Net income as a share of revenue: how much profit each soum of sales leaves behind. With zero revenue the margin is undefined — the cell says so instead of showing a dash." },
    uz: { term: "Sof marja", def: "Sof foydaning tushumdagi ulushi: har bir topilgan so‘mdan qancha foyda qolishi. Tushumi nol bo‘lgan emitentda marja aniqlanmaydi — katakda chiziqcha emas, izoh turadi." },
  },
  roe: {
    ru: { term: "ROE (Return on Equity)", def: "Рентабельность собственного капитала: сколько чистой прибыли приходится на каждый сум капитала акционеров. Сравнивать имеет смысл внутри одной отрасли — у банков и у производства нормы разные." },
    en: { term: "ROE (return on equity)", def: "How much net income each soum of shareholders' equity produces. It only compares meaningfully within an industry — banks and manufacturers sit at different norms." },
    uz: { term: "ROE (kapital rentabelligi)", def: "Aksiyadorlar kapitalining har bir so‘miga qancha sof foyda to‘g‘ri kelishi. Solishtirish faqat bitta soha ichida ma’noga ega — banklar va ishlab chiqarishda me’yorlar har xil." },
  },
  roa: {
    ru: { term: "ROA (Return on Assets)", def: "Рентабельность активов: сколько прибыли компания получает на каждый сум всех своих активов, независимо от того, куплены они за свои деньги или в долг." },
    en: { term: "ROA (return on assets)", def: "How much profit the company earns on each soum of its assets, regardless of whether those assets were funded by equity or debt." },
    uz: { term: "ROA (aktivlar rentabelligi)", def: "Kompaniya o‘z aktivlarining har bir so‘midan qancha foyda olishi — bu aktivlar o‘z mablag‘iga yoki qarzga olinganidan qat’i nazar." },
  },
  debtEq: {
    ru: { term: "Долг / Капитал (D/E)", def: "Отношение обязательств к собственному капиталу. D/E = 2 означает два сума заёмных на каждый сум собственных. У банков высокий D/E — норма профессии, а не тревога: чужие деньги и есть их сырьё." },
    en: { term: "Debt to equity (D/E)", def: "Liabilities against shareholders' equity. D/E = 2 means two soum borrowed for every soum owned. A high D/E at a bank is the shape of the business, not a warning — other people's money is its raw material." },
    uz: { term: "Qarz / Kapital (D/E)", def: "Majburiyatlarning o‘z kapitaliga nisbati. D/E = 2 — har bir o‘z so‘miga ikki so‘m qarz. Bankda yuqori D/E xavotir emas, kasb tabiati: o‘zganing puli ularning xomashyosi." },
  },
  debtEbitda: {
    ru: { term: "Долг / EBITDA", def: "Сколько лет нужно работать, чтобы погасить весь долг из операционной прибыли. До 2× — низкая нагрузка, выше 4× — высокая." },
    en: { term: "Debt / EBITDA", def: "How many years of operating profit it would take to repay all debt. Under 2× is light, above 4× is heavy." },
    uz: { term: "Qarz / EBITDA", def: "Butun qarzni operatsion foyda hisobidan qoplash uchun necha yil kerakligi. 2× gacha — past yuk, 4× dan yuqori — yuqori." },
  },
  interestCoverage: {
    ru: { term: "Покрытие процентов", def: "Отношение EBITDA к годовым процентным платежам. Ниже 2× — тревожный сигнал: прибыли едва хватает на обслуживание долга." },
    en: { term: "Interest coverage", def: "EBITDA against annual interest payments. Below 2× is a warning: earnings barely cover the cost of the debt." },
    uz: { term: "Foizlarni qoplash", def: "EBITDA ning yillik foiz to‘lovlariga nisbati. 2× dan past — xavotirli signal: foyda qarzga xizmat ko‘rsatishga zo‘rg‘a yetadi." },
  },
  currentRatio: {
    ru: { term: "Коэффициент текущей ликвидности", def: "Оборотные активы, делённые на краткосрочные обязательства. Норма — выше 1,5." },
    en: { term: "Current ratio", def: "Current assets divided by current liabilities. Above 1.5 is the usual comfort level." },
    uz: { term: "Joriy likvidlik koeffitsiyenti", def: "Aylanma aktivlarning qisqa muddatli majburiyatlarga nisbati. Me’yor — 1,5 dan yuqori." },
  },
  quickRatio: {
    ru: { term: "Коэффициент быстрой ликвидности", def: "То же, но без учёта запасов, — более консервативная оценка платёжеспособности." },
    en: { term: "Quick ratio", def: "The same, excluding inventory — a more conservative read on solvency." },
    uz: { term: "Tez likvidlik koeffitsiyenti", def: "Xuddi shu, lekin zaxiralarsiz — to‘lov qobiliyatining ancha konservativ bahosi." },
  },

  // ── Мультипликаторы ───────────────────────────────────────────────────────
  mktCap: {
    ru: { term: "Капитализация", def: "Рыночная цена одной бумаги, умноженная на число выпущенных бумаг этого класса. Число акций берётся с uzse.uz. У эмитента с обычными и привилегированными акциями каждый класс считается отдельно." },
    en: { term: "Market capitalisation", def: "The market price of one security times the number issued in that class. Share counts come from uzse.uz. Where an issuer has both ordinary and preferred stock, each class is counted separately." },
    uz: { term: "Kapitalizatsiya", def: "Bitta qog‘ozning bozor narxi shu sinfda chiqarilgan qog‘ozlar soniga ko‘paytirilgani. Aksiyalar soni uzse.uz’dan olinadi. Oddiy va imtiyozli aksiyalari bor emitentda har bir sinf alohida hisoblanadi." },
  },
  pe: {
    ru: { term: "P/E (Price to Earnings)", def: "Капитализация, делённая на годовую чистую прибыль: за сколько лет прибыли окупается текущая цена. Если последняя отчётность эмитента — квартал или полугодие, знаменателем берётся последний полный финансовый год, чтобы во всех строках делить на 12 месяцев; период подписан на самой ячейке." },
    en: { term: "P/E (price to earnings)", def: "Market capitalisation over annual net income: how many years of profit the current price is worth. When the issuer's latest filing covers a quarter or a half-year, the denominator is the last complete fiscal year, so every row divides by twelve months; the cell names the period it used." },
    uz: { term: "P/E (narx / foyda)", def: "Kapitalizatsiyaning yillik sof foydaga nisbati: joriy narx necha yillik foydaga teng. Agar emitentning oxirgi hisoboti chorak yoki yarim yil bo‘lsa, maxraj sifatida oxirgi to‘liq moliyaviy yil olinadi — shunda har bir qator 12 oyga bo‘linadi; katakda qaysi davr ishlatilgani yozilgan." },
  },
  pb: {
    ru: { term: "P/B (Price to Book)", def: "Капитализация, делённая на собственный капитал. P/B меньше 1 означает, что рынок оценивает компанию дешевле её балансового капитала." },
    en: { term: "P/B (price to book)", def: "Market capitalisation over shareholders' equity. A P/B under 1 means the market values the company below the equity on its own balance sheet." },
    uz: { term: "P/B (narx / balans qiymati)", def: "Kapitalizatsiyaning o‘z kapitaliga nisbati. P/B 1 dan kichik bo‘lsa, bozor kompaniyani balansdagi kapitalidan arzonroq baholayapti." },
  },
  evEbitda: {
    ru: { term: "EV/EBITDA", def: "Стоимость бизнеса вместе с долгом, делённая на EBITDA. Более полный аналог P/E: учитывает долговую нагрузку, поэтому сравнивает компании с разной структурой капитала честнее." },
    en: { term: "EV/EBITDA", def: "Enterprise value, debt included, over EBITDA. A fuller counterpart to P/E: because it carries the debt, it compares companies with different capital structures more fairly." },
    uz: { term: "EV/EBITDA", def: "Qarz bilan birga biznes qiymatining EBITDA ga nisbati. P/E ning to‘liqroq muqobili: qarz yukini hisobga oladi va turli kapital tuzilmasidagi kompaniyalarni adolatliroq solishtiradi." },
  },

  // ── Инструменты и корпоративные события ───────────────────────────────────
  share: {
    ru: { term: "Акция", def: "Ценная бумага, дающая владельцу долю в компании и статус совладельца — акционера." },
    en: { term: "Share", def: "A security giving its holder a stake in the company and the standing of a co-owner — a shareholder." },
    uz: { term: "Aksiya", def: "Egasiga kompaniyada ulush va hammulkdor — aksiyador maqomini beruvchi qimmatli qog‘oz." },
  },
  preferred: {
    ru: { term: "Привилегированные акции (префы)", def: "Дают приоритет по дивидендам, но обычно без права голоса. На бирже обозначаются буквой P в конце тикера — например, HMKBP." },
    en: { term: "Preferred shares", def: "They rank ahead on dividends but usually carry no vote. The exchange marks them with a trailing P — HMKBP, for example." },
    uz: { term: "Imtiyozli aksiyalar", def: "Dividendlarda ustunlik beradi, lekin odatda ovoz huquqisiz. Birjada ticker oxiridagi P harfi bilan belgilanadi — masalan, HMKBP." },
  },
  bond: {
    ru: { term: "Облигация", def: "Долговая бумага: вы даёте компании или государству в долг, они возвращают номинал и купонный доход в срок." },
    en: { term: "Bond", def: "A debt security: you lend to a company or the state, and they return the principal plus coupon on schedule." },
    uz: { term: "Obligatsiya", def: "Qarz qog‘ozi: siz kompaniyaga yoki davlatga qarz berasiz, ular nominal va kupon daromadini muddatida qaytaradi." },
  },
  issuer: {
    ru: { term: "Эмитент", def: "Юридическое лицо, выпустившее ценные бумаги и несущее по ним обязательства перед владельцами." },
    en: { term: "Issuer", def: "The legal entity that issued the securities and owes the obligations attached to them." },
    uz: { term: "Emitent", def: "Qimmatli qog‘ozlarni chiqargan va ular bo‘yicha egalari oldida majburiyat oluvchi yuridik shaxs." },
  },
  listing: {
    ru: { term: "Листинг", def: "Включение ценных бумаг в официальный список биржи, после чего ими можно торговать." },
    en: { term: "Listing", def: "Admission of securities to the exchange's official list, after which they can be traded." },
    uz: { term: "Listing", def: "Qimmatli qog‘ozlarni birjaning rasmiy ro‘yxatiga kiritish, shundan so‘ng ular bilan savdo qilish mumkin." },
  },
  delisting: {
    ru: { term: "Делистинг", def: "Исключение ценных бумаг из биржевого списка — по инициативе компании или самой биржи." },
    en: { term: "Delisting", def: "Removal of securities from the exchange's list, at the company's initiative or the exchange's." },
    uz: { term: "Delisting", def: "Qimmatli qog‘ozlarni birja ro‘yxatidan chiqarish — kompaniya yoki birjaning tashabbusi bilan." },
  },
  dividends: {
    ru: { term: "Дивиденды", def: "Часть прибыли, распределяемая компанией между акционерами." },
    en: { term: "Dividends", def: "The part of profit a company distributes to its shareholders." },
    uz: { term: "Dividendlar", def: "Kompaniya aksiyadorlar o‘rtasida taqsimlaydigan foyda qismi." },
  },

  // ── Облигации ─────────────────────────────────────────────────────────────
  // Дополнение 1 §А.3: par comes from uzse (`parval`), the coupon rate is derived
  // from the issuer's own filings, and maturity is never published as stated —
  // so these definitions say where the number came from, not just what it means.
  par: {
    ru: { term: "Номинал", def: "Сумма, которую эмитент обязуется вернуть держателю в конце срока, и база, от которой считается купон. Публикуется биржей." },
    en: { term: "Par value", def: "The amount the issuer undertakes to repay at maturity, and the base the coupon is calculated on. Published by the exchange." },
    uz: { term: "Nominal", def: "Emitent muddat oxirida egasiga qaytarishni majburiyatiga olgan summa va kupon hisoblanadigan baza. Birja tomonidan e’lon qilinadi." },
  },
  parPercent: {
    ru: { term: "% номинала", def: "Рыночная цена облигации в процентах от номинала. 100% — торгуется по номиналу, ниже — с дисконтом, выше — с премией." },
    en: { term: "% of par", def: "The bond's market price as a percentage of par. 100% is at par; below is a discount, above is a premium." },
    uz: { term: "Nominalning %", def: "Obligatsiyaning bozor narxi nominalga nisbatan foizda. 100% — nominal bo‘yicha, past — diskont bilan, yuqori — mukofot bilan." },
  },
  coupon: {
    ru: { term: "Купон", def: "Процент от номинала, который эмитент платит держателю за период. Ставка выведена из существенных фактов эмитента на openinfo.uz — отдельного проспекта выпуска в открытом доступе нет." },
    en: { term: "Coupon", def: "The percentage of par the issuer pays the holder each period. The rate is derived from the issuer's material-fact filings on openinfo.uz — no public prospectus exists for these issues." },
    uz: { term: "Kupon", def: "Emitent har davrda egasiga to‘laydigan nominalning foizi. Stavka emitentning openinfo.uz’dagi muhim faktlaridan chiqarilgan — bu chiqarishlar uchun ochiq prospekt mavjud emas." },
  },
  runningYield: {
    ru: { term: "Текущая доходность", def: "Годовой купон, делённый на рыночную цену. Показывает отдачу от купона при покупке сегодня, но не учитывает возврат номинала в конце срока." },
    en: { term: "Running yield", def: "The annual coupon over the market price. It shows the coupon return on today's purchase but ignores the repayment of par at maturity." },
    uz: { term: "Joriy daromadlilik", def: "Yillik kuponning bozor narxiga nisbati. Bugun sotib olganda kupondan qaytimni ko‘rsatadi, lekin muddat oxirida nominal qaytishini hisobga olmaydi." },
  },
  ytm: {
    ru: { term: "Доходность к погашению (YTM)", def: "Полная годовая доходность, если держать бумагу до погашения: купоны плюс разница между ценой покупки и номиналом. Считается только там, где известен срок погашения." },
    en: { term: "Yield to maturity (YTM)", def: "The full annual return from holding to maturity: coupons plus the gap between purchase price and par. Computed only where the maturity date is known." },
    uz: { term: "So‘ndirishgacha daromadlilik (YTM)", def: "Qog‘ozni so‘ndirishgacha ushlab turgandagi to‘liq yillik daromad: kuponlar va sotib olish narxi bilan nominal o‘rtasidagi farq. Faqat so‘ndirish muddati ma’lum bo‘lgan joyda hisoblanadi." },
  },
  duration: {
    ru: { term: "Дюрация", def: "Средний срок возврата вложенных денег с учётом купонов. Чем она больше, тем сильнее цена облигации реагирует на изменение ставок." },
    en: { term: "Duration", def: "The average time to recover the money invested, coupons included. The longer it is, the more the bond's price moves when rates change." },
    uz: { term: "Dyuratsiya", def: "Kuponlarni hisobga olgan holda qo‘yilgan pulning qaytish o‘rtacha muddati. U qancha uzun bo‘lsa, stavkalar o‘zgarganda obligatsiya narxi shuncha kuchli reaksiya qiladi." },
  },
};

/** One term in one language, falling back to Russian while a translation is missing. */
export function termFor(id, lang) {
  const entry = TERMS[id];
  if (!entry) return null;
  return entry[lang] || entry.ru;
}

