"""manual_company_info.py — curated, multilingual descriptions for UZSE issuers.

Used by ``securities_catalog`` as a fallback when an issuer has no Wikipedia
article (which is most small/medium Uzbek companies). Keyed by the *base* ticker;
the lookup in ``securities_catalog._manual_info`` resolves preferred/common
siblings (``HMKB`` <-> ``HMKBP``) and bond series codes (``BFMT3V2`` -> ``BFMT``)
to the same entry.

Descriptions are intentionally conservative: they state what each company does,
its sector and home city, and that its securities trade on the Republican Stock
Exchange "Toshkent". Specific unverified figures/dates are deliberately omitted.
``url`` is the issuer's official site where known, otherwise ``None`` (no link).
"""
from __future__ import annotations

from typing import Any

MANUAL_INFO: dict[str, dict[str, Any]] = {
    # ── Grain / food ────────────────────────────────────────────────────────
    "TKDM": {
        "title": "Toshkentdonmahsulotlari",
        "url": "https://www.tdm.uz",
        "ru": (
            "«Toshkentdonmahsulotlari» (ТДМ) — одно из ведущих предприятий пищевой "
            "инфраструктуры Ташкента, специализирующееся на переработке зерна. Общество "
            "производит муку высшего и первого сорта, манную крупу, комбикорма и другие "
            "крупяные изделия, а также занимается оптовой и розничной торговлей "
            "хлебопродуктами и кормами. В состав предприятия входят мельничный комплекс, "
            "элеватор ёмкостью 52 тысячи тонн зерна и комбикормовый завод, введённый в "
            "эксплуатацию в 1960 году и модернизированный в 2007 году. Предприятие "
            "расположено в Яшнабадском районе города Ташкента. Привилегированные акции "
            "общества торгуются на Республиканской фондовой бирже «Тошкент» под тикером TKDMP."
        ),
        "en": (
            "Toshkentdonmahsulotlari (TDM) is one of Tashkent's leading food-industry "
            "enterprises, specialising in grain processing and milling. The company produces "
            "premium- and first-grade wheat flour, semolina, compound animal feed and other "
            "cereal products, and runs both wholesale and retail trade in grain products and "
            "feed. Its facilities include a flour-milling complex, a grain elevator with a "
            "capacity of 52,000 tonnes, and a compound-feed plant first commissioned in 1960 "
            "and modernised in 2007. The enterprise is located in the Yashnabad district of "
            "Tashkent. Its preferred shares trade on the Republican Stock Exchange "
            "\"Toshkent\" under the ticker TKDMP."
        ),
        "uz": (
            "«Toshkentdonmahsulotlari» (TDM) — Toshkentning yetakchi oziq-ovqat va don qayta "
            "ishlash korxonalaridan biri. Korxona oliy va birinchi navli bug'doy uni, manniy "
            "yormasi, aralash yem (kombikorm) va boshqa yorma mahsulotlarini ishlab chiqaradi, "
            "shuningdek don mahsulotlari va yemlarni ulgurji va chakana savdo qiladi. Korxona "
            "tarkibiga un tortish majmuasi, 52 ming tonna g'alla sig'imiga ega elevator va "
            "1960-yilda ishga tushirilib, 2007-yilda modernizatsiya qilingan kombikorm zavodi "
            "kiradi. Korxona Toshkent shahrining Yashnobod tumanida joylashgan. Imtiyozli "
            "aksiyalari «Toshkent» Respublika fond birjasida TKDMP tikeri ostida sotiladi."
        ),
    },
    "OHDN": {
        "title": "Ohangaron don",
        "url": None,
        "ru": (
            "«Ohangaron don» — предприятие по переработке зерна, расположенное в городе "
            "Ахангаран Ташкентской области. Общество занимается хранением и переработкой "
            "зерна, производством муки и сопутствующих хлебопродуктов. Акции компании "
            "торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Ohangaron Don is a grain-processing enterprise based in Ahangaran, in the "
            "Tashkent region of Uzbekistan. The company stores and processes grain and "
            "produces flour and related grain products. Its shares trade on the Republican "
            "Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Ohangaron don» — Toshkent viloyatining Ohangaron shahrida joylashgan don qayta "
            "ishlash korxonasi. Korxona g'allani saqlash va qayta ishlash, un hamda tegishli "
            "don mahsulotlarini ishlab chiqarish bilan shug'ullanadi. Jamiyat aksiyalari "
            "«Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Banks ───────────────────────────────────────────────────────────────
    "HMKB": {
        "title": "Hamkorbank",
        "url": "https://hamkorbank.uz",
        "ru": (
            "«Hamkorbank» — один из крупнейших частных коммерческих банков Узбекистана со "
            "штаб-квартирой в Андижане. Банк предоставляет полный спектр услуг для частных "
            "лиц, малого и среднего бизнеса: кредитование, депозиты, расчётно-кассовое "
            "обслуживание и микрофинансирование, и активно сотрудничает с международными "
            "финансовыми институтами. Обыкновенные и привилегированные акции банка торгуются "
            "на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Hamkorbank is one of the largest private commercial banks in Uzbekistan, "
            "headquartered in Andijan. It offers a full range of services to individuals and "
            "to small and medium-sized businesses — lending, deposits, settlement services "
            "and microfinance — and works closely with international financial institutions. "
            "Its ordinary and preferred shares trade on the Republican Stock Exchange "
            "\"Toshkent\"."
        ),
        "uz": (
            "«Hamkorbank» — Andijon shahrida joylashgan O'zbekistonning yirik xususiy tijorat "
            "banklaridan biri. Bank jismoniy shaxslar hamda kichik va o'rta biznesga "
            "kreditlash, omonatlar, hisob-kitob xizmatlari va mikromoliyalashtirishni taklif "
            "etadi va xalqaro moliya institutlari bilan faol hamkorlik qiladi. Bankning oddiy "
            "va imtiyozli aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "IPKY": {
        "title": "Ipak Yo'li Bank",
        "url": "https://ipakyulibank.uz",
        "ru": (
            "«Ipak Yo'li» (Ипак Йули банк) — один из старейших частных коммерческих банков "
            "Узбекистана. Банк обслуживает физических лиц и корпоративных клиентов, предлагая "
            "кредиты, депозиты, платёжные и расчётные услуги. Акции банка торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Ipak Yo'li (Ipak Yuli Bank) is one of the oldest private commercial banks in "
            "Uzbekistan. It serves retail and corporate customers with loans, deposits, and "
            "payment and settlement services. The bank's shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Ipak Yo'li» banki — O'zbekistonning eng eski xususiy tijorat banklaridan biri. "
            "Bank jismoniy va korporativ mijozlarga kreditlar, omonatlar, to'lov va hisob-kitob "
            "xizmatlarini taklif etadi. Bank aksiyalari «Toshkent» Respublika fond birjasida "
            "sotiladi."
        ),
    },
    "IPTB": {
        "title": "Ipoteka Bank",
        "url": "https://ipotekabank.uz",
        "ru": (
            "«Ipoteka-bank» — один из крупнейших универсальных банков Узбекистана с сильными "
            "позициями в ипотечном и розничном кредитовании. В 2023 году контрольный пакет "
            "банка приобрёл венгерский OTP Bank, после чего банк вошёл в международную "
            "банковскую группу OTP. Акции банка торгуются на Республиканской фондовой бирже "
            "«Тошкент»."
        ),
        "en": (
            "Ipoteka-Bank is one of Uzbekistan's largest universal banks, with a strong "
            "position in mortgage and retail lending. In 2023 a controlling stake was acquired "
            "by Hungary's OTP Bank, bringing it into the international OTP banking group. The "
            "bank's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Ipoteka-bank» — O'zbekistonning yirik universal banklaridan biri bo'lib, ipoteka "
            "va chakana kreditlashda kuchli o'rin egallaydi. 2023-yilda bankning nazorat "
            "paketini Vengriyaning OTP Bank banki sotib oldi va bank xalqaro OTP bank guruhiga "
            "qo'shildi. Bank aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "AGBA": {
        "title": "Agrobank",
        "url": "https://agrobank.uz",
        "ru": (
            "«Agrobank» — один из крупнейших банков Узбекистана с государственным участием, "
            "исторически специализирующийся на финансировании сельского хозяйства и "
            "агропромышленного комплекса. Банк обслуживает фермеров, предприятия АПК и "
            "население через широкую сеть отделений по всей стране. Обыкновенные и "
            "привилегированные акции банка торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Agrobank is one of Uzbekistan's largest state-participated banks, historically "
            "focused on financing agriculture and the agro-industrial sector. It serves "
            "farmers, agribusinesses and the public through a wide branch network across the "
            "country. Its ordinary and preferred shares trade on the Republican Stock Exchange "
            "\"Toshkent\"."
        ),
        "uz": (
            "«Agrobank» — O'zbekistonning davlat ishtirokidagi yirik banklaridan biri bo'lib, "
            "an'anaviy ravishda qishloq xo'jaligi va agrosanoat majmuasini moliyalashtirishga "
            "ixtisoslashgan. Bank mamlakat bo'ylab keng filiallar tarmog'i orqali fermerlar, "
            "agrobiznes korxonalari va aholiga xizmat ko'rsatadi. Bankning oddiy va imtiyozli "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "SQBN": {
        "title": "SQB (O'zsanoatqurilishbank)",
        "url": "https://sqb.uz",
        "ru": (
            "«O'zsanoatqurilishbank» (SQB) — один из крупнейших банков Узбекистана с "
            "государственным участием, обслуживающий корпоративных клиентов промышленного и "
            "строительного секторов, а также розничных клиентов. Банк предлагает кредитование, "
            "депозиты и расчётно-кассовые услуги по всей стране. Обыкновенные и "
            "привилегированные акции банка торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'zsanoatqurilishbank (SQB) is one of Uzbekistan's largest state-participated "
            "banks, serving corporate clients in the industrial and construction sectors as "
            "well as retail customers. It provides lending, deposits and settlement services "
            "nationwide. Its ordinary and preferred shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zsanoatqurilishbank» (SQB) — O'zbekistonning davlat ishtirokidagi yirik "
            "banklaridan biri bo'lib, sanoat va qurilish sohasidagi korporativ mijozlarga "
            "hamda chakana mijozlarga xizmat ko'rsatadi. Bank mamlakat bo'ylab kreditlash, "
            "omonatlar va hisob-kitob xizmatlarini taklif etadi. Bankning oddiy va imtiyozli "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "TNBN": {
        "title": "Turonbank",
        "url": "https://turonbank.uz",
        "ru": (
            "«Turonbank» — коммерческий банк Узбекистана с государственным участием, "
            "предоставляющий услуги корпоративным и розничным клиентам: кредитование, "
            "депозиты, расчётно-кассовое обслуживание и международные операции. Банк имеет "
            "сеть отделений по всей стране. Акции банка торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "Turonbank is a state-participated commercial bank in Uzbekistan, serving "
            "corporate and retail clients with lending, deposits, settlement services and "
            "international operations through a nationwide branch network. The bank's shares "
            "trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Turonbank» — O'zbekistonning davlat ishtirokidagi tijorat banki bo'lib, "
            "korporativ va chakana mijozlarga kreditlash, omonatlar, hisob-kitob xizmatlari va "
            "xalqaro operatsiyalarni taklif etadi hamda mamlakat bo'ylab filiallar tarmog'iga "
            "ega. Bank aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "TRSB": {
        "title": "Trustbank",
        "url": "https://trustbank.uz",
        "ru": (
            "«Trastbank» (Trustbank) — один из первых частных коммерческих банков Узбекистана. "
            "Банк предоставляет полный спектр банковских услуг для частных лиц и бизнеса, "
            "включая кредитование, депозиты и платёжные сервисы. Акции банка торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Trustbank is one of the first private commercial banks in Uzbekistan. It offers "
            "a full range of banking services to individuals and businesses, including "
            "lending, deposits and payment services. The bank's shares trade on the Republican "
            "Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Trastbank» (Trustbank) — O'zbekistonning birinchi xususiy tijorat banklaridan "
            "biri. Bank jismoniy shaxslar va biznesga kreditlash, omonatlar va to'lov "
            "xizmatlarini o'z ichiga olgan to'liq bank xizmatlarini taklif etadi. Bank "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "ALKB": {
        "title": "Aloqabank",
        "url": "https://aloqabank.uz",
        "ru": (
            "«Aloqabank» — коммерческий банк Узбекистана с государственным участием, исторически "
            "связанный с отраслью связи и информационных технологий. Банк обслуживает "
            "корпоративных и розничных клиентов, предлагая кредиты, депозиты и цифровые "
            "платёжные сервисы. Обыкновенные и привилегированные акции банка торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Aloqabank is a state-participated commercial bank in Uzbekistan, historically "
            "linked to the communications and IT sector. It serves corporate and retail "
            "customers with loans, deposits and digital payment services. Its ordinary and "
            "preferred shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Aloqabank» — O'zbekistonning davlat ishtirokidagi tijorat banki bo'lib, "
            "an'anaviy ravishda aloqa va axborot texnologiyalari tarmog'i bilan bog'liq. Bank "
            "korporativ va chakana mijozlarga kreditlar, omonatlar va raqamli to'lov "
            "xizmatlarini taklif etadi. Bankning oddiy va imtiyozli aksiyalari «Toshkent» "
            "Respublika fond birjasida sotiladi."
        ),
    },
    "GRBK": {
        "title": "Garant Bank",
        "url": "https://garantbank.uz",
        "ru": (
            "«Garant Bank» — частный коммерческий банк Узбекистана, предоставляющий услуги "
            "корпоративным и частным клиентам: кредитование, депозиты, расчётно-кассовое "
            "обслуживание и валютные операции. Акции банка торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "Garant Bank is a private commercial bank in Uzbekistan, providing corporate and "
            "retail clients with lending, deposits, settlement services and foreign-exchange "
            "operations. The bank's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Garant Bank» — O'zbekistondagi xususiy tijorat banki bo'lib, korporativ va "
            "jismoniy mijozlarga kreditlash, omonatlar, hisob-kitob va valyuta operatsiyalari "
            "xizmatlarini taqdim etadi. Bank aksiyalari «Toshkent» Respublika fond birjasida "
            "sotiladi."
        ),
    },
    "MCBA": {
        "title": "Mikrokreditbank",
        "url": "https://mkbank.uz",
        "ru": (
            "«Mikrokreditbank» — банк Узбекистана с государственным участием, специализирующийся "
            "на микрокредитовании, поддержке малого бизнеса, частного предпринимательства и "
            "населения. Банк работает через широкую сеть отделений по всей стране. Обыкновенные "
            "и привилегированные акции банка торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Mikrokreditbank is a state-participated bank in Uzbekistan specialising in "
            "microcredit and in supporting small businesses, private entrepreneurs and the "
            "public, operating through a wide branch network across the country. Its ordinary "
            "and preferred shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Mikrokreditbank» — O'zbekistonning davlat ishtirokidagi banki bo'lib, "
            "mikrokreditlash hamda kichik biznes, xususiy tadbirkorlik va aholini qo'llab-"
            "quvvatlashga ixtisoslashgan va mamlakat bo'ylab keng filiallar tarmog'i orqali "
            "ishlaydi. Bankning oddiy va imtiyozli aksiyalari «Toshkent» Respublika fond "
            "birjasida sotiladi."
        ),
    },
    "UNVB": {
        "title": "Universal Bank",
        "url": None,
        "ru": (
            "«Universal Bank» — частный коммерческий банк Узбекистана, предоставляющий банковские "
            "услуги физическим и юридическим лицам, включая кредитование, депозиты и "
            "расчётно-кассовое обслуживание. Акции банка торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "Universal Bank is a private commercial bank in Uzbekistan, offering banking "
            "services to individuals and companies, including lending, deposits and settlement "
            "services. The bank's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Universal bank» — O'zbekistondagi xususiy tijorat banki bo'lib, jismoniy va "
            "yuridik shaxslarga kreditlash, omonatlar va hisob-kitob xizmatlarini taklif etadi. "
            "Bank aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "BRBN": {
        "title": "Business Development Bank",
        "url": None,
        "ru": (
            "«Biznesni rivojlantirish banki» (Банк развития бизнеса) — коммерческий банк "
            "Узбекистана, ориентированный на финансирование и поддержку предпринимательства, "
            "малого и среднего бизнеса. Банк предоставляет кредиты, депозиты и расчётные услуги. "
            "Обыкновенные и привилегированные акции банка торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "The Business Development Bank (Biznesni rivojlantirish banki) is a commercial bank "
            "in Uzbekistan focused on financing and supporting entrepreneurship and small and "
            "medium-sized businesses, providing loans, deposits and settlement services. Its "
            "ordinary and preferred shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Biznesni rivojlantirish banki» — O'zbekistondagi tijorat banki bo'lib, "
            "tadbirkorlik hamda kichik va o'rta biznesni moliyalashtirish va qo'llab-quvvatlashga "
            "yo'naltirilgan; kreditlar, omonatlar va hisob-kitob xizmatlarini taqdim etadi. "
            "Bankning oddiy va imtiyozli aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Exchange / capital markets ──────────────────────────────────────────
    "URTS": {
        "title": "Uzbek Commodity Exchange (UzEX)",
        "url": "https://uzex.uz",
        "ru": (
            "Узбекская республиканская товарно-сырьевая биржа (UzEX) — крупнейшая товарная "
            "биржа Узбекистана и одна из ведущих в Центральной Азии, основанная в 1994 году. "
            "На бирже торгуются высоколиквидные товары: чёрные и цветные металлы, "
            "нефтепродукты, хлопковое волокно, минеральные удобрения, зерно и другая продукция; "
            "биржа также является оператором портала государственных закупок. Акции биржи "
            "торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "The Uzbek Republican Commodity Exchange (UzEX) is the largest commodity exchange "
            "in Uzbekistan and one of the leading exchanges in Central Asia, established in "
            "1994. It trades highly liquid commodities — ferrous and non-ferrous metals, "
            "petroleum products, cotton fibre, mineral fertilizers, grain and more — and also "
            "operates the national public-procurement portal. The exchange's shares trade on "
            "the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "O'zbekiston Respublika tovar-xom ashyo birjasi (UzEX) — 1994-yilda tashkil "
            "etilgan O'zbekistondagi eng yirik tovar birjasi va Markaziy Osiyodagi yetakchi "
            "birjalardan biri. Birjada yuqori likvidli tovarlar — qora va rangli metallar, "
            "neft mahsulotlari, paxta tolasi, mineral o'g'itlar, g'alla va boshqalar sotiladi; "
            "shuningdek birja davlat xaridlari portali operatori hisoblanadi. Birja aksiyalari "
            "«Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Insurance / leasing / investment ────────────────────────────────────
    "KASU": {
        "title": "Kapital Sug'urta",
        "url": None,
        "ru": (
            "«Kapital sug'urta» — страховая компания Узбекистана, предлагающая широкий спектр "
            "услуг общего страхования для частных лиц и бизнеса, включая имущественное, "
            "транспортное и страхование ответственности. Обыкновенные и привилегированные акции "
            "компании торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Kapital Sug'urta is an Uzbek insurance company offering a broad range of general "
            "insurance services for individuals and businesses, including property, motor and "
            "liability cover. Its ordinary and preferred shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Kapital sug'urta» — O'zbekistondagi sug'urta kompaniyasi bo'lib, jismoniy "
            "shaxslar va biznes uchun mol-mulk, transport va javobgarlik sug'urtasini o'z "
            "ichiga olgan keng umumiy sug'urta xizmatlarini taklif etadi. Kompaniyaning oddiy "
            "va imtiyozli aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "ALSM": {
        "title": "ALSKOM",
        "url": None,
        "ru": (
            "«ALSKOM» — одна из старейших страховых компаний Узбекистана, предоставляющая услуги "
            "общего страхования: имущества, грузов, транспорта, ответственности и других "
            "рисков для корпоративных и частных клиентов. Обыкновенные и привилегированные акции "
            "компании торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "ALSKOM is one of the oldest insurance companies in Uzbekistan, providing general "
            "insurance for property, cargo, motor, liability and other risks to corporate and "
            "retail clients. Its ordinary and preferred shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«ALSKOM» — O'zbekistonning eng eski sug'urta kompaniyalaridan biri bo'lib, "
            "korporativ va jismoniy mijozlarga mol-mulk, yuk, transport, javobgarlik va boshqa "
            "xavflar bo'yicha umumiy sug'urta xizmatlarini taqdim etadi. Kompaniyaning oddiy va "
            "imtiyozli aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "TMYS": {
        "title": "Temiryo'l-Sug'urta",
        "url": None,
        "ru": (
            "«Temiryo'l-sug'urta» — страховая компания Узбекистана, исторически связанная с "
            "железнодорожной отраслью. Компания оказывает услуги общего страхования, включая "
            "страхование грузов, транспорта, имущества и ответственности. Акции компании "
            "торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Temiryo'l-Sug'urta is an Uzbek insurance company historically associated with the "
            "railway sector. It provides general insurance services, including cover for cargo, "
            "transport, property and liability. The company's shares trade on the Republican "
            "Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Temiryo'l-sug'urta» — temir yo'l tarmog'i bilan an'anaviy bog'liq bo'lgan "
            "O'zbekistondagi sug'urta kompaniyasi. Kompaniya yuk, transport, mol-mulk va "
            "javobgarlikni o'z ichiga olgan umumiy sug'urta xizmatlarini ko'rsatadi. Kompaniya "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UZAS": {
        "title": "O'zagrosug'urta",
        "url": None,
        "ru": (
            "«O'zagrosug'urta» (Узагросугурта) — страховая компания Узбекистана с "
            "государственным участием, специализирующаяся на страховании в сельском хозяйстве, "
            "включая страхование урожая, скота и имущества аграрного сектора, а также общие "
            "виды страхования. Акции компании торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'zagrosug'urta is a state-participated Uzbek insurance company specialising in "
            "agricultural insurance — crops, livestock and farm property — alongside general "
            "insurance lines. The company's shares trade on the Republican Stock Exchange "
            "\"Toshkent\"."
        ),
        "uz": (
            "«O'zagrosug'urta» — davlat ishtirokidagi O'zbekiston sug'urta kompaniyasi bo'lib, "
            "qishloq xo'jaligi sug'urtasi — hosil, chorva va agrar sektor mol-mulkini "
            "sug'urtalash, shuningdek umumiy sug'urta turlariga ixtisoslashgan. Kompaniya "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UZINP": {
        "title": "Uzbekinvest",
        "url": "https://uzbekinvest.uz",
        "ru": (
            "«O'zbekinvest» (Uzbekinvest) — национальная экспортно-импортная страховая компания "
            "Узбекистана с государственным участием. Компания предоставляет страхование "
            "экспортных кредитов и инвестиций, а также широкий спектр услуг общего страхования "
            "для бизнеса. Акции компании торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Uzbekinvest is Uzbekistan's national export-import insurance company, with state "
            "participation. It provides export-credit and investment insurance as well as a "
            "broad range of general insurance services for businesses. The company's shares "
            "trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zbekinvest» (Uzbekinvest) — davlat ishtirokidagi O'zbekistonning milliy "
            "eksport-import sug'urta kompaniyasi. Kompaniya eksport kreditlari va "
            "investitsiyalarni sug'urtalash, shuningdek biznes uchun keng umumiy sug'urta "
            "xizmatlarini taqdim etadi. Kompaniya aksiyalari «Toshkent» Respublika fond "
            "birjasida sotiladi."
        ),
    },
    "UZNF": {
        "title": "National Investment Fund of Uzbekistan",
        "url": None,
        "ru": (
            "Национальный инвестиционный фонд Республики Узбекистан — государственный "
            "инвестиционный институт, созданный для управления долями государства в компаниях, "
            "привлечения инвесторов и развития рынка капитала в рамках программы приватизации. "
            "Акции фонда торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "The National Investment Fund of the Republic of Uzbekistan is a state investment "
            "institution created to manage the state's stakes in companies, attract investors "
            "and develop the capital market as part of the privatisation programme. The fund's "
            "shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "O'zbekiston Respublikasi Milliy investitsiya jamg'armasi — davlatning "
            "kompaniyalardagi ulushlarini boshqarish, investorlarni jalb qilish va xususiylashtirish "
            "dasturi doirasida kapital bozorini rivojlantirish uchun tashkil etilgan davlat "
            "investitsiya instituti. Jamg'arma aksiyalari «Toshkent» Respublika fond birjasida "
            "sotiladi."
        ),
    },
    "UZAL": {
        "title": "O'zagrolizing",
        "url": None,
        "ru": (
            "«O'zagrolizing» (Узагролизинг) — лизинговая компания Узбекистана с государственным "
            "участием, обеспечивающая фермерские и сельскохозяйственные предприятия техникой и "
            "оборудованием на условиях лизинга. Компания играет важную роль в модернизации "
            "аграрного сектора страны. Акции компании торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "O'zagrolizing is a state-participated leasing company in Uzbekistan that supplies "
            "farms and agricultural enterprises with machinery and equipment on lease terms, "
            "playing an important role in modernising the country's agricultural sector. The "
            "company's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zagrolizing» — davlat ishtirokidagi O'zbekiston lizing kompaniyasi bo'lib, "
            "fermer va qishloq xo'jaligi korxonalarini lizing asosida texnika va uskunalar "
            "bilan ta'minlaydi hamda mamlakat agrar sektorini modernizatsiya qilishda muhim "
            "rol o'ynaydi. Kompaniya aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UZML": {
        "title": "UzMED-lizing",
        "url": None,
        "ru": (
            "«UzMED-lizing» — лизинговая компания Узбекистана, специализирующаяся на "
            "финансировании поставок медицинского оборудования и техники для учреждений "
            "здравоохранения на условиях лизинга. Акции компании торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "UzMED-lizing is an Uzbek leasing company specialising in financing the supply of "
            "medical equipment and devices to healthcare institutions on lease terms. The "
            "company's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«UzMED-lizing» — sog'liqni saqlash muassasalariga tibbiyot uskunalari va "
            "qurilmalarini lizing asosida yetkazib berishni moliyalashtirishga ixtisoslashgan "
            "O'zbekiston lizing kompaniyasi. Kompaniya aksiyalari «Toshkent» Respublika fond "
            "birjasida sotiladi."
        ),
    },
    # ── Manufacturing / industry ────────────────────────────────────────────
    "UZMK": {
        "title": "Uzmetkombinat",
        "url": None,
        "ru": (
            "«O'zmetkombinat» (Узметкомбинат) — крупнейшее металлургическое предприятие "
            "Узбекистана, расположенное в городе Бекабад. Комбинат производит стальной прокат и "
            "другую металлопродукцию, являясь основой чёрной металлургии страны. Обыкновенные и "
            "привилегированные акции предприятия торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Uzmetkombinat (O'zmetkombinat) is Uzbekistan's largest metallurgical enterprise, "
            "located in the city of Bekabad. The plant produces rolled steel and other metal "
            "products and is the backbone of the country's ferrous metallurgy. Its ordinary and "
            "preferred shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zmetkombinat» — Bekobod shahrida joylashgan O'zbekistonning eng yirik "
            "metallurgiya korxonasi. Kombinat prokat po'lat va boshqa metall mahsulotlarini "
            "ishlab chiqaradi hamda mamlakat qora metallurgiyasining asosi hisoblanadi. "
            "Korxonaning oddiy va imtiyozli aksiyalari «Toshkent» Respublika fond birjasida "
            "sotiladi."
        ),
    },
    "KVTS": {
        "title": "Kvarts",
        "url": None,
        "ru": (
            "«Kvarts» — предприятие Узбекистана по производству стекла и стеклоизделий, "
            "расположенное в городе Кувасай Ферганской области. Завод выпускает листовое стекло "
            "и стеклянную тару для пищевой и других отраслей. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Kvarts is an Uzbek glass and glassware producer located in Quvasoy, in the "
            "Fergana region. The plant manufactures sheet glass and glass containers for the "
            "food and other industries. Its shares trade on the Republican Stock Exchange "
            "\"Toshkent\"."
        ),
        "uz": (
            "«Kvarts» — Farg'ona viloyatining Quvasoy shahrida joylashgan O'zbekistonning oyna "
            "va shisha buyumlari ishlab chiqaruvchi korxonasi. Zavod oziq-ovqat va boshqa "
            "tarmoqlar uchun listli oyna hamda shisha idishlar ishlab chiqaradi. Korxona "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "QZSM": {
        "title": "Qizilqumsement",
        "url": None,
        "ru": (
            "«Qizilqumsement» (Кызылкумцемент) — один из крупнейших производителей цемента в "
            "Узбекистане, расположенный в Навоийской области. Предприятие выпускает портландцемент "
            "и другие строительные материалы. Акции предприятия торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "Qizilqumsement (Kyzylkumcement) is one of the largest cement producers in "
            "Uzbekistan, located in the Navoi region. The enterprise manufactures Portland "
            "cement and other building materials. Its shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Qizilqumsement» — Navoiy viloyatida joylashgan O'zbekistonning eng yirik sement "
            "ishlab chiqaruvchilaridan biri. Korxona portlandsement va boshqa qurilish "
            "materiallarini ishlab chiqaradi. Korxona aksiyalari «Toshkent» Respublika fond "
            "birjasida sotiladi."
        ),
    },
    "BECM": {
        "title": "Bekobodsement",
        "url": None,
        "ru": (
            "«Bekobodsement» (Бекабадцемент) — один из старейших цементных заводов Узбекистана, "
            "расположенный в городе Бекабад Ташкентской области. Предприятие производит "
            "портландцемент и другую продукцию для строительной отрасли. Обыкновенные и "
            "привилегированные акции предприятия торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Bekobodsement (Bekabadcement) is one of the oldest cement plants in Uzbekistan, "
            "located in the city of Bekabad in the Tashkent region. The enterprise produces "
            "Portland cement and other products for the construction industry. Its ordinary and "
            "preferred shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Bekobodsement» — Toshkent viloyatining Bekobod shahrida joylashgan "
            "O'zbekistonning eng eski sement zavodlaridan biri. Korxona portlandsement va "
            "qurilish sohasi uchun boshqa mahsulotlarni ishlab chiqaradi. Korxonaning oddiy va "
            "imtiyozli aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UZMT": {
        "title": "UzAuto Motors",
        "url": "https://uzautomotors.com",
        "ru": (
            "«UzAuto Motors» — крупнейший производитель легковых автомобилей в Узбекистане, "
            "ранее известный как GM Uzbekistan. Завод расположен в городе Асака Андижанской "
            "области и выпускает автомобили под брендами Chevrolet и собственными марками для "
            "внутреннего рынка и экспорта. Акции компании торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "UzAuto Motors is the largest passenger-car manufacturer in Uzbekistan, formerly "
            "known as GM Uzbekistan. Its plant is located in Asaka, in the Andijan region, and "
            "produces vehicles under the Chevrolet and its own brands for the domestic market "
            "and export. The company's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«UzAuto Motors» — ilgari GM Uzbekistan nomi bilan tanilgan O'zbekistondagi eng "
            "yirik yengil avtomobil ishlab chiqaruvchisi. Korxona Andijon viloyatining Asaka "
            "shahrida joylashgan bo'lib, ichki bozor va eksport uchun Chevrolet hamda o'z "
            "brendlari ostida avtomobillar ishlab chiqaradi. Kompaniya aksiyalari «Toshkent» "
            "Respublika fond birjasida sotiladi."
        ),
    },
    "FRAZP": {
        "title": "Farg'onaazot",
        "url": None,
        "ru": (
            "«Farg'onaazot» (Ферганаазот) — крупное химическое предприятие Узбекистана, "
            "расположенное в Фергане. Завод производит азотные удобрения и другую химическую "
            "продукцию для сельского хозяйства и промышленности. Привилегированные акции "
            "предприятия торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Farg'onaazot (Ferghanaazot) is a major chemical enterprise in Uzbekistan, located "
            "in Fergana. The plant produces nitrogen fertilizers and other chemical products "
            "for agriculture and industry. Its preferred shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Farg'onaazot» — Farg'ona shahrida joylashgan O'zbekistonning yirik kimyo "
            "korxonasi. Zavod qishloq xo'jaligi va sanoat uchun azotli o'g'itlar va boshqa "
            "kimyoviy mahsulotlarni ishlab chiqaradi. Korxonaning imtiyozli aksiyalari "
            "«Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "DORI": {
        "title": "Dori-Darmon",
        "url": "https://doridarmon.uz",
        "ru": (
            "«Dori-Darmon» — одно из ведущих предприятий Узбекистана в сфере оптовой и "
            "розничной торговли фармацевтической продукцией, с разветвлённой аптечной сетью по "
            "всей стране. Компания занимается хранением, распределением и реализацией "
            "лекарственных средств и медицинских товаров. Акции компании торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Dori-Darmon is one of Uzbekistan's leading companies in the wholesale and retail "
            "distribution of pharmaceuticals, with an extensive pharmacy network across the "
            "country. It stores, distributes and sells medicines and medical products. The "
            "company's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Dori-Darmon» — mamlakat bo'ylab keng dorixonalar tarmog'iga ega bo'lgan, "
            "farmatsevtika mahsulotlarini ulgurji va chakana savdo qilish sohasidagi "
            "O'zbekistonning yetakchi korxonalaridan biri. Kompaniya dori vositalari va "
            "tibbiyot tovarlarini saqlash, taqsimlash va sotish bilan shug'ullanadi. Kompaniya "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "BIOK": {
        "title": "Biokimyo",
        "url": None,
        "ru": (
            "«Biokimyo» (Андижанский биохимический завод) — промышленное предприятие Узбекистана, "
            "расположенное в Андижанской области. Завод специализируется на биохимическом "
            "производстве, включая спирт, дрожжи, углекислоту и кормовые продукты. Акции "
            "предприятия торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Biokimyo (the Andijan Biochemistry Plant) is an Uzbek industrial enterprise "
            "located in the Andijan region. The plant specialises in biochemical production, "
            "including alcohol, yeast, carbon dioxide and feed products. Its shares trade on "
            "the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Biokimyo» (Andijon biokimyo zavodi) — Andijon viloyatida joylashgan "
            "O'zbekistonning sanoat korxonasi. Zavod spirt, achitqi, karbonat angidrid va yem "
            "mahsulotlarini o'z ichiga olgan biokimyoviy ishlab chiqarishga ixtisoslashgan. "
            "Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UZHM": {
        "title": "O'zbekkimyomash",
        "url": None,
        "ru": (
            "«O'zbekkimyomash zavodi» (Узбекхиммаш) — машиностроительное предприятие Узбекистана, "
            "специализирующееся на производстве оборудования и машин для химической и смежных "
            "отраслей промышленности. Акции предприятия торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "O'zbekkimyomash (Uzbekkhimmash) is an Uzbek machine-building enterprise "
            "specialising in the manufacture of equipment and machinery for the chemical and "
            "related industries. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zbekkimyomash zavodi» — kimyo va unga aloqador sanoat tarmoqlari uchun uskuna "
            "va mashinalar ishlab chiqarishga ixtisoslashgan O'zbekiston mashinasozlik "
            "korxonasi. Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "MXUS": {
        "title": "93-Maxsus Trest",
        "url": "http://trest.uz",
        "ru": (
            "«93-Maxsus trest» (Специальный трест № 93) — одно из старейших строительных "
            "предприятий Узбекистана, расположенное в Ташкенте. Трест выполняет специальные "
            "строительные и монтажно-промышленные работы. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "93-Maxsus Trest (Special Trust No. 93) is one of the oldest construction "
            "enterprises in Uzbekistan, based in Tashkent. The trust carries out specialised "
            "construction and industrial assembly works. Its shares trade on the Republican "
            "Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«93-Maxsus trest» — Toshkentda joylashgan O'zbekistonning eng eski qurilish "
            "korxonalaridan biri. Trest maxsus qurilish va sanoat-montaj ishlarini bajaradi. "
            "Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Oil, gas & mining ───────────────────────────────────────────────────
    "AGMKP": {
        "title": "Almalyk Mining and Metallurgical Complex (AMMC)",
        "url": "https://agmk.uz",
        "ru": (
            "Алмалыкский горно-металлургический комбинат (АГМК) — одно из крупнейших "
            "горнодобывающих и металлургических предприятий Узбекистана, расположенное в городе "
            "Алмалык. Комбинат добывает и перерабатывает медь, золото, серебро, цинк и другие "
            "металлы. Привилегированные акции комбината торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "The Almalyk Mining and Metallurgical Complex (AMMC) is one of Uzbekistan's largest "
            "mining and metallurgical enterprises, located in the city of Almalyk. It mines and "
            "processes copper, gold, silver, zinc and other metals. Its preferred shares trade "
            "on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "Olmaliq kon-metallurgiya kombinati (AGMK) — Olmaliq shahrida joylashgan "
            "O'zbekistonning eng yirik konchilik va metallurgiya korxonalaridan biri. Kombinat "
            "mis, oltin, kumush, rux va boshqa metallarni qazib oladi va qayta ishlaydi. "
            "Kombinatning imtiyozli aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "BNGP": {
        "title": "Buxoroneftgazparmalash",
        "url": None,
        "ru": (
            "«Buxoroneftgazparmalash» (Бухаранефтегазбурение) — предприятие Узбекистана, "
            "оказывающее услуги бурения нефтяных и газовых скважин в Бухарской области. Компания "
            "обслуживает нефтегазодобывающую отрасль страны. Обыкновенные и привилегированные "
            "акции предприятия торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Buxoroneftgazparmalash (Bukhara Oil and Gas Drilling) is an Uzbek enterprise "
            "providing oil- and gas-well drilling services in the Bukhara region, serving the "
            "country's oil and gas production industry. Its ordinary and preferred shares trade "
            "on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Buxoroneftgazparmalash» — Buxoro viloyatida neft va gaz quduqlarini burg'ulash "
            "xizmatlarini ko'rsatuvchi O'zbekiston korxonasi bo'lib, mamlakat neft-gaz qazib "
            "olish tarmog'iga xizmat qiladi. Korxonaning oddiy va imtiyozli aksiyalari "
            "«Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "NGQS": {
        "title": "Neft va gaz quduqlarini sinash",
        "url": None,
        "ru": (
            "«Neft va gaz quduqlarini sinash» (Испытание нефтяных и газовых скважин) — "
            "предприятие Узбекистана, специализирующееся на испытании и освоении нефтяных и "
            "газовых скважин для нефтегазовой отрасли. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Neft va gaz quduqlarini sinash (Oil and Gas Well Testing) is an Uzbek enterprise "
            "specialising in the testing and completion of oil and gas wells for the oil and "
            "gas industry. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Neft va gaz quduqlarini sinash» — neft-gaz tarmog'i uchun neft va gaz quduqlarini "
            "sinash va o'zlashtirishga ixtisoslashgan O'zbekiston korxonasi. Korxona aksiyalari "
            "«Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UZGFP": {
        "title": "O'zbekgeofizika",
        "url": None,
        "ru": (
            "«O'zbekgeofizika» (Узбекгеофизика) — предприятие Узбекистана, оказывающее "
            "геофизические услуги при разведке месторождений нефти, газа и других полезных "
            "ископаемых. Привилегированные акции предприятия торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'zbekgeofizika (Uzbekgeofizika) is an Uzbek enterprise providing geophysical "
            "services for the exploration of oil, gas and other mineral deposits. Its preferred "
            "shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zbekgeofizika» — neft, gaz va boshqa foydali qazilma konlarini qidirishda "
            "geofizik xizmatlar ko'rsatuvchi O'zbekiston korxonasi. Korxonaning imtiyozli "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UZIR": {
        "title": "O'zbekko'mir (Uzbekcoal)",
        "url": None,
        "ru": (
            "«O'zbekko'mir» (Узбекуголь) — основное угледобывающее предприятие Узбекистана. "
            "Компания ведёт добычу угля, в том числе на Ангренском месторождении, обеспечивая "
            "топливом энергетику и промышленность страны. Обыкновенные и привилегированные акции "
            "компании торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'zbekko'mir (Uzbekcoal) is Uzbekistan's principal coal-mining company. It "
            "extracts coal, including at the Angren deposit, supplying fuel to the country's "
            "power sector and industry. Its ordinary and preferred shares trade on the "
            "Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zbekko'mir» — O'zbekistonning asosiy ko'mir qazib oluvchi korxonasi. Kompaniya, "
            "jumladan Angren konida ko'mir qazib oladi va mamlakat energetikasi hamda sanoatini "
            "yoqilg'i bilan ta'minlaydi. Kompaniyaning oddiy va imtiyozli aksiyalari «Toshkent» "
            "Respublika fond birjasida sotiladi."
        ),
    },
    "UZNGP": {
        "title": "Uzbekneftegaz",
        "url": "https://www.ung.uz",
        "ru": (
            "«O'zbekneftgaz» (Узбекнефтегаз) — национальная нефтегазовая компания Узбекистана, "
            "осуществляющая разведку, добычу, переработку и транспортировку нефти и природного "
            "газа. Компания играет ключевую роль в энергетическом секторе страны. "
            "Привилегированные акции компании торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Uzbekneftegaz (O'zbekneftgaz) is Uzbekistan's national oil and gas company, "
            "engaged in the exploration, production, refining and transport of oil and natural "
            "gas, and a key player in the country's energy sector. Its preferred shares trade "
            "on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zbekneftgaz» — neft va tabiiy gazni qidirish, qazib olish, qayta ishlash va "
            "tashish bilan shug'ullanuvchi O'zbekistonning milliy neft-gaz kompaniyasi bo'lib, "
            "mamlakat energetika sektorida muhim o'rin tutadi. Kompaniyaning imtiyozli "
            "aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Transport, telecom & infrastructure ─────────────────────────────────
    "UZTL": {
        "title": "Uzbektelecom",
        "url": "https://uztelecom.uz",
        "ru": (
            "«O'zbektelekom» (Узбектелеком) — национальный оператор связи Узбекистана, "
            "предоставляющий услуги фиксированной и мобильной связи, передачи данных и доступа в "
            "интернет по всей стране. Компания развивает магистральную и широкополосную "
            "инфраструктуру связи. Обыкновенные и привилегированные акции компании торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Uzbektelecom is Uzbekistan's national telecommunications operator, providing "
            "fixed-line and mobile communications, data transmission and internet access across "
            "the country, and developing the national backbone and broadband infrastructure. "
            "Its ordinary and preferred shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zbektelekom» — O'zbekistonning milliy aloqa operatori bo'lib, mamlakat bo'ylab "
            "statsionar va mobil aloqa, ma'lumotlar uzatish va internetga ulanish xizmatlarini "
            "taqdim etadi hamda magistral va keng polosali aloqa infratuzilmasini "
            "rivojlantiradi. Kompaniyaning oddiy va imtiyozli aksiyalari «Toshkent» Respublika "
            "fond birjasida sotiladi."
        ),
    },
    "UPOS": {
        "title": "O'zbekiston Pochtasi (Uzbekistan Post)",
        "url": "https://pochta.uz",
        "ru": (
            "«O'zbekiston pochtasi» (Почта Узбекистана) — национальный почтовый оператор "
            "Узбекистана, предоставляющий услуги почтовой связи, доставки посылок, финансовых и "
            "логистических сервисов через широкую сеть отделений по всей стране. Акции компании "
            "торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'zbekiston Pochtasi (Uzbekistan Post) is the national postal operator of "
            "Uzbekistan, providing postal services, parcel delivery, and financial and "
            "logistics services through a wide network of offices across the country. The "
            "company's shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zbekiston pochtasi» — O'zbekistonning milliy pochta operatori bo'lib, mamlakat "
            "bo'ylab keng filiallar tarmog'i orqali pochta aloqasi, jo'natmalarni yetkazib "
            "berish, moliyaviy va logistika xizmatlarini taqdim etadi. Kompaniya aksiyalari "
            "«Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UTGA": {
        "title": "O'ztransgaz",
        "url": None,
        "ru": (
            "«O'ztransgaz» (Узтрансгаз) — предприятие Узбекистана, отвечающее за "
            "транспортировку природного газа по магистральным газопроводам, его хранение и "
            "поставку потребителям. Компания эксплуатирует и обслуживает газотранспортную "
            "систему страны. Привилегированные акции предприятия торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'ztransgaz (Uztransgaz) is an Uzbek enterprise responsible for transporting "
            "natural gas through trunk pipelines, storing it and delivering it to consumers, "
            "operating and maintaining the country's gas-transport system. Its preferred shares "
            "trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'ztransgaz» — tabiiy gazni magistral gaz quvurlari orqali tashish, saqlash va "
            "iste'molchilarga yetkazib berish uchun mas'ul bo'lgan O'zbekiston korxonasi bo'lib, "
            "mamlakat gaz-transport tizimini ishlatadi va xizmat ko'rsatadi. Korxonaning "
            "imtiyozli aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "QATT": {
        "title": "Qashqadaryo Texnologik Transport",
        "url": None,
        "ru": (
            "«Qashqadaryo texnologik transport» — транспортное предприятие Узбекистана, "
            "оказывающее технологические транспортные услуги, преимущественно для предприятий "
            "нефтегазовой отрасли Кашкадарьинской области. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Qashqadaryo Texnologik Transport is an Uzbek transport enterprise providing "
            "technological transport services, primarily for oil and gas companies in the "
            "Kashkadarya region. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Qashqadaryo texnologik transport» — asosan Qashqadaryo viloyatidagi neft-gaz "
            "tarmog'i korxonalari uchun texnologik transport xizmatlarini ko'rsatuvchi "
            "O'zbekiston transport korxonasi. Korxona aksiyalari «Toshkent» Respublika fond "
            "birjasida sotiladi."
        ),
    },
    "UTYK": {
        "title": "O'ztemiryo'lkonteyner",
        "url": "https://utk.uz",
        "ru": (
            "«O'ztemiryo'lkonteyner» (Узтемирйулконтейнер) — оператор контейнерного парка "
            "железных дорог Узбекистана. Компания организует контейнерные перевозки и "
            "транспортно-экспедиторское обслуживание экспортных, импортных, транзитных и "
            "внутренних грузов через сеть терминалов по всей стране. Акции компании торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'ztemiryo'lkonteyner is the operator of the container fleet of Uzbekistan "
            "Railways. The company organises container transport and freight-forwarding "
            "services for export, import, transit and domestic cargo through a network of "
            "terminals across the country. Its shares trade on the Republican Stock Exchange "
            "\"Toshkent\"."
        ),
        "uz": (
            "«O'ztemiryo'lkonteyner» — O'zbekiston temir yo'llarining konteyner parki "
            "operatori. Kompaniya mamlakat bo'ylab terminallar tarmog'i orqali eksport, import, "
            "tranzit va ichki yuklar uchun konteyner tashish va transport-ekspeditsiya "
            "xizmatlarini tashkil etadi. Kompaniya aksiyalari «Toshkent» Respublika fond "
            "birjasida sotiladi."
        ),
    },
    "UVGT": {
        "title": "O'zvagonta'mir",
        "url": "https://uzvagontamir.uz",
        "ru": (
            "«O'zvagonta'mir» (Узвагонтаъмир) — предприятие Узбекистана, специализирующееся на "
            "ремонте грузовых железнодорожных вагонов. Компания выполняет капитальный и средний "
            "ремонт вагонов и колёсных пар через сеть вагоноремонтных депо и связана с "
            "железнодорожной системой страны. Акции компании торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'zvagonta'mir is an Uzbek enterprise specialising in the repair of freight "
            "railway wagons. It carries out major and medium repairs of wagons and wheel sets "
            "through a network of wagon-repair depots and is part of the country's railway "
            "system. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zvagonta'mir» — yuk temir yo'l vagonlarini ta'mirlashga ixtisoslashgan "
            "O'zbekiston korxonasi. Kompaniya vagon ta'mirlash depolari tarmog'i orqali "
            "vagonlar va g'ildirak juftlarini kapital va o'rta ta'mirlashni amalga oshiradi "
            "hamda mamlakat temir yo'l tizimi bilan bog'liq. Kompaniya aksiyalari «Toshkent» "
            "Respublika fond birjasida sotiladi."
        ),
    },
    "YRFS": {
        "title": "Yo'lreftrans",
        "url": None,
        "ru": (
            "«Yo'lreftrans» (Йулрефтранс) — предприятие Узбекистана, эксплуатирующее парк "
            "рефрижераторного подвижного состава железных дорог. Компания обеспечивает перевозку "
            "скоропортящихся грузов в рефрижераторных секциях. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Yo'lreftrans is an Uzbek enterprise that operates the refrigerated rolling stock "
            "of the railways, providing transport of perishable goods in refrigerated sections. "
            "Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Yo'lreftrans» — temir yo'llarning refrijerator harakat tarkibini ishlatuvchi "
            "O'zbekiston korxonasi bo'lib, tez buziladigan yuklarni refrijerator seksiyalarida "
            "tashishni ta'minlaydi. Korxona aksiyalari «Toshkent» Respublika fond birjasida "
            "sotiladi."
        ),
    },
    "MIQE": {
        "title": "Minora Qurish Ekspeditsiyasi",
        "url": "https://www.mqe-aj.uz",
        "ru": (
            "«Minora qurish ekspeditsiyasi» — предприятие Узбекистана, расположенное в Карши "
            "Кашкадарьинской области, специализирующееся на монтаже, демонтаже и перевозке "
            "буровых вышек и оборудования для нефтегазовой отрасли. Компания обслуживает "
            "буровые и нефтегазодобывающие предприятия страны. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Minora Qurish Ekspeditsiyasi is an Uzbek enterprise based in Karshi, in the "
            "Kashkadarya region, specialising in the assembly, dismantling and transport of "
            "drilling rigs and equipment for the oil and gas industry. It serves the country's "
            "drilling and oil-and-gas production companies. Its shares trade on the Republican "
            "Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Minora qurish ekspeditsiyasi» — Qashqadaryo viloyatining Qarshi shahrida "
            "joylashgan, neft-gaz tarmog'i uchun burg'ulash minoralari va uskunalarini "
            "yig'ish, demontaj qilish va tashishga ixtisoslashgan O'zbekiston korxonasi. "
            "Kompaniya mamlakat burg'ulash va neft-gaz qazib olish korxonalariga xizmat "
            "ko'rsatadi. Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "BTRL": {
        "title": "Boshtransloyiha",
        "url": None,
        "ru": (
            "«Boshtransloyiha» — проектный институт Узбекистана, специализирующийся на "
            "проектировании объектов транспортной инфраструктуры — автомобильных дорог, мостов "
            "и сопутствующих сооружений. Акции предприятия торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "Boshtransloyiha is an Uzbek design institute specialising in the engineering and "
            "design of transport-infrastructure projects — roads, bridges and related "
            "structures. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Boshtransloyiha» — transport infratuzilmasi obyektlari — avtomobil yo'llari, "
            "ko'priklar va tegishli inshootlarni loyihalashga ixtisoslashgan O'zbekiston loyiha "
            "instituti. Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "CBSK": {
        "title": "Chilonzor Buyum Savdo Kompleksi",
        "url": None,
        "ru": (
            "«Chilonzor buyum savdo kompleksi» — торговое предприятие Узбекистана, управляющее "
            "крупным торговым комплексом по продаже промышленных и потребительских товаров в "
            "Чиланзарском районе Ташкента. Акции предприятия торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "Chilonzor Buyum Savdo Kompleksi is an Uzbek retail enterprise operating a large "
            "trading complex for industrial and consumer goods in the Chilanzar district of "
            "Tashkent. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Chilonzor buyum savdo kompleksi» — Toshkentning Chilonzor tumanida sanoat va "
            "iste'mol tovarlari savdosi bo'yicha yirik savdo majmuasini boshqaruvchi "
            "O'zbekiston savdo korxonasi. Korxona aksiyalari «Toshkent» Respublika fond "
            "birjasida sotiladi."
        ),
    },
    # ── Insurance ───────────────────────────────────────────────────────────
    "KFSK": {
        "title": "Kafolat sug'urta",
        "url": None,
        "ru": (
            "«Kafolat sug'urta» — одна из старейших и крупнейших страховых компаний "
            "Узбекистана. Общество предоставляет широкий спектр услуг общего страхования для "
            "населения и бизнеса, включая страхование имущества, транспорта, грузов, "
            "ответственности и других рисков, через сеть филиалов по всей стране. Акции "
            "компании торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Kafolat Insurance is one of the oldest and largest insurance companies in "
            "Uzbekistan. It offers a broad range of general insurance for individuals and "
            "businesses — property, motor, cargo, liability and other risks — through a "
            "nationwide branch network. The company's shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Kafolat sug'urta» — O'zbekistonning eng eski va yirik sug'urta kompaniyalaridan "
            "biri. Jamiyat mamlakat bo'ylab filiallar tarmog'i orqali aholi va biznesga "
            "mol-mulk, transport, yuk, javobgarlik va boshqa xavflar bo'yicha keng umumiy "
            "sug'urta xizmatlarini taqdim etadi. Kompaniya aksiyalari «Toshkent» Respublika "
            "fond birjasida sotiladi."
        ),
    },
    # ── Manufacturing ─────────────────────────────────────────────────────────
    "KSCM": {
        "title": "Quvasoysement",
        "url": None,
        "ru": (
            "«Quvasoysement» (Кувасайцемент) — производитель цемента, расположенный в городе "
            "Кувасай Ферганской области. Предприятие выпускает портландцемент и другие "
            "строительные материалы. Акции предприятия торгуются на Республиканской фондовой "
            "бирже «Тошкент»."
        ),
        "en": (
            "Quvasoysement is a cement producer located in Quvasoy, in the Fergana region of "
            "Uzbekistan. The enterprise manufactures Portland cement and other building "
            "materials. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Quvasoysement» — Farg'ona viloyatining Quvasoy shahrida joylashgan sement ishlab "
            "chiqaruvchi korxona. Korxona portlandsement va boshqa qurilish materiallarini "
            "ishlab chiqaradi. Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Oil, gas & energy construction ────────────────────────────────────────
    "NGQT": {
        "title": "Neftgazqurilishta'mir",
        "url": None,
        "ru": (
            "«Neftgazqurilishta'mir» — предприятие Узбекистана, специализирующееся на "
            "строительстве и ремонте объектов нефтегазовой отрасли. Акции предприятия "
            "торгуются на Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Neftgazqurilishta'mir is an Uzbek enterprise specialising in the construction and "
            "repair of oil and gas industry facilities. Its shares trade on the Republican "
            "Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Neftgazqurilishta'mir» — neft-gaz tarmog'i obyektlarini qurish va ta'mirlashga "
            "ixtisoslashgan O'zbekiston korxonasi. Korxona aksiyalari «Toshkent» Respublika "
            "fond birjasida sotiladi."
        ),
    },
    "YGSY": {
        "title": "Yuggazstroy",
        "url": None,
        "ru": (
            "«Yuggazstroy» (Юггазстрой) — строительное предприятие Узбекистана, выполняющее "
            "строительно-монтажные работы для газовой отрасли, включая сооружение "
            "газопроводов и объектов газовой инфраструктуры. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Yuggazstroy is an Uzbek construction enterprise carrying out construction and "
            "assembly works for the gas industry, including gas pipelines and gas-"
            "infrastructure facilities. Its shares trade on the Republican Stock Exchange "
            "\"Toshkent\"."
        ),
        "uz": (
            "«Yuggazstroy» — gaz tarmog'i uchun qurilish-montaj ishlarini, jumladan gaz "
            "quvurlari va gaz infratuzilmasi obyektlarini bunyod etuvchi O'zbekiston qurilish "
            "korxonasi. Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Power-grid & engineering construction ─────────────────────────────────
    "METQ": {
        "title": "Maxsuselektrtarmoqqurilish",
        "url": None,
        "ru": (
            "«Maxsuselektrtarmoqqurilish» — предприятие Узбекистана, специализирующееся на "
            "строительстве и монтаже специальных электрических сетей и линий "
            "электропередачи. Акции предприятия торгуются на Республиканской фондовой бирже "
            "«Тошкент»."
        ),
        "en": (
            "Maxsuselektrtarmoqqurilish is an Uzbek enterprise specialising in the "
            "construction and installation of special electrical grids and power-transmission "
            "lines. Its shares trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Maxsuselektrtarmoqqurilish» — maxsus elektr tarmoqlari va elektr uzatish "
            "liniyalarini qurish va montaj qilishga ixtisoslashgan O'zbekiston korxonasi. "
            "Korxona aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    "UQEQ": {
        "title": "O'zqishloqelektrqurilish",
        "url": None,
        "ru": (
            "«O'zqishloqelektrqurilish» — предприятие Узбекистана, выполняющее строительство "
            "электросетей и электрификацию сельских районов. Акции предприятия торгуются на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "O'zqishloqelektrqurilish is an Uzbek enterprise that builds electrical grids and "
            "carries out rural electrification. Its shares trade on the Republican Stock "
            "Exchange \"Toshkent\"."
        ),
        "uz": (
            "«O'zqishloqelektrqurilish» — qishloq hududlarida elektr tarmoqlari qurilishi va "
            "elektrlashtirish ishlarini bajaruvchi O'zbekiston korxonasi. Korxona aksiyalari "
            "«Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Design & engineering ──────────────────────────────────────────────────
    "TGPG": {
        "title": "Tashgiprogor",
        "url": None,
        "ru": (
            "«Tashgiprogor» (ТАШГИПРОГОР) — проектный институт Узбекистана, специализирующийся "
            "на градостроительном проектировании, разработке генеральных планов городов и "
            "проектов планировки территорий. Акции института торгуются на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "Tashgiprogor is an Uzbek design institute specialising in urban planning — master "
            "plans for cities and territorial-planning projects. Its shares trade on the "
            "Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Tashgiprogor» — shaharsozlik loyihalash, shaharlarning bosh rejalari va "
            "hududlarni rejalashtirish loyihalarini ishlab chiqishga ixtisoslashgan O'zbekiston "
            "loyiha instituti. Institut aksiyalari «Toshkent» Respublika fond birjasida sotiladi."
        ),
    },
    # ── Microfinance & fintech (bond issuers) ───────────────────────────────
    "ACMT": {
        "title": "Agat Credit",
        "url": "https://agatcredit.uz",
        "ru": (
            "«Agat Credit» — одна из активных микрофинансовых организаций Узбекистана, "
            "предоставляющая займы населению и предпринимателям. Компания выпускает "
            "корпоративные облигации, обращающиеся на Республиканской фондовой бирже «Тошкент», "
            "и развивается в сторону микрофинансового банка."
        ),
        "en": (
            "Agat Credit is one of Uzbekistan's active microfinance organisations, providing "
            "loans to individuals and entrepreneurs. The company issues corporate bonds that "
            "trade on the Republican Stock Exchange \"Toshkent\" and is evolving towards "
            "becoming a microfinance bank."
        ),
        "uz": (
            "«Agat Credit» — aholi va tadbirkorlarga kreditlar beruvchi O'zbekistonning faol "
            "mikromoliya tashkilotlaridan biri. Kompaniya «Toshkent» Respublika fond birjasida "
            "sotiladigan korporativ obligatsiyalar chiqaradi va mikromoliya banki tomon "
            "rivojlanmoqda."
        ),
    },
    "BFMT": {
        "title": "Biznes Finans",
        "url": "https://bizfin.uz",
        "ru": (
            "«Biznes Finans» — микрофинансовая организация Узбекистана, работающая на основании "
            "лицензии Центрального банка и обслуживающая клиентов в нескольких регионах страны. "
            "Компания выпускает корпоративные облигации, обращающиеся на Республиканской "
            "фондовой бирже «Тошкент»."
        ),
        "en": (
            "Biznes Finans is an Uzbek microfinance organisation operating under a Central Bank "
            "licence and serving clients across several regions of the country. The company "
            "issues corporate bonds that trade on the Republican Stock Exchange \"Toshkent\"."
        ),
        "uz": (
            "«Biznes Finans» — Markaziy bank litsenziyasi asosida faoliyat yurituvchi va "
            "mamlakatning bir necha hududidagi mijozlarga xizmat ko'rsatuvchi O'zbekiston "
            "mikromoliya tashkiloti. Kompaniya «Toshkent» Respublika fond birjasida sotiladigan "
            "korporativ obligatsiyalar chiqaradi."
        ),
    },
    "CTFB": {
        "title": "Contact Finance",
        "url": "https://www.contactfinance.uz",
        "ru": (
            "«Contact Finance» — микрофинансовая организация Узбекистана, предоставляющая "
            "населению краткосрочные займы и финансовые услуги в соответствии с требованиями "
            "Центрального банка. Компания выпускает корпоративные облигации, обращающиеся на "
            "Республиканской фондовой бирже «Тошкент»."
        ),
        "en": (
            "Contact Finance is an Uzbek microfinance organisation providing short-term loans "
            "and financial services to the public in line with Central Bank requirements. The "
            "company issues corporate bonds that trade on the Republican Stock Exchange "
            "\"Toshkent\"."
        ),
        "uz": (
            "«Contact Finance» — Markaziy bank talablariga muvofiq aholiga qisqa muddatli "
            "kreditlar va moliyaviy xizmatlar taqdim etuvchi O'zbekiston mikromoliya tashkiloti. "
            "Kompaniya «Toshkent» Respublika fond birjasida sotiladigan korporativ obligatsiyalar "
            "chiqaradi."
        ),
    },
    "UZUMS": {
        "title": "Uzum Sarmoya",
        "url": "https://uzum.com",
        "ru": (
            "«Uzum Sarmoya» — финансово-инвестиционное подразделение группы Uzum, узбекской "
            "цифровой экосистемы, объединяющей электронную коммерцию, финтех и банковские "
            "сервисы. Компания выпускает корпоративные облигации, обращающиеся на Республиканской "
            "фондовой бирже «Тошкент», направляя средства на развитие финтех-направления группы."
        ),
        "en": (
            "Uzum Sarmoya is the financing and investment arm of Uzum, an Uzbek digital "
            "ecosystem combining e-commerce, fintech and banking services. The company issues "
            "corporate bonds that trade on the Republican Stock Exchange \"Toshkent\", with "
            "proceeds directed to developing the group's fintech business."
        ),
        "uz": (
            "«Uzum Sarmoya» — elektron tijorat, fintex va bank xizmatlarini birlashtiruvchi "
            "O'zbekiston raqamli ekotizimi bo'lmish Uzum guruhining moliya-investitsiya "
            "bo'linmasi. Kompaniya «Toshkent» Respublika fond birjasida sotiladigan korporativ "
            "obligatsiyalar chiqaradi va mablag'larni guruhning fintex yo'nalishini "
            "rivojlantirishga yo'naltiradi."
        ),
    },
}
