"""Statement line definitions, label matching, and translations."""

from __future__ import annotations
import re
from reporting.localization import _normalize_language


def _clean_article_label(label: str) -> str:
    text = str(label or "").replace("\n", " ").strip(" -–—|")
    return " ".join(text.split())[:180] or "—"


def _normalize_article_label_key(label: str) -> str:
    text = str(label or "").lower()
    text = re.sub(r"^[\s\d\.\)\-–—]+", "", text)
    text = re.sub(r"^[a-zа-яё]\s*[\.\)]\s*", "", text)
    text = text.replace("ё", "е")
    text = re.sub(r"\b(а|б|в|г|д|е|ж|з|и|к|л)\b", " ", text)
    text = re.sub(r"[^a-zа-я0-9]+", " ", text)
    return " ".join(text.split())


def _asset_article_specs() -> list[dict]:
    return [
        {"label": "1. Касса и платёжные документы", "line_codes": ["n:1"], "keywords": ["касс"]},
        {"label": "2. Средства к получению из ЦБРУ", "line_codes": ["n:2"], "keywords": ["цбру"]},
        {"label": "3. Средства к получению из других банков", "line_codes": ["n:3"], "keywords": ["других банков"]},
        {"label": "5. Инвестиции (нетто)", "line_codes": ["n:5"], "keywords": ["инвести"], "exclude": ["резерв"], "prefer_clean": True},
        {"label": "7. Кредиты и лизинг (нетто)", "line_codes": ["n:7"], "keywords": ["кредит"], "exclude": ["брутто", "резерв", "минус"], "prefer_clean": True},
        {"label": "— в т.ч. брутто-кредиты", "keywords": ["брутто", "кредит"], "prefer_gross": True},
        {"label": "— в т.ч. резерв на потери", "keywords": ["резерв", "кредит"], "any_keywords": [["потер", "лизинг"]]},
        {"label": "10. Основные средства (нетто)", "line_codes": ["n:10"], "keywords": ["основные средства"]},
        {"label": "11. Начисленные проценты к получению", "line_codes": ["n:11"], "keywords": ["начисленные проценты"]},
        {"label": "13. Другие активы", "line_codes": ["n:13"], "keywords": ["другие активы"], "exclude": ["приобрет", "резерв"]},
        {"label": "14. ИТОГО АКТИВОВ", "line_codes": ["n:14"], "keywords": ["итого актив"], "keep_zero": True},
    ]


def _liability_article_specs() -> list[dict]:
    deposit_parts = [
        {"line_codes": ["n:15"], "keywords": ["депозит", "востреб"]},
        {"line_codes": ["n:16"], "keywords": ["сберегатель", "депозит"]},
        {"line_codes": ["n:17"], "keywords": ["сроч", "депозит"]},
    ]
    return [
        {"label": "Клиентские депозиты, всего", "aggregate": deposit_parts, "allow_duplicate": True},
        {"label": "15. Депозиты до востребования", "line_codes": ["n:15"], "keywords": ["депозит", "востреб"]},
        {"label": "16. Сберегательные депозиты", "line_codes": ["n:16"], "keywords": ["сберегатель", "депозит"]},
        {"label": "17. Срочные депозиты", "line_codes": ["n:17"], "keywords": ["сроч", "депозит"]},
        {"label": "18. К оплате в ЦБРУ", "line_codes": ["n:18"], "keywords": ["цбру"]},
        {"label": "19. К оплате в другие банки", "line_codes": ["n:19"], "keywords": ["другие банки"]},
        {"label": "20. РЕПО / проданные ценные бумаги", "line_codes": ["n:20"], "keywords": ["выкупом"]},
        {"label": "21. Кредиты и лизинг к оплате", "line_codes": ["n:21"], "keywords": ["кредит", "оплат"]},
        {"label": "22. Субординированный долг", "line_codes": ["n:22"], "keywords": ["субординир"]},
        {"label": "23. Начисленные проценты к оплате", "line_codes": ["n:23"], "keywords": ["начисленные проценты"]},
        {"label": "24. Другие обязательства", "line_codes": ["n:24"], "keywords": ["другие обязательства"]},
        {"label": "25. ИТОГО ОБЯЗАТЕЛЬСТВ", "line_codes": ["n:25"], "keywords": ["итого обязательств"], "keep_zero": True},
        {"label": "26. Уставный капитал", "line_codes": ["n:26"], "keywords": ["уставный капитал"]},
        {"label": "28. Резервный капитал", "line_codes": ["n:28"], "keywords": ["резервный капитал"]},
        {"label": "29. Нераспределённая прибыль", "line_codes": ["n:29"], "keywords": ["нераспредел"]},
        {"label": "30. ИТОГО СОБСТВЕННОГО КАПИТАЛА", "line_codes": ["n:30"], "keywords": ["итого собственного капитала"], "keep_zero": True},
        {"label": "31. ИТОГО ОБЯЗАТЕЛЬСТВ И КАПИТАЛА", "line_codes": ["n:31"], "keywords": ["итого обязательств", "капитал"], "keep_zero": True},
    ]


def _income_article_specs() -> list[dict]:
    return [
        {"label": "Процентные доходы: ЦБРУ", "keywords": ["процентные доходы", "цбру"]},
        {"label": "Процентные доходы: другие банки", "keywords": ["процентные доходы", "других банках"]},
        {"label": "Процентные доходы: торговые ценные бумаги", "keywords": ["процентные доходы", "купли-продажи"]},
        {"label": "Процентные доходы: кредиты и лизинг", "keywords": ["процент", "кредит", "лизингов"]},
        {"label": "Другие процентные доходы", "keywords": ["другие процентные доходы"]},
        {"label": "ИТОГО ПРОЦЕНТНЫХ ДОХОДОВ", "keywords": ["итого процентных доход"], "prefer_total": True, "keep_zero": True},
        {"label": "Процентные расходы по депозитам", "keywords": ["итого процентных расходов по депозитам"], "prefer_total": True},
        {"label": "Процентные расходы по кредитам к оплате", "keywords": ["процентные расходы", "кредитам к оплате"]},
        {"label": "Другие процентные расходы", "keywords": ["другие процентные расходы"]},
        {"label": "ИТОГО ПРОЦЕНТНЫХ РАСХОДОВ", "keywords": ["итого процентных расходов"], "exclude": ["депозитам", "займам"], "prefer_total": True, "keep_zero": True},
        {"label": "Чистые процентные доходы до резервов", "line_codes": ["n:3"], "keywords": ["чистые процентные доходы до"]},
        {"label": "Оценка возможных убытков по кредитам и лизингу", "keywords": ["оценка возможных убытков", "кредитам"]},
        {"label": "Чистые процентные доходы после резервов", "keywords": ["после оценки возможных убытков"]},
        {"label": "Комиссионные доходы", "keywords": ["доходы от комиссий"]},
        {"label": "Прибыль в иностранной валюте", "keywords": ["прибыль в иностранной валюте"]},
        {"label": "Другие беспроцентные доходы", "keywords": ["другие беспроцентные доходы"]},
        {"label": "ИТОГО БЕСПРОЦЕНТНЫХ ДОХОДОВ", "keywords": ["итого беспроцентных доход"], "prefer_total": True, "keep_zero": True},
        {"label": "ИТОГО БЕСПРОЦЕНТНЫХ РАСХОДОВ", "keywords": ["итого беспроцентных расходов"], "prefer_total": True},
        {"label": "Чистый доход до операционных расходов", "line_codes": ["n:6"], "keywords": ["чистый доход до операционных расходов"]},
        {"label": "Операционные расходы: персонал", "keywords": ["заработная плата"]},
        {"label": "Операционные расходы: административные", "keywords": ["административные расходы"]},
        {"label": "Операционные расходы: износ", "keywords": ["расходы на износ"]},
        {"label": "Операционные расходы: страхование и налоги", "keywords": ["страхование", "налоги"]},
        {"label": "ИТОГО ОПЕРАЦИОННЫХ РАСХОДОВ", "keywords": ["итого операционных расходов"], "prefer_total": True},
        {"label": "Чистая прибыль до налога", "line_codes": ["n:9"], "keywords": ["чистая прибыль до уплаты налогов"]},
        {"label": "Налог на прибыль", "keywords": ["оценка налога на прибыль"]},
        {"label": "ЧИСТАЯ ПРИБЫЛЬ", "line_codes": ["n:11"], "keywords": ["чистая прибыль"], "keep_zero": True},
    ]


_ARTICLE_LABEL_TRANSLATIONS = {
    "en": {
        "1. Касса и платёжные документы": "1. Cash and payment documents",
        "2. Средства к получению из ЦБРУ": "2. Due from the Central Bank",
        "3. Средства к получению из других банков": "3. Due from other banks",
        "5. Инвестиции (нетто)": "5. Investments, net",
        "7. Кредиты и лизинг (нетто)": "7. Loans and leasing, net",
        "— в т.ч. брутто-кредиты": "- including gross loans",
        "— в т.ч. резерв на потери": "- including loss allowance",
        "10. Основные средства (нетто)": "10. Fixed assets, net",
        "11. Начисленные проценты к получению": "11. Accrued interest receivable",
        "13. Другие активы": "13. Other assets",
        "14. ИТОГО АКТИВОВ": "14. TOTAL ASSETS",
        "Клиентские депозиты, всего": "Client deposits, total",
        "15. Депозиты до востребования": "15. Demand deposits",
        "16. Сберегательные депозиты": "16. Savings deposits",
        "17. Срочные депозиты": "17. Term deposits",
        "18. К оплате в ЦБРУ": "18. Due to the Central Bank",
        "19. К оплате в другие банки": "19. Due to other banks",
        "20. РЕПО / проданные ценные бумаги": "20. REPO / securities sold",
        "21. Кредиты и лизинг к оплате": "21. Loans and leasing payable",
        "22. Субординированный долг": "22. Subordinated debt",
        "23. Начисленные проценты к оплате": "23. Accrued interest payable",
        "24. Другие обязательства": "24. Other liabilities",
        "25. ИТОГО ОБЯЗАТЕЛЬСТВ": "25. TOTAL LIABILITIES",
        "26. Уставный капитал": "26. Charter capital",
        "28. Резервный капитал": "28. Reserve capital",
        "29. Нераспределённая прибыль": "29. Retained earnings",
        "30. ИТОГО СОБСТВЕННОГО КАПИТАЛА": "30. TOTAL EQUITY",
        "31. ИТОГО ОБЯЗАТЕЛЬСТВ И КАПИТАЛА": "31. TOTAL LIABILITIES AND EQUITY",
        "Процентные доходы: ЦБРУ": "Interest income: Central Bank",
        "Процентные доходы: другие банки": "Interest income: other banks",
        "Процентные доходы: торговые ценные бумаги": "Interest income: trading securities",
        "Процентные доходы: кредиты и лизинг": "Interest income: loans and leasing",
        "Другие процентные доходы": "Other interest income",
        "ИТОГО ПРОЦЕНТНЫХ ДОХОДОВ": "TOTAL INTEREST INCOME",
        "Процентные расходы по депозитам": "Interest expense on deposits",
        "Процентные расходы по кредитам к оплате": "Interest expense on borrowings payable",
        "Другие процентные расходы": "Other interest expense",
        "ИТОГО ПРОЦЕНТНЫХ РАСХОДОВ": "TOTAL INTEREST EXPENSE",
        "Чистые процентные доходы до резервов": "Net interest income before provisions",
        "Оценка возможных убытков по кредитам и лизингу": "Provision for possible losses on loans and leasing",
        "Чистые процентные доходы после резервов": "Net interest income after provisions",
        "Комиссионные доходы": "Fee and commission income",
        "Прибыль в иностранной валюте": "Foreign exchange profit",
        "Другие беспроцентные доходы": "Other non-interest income",
        "ИТОГО БЕСПРОЦЕНТНЫХ ДОХОДОВ": "TOTAL NON-INTEREST INCOME",
        "ИТОГО БЕСПРОЦЕНТНЫХ РАСХОДОВ": "TOTAL NON-INTEREST EXPENSE",
        "Чистый доход до операционных расходов": "Net income before operating expenses",
        "Операционные расходы: персонал": "Operating expenses: personnel",
        "Операционные расходы: административные": "Operating expenses: administrative",
        "Операционные расходы: износ": "Operating expenses: depreciation",
        "Операционные расходы: страхование и налоги": "Operating expenses: insurance and taxes",
        "ИТОГО ОПЕРАЦИОННЫХ РАСХОДОВ": "TOTAL OPERATING EXPENSES",
        "Чистая прибыль до налога": "Net profit before tax",
        "Налог на прибыль": "Income tax",
        "ЧИСТАЯ ПРИБЫЛЬ": "NET PROFIT",
    }
}


def _article_display_label(label: str, language: str) -> str:
    text = _clean_article_label(label)
    lang = _normalize_language(language)
    if lang == "ru":
        return text
    translations = _ARTICLE_LABEL_TRANSLATIONS.get(lang) or {}
    if text in translations:
        return translations[text]

    lowered = text.lower()
    prefix_match = re.match(r"^(\d+\.\s*)", text)
    prefix = prefix_match.group(1) if prefix_match else ""
    fallback_rules = [
        (("итого", "актив"), "TOTAL ASSETS"),
        (("клиентские депозиты",), "Client deposits, total"),
        (("депозит", "востреб"), "Demand deposits"),
        (("сберегатель", "депозит"), "Savings deposits"),
        (("сроч", "депозит"), "Term deposits"),
        (("итого", "обязательств", "капитал"), "TOTAL LIABILITIES AND EQUITY"),
        (("итого", "обязательств"), "TOTAL LIABILITIES"),
        (("итого", "собственного капитала"), "TOTAL EQUITY"),
        (("уставный капитал",), "Charter capital"),
        (("резервный капитал",), "Reserve capital"),
        (("нераспредел",), "Retained earnings"),
        (("касс",), "Cash and payment documents"),
        (("цбру",), "Central Bank balances"),
        (("других банков",), "Due from/to other banks"),
        (("инвест",), "Investments"),
        (("кредит", "лизинг", "нетто"), "Loans and leasing, net"),
        (("брутто", "кредит"), "Gross loans"),
        (("резерв", "потер"), "Loss allowance"),
        (("основные средства",), "Fixed assets, net"),
        (("начисленные проценты", "получ"), "Accrued interest receivable"),
        (("начисленные проценты", "оплат"), "Accrued interest payable"),
        (("другие активы",), "Other assets"),
        (("другие обязательства",), "Other liabilities"),
        (("итого процентных доход",), "TOTAL INTEREST INCOME"),
        (("итого процентных расход",), "TOTAL INTEREST EXPENSE"),
        (("чистые процентные доходы до",), "Net interest income before provisions"),
        (("после оценки возможных убытков",), "Net interest income after provisions"),
        (("итого беспроцентных доход",), "TOTAL NON-INTEREST INCOME"),
        (("итого беспроцентных расход",), "TOTAL NON-INTEREST EXPENSE"),
        (("итого операционных расход",), "TOTAL OPERATING EXPENSES"),
        (("чистая прибыль до",), "Net profit before tax"),
        (("налог на прибыль",), "Income tax"),
        (("чистая прибыль",), "NET PROFIT"),
    ]
    for keywords, translation in fallback_rules:
        if all(keyword in lowered for keyword in keywords):
            return f"{prefix}{translation}" if prefix and not translation.startswith(prefix) else translation
    return text


def _article_supplemental_label_is_noise(label: str) -> bool:
    cleaned = _clean_article_label(label)
    if not cleaned or cleaned in {"-", "\u2013", "\u2014"}:
        return True
    if len(cleaned) <= 2 and not re.search(r"\d", cleaned):
        return True
    if re.fullmatch(r"(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4})", cleaned):
        return True
    lowered = cleaned.lower()
    noise_tokens = (
        "reporting date",
        "date of report",
        "balance sheet",
        "income statement",
        "\u0434\u0430\u0442\u0430 \u043e\u0442\u0447\u0435\u0442\u043d\u043e\u0441\u0442\u0438",
        "\u0431\u0443\u0445\u0433\u0430\u043b\u0442\u0435\u0440\u0441\u043a\u0438\u0439 \u0431\u0430\u043b\u0430\u043d\u0441",
        "\u0444\u043e\u0440\u043c\u0430 \u2116",
        "\u043e\u0442\u0447\u0435\u0442 \u043e \u0444\u0438\u043d\u0430\u043d\u0441\u043e\u0432\u044b\u0445 \u0440\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442\u0430\u0445",
    )
    return any(token in lowered for token in noise_tokens)


def _is_total_report_label(label: str) -> bool:
    lowered = str(label or "").lower()
    return any(token in lowered for token in ("итого", "total", "jami", "всего"))
