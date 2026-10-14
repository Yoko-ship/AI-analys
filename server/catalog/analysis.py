"""Deterministic catalogue lenses, chosen by organization kind.

Every catalogue analysis — financial analysis, SWOT, conclusion, comparison,
ratios — is built here from the verified filing cache, and every one of them
first asks what kind of organization it is describing
(:mod:`catalogue.organization`). A bank files no revenue or cost of sales and
is judged on return on equity, cost/income and capital; an insurer on its
result and capital against reserves; a fund on its net assets (NAV); a factory
on margin, growth and leverage. One set of factory formulas applied to all of
them is what produced «D — Слабая компания» for the strongest banks and
«Выручка: 0» for a fund.

The scoring and the verdict text are one function of one number: red flags
lower and cap the score, and the verdict is read off the capped score, so the
two cannot point in different directions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from catalogue.organization import BANK, FINANCIAL, FUND, INDUSTRY, INSURANCE

LANGUAGES = ("ru", "uz", "en")


def tr(lang: str, ru: str, uz: str, en: str) -> str:
    return {"ru": ru, "uz": uz, "en": en}.get(lang, ru)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def fmt_number(value: Any, lang: str, digits: int = 1) -> str:
    number = _num(value)
    if number is None:
        return tr(lang, "нет данных", "ma’lumot yo‘q", "no data")
    rendered = f"{abs(number):,.{digits}f}"
    if digits:
        rendered = rendered.rstrip("0").rstrip(".")
    if lang in ("ru", "uz"):
        rendered = rendered.replace(",", " ").replace(".", ",")
    return ("−" if number < 0 and rendered.strip("0,. ") else "") + rendered


def fmt_pct(value: Any, lang: str, digits: int = 1) -> str:
    number = _num(value)
    return fmt_number(number, lang, digits) + "%" if number is not None else fmt_number(None, lang)


_SCALES = ((1e12, "трлн", "trln", "trn"), (1e9, "млрд", "mlrd", "bn"), (1e6, "млн", "mln", "mn"))


def fmt_money(thousands: Any, lang: str) -> str:
    """A statement amount (stored in thousand UZS) as a reader says it."""
    number = _num(thousands)
    if number is None:
        return fmt_number(None, lang)
    uzs = number * 1000
    currency = tr(lang, "сум", "so‘m", "UZS")
    for threshold, ru, uz, en in _SCALES:
        if abs(uzs) >= threshold:
            scaled = uzs / threshold
            return f"{fmt_number(scaled, lang, 2 if abs(scaled) < 10 else 1)} {tr(lang, ru, uz, en)} {currency}"
    return f"{fmt_number(uzs, lang, 0)} {currency}"


def standard_label(form: str, lang: str) -> str:
    return tr(lang, "МСФО", "MHXS", "IFRS") if form == "MSFO" else tr(lang, "НСБУ", "BHMS", "NSBU")


def period_label(year: int, quarter: int, lang: str) -> str:
    quarter = int(quarter or 0)
    if not quarter:
        return tr(lang, f"{year} год", f"{year} yil", f"FY{year}")
    months = quarter * 3
    return tr(lang, f"{months} мес. {year} года", f"{year} yil {months} oy", f"{months}M {year}")


def next_period(year: int, quarter: int) -> tuple[int, int]:
    quarter = int(quarter or 0)
    if not quarter:
        return year + 1, 1
    return (year, 0) if quarter >= 3 else (year, quarter + 1)


KIND_LABELS = {
    BANK: ("банк", "bank", "bank"),
    INSURANCE: ("страховая компания", "sug‘urta kompaniyasi", "insurer"),
    FUND: ("инвестиционный фонд", "investitsiya fondi", "investment fund"),
    FINANCIAL: ("финансовая организация", "moliya tashkiloti", "financial company"),
    INDUSTRY: ("компания", "kompaniya", "company"),
}

KIND_PLURALS = {
    BANK: ("банкам", "banklar", "banks"),
    INSURANCE: ("страховым компаниям", "sug‘urta kompaniyalari", "insurers"),
    FUND: ("фондам", "fondlar", "funds"),
    FINANCIAL: ("финансовым организациям", "moliya tashkilotlari", "financial companies"),
    INDUSTRY: ("компаниям", "kompaniyalar", "companies"),
}


def kind_label(kind: str, lang: str) -> str:
    return tr(lang, *KIND_LABELS.get(kind, KIND_LABELS[INDUSTRY]))


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------

# A change measured from a base below 1% of the new value is a ratio, not a
# percentage: «+14 462 071 915%» is how a bank's profit against a near-zero
# prior read. At or beyond this multiple the change is stated «в N раз».
TIMES_THRESHOLD = 100.0


def times_word(value: float) -> str:
    """«в 2 раза», «в 5 раз», «в 22 раза», «в 12 раз»."""
    whole = int(round(abs(value)))
    return "раза" if whole % 10 in (2, 3, 4) and whole % 100 not in (12, 13, 14) else "раз"


def change_pct(current: Any, previous: Any) -> float | None:
    cur, prev = _num(current), _num(previous)
    if cur is None or prev is None or prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100


def describe_change(current: Any, previous: Any, lang: str, *, money: bool = True) -> str | None:
    """A change a reader can trust: a percentage, «в N раз», or «с X до Y»."""
    cur, prev = _num(current), _num(previous)
    if cur is None or prev is None:
        return None
    show = (lambda v: fmt_money(v, lang)) if money else (lambda v: fmt_pct(v, lang))
    span = tr(lang, f"с {show(prev)} до {show(cur)}", f"{show(prev)} dan {show(cur)} gacha",
              f"from {show(prev)} to {show(cur)}")
    if prev == 0 or (cur != 0 and (cur < 0) != (prev < 0)):
        return span
    if cur == prev:
        return tr(lang, f"без изменений ({show(cur)})", f"o‘zgarishsiz ({show(cur)})", f"unchanged ({show(cur)})")
    ratio = cur / prev
    if ratio >= TIMES_THRESHOLD:
        times = fmt_number(ratio, lang, 0)
        return tr(lang, f"рост в {times} {times_word(ratio)} ({span})", f"{times} barobar o‘sish ({span})",
                  f"{times}× higher ({span})")
    if 0 < ratio <= 1 / TIMES_THRESHOLD:
        times = fmt_number(1 / ratio, lang, 0)
        return tr(lang, f"снижение в {times} {times_word(1 / ratio)} ({span})", f"{times} barobar kamayish ({span})",
                  f"{times}× lower ({span})")
    pct = change_pct(cur, prev)
    sign = "+" if pct > 0 else ""
    return f"{sign}{fmt_pct(pct, lang)} ({span})"


# ---------------------------------------------------------------------------
# Metrics by kind
# ---------------------------------------------------------------------------

METRIC_KEYS: dict[str, tuple[str, ...]] = {
    INDUSTRY: ("ROA", "ROE", "net_margin", "debt_ratio", "debt_to_equity"),
    FINANCIAL: ("ROA", "ROE", "net_margin", "equity_to_assets"),
    BANK: ("ROA", "ROE", "equity_to_assets", "cost_to_income", "cost_of_risk"),
    INSURANCE: ("ROA", "ROE", "net_margin", "equity_to_assets"),
    FUND: ("nav_return", "expense_ratio", "cash_share", "liabilities_to_nav"),
}

METRIC_LABELS = {
    "ROA": ("ROA", "ROA", "ROA"),
    "ROE": ("ROE", "ROE", "ROE"),
    "net_margin": ("Чистая маржа", "Sof marja", "Net margin"),
    "debt_ratio": ("Доля обязательств", "Majburiyatlar ulushi", "Debt ratio"),
    "debt_to_equity": ("Обязательства/капитал", "Majburiyat/kapital", "Debt/equity"),
    "equity_to_assets": ("Капитал/активы", "Kapital/aktivlar", "Equity/assets"),
    "cost_to_income": ("Расходы/доходы (CIR)", "Xarajat/daromad (CIR)", "Cost/income (CIR)"),
    "cost_of_risk": ("Стоимость риска", "Risk qiymati", "Cost of risk"),
    "nav_return": ("Доходность NAV", "NAV daromadliligi", "Return on NAV"),
    "expense_ratio": ("Расходы фонда к NAV", "Fond xarajatlari / NAV", "Expenses to NAV"),
    "cash_share": ("Денежные средства в активах", "Aktivlarda pul mablag‘lari", "Cash share of assets"),
    "liabilities_to_nav": ("Обязательства к NAV", "Majburiyatlar / NAV", "Liabilities to NAV"),
}

# Flow divided by a balance: a year-to-date figure is stated per year.
ANNUALIZED_METRICS = frozenset({"ROA", "ROE", "nav_return", "expense_ratio"})
MULTIPLE_METRICS = frozenset({"debt_to_equity"})

# A bank's cost/income outside this band is a mapping artefact, not a cost
# structure: across the 17 listed banks' 2024–2025 annuals the filed ratio runs
# 26–98% (171% for a loss year), while a 1% reading comes from an operating
# expense line the form left nearly empty.
_CIR_PLAUSIBLE = (10.0, 300.0)
# The indicator feed's cost of risk carries the odd unit slip (432% for one
# bank-year); a credit loss rate beyond half the book is not a rate.
_COR_PLAUSIBLE = (-10.0, 50.0)


def metric_label(key: str, lang: str) -> str:
    return tr(lang, *METRIC_LABELS.get(key, (key, key, key)))


def fmt_metric(key: str, value: Any, lang: str) -> str:
    if _num(value) is None:
        return fmt_number(None, lang)
    if key in MULTIPLE_METRICS:
        return fmt_number(value, lang, 2) + "×"
    return fmt_pct(value, lang)


def kind_metrics(kind: str, payload: dict[str, Any] | None,
                 cost_of_risk: Any = None) -> dict[str, float | None]:
    """The ratios a kind of organization is judged on, from one filing period."""
    payload = payload or {}
    values = payload.get("all_values") or {}
    base = payload.get("metrics") or {}
    months = payload.get("period_months") or 12
    scale = 12 / months if months in (3, 6, 9, 12) else 1.0

    def pct(numerator: Any, denominator: Any, factor: float = 1.0) -> float | None:
        top, bottom = _num(numerator), _num(denominator)
        if top is None or bottom is None or bottom <= 0:
            return None
        return round(top / bottom * 100 * factor, 2)

    assets, equity = _num(values.get("total_assets")), _num(values.get("total_equity"))
    liabilities = _num(values.get("total_liabilities"))
    result: dict[str, float | None] = {}
    for key in METRIC_KEYS.get(kind, METRIC_KEYS[INDUSTRY]):
        if key in ("ROA", "ROE", "net_margin", "debt_ratio", "debt_to_equity"):
            result[key] = _num(base.get(key))
        elif key == "equity_to_assets":
            result[key] = pct(equity, assets)
        elif key == "cost_to_income":
            expenses, income = _num(values.get("operating_expenses")), _num(values.get("gross_profit"))
            value = pct(abs(expenses) if expenses is not None else None, income)
            result[key] = value if value is not None and _CIR_PLAUSIBLE[0] <= value <= _CIR_PLAUSIBLE[1] else None
        elif key == "cost_of_risk":
            value = _num(cost_of_risk) if months == 12 else None
            result[key] = round(value, 2) if value is not None and _COR_PLAUSIBLE[0] <= value <= _COR_PLAUSIBLE[1] else None
        elif key == "nav_return":
            result[key] = pct(values.get("net_income"), equity, scale)
        elif key == "expense_ratio":
            expenses = _num(values.get("operating_expenses"))
            result[key] = pct(abs(expenses) if expenses is not None else None, equity, scale)
        elif key == "cash_share":
            result[key] = pct(values.get("cash"), assets)
        elif key == "liabilities_to_nav":
            result[key] = pct(liabilities, equity)
    return result


def peer_average(metrics_list: list[dict[str, Any]], minimum: int = 3) -> dict[str, Any]:
    """The sector's typical value of each metric for the same period.

    The median, not the mean: across the 30 listed industrial companies'
    half-year 2026 filings a handful of loss-makers with thin equity drag the
    mean ROE to −12% while the typical company earns a positive return, and a
    «sector average» below every ordinary peer misleads. Fewer than
    ``minimum`` peers is not a sector, and the field is left out rather than
    shown as one company's figure.
    """
    out: dict[str, Any] = {}
    counted = 0
    for key in sorted({k for metrics in metrics_list for k in metrics}):
        values = sorted(v for v in (_num(m.get(key)) for m in metrics_list) if v is not None)
        if len(values) >= minimum:
            middle = len(values) // 2
            median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
            out[key] = round(median, 2)
            counted = max(counted, len(values))
    if out:
        out["n"] = counted
        out["stat"] = "median"
    return out


# ---------------------------------------------------------------------------
# Red flags
# ---------------------------------------------------------------------------

HIGH, MEDIUM = "high", "medium"

_FLAG_TEXT = {
    "net_loss": ("чистый убыток за период", "davr uchun sof zarar", "net loss for the period"),
    "negative_equity": ("отрицательный собственный капитал", "salbiy xususiy kapital", "negative equity"),
    "net_income_decline": ("чистая прибыль снизилась более чем на 20%", "sof foyda 20% dan ko‘proq kamaydi",
                           "net income fell by more than 20%"),
    "revenue_decline": ("выручка (доходы) снизилась более чем на 20%", "tushum 20% dan ko‘proq kamaydi",
                        "revenue fell by more than 20%"),
    "operating_income_decline": ("операционная прибыль снизилась", "operatsion foyda kamaydi",
                                 "operating income declined"),
    "negative_operating_result": ("операционный убыток", "operatsion zarar", "operating loss"),
    "liabilities_outpace_equity": ("обязательства растут быстрее капитала", "majburiyatlar kapitaldan tezroq o‘smoqda",
                                   "liabilities are growing faster than equity"),
    "high_cost_to_income": ("расходы поглощают более 80% операционного дохода", "xarajatlar operatsion daromadning 80% dan ortig‘ini yutmoqda",
                            "costs absorb over 80% of operating income"),
    "thin_capital": ("капитал ниже 10% активов", "kapital aktivlarning 10% idan past", "equity below 10% of assets"),
    "high_cost_of_risk": ("стоимость риска выше 5%", "risk qiymati 5% dan yuqori", "cost of risk above 5%"),
}


def red_flags(kind: str, current: dict[str, Any], previous: dict[str, Any] | None,
              opening: dict[str, Any] | None, metrics: dict[str, Any], lang: str) -> list[dict[str, Any]]:
    """Negative signals from one period against its comparable ones.

    The thresholds are the company page's (financial_analysis.sector_assessment):
    a ≥20% fall in net income is a high-materiality signal, a ≥20% fall in
    revenue, any fall in operating income beyond 3% and liabilities outgrowing
    equity by 3 points are medium. A fund has no revenue or operating line of
    its own, so only its result and capital are tested.
    """
    cur = current or {}
    prev = previous or {}
    opn = opening or {}
    flags: list[dict[str, Any]] = []

    def add(code: str, severity: str, detail: str | None = None) -> None:
        text = tr(lang, *_FLAG_TEXT[code])
        flags.append({"code": code, "severity": severity,
                      "text": f"{text}: {detail}" if detail else text})

    net_income = _num(cur.get("net_income"))
    equity = _num(cur.get("total_equity"))
    if net_income is not None and net_income < 0:
        add("net_loss", HIGH, fmt_money(net_income, lang))
    if equity is not None and equity < 0:
        add("negative_equity", HIGH, fmt_money(equity, lang))
    income_change = change_pct(net_income, prev.get("net_income"))
    if (income_change is not None and income_change <= -20 and (net_income or 0) >= 0):
        add("net_income_decline", HIGH, describe_change(net_income, prev.get("net_income"), lang))
    if kind != FUND:
        revenue_change = change_pct(cur.get("revenue"), prev.get("revenue"))
        if revenue_change is not None and revenue_change <= -20:
            add("revenue_decline", MEDIUM, describe_change(cur.get("revenue"), prev.get("revenue"), lang))
        operating = _num(cur.get("operating_income"))
        if operating is not None and operating < 0 and kind == INDUSTRY:
            add("negative_operating_result", MEDIUM, fmt_money(operating, lang))
        else:
            operating_change = change_pct(operating, prev.get("operating_income"))
            if operating_change is not None and -20 < operating_change < -3 and kind == INDUSTRY:
                add("operating_income_decline", MEDIUM,
                    describe_change(operating, prev.get("operating_income"), lang))
        debt_growth = change_pct(cur.get("total_liabilities"), opn.get("total_liabilities"))
        equity_growth = change_pct(cur.get("total_equity"), opn.get("total_equity"))
        if (debt_growth is not None and equity_growth is not None
                and debt_growth > max(3.0, equity_growth + 3.0)):
            add("liabilities_outpace_equity", MEDIUM,
                tr(lang, f"обязательства {fmt_pct(debt_growth, lang)}, капитал {fmt_pct(equity_growth, lang)}",
                   f"majburiyatlar {fmt_pct(debt_growth, lang)}, kapital {fmt_pct(equity_growth, lang)}",
                   f"liabilities {fmt_pct(debt_growth, lang)}, equity {fmt_pct(equity_growth, lang)}"))
    if kind == BANK:
        cir = _num(metrics.get("cost_to_income"))
        if cir is not None and cir > 80:
            add("high_cost_to_income", MEDIUM, fmt_pct(cir, lang))
        capital = _num(metrics.get("equity_to_assets"))
        if capital is not None and capital < 10:
            add("thin_capital", MEDIUM, fmt_pct(capital, lang))
        cor = _num(metrics.get("cost_of_risk"))
        if cor is not None and cor > 5:
            add("high_cost_of_risk", MEDIUM, fmt_pct(cor, lang))
    return flags


# One signal, two names: a profit that turned into a loss is both «net loss»
# and «net income decline», and must cost the score once.
_SAME_SIGNAL = {
    "net_income_decline": "net_loss",
    "operating_income_decline": "negative_operating_result",
}


def merge_published_risks(flags: list[dict[str, Any]], risks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Add the company page's own risks for the same period, once per signal."""
    seen = {_SAME_SIGNAL.get(flag["code"], flag["code"]) for flag in flags}
    merged = list(flags)
    for risk in risks or []:
        code = str(risk.get("code") or "")
        severity = str(risk.get("severity") or "").lower()
        family = _SAME_SIGNAL.get(code, code)
        if not code or family in seen or severity not in (HIGH, MEDIUM):
            continue
        seen.add(family)
        merged.append({"code": code, "severity": severity,
                       "text": str(risk.get("title") or code), "source": "company_report"})
    return merged


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

MIN_CHECKS = 4
# A flagged filing is never «positive»: any medium or high flag caps the score
# here, below the positive band, and each flag also costs points.
FLAG_CAP = 70
FLAG_PENALTY = {HIGH: 20, MEDIUM: 10}
POSITIVE_FROM = 75
NEGATIVE_BELOW = 40

_CHECK_LABELS = {
    "profit": ("прибыль за период", "davr foydasi", "profit for the period"),
    "revenue_growth": ("рост выручки", "tushum o‘sishi", "revenue growth"),
    "income_growth": ("рост прибыли", "foyda o‘sishi", "profit growth"),
    "nav_growth": ("рост NAV", "NAV o‘sishi", "NAV growth"),
}


def _checks(kind: str, current: dict[str, Any], previous: dict[str, Any] | None,
            opening: dict[str, Any] | None, metrics: dict[str, Any]) -> list[tuple[str, bool]]:
    cur, prev, opn = current or {}, previous or {}, opening or {}
    out: list[tuple[str, bool]] = []

    def check(code: str, value: Any, passes) -> None:
        number = _num(value)
        if number is not None:
            out.append((code, bool(passes(number))))

    check("profit", cur.get("net_income"), lambda v: v > 0)
    income_delta = None
    if _num(cur.get("net_income")) is not None and _num(prev.get("net_income")) is not None:
        income_delta = _num(cur.get("net_income")) - _num(prev.get("net_income"))
    check("income_growth", income_delta, lambda v: v > 0)
    if kind == FUND:
        nav_delta = None
        if _num(cur.get("total_equity")) is not None and _num(opn.get("total_equity")) is not None:
            nav_delta = _num(cur.get("total_equity")) - _num(opn.get("total_equity"))
        check("nav_growth", nav_delta, lambda v: v > 0)
        check("nav_return", metrics.get("nav_return"), lambda v: v > 0)
        check("expense_ratio", metrics.get("expense_ratio"), lambda v: v <= 5)
        check("liabilities_to_nav", metrics.get("liabilities_to_nav"), lambda v: v <= 30)
        return out
    check("revenue_growth", change_pct(cur.get("revenue"), prev.get("revenue")), lambda v: v > 0)
    if kind == INDUSTRY:
        check("debt_ratio", metrics.get("debt_ratio"), lambda v: v < 70)
        check("ROE", metrics.get("ROE"), lambda v: v > 0)
        check("net_margin", metrics.get("net_margin"), lambda v: v > 0)
    elif kind == BANK:
        # Calibrated on the 17 listed banks' 2025 annuals: ROE ≥ 10% and
        # ROA ≥ 1% split them 8/9 and 9/8; CIR ≤ 60% holds for the 8 most
        # profitable; capital ≥ 10% fails only the thinnest bank.
        check("ROE", metrics.get("ROE"), lambda v: v >= 10)
        check("ROA", metrics.get("ROA"), lambda v: v >= 1)
        check("equity_to_assets", metrics.get("equity_to_assets"), lambda v: v >= 10)
        check("cost_to_income", metrics.get("cost_to_income"), lambda v: v <= 60)
        check("cost_of_risk", metrics.get("cost_of_risk"), lambda v: v <= 3)
    elif kind == INSURANCE:
        check("ROE", metrics.get("ROE"), lambda v: v >= 10)
        check("net_margin", metrics.get("net_margin"), lambda v: v >= 5)
        check("equity_to_assets", metrics.get("equity_to_assets"), lambda v: v >= 20)
    else:  # FINANCIAL
        check("ROE", metrics.get("ROE"), lambda v: v >= 8)
        check("net_margin", metrics.get("net_margin"), lambda v: v > 0)
        check("equity_to_assets", metrics.get("equity_to_assets"), lambda v: v >= 10)
    return out


def verdict_for(score: int | None) -> str:
    if score is None:
        return "insufficient"
    if score >= POSITIVE_FROM:
        return "positive"
    if score < NEGATIVE_BELOW:
        return "negative"
    return "mixed"


def score_subject(kind: str, current: dict[str, Any], previous: dict[str, Any] | None,
                  opening: dict[str, Any] | None, metrics: dict[str, Any],
                  flags: list[dict[str, Any]]) -> dict[str, Any]:
    checks = _checks(kind, current, previous, opening, metrics)
    base = (round(sum(passed for _, passed in checks) / len(checks) * 100)
            if len(checks) >= MIN_CHECKS else None)
    value = base
    capped = False
    if value is not None and flags:
        value = max(0, value - sum(FLAG_PENALTY.get(f["severity"], 0) for f in flags))
        if value > FLAG_CAP:
            value, capped = FLAG_CAP, True
    return {"value": value, "base": base, "checks": [{"code": c, "passed": p} for c, p in checks],
            "available": len(checks), "passed": sum(p for _, p in checks), "capped": capped,
            "verdict": verdict_for(value)}


_CHECK_RULES = {
    (INDUSTRY, "debt_ratio"): "< 70%", (INDUSTRY, "ROE"): "> 0%", (INDUSTRY, "net_margin"): "> 0%",
    (BANK, "ROE"): "≥ 10%", (BANK, "ROA"): "≥ 1%", (BANK, "equity_to_assets"): "≥ 10%",
    (BANK, "cost_to_income"): "≤ 60%", (BANK, "cost_of_risk"): "≤ 3%",
    (INSURANCE, "ROE"): "≥ 10%", (INSURANCE, "net_margin"): "≥ 5%", (INSURANCE, "equity_to_assets"): "≥ 20%",
    (FINANCIAL, "ROE"): "≥ 8%", (FINANCIAL, "net_margin"): "> 0%", (FINANCIAL, "equity_to_assets"): "≥ 10%",
    (FUND, "nav_return"): "> 0%", (FUND, "expense_ratio"): "≤ 5%", (FUND, "liabilities_to_nav"): "≤ 30%",
}


def check_label(code: str, lang: str, kind: str | None = None) -> str:
    if code == "revenue_growth" and kind in (BANK, INSURANCE, FINANCIAL):
        return tr(lang, "рост: ", "o‘sish: ", "growth: ") + tr(lang, *_revenue_names(kind))
    if code in _CHECK_LABELS:
        return tr(lang, *_CHECK_LABELS[code])
    rule = _CHECK_RULES.get((kind, code))
    return f"{metric_label(code, lang)} {rule}" if rule else metric_label(code, lang)


# ---------------------------------------------------------------------------
# The subject of an analysis
# ---------------------------------------------------------------------------

@dataclass
class Subject:
    ticker: str
    name: str
    kind: str
    form: str
    year: int
    quarter: int
    current: dict[str, Any]
    previous: dict[str, Any] | None = None
    opening: dict[str, Any] | None = None
    sector_template: str | None = None
    cost_of_risk: Any = None
    prev_cost_of_risk: Any = None
    peer_avg: dict[str, Any] = field(default_factory=dict)
    published_risks: list[dict[str, Any]] = field(default_factory=list)
    market: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    prev_metrics: dict[str, Any] = field(default_factory=dict)
    flags: list[dict[str, Any]] = field(default_factory=list)
    score: dict[str, Any] = field(default_factory=dict)

    @property
    def values(self) -> dict[str, Any]:
        return (self.current or {}).get("all_values") or {}

    @property
    def prev_values(self) -> dict[str, Any]:
        return (self.previous or {}).get("all_values") or {} if (self.previous or {}).get("has_data") else {}

    @property
    def opening_values(self) -> dict[str, Any]:
        return (self.opening or {}).get("all_values") or {} if (self.opening or {}).get("has_data") else {}

    @property
    def annualized(self) -> bool:
        return bool((self.current or {}).get("annualized"))

    def evaluate(self, lang: str) -> "Subject":
        self.metrics = kind_metrics(self.kind, self.current, self.cost_of_risk)
        if (self.previous or {}).get("has_data"):
            self.prev_metrics = kind_metrics(self.kind, self.previous, self.prev_cost_of_risk)
        own = red_flags(self.kind, self.values, self.prev_values, self.opening_values, self.metrics, lang)
        self.flags = merge_published_risks(own, self.published_risks)
        self.score = score_subject(self.kind, self.values, self.prev_values, self.opening_values,
                                   self.metrics, self.flags)
        return self


# ---------------------------------------------------------------------------
# Sentences
# ---------------------------------------------------------------------------

def _join(parts: list[str], lang: str) -> str:
    return "; ".join(p for p in parts if p)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if not text or text.endswith((".", "!", "?")) else text + "."


def _upper_first(text: str) -> str:
    """Capitalise the first letter only — str.capitalize would lower «ROE»."""
    return text[:1].upper() + text[1:] if text else text


def _amount_parts(subject: Subject, lang: str) -> tuple[list[str], list[str]]:
    v = subject.values
    kind = subject.kind

    def item(ru: str, uz: str, en: str, key: str) -> str | None:
        value = _num(v.get(key))
        if value is None:
            return None
        # An expense line is filed with either sign; it is stated as an amount.
        return f"{tr(lang, ru, uz, en)}: {fmt_money(abs(value) if key == 'operating_expenses' else value, lang)}"

    if kind == BANK:
        flows = [item("Процентные доходы", "Foizli daromadlar", "Interest income", "revenue"),
                 item("Чистый доход до операционных расходов", "Operatsion xarajatlargacha sof daromad",
                      "Net income before operating expenses", "gross_profit"),
                 item("Операционные расходы", "Operatsion xarajatlar", "Operating expenses", "operating_expenses"),
                 item("Чистая прибыль", "Sof foyda", "Net income", "net_income")]
    elif kind == INSURANCE:
        flows = [item("Доходы от страховой деятельности", "Sug‘urta faoliyati daromadlari", "Insurance revenue", "revenue"),
                 item("Операционный результат", "Operatsion natija", "Operating result", "operating_income"),
                 item("Чистая прибыль", "Sof foyda", "Net income", "net_income")]
    elif kind == FUND:
        flows = [item("Результат периода (изменение NAV от операций)", "Davr natijasi (NAV o‘zgarishi)",
                      "Result for the period (change in NAV from operations)", "net_income"),
                 item("Расходы фонда", "Fond xarajatlari", "Fund expenses", "operating_expenses")]
    elif kind == FINANCIAL:
        flows = [item("Доходы", "Daromadlar", "Income", "revenue"),
                 item("Операционная прибыль", "Operatsion foyda", "Operating income", "operating_income"),
                 item("Чистая прибыль", "Sof foyda", "Net income", "net_income")]
    else:
        flows = [item("Выручка", "Tushum", "Revenue", "revenue"),
                 item("Валовая прибыль", "Yalpi foyda", "Gross profit", "gross_profit"),
                 item("Операционная прибыль", "Operatsion foyda", "Operating income", "operating_income"),
                 item("Чистая прибыль", "Sof foyda", "Net income", "net_income")]
    if kind == FUND:
        balance = [item("Чистые активы (NAV)", "Sof aktivlar (NAV)", "Net assets (NAV)", "total_equity"),
                   item("Активы", "Aktivlar", "Assets", "total_assets"),
                   item("Денежные средства", "Pul mablag‘lari", "Cash", "cash"),
                   item("Обязательства", "Majburiyatlar", "Liabilities", "total_liabilities")]
    else:
        balance = [item("Активы", "Aktivlar", "Assets", "total_assets"),
                   item("Обязательства" if kind != INSURANCE else "Обязательства, включая страховые резервы",
                        "Majburiyatlar" if kind != INSURANCE else "Majburiyatlar (sug‘urta zaxiralari bilan)",
                        "Liabilities" if kind != INSURANCE else "Liabilities incl. insurance reserves",
                        "total_liabilities"),
                   item("Собственный капитал", "Xususiy kapital", "Equity", "total_equity"),
                   item("Денежные средства", "Pul mablag‘lari", "Cash", "cash")]
    return [p for p in flows if p], [p for p in balance if p]


def _revenue_names(kind: str) -> tuple[str, str, str]:
    if kind == BANK:
        return ("процентные доходы", "foizli daromadlar", "interest income")
    if kind == INSURANCE:
        return ("доходы от страховой деятельности", "sug‘urta faoliyati daromadlari", "insurance revenue")
    if kind == FINANCIAL:
        return ("доходы", "daromadlar", "income")
    return ("выручка", "tushum", "revenue")


def _comparable_label(subject: Subject, lang: str) -> str:
    return period_label(subject.year - 1, subject.quarter, lang)


def _trend_parts(subject: Subject, lang: str) -> list[str]:
    parts: list[str] = []
    prev = subject.prev_values
    v = subject.values
    flow_keys = (("net_income", ("результат периода", "davr natijasi", "result for the period")),) if subject.kind == FUND else (
        ("revenue", _revenue_names(subject.kind)),
        ("net_income", ("чистая прибыль", "sof foyda", "net income")),
    )
    for key, names in flow_keys:
        text = describe_change(v.get(key), prev.get(key), lang)
        if text:
            parts.append(f"{tr(lang, *names)}: {text}")
    if parts:
        parts = [tr(lang, f"К {_comparable_label(subject, lang)}", f"{_comparable_label(subject, lang)} ga nisbatan",
                    f"Against {_comparable_label(subject, lang)}") + " — " + "; ".join(parts)]
    opening = subject.opening_values
    balance = []
    for key, names in ((("total_equity", ("NAV", "NAV", "NAV")),) if subject.kind == FUND else (
            ("total_assets", ("активы", "aktivlar", "assets")), ("total_equity", ("капитал", "kapital", "equity")))):
        text = describe_change(v.get(key), opening.get(key), lang)
        if text:
            balance.append(f"{tr(lang, *names)}: {text}")
    if balance:
        parts.append(tr(lang, f"С начала года (31.12.{subject.year - 1})", f"Yil boshidan (31.12.{subject.year - 1})",
                        f"Since 31.12.{subject.year - 1}") + " — " + "; ".join(balance))
    return parts


def _metric_parts(subject: Subject, lang: str, *, with_peers: bool = True) -> list[str]:
    parts = []
    annual_note = tr(lang, " в годовом выражении", " yillik hisobda", " annualised")
    for key, value in subject.metrics.items():
        if _num(value) is None:
            continue
        text = f"{metric_label(key, lang)}: {fmt_metric(key, value, lang)}"
        if subject.annualized and key in ANNUALIZED_METRICS:
            text += annual_note
        avg = subject.peer_avg.get(key) if with_peers else None
        if _num(avg) is not None:
            text += tr(lang, f" (медиана по {subject.peer_avg.get('n')} {tr(lang, *KIND_PLURALS[subject.kind])}: {fmt_metric(key, avg, lang)})",
                       f" ({subject.peer_avg.get('n')} ta {tr(lang, *KIND_PLURALS[subject.kind])} bo‘yicha mediana: {fmt_metric(key, avg, lang)})",
                       f" (median of {subject.peer_avg.get('n')} {tr(lang, *KIND_PLURALS[subject.kind])}: {fmt_metric(key, avg, lang)})")
        parts.append(text)
    return parts


def _no_data(lang: str) -> str:
    return tr(lang, "Нет данных в подтверждённой отчётности.", "Tasdiqlangan hisobotda ma’lumot yo‘q.",
              "No data in the verified filing.")


def _nav_per_share(subject: Subject) -> float | None:
    nav = _num(subject.values.get("total_equity"))
    shares = _num(subject.market.get("shares"))
    if nav is None or shares is None or shares <= 0 or nav <= 0:
        return None
    return nav * 1000 / shares


def _valuation_text(subject: Subject, lang: str) -> str:
    if subject.kind == FUND:
        per_share = _nav_per_share(subject)
        if per_share is None:
            return tr(lang,
                      "NAV на акцию не рассчитывается: в листинге нет подтверждённого числа акций фонда.",
                      "Aksiyaga NAV hisoblanmaydi: listingda fond aksiyalarining tasdiqlangan soni yo‘q.",
                      "NAV per share is not calculated: the listing states no verified share count for the fund.")
        text = tr(lang, f"NAV на акцию: {fmt_number(per_share, lang, 2)} сум (NAV на конец периода, число акций — по листингу биржи).",
                  f"Aksiyaga NAV: {fmt_number(per_share, lang, 2)} so‘m (davr oxiridagi NAV, aksiyalar soni — birja listingi bo‘yicha).",
                  f"NAV per share: UZS {fmt_number(per_share, lang, 2)} (period-end NAV, share count from the exchange listing).")
        price = _num(subject.market.get("price"))
        if price is not None and price > 0:
            premium = (price / per_share - 1) * 100
            when = subject.market.get("price_date") or ""
            word = (tr(lang, "премия", "mukofot", "premium") if premium >= 0 else tr(lang, "дисконт", "chegirma", "discount"))
            text += " " + tr(lang, f"Цена последней сделки {fmt_number(price, lang, 2)} сум ({when}): {word} {fmt_pct(abs(premium), lang)} к NAV на акцию.",
                             f"Oxirgi bitim narxi {fmt_number(price, lang, 2)} so‘m ({when}): aksiyaga NAV ga nisbatan {word} {fmt_pct(abs(premium), lang)}.",
                             f"Last trade UZS {fmt_number(price, lang, 2)} ({when}): a {fmt_pct(abs(premium), lang)} {word} to NAV per share.")
        else:
            text += " " + tr(lang, "Подтверждённой цены сделки нет — премия или дисконт к NAV не рассчитываются.",
                             "Tasdiqlangan bitim narxi yo‘q — NAV ga mukofot yoki chegirma hisoblanmaydi.",
                             "No verified trade price — no premium or discount to NAV is stated.")
        return text
    return tr(lang,
              "Справедливая цена акции не рассчитывается только по финансовому отчёту: для неё нужны подтверждённая рыночная цена и модель оценки.",
              "Faqat moliyaviy hisobot asosida adolatli aksiya narxi hisoblanmaydi; buning uchun tasdiqlangan bozor narxi va baholash modeli kerak.",
              "A fair share price is not calculated from a financial statement alone; it requires a verified market price and a valuation model.")


def _market_text(subject: Subject, lang: str) -> str:
    price = _num(subject.market.get("price"))
    if price is not None and price > 0:
        return tr(lang, f"Последняя сделка: {fmt_number(price, lang, 2)} сум ({subject.market.get('price_date') or '—'}). Котировка в расчёт показателей отчётности не подмешивается.",
                  f"Oxirgi bitim: {fmt_number(price, lang, 2)} so‘m ({subject.market.get('price_date') or '—'}). Kotirovka hisobot ko‘rsatkichlariga aralashtirilmaydi.",
                  f"Last trade: UZS {fmt_number(price, lang, 2)} ({subject.market.get('price_date') or '—'}). The quote is not mixed into the filing's figures.")
    return tr(lang, "Результат относится только к выбранному финансовому отчёту. Рыночные котировки в расчёт не подмешивались.",
              "Ushbu natija tanlangan moliyaviy hisobotga tegishli. Bozor kotirovkasi bu hisob-kitobga aralashtirilmagan.",
              "This result is limited to the selected financial filing. Market quotes were not mixed into the calculation.")


def _dossier(subject: Subject, lang: str) -> str:
    text = tr(lang,
              f"{subject.name} — {kind_label(subject.kind, lang)}. Проанализирован отчёт по {standard_label(subject.form, lang)} за {period_label(subject.year, subject.quarter, lang)}.",
              f"{subject.name} — {kind_label(subject.kind, lang)}. {standard_label(subject.form, lang)} bo‘yicha {period_label(subject.year, subject.quarter, lang)} hisoboti tahlil qilindi.",
              f"{subject.name} is a {kind_label(subject.kind, lang)}. The {standard_label(subject.form, lang)} filing for {period_label(subject.year, subject.quarter, lang)} was analysed.")
    if subject.kind == FUND:
        text += " " + tr(lang, "Фонд описывается чистыми активами (NAV = активы − обязательства): выручка и ROE промышленной компании к нему не применяются.",
                         "Fond sof aktivlar (NAV = aktivlar − majburiyatlar) bilan tavsiflanadi: sanoat kompaniyasining tushumi va ROE qo‘llanilmaydi.",
                         "A fund is described by its net assets (NAV = assets − liabilities); an industrial company's revenue and ROE do not apply.")
    elif subject.kind == BANK:
        text += " " + tr(lang, "Банк оценивается по доходности капитала, расходам к доходам и достаточности капитала, а не по выручке и марже.",
                         "Bank kapital daromadliligi, xarajat/daromad va kapital yetarliligi bo‘yicha baholanadi.",
                         "A bank is judged on return on equity, cost/income and capital, not on revenue and margin.")
    elif subject.kind == INSURANCE:
        text += " " + tr(lang, "Страховая компания оценивается по результату и капиталу относительно активов, включая страховые резервы.",
                         "Sug‘urta kompaniyasi natija va aktivlarga (sug‘urta zaxiralari bilan) nisbatan kapital bo‘yicha baholanadi.",
                         "An insurer is judged on its result and on capital against assets, insurance reserves included.")
    if subject.annualized:
        text += " " + tr(lang, "Доходность за неполный год приведена к годовому выражению.",
                         "To‘liq bo‘lmagan yil daromadliligi yillik hisobga keltirilgan.",
                         "Returns for a part-year are annualised.")
    for note in subject.notes:
        text += " " + _sentence(note)
    return text


# ---------------------------------------------------------------------------
# Lenses
# ---------------------------------------------------------------------------

def financial_sections(subject: Subject, lang: str) -> dict[str, str]:
    flows, balance = _amount_parts(subject, lang)
    money = " ".join(_sentence(_join(group, lang)) for group in (flows, balance) if group)
    trend = _trend_parts(subject, lang)
    metrics = _metric_parts(subject, lang)
    return {
        "ДОСЬЕ": _dossier(subject, lang),
        "ЧТО_С_ДЕНЬГАМИ": money or _no_data(lang),
        "ТРЕНД": _sentence(". ".join(trend)) if trend else tr(lang, "Сопоставимые данные отсутствуют.", "Taqqoslanadigan ma’lumot yo‘q.", "No comparable data is available."),
        "ЭФФЕКТИВНОСТЬ": _sentence(_join(metrics, lang)) if metrics else _no_data(lang),
        "ОЦЕНКА_ЦЕНЫ": _valuation_text(subject, lang),
        "РЫНОЧНЫЕ_ДАННЫЕ": _market_text(subject, lang),
    }


def _sector_risk(subject: Subject, lang: str) -> str | None:
    try:
        from financial_analysis.sector_templates import SECTOR_PROFILES
    except Exception:  # noqa: BLE001 — the SWOT stands without the sector sentence
        return None
    profile = SECTOR_PROFILES.get(subject.sector_template or "")
    if not profile:
        return None
    ru, uz, en = profile["risk"]
    return tr(lang, ru, uz, en)


def swot_sections(subject: Subject, lang: str) -> dict[str, str]:
    v, prev, m, avg = subject.values, subject.prev_values, subject.metrics, subject.peer_avg
    strengths: list[str] = []
    weaknesses: list[str] = []
    opportunities: list[str] = []
    threats: list[str] = []
    net_income = _num(v.get("net_income"))
    if net_income is not None:
        (strengths if net_income > 0 else weaknesses).append(
            tr(lang, f"{'прибыль' if net_income > 0 else 'убыток'} за период {fmt_money(abs(net_income), lang)}",
               f"davr {'foydasi' if net_income > 0 else 'zarari'} {fmt_money(abs(net_income), lang)}",
               f"{'profit' if net_income > 0 else 'loss'} for the period of {fmt_money(abs(net_income), lang)}"))
    income_text = describe_change(v.get("net_income"), prev.get("net_income"), lang)
    delta = change_pct(v.get("net_income"), prev.get("net_income"))
    if income_text and delta is not None and abs(delta) >= 3:
        (strengths if delta > 0 else weaknesses).append(
            tr(lang, f"чистая прибыль к {_comparable_label(subject, lang)}: {income_text}",
               f"{_comparable_label(subject, lang)} ga nisbatan sof foyda: {income_text}",
               f"net income against {_comparable_label(subject, lang)}: {income_text}"))
    headline = {BANK: "ROE", INSURANCE: "ROE", FINANCIAL: "ROE", INDUSTRY: "ROE", FUND: "nav_return"}[subject.kind]
    mentioned: set[str] = set()
    for key in dict.fromkeys((headline, *m)):
        value, mean = _num(m.get(key)), _num(avg.get(key))
        if value is None or mean is None or key in ("cost_of_risk", "cash_share"):
            continue
        lower_is_better = key in ("cost_to_income", "debt_ratio", "debt_to_equity", "expense_ratio", "liabilities_to_nav")
        better = value < mean if lower_is_better else value > mean
        if abs(value - mean) < 0.5:
            continue
        text = tr(lang, f"{metric_label(key, lang)} {fmt_metric(key, value, lang)} против медианы {fmt_metric(key, mean, lang)} по {avg.get('n')} {tr(lang, *KIND_PLURALS[subject.kind])}",
                  f"{metric_label(key, lang)} {fmt_metric(key, value, lang)}, {avg.get('n')} ta {tr(lang, *KIND_PLURALS[subject.kind])} bo‘yicha mediana {fmt_metric(key, mean, lang)}",
                  f"{metric_label(key, lang)} of {fmt_metric(key, value, lang)} against a {fmt_metric(key, mean, lang)} median of {avg.get('n')} {tr(lang, *KIND_PLURALS[subject.kind])}")
        (strengths if better else weaknesses).append(text)
        mentioned.add(key)
        if not better and key == headline and (net_income or 0) > 0:
            opportunities.append(tr(lang, f"доходность ниже медианы сектора при прибыльной работе: сближение {metric_label(key, lang)} с медианой ({fmt_metric(key, mean, lang)}) — резерв роста прибыли",
                                    f"daromadlilik tarmoq medianasidan past: {metric_label(key, lang)} ni mediana ({fmt_metric(key, mean, lang)}) darajaga yaqinlashtirish — foyda o‘sishi zaxirasi",
                                    f"returns trail the sector while profitable: closing {metric_label(key, lang)} to the {fmt_metric(key, mean, lang)} median is room for profit growth"))
    capital = _num(m.get("equity_to_assets"))
    debt_ratio = _num(m.get("debt_ratio"))
    cash_share = None
    if _num(v.get("cash")) is not None and _num(v.get("total_assets")):
        cash_share = _num(v.get("cash")) / _num(v.get("total_assets")) * 100
    if subject.kind in (BANK, FINANCIAL) and capital is not None:
        if capital >= 12:
            if "equity_to_assets" not in mentioned:
                strengths.append(tr(lang, f"капитал {fmt_pct(capital, lang)} активов", f"kapital aktivlarning {fmt_pct(capital, lang)}", f"equity at {fmt_pct(capital, lang)} of assets"))
            opportunities.append(tr(lang, f"запас капитала ({fmt_pct(capital, lang)} активов) позволяет наращивать активы без немедленного привлечения капитала",
                                    f"kapital zaxirasi (aktivlarning {fmt_pct(capital, lang)}) yangi kapital jalb qilmasdan aktivlarni oshirishga imkon beradi",
                                    f"the capital buffer ({fmt_pct(capital, lang)} of assets) leaves room to grow assets without raising equity at once"))
        elif capital < 10 and "equity_to_assets" not in mentioned:
            weaknesses.append(tr(lang, f"капитал лишь {fmt_pct(capital, lang)} активов", f"kapital aktivlarning atigi {fmt_pct(capital, lang)}", f"equity only {fmt_pct(capital, lang)} of assets"))
    if subject.kind == BANK:
        cir = _num(m.get("cost_to_income"))
        if cir is not None and "cost_to_income" not in mentioned:
            (strengths if cir <= 50 else weaknesses if cir > 70 else []).append(
                tr(lang, f"расходы/доходы {fmt_pct(cir, lang)}", f"xarajat/daromad {fmt_pct(cir, lang)}", f"cost/income of {fmt_pct(cir, lang)}"))
        if cir is not None:
            prev_cir = _num(subject.prev_metrics.get("cost_to_income"))
            if prev_cir is not None and cir < prev_cir - 2:
                opportunities.append(tr(lang, f"расходы/доходы снизились с {fmt_pct(prev_cir, lang)} до {fmt_pct(cir, lang)}: при сохранении тенденции прибыль может расти быстрее доходов",
                                        f"xarajat/daromad {fmt_pct(prev_cir, lang)} dan {fmt_pct(cir, lang)} gacha kamaydi: tendensiya saqlansa, foyda daromaddan tezroq o‘sishi mumkin",
                                        f"cost/income fell from {fmt_pct(prev_cir, lang)} to {fmt_pct(cir, lang)}: if the trend holds, profit can outgrow income"))
        cor = _num(m.get("cost_of_risk"))
        if cor is not None and cor > 2:
            threats.append(tr(lang, f"стоимость риска {fmt_pct(cor, lang)}: кредитные потери заметно снижают прибыль",
                              f"risk qiymati {fmt_pct(cor, lang)}: kredit yo‘qotishlari foydani sezilarli kamaytiradi",
                              f"cost of risk at {fmt_pct(cor, lang)}: credit losses weigh on profit"))
    if subject.kind == INDUSTRY and debt_ratio is not None:
        if debt_ratio < 50:
            if "debt_ratio" not in mentioned:
                strengths.append(tr(lang, f"обязательства {fmt_pct(debt_ratio, lang)} активов", f"majburiyatlar aktivlarning {fmt_pct(debt_ratio, lang)}", f"liabilities at {fmt_pct(debt_ratio, lang)} of assets"))
            opportunities.append(tr(lang, f"невысокая долговая нагрузка ({fmt_pct(debt_ratio, lang)} активов) оставляет возможность финансировать развитие заёмными средствами",
                                    f"past qarz yuki (aktivlarning {fmt_pct(debt_ratio, lang)}) rivojlanishni qarz mablag‘lari hisobidan moliyalashtirish imkonini beradi",
                                    f"low leverage ({fmt_pct(debt_ratio, lang)} of assets) leaves room to fund expansion with debt"))
        elif debt_ratio >= 70 and "debt_ratio" not in mentioned:
            weaknesses.append(tr(lang, f"обязательства {fmt_pct(debt_ratio, lang)} активов", f"majburiyatlar aktivlarning {fmt_pct(debt_ratio, lang)}", f"liabilities at {fmt_pct(debt_ratio, lang)} of assets"))
    if subject.kind in (INDUSTRY, FINANCIAL) and cash_share is not None and cash_share >= 10:
        opportunities.append(tr(lang, f"денежные средства {fmt_pct(cash_share, lang)} активов ({fmt_money(v.get('cash'), lang)}) — ресурс для инвестиций или выплат акционерам",
                                f"pul mablag‘lari aktivlarning {fmt_pct(cash_share, lang)} ({fmt_money(v.get('cash'), lang)}) — investitsiya yoki aksiyadorlarga to‘lov manbai",
                                f"cash at {fmt_pct(cash_share, lang)} of assets ({fmt_money(v.get('cash'), lang)}) can fund investment or shareholder payouts"))
    margin, prev_margin = _num(m.get("net_margin")), _num(subject.prev_metrics.get("net_margin"))
    if margin is not None and prev_margin is not None and margin > prev_margin + 1 and margin > 0:
        opportunities.append(tr(lang, f"чистая маржа выросла с {fmt_pct(prev_margin, lang)} до {fmt_pct(margin, lang)}: при сохранении тенденции прибыль может расти быстрее выручки",
                                f"sof marja {fmt_pct(prev_margin, lang)} dan {fmt_pct(margin, lang)} gacha oshdi: tendensiya saqlansa, foyda tushumdan tezroq o‘sishi mumkin",
                                f"net margin rose from {fmt_pct(prev_margin, lang)} to {fmt_pct(margin, lang)}: if it holds, profit can outgrow revenue"))
    if subject.kind == FUND:
        per_share, price = _nav_per_share(subject), _num(subject.market.get("price"))
        if per_share and price:
            premium = (price / per_share - 1) * 100
            if premium < -5:
                opportunities.append(tr(lang, f"акции торгуются с дисконтом {fmt_pct(-premium, lang)} к NAV на акцию: сокращение дисконта — источник доходности",
                                        f"aksiyalar NAV ga nisbatan {fmt_pct(-premium, lang)} chegirma bilan savdoda: chegirmaning qisqarishi — daromad manbai",
                                        f"the shares trade at a {fmt_pct(-premium, lang)} discount to NAV per share: a narrowing discount is a source of return"))
            elif premium > 5:
                threats.append(tr(lang, f"цена выше NAV на акцию на {fmt_pct(premium, lang)}: премия может сократиться",
                                  f"narx aksiyaga NAV dan {fmt_pct(premium, lang)} yuqori: mukofot qisqarishi mumkin",
                                  f"the price is {fmt_pct(premium, lang)} above NAV per share: the premium can shrink"))
        threats.append(tr(lang, "разложение изменения NAV по портфельным компаниям в отчётности не раскрыто — источник результата фонда не подтверждён",
                          "NAV o‘zgarishining portfel kompaniyalari bo‘yicha taqsimoti hisobotda oshkor etilmagan",
                          "the filing does not break the change in NAV down by portfolio company, so the source of the result is unverified"))
    for flag in subject.flags:
        threats.append(flag["text"])
    sector_risk = _sector_risk(subject, lang)
    if sector_risk:
        threats.append(sector_risk.rstrip("."))
    none_text = tr(lang, "По данным выбранного отчёта выраженных сигналов нет.", "Tanlangan hisobot ma’lumotlarida aniq signal yo‘q.",
                   "The selected filing shows no clear signal here.")
    return {
        "СИЛЬНЫЕ_СТОРОНЫ": _sentence(_upper_first(_join(strengths, lang))) if strengths else none_text,
        "СЛАБЫЕ_СТОРОНЫ": _sentence(_upper_first(_join(weaknesses, lang))) if weaknesses else none_text,
        "ВОЗМОЖНОСТИ": _sentence(_upper_first(_join(opportunities, lang))) if opportunities else none_text,
        "УГРОЗЫ": _sentence(_upper_first(_join(threats, lang))) if threats else none_text,
        "КАТАЛИЗАТОРЫ": catalyst_text(subject, lang),
    }


def catalyst_text(subject: Subject, lang: str) -> str:
    """What the next filing will settle for this issuer, in its own figures."""
    v, prev = subject.values, subject.prev_values
    upcoming = period_label(*next_period(subject.year, subject.quarter), lang)
    movements = []
    sources = (("net_income", ("чистой прибыли", "sof foyda", "net income"), prev),
               ("revenue", ("процентных доходов", "foizli daromadlar", "interest income") if subject.kind == BANK
                else ("выручки", "tushum", "revenue"), prev))
    if subject.kind == FUND:
        sources = (("net_income", ("результата фонда", "fond natijasi", "fund result"), prev),
                   ("total_equity", ("NAV", "NAV", "NAV"), subject.opening_values))
    for key, names, base in sources:
        pct = change_pct(v.get(key), base.get(key))
        text = describe_change(v.get(key), base.get(key), lang)
        if pct is not None and text:
            movements.append((abs(pct), key, names, pct, text))
    movements.sort(reverse=True)
    lead = tr(lang, f"Отчёт {subject.name} за {upcoming}", f"{subject.name} ning {upcoming} hisoboti",
              f"{subject.name}'s report for {upcoming}")
    if movements:
        _, _, names, pct, text = movements[0]
        verb = tr(lang, "рост" if pct > 0 else "снижение", "o‘sish" if pct > 0 else "pasayish", "rise" if pct > 0 else "fall")
        body = tr(lang, f"{lead} покажет, сохранится ли {verb} {names[0]}: {text}.",
                  f"{lead} {names[1]} {verb}i davom etadimi-yo‘qligini ko‘rsatadi: {text}.",
                  f"{lead} will show whether the {names[2]} {verb} holds: {text}.")
    else:
        body = tr(lang, f"{lead} даст первую сопоставимую точку для оценки динамики.",
                  f"{lead} dinamikani baholash uchun birinchi taqqoslanadigan nuqtani beradi.",
                  f"{lead} will give the first comparable point for the trend.")
    watch = [f"{metric_label(k, lang)} {fmt_metric(k, val, lang)}" for k, val in subject.metrics.items()
             if _num(val) is not None][:2]
    if watch:
        body += " " + tr(lang, f"Ключевые показатели для наблюдения: {', '.join(watch)}.",
                         f"Kuzatiladigan asosiy ko‘rsatkichlar: {', '.join(watch)}.",
                         f"Key metrics to watch: {', '.join(watch)}.")
    if subject.flags:
        body += " " + tr(lang, f"Отдельно — снимется ли флаг: {subject.flags[0]['text']}.",
                         f"Alohida — bayroq olib tashlanadimi: {subject.flags[0]['text']}.",
                         f"Also whether this flag clears: {subject.flags[0]['text']}.")
    return body


_VERDICT_TEXT = {
    "positive": ("финансовые сигналы положительные", "moliyaviy signallar ijobiy", "financial signals are positive"),
    "mixed": ("финансовые сигналы смешанные", "moliyaviy signallar aralash", "financial signals are mixed"),
    "negative": ("финансовые сигналы отрицательные", "moliyaviy signallar salbiy", "financial signals are negative"),
    "insufficient": ("данных недостаточно для вывода", "xulosa uchun ma’lumot yetarli emas", "there is not enough data for a conclusion"),
}


def flags_text(flags: list[dict[str, Any]], lang: str) -> str:
    if not flags:
        return tr(lang, "Красных флагов по данным отчёта не выявлено.", "Hisobot ma’lumotlarida qizil bayroqlar aniqlanmadi.",
                  "No red flags were found in the filing.")
    level = {HIGH: tr(lang, "высокий", "yuqori", "high"), MEDIUM: tr(lang, "средний", "o‘rta", "medium")}
    return _sentence(_upper_first("; ".join(f"{flag['text']} — {level[flag['severity']]}" for flag in flags)))


def scoring_text(subject: Subject, lang: str) -> str:
    score = subject.score
    label = kind_label(subject.kind, lang)
    if score.get("value") is None:
        return tr(lang, f"Для надёжной оценки нужны минимум {MIN_CHECKS} показателя из набора для типа «{label}»; доступно {score.get('available', 0)}.",
                  f"Ishonchli baho uchun «{label}» turi uchun kamida {MIN_CHECKS} ta ko‘rsatkich kerak; mavjud: {score.get('available', 0)}.",
                  f"A reliable score needs at least {MIN_CHECKS} of the {label} metrics; {score.get('available', 0)} are available.")
    passed = [check_label(c["code"], lang, subject.kind) for c in score["checks"] if c["passed"]]
    failed = [check_label(c["code"], lang, subject.kind) for c in score["checks"] if not c["passed"]]
    text = tr(lang, f"Оценка по показателям для типа «{label}»: {score['value']}/100 — выполнено {score['passed']} из {score['available']} условий.",
              f"«{label}» turi ko‘rsatkichlari bo‘yicha baho: {score['value']}/100 — {score['available']} shartdan {score['passed']} tasi bajarildi.",
              f"Score on the {label} metrics: {score['value']}/100 — {score['passed']} of {score['available']} conditions met.")
    if passed:
        text += " " + tr(lang, f"Выполнены: {', '.join(passed)}.", f"Bajarildi: {', '.join(passed)}.", f"Met: {', '.join(passed)}.")
    if failed:
        text += " " + tr(lang, f"Не выполнены: {', '.join(failed)}.", f"Bajarilmadi: {', '.join(failed)}.", f"Not met: {', '.join(failed)}.")
    if subject.flags:
        text += " " + tr(lang, f"Красные флаги снижают оценку (высокий — на {FLAG_PENALTY[HIGH]}, средний — на {FLAG_PENALTY[MEDIUM]} баллов) и ограничивают её {FLAG_CAP} баллами: без них она составила бы {score['base']}/100.",
                         f"Qizil bayroqlar bahoni pasaytiradi (yuqori — {FLAG_PENALTY[HIGH]}, o‘rta — {FLAG_PENALTY[MEDIUM]} ball) va uni {FLAG_CAP} ball bilan cheklaydi: ularsiz {score['base']}/100 bo‘lardi.",
                         f"Red flags lower the score (high by {FLAG_PENALTY[HIGH]}, medium by {FLAG_PENALTY[MEDIUM]} points) and cap it at {FLAG_CAP}: without them it would be {score['base']}/100.")
    return text


def recommendation_sections(subject: Subject, lang: str) -> dict[str, str]:
    verdict = subject.score.get("verdict", "insufficient")
    period = period_label(subject.year, subject.quarter, lang)
    verdict_text = tr(lang, *_VERDICT_TEXT[verdict])
    line = tr(lang, f"За {period} {verdict_text}", f"{period} uchun {verdict_text}", f"For {period}, {verdict_text}")
    if subject.score.get("value") is not None:
        line += f" ({subject.score['value']}/100)"
    if subject.flags:
        line += tr(lang, f"; учтены красные флаги: {len(subject.flags)}", f"; qizil bayroqlar hisobga olindi: {len(subject.flags)}",
                   f"; red flags taken into account: {len(subject.flags)}")
    return {
        "СКОРИНГ": scoring_text(subject, lang),
        "КРАСНЫЕ_ФЛАГИ": flags_text(subject.flags, lang),
        "ОЦЕНКА_ЦЕНЫ": _valuation_text(subject, lang),
        "ВЕРДИКТ": _sentence(line),
        "ИТОГ": tr(lang, "Это не инвестиционная рекомендация; вывод и оценка основаны только на показателях выбранного отчёта и одинаково учитывают красные флаги.",
                   "Bu investitsiya tavsiyasi emas; xulosa va baho faqat tanlangan hisobot ko‘rsatkichlariga asoslangan va qizil bayroqlarni bir xil hisobga oladi.",
                   "This is not investment advice; the conclusion and the score use only the selected filing's figures and treat red flags the same way."),
    }


def comparison_rows(left: Subject, right: Subject) -> list[dict[str, Any]]:
    rows = []
    for key in dict.fromkeys((*left.metrics, *right.metrics)):
        rows.append({"metric": key, "left": _num(left.metrics.get(key)), "right": _num(right.metrics.get(key)),
                     "annualized": key in ANNUALIZED_METRICS and left.annualized})
    for key in ("total_assets", "total_equity", "net_income", "revenue"):
        if left.kind == FUND and key == "revenue":
            continue
        rows.append({"metric": key, "left": _num(left.values.get(key)), "right": _num(right.values.get(key)),
                     "money": True})
    return rows


def multi_company_sections(left: Subject, right: Subject, lang: str) -> dict[str, str]:
    period = period_label(left.year, left.quarter, lang)
    parts = []
    for key in dict.fromkeys((*left.metrics, *right.metrics)):
        a, b = left.metrics.get(key), right.metrics.get(key)
        if _num(a) is None and _num(b) is None:
            continue
        parts.append(f"{metric_label(key, lang)}: {fmt_metric(key, a, lang)} {tr(lang, 'против', 'va', 'vs')} {fmt_metric(key, b, lang)}")
    size_key = "total_equity" if left.kind == FUND else "total_assets"
    size_name = tr(lang, "NAV", "NAV", "NAV") if left.kind == FUND else tr(lang, "активы", "aktivlar", "assets")
    if _num(left.values.get(size_key)) is not None or _num(right.values.get(size_key)) is not None:
        parts.append(f"{size_name}: {fmt_money(left.values.get(size_key), lang)} {tr(lang, 'против', 'va', 'vs')} {fmt_money(right.values.get(size_key), lang)}")
    head = tr(lang, f"{left.name} против {right.name} ({kind_label(left.kind, lang)}, {standard_label(left.form, lang)}, {period})",
              f"{left.name} va {right.name} ({kind_label(left.kind, lang)}, {standard_label(left.form, lang)}, {period})",
              f"{left.name} versus {right.name} ({kind_label(left.kind, lang)}, {standard_label(left.form, lang)}, {period})")
    comparison = head + ": " + ("; ".join(parts) if parts else tr(lang, "сопоставимых показателей нет", "taqqoslanadigan ko‘rsatkich yo‘q", "no comparable metrics"))
    if left.annualized:
        comparison += tr(lang, ". Доходность приведена к годовому выражению", ". Daromadlilik yillik hisobga keltirilgan", ". Returns are annualised")

    def score_line(subject: Subject) -> str:
        score = subject.score
        if score.get("value") is None:
            return tr(lang, f"{subject.name} — нет данных (доступно показателей: {score.get('available', 0)} из нужных {MIN_CHECKS})",
                      f"{subject.name} — ma’lumot yo‘q ({score.get('available', 0)} ta ko‘rsatkich, kerak {MIN_CHECKS})",
                      f"{subject.name} — no data ({score.get('available', 0)} metrics available, {MIN_CHECKS} needed)")
        verdict = tr(lang, *_VERDICT_TEXT[score["verdict"]])
        flags = (tr(lang, f", красных флагов: {len(subject.flags)}", f", qizil bayroqlar: {len(subject.flags)}",
                    f", red flags: {len(subject.flags)}") if subject.flags else "")
        return f"{subject.name} — {score['value']}/100 ({verdict}{flags})"

    efficiency = tr(lang, "Оценка по одному набору показателей для типа «{}»: ", "«{}» turi uchun bir xil ko‘rsatkichlar bo‘yicha baho: ",
                    "Score on the same {} metric set: ").format(kind_label(left.kind, lang))
    efficiency += "; ".join((score_line(left), score_line(right)))
    return {"СРАВНЕНИЕ": _sentence(comparison), "СКОРИНГ": _sentence(efficiency)}


def build_sections(analysis_type: str, subject: Subject, lang: str) -> dict[str, str]:
    if analysis_type == "financial":
        return financial_sections(subject, lang)
    if analysis_type == "swot":
        return swot_sections(subject, lang)
    if analysis_type == "recommendation":
        return recommendation_sections(subject, lang)
    return {}


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

_UNAVAILABLE_TEXT = {
    "empty_filing": ("отчёт за {period} пуст — все строки нулевые", "{period} hisoboti bo‘sh — barcha qatorlar nol",
                     "the {period} filing is empty — every line is nought"),
    "no_balance": ("в отчёте за {period} нет баланса (итог активов не больше нуля)", "{period} hisobotida balans yo‘q (aktivlar jami noldan katta emas)",
                   "the {period} filing has no balance sheet (total assets not above zero)"),
    "implausible_scale": ("в отчёте за {period} вместо сумм указаны номера строк формы", "{period} hisobotida summalar o‘rniga shakl qator raqamlari ko‘rsatilgan",
                          "the {period} filing states the form's line numbers instead of amounts"),
    "duplicate_period": ("показатели отчёта за {period} совпадают с отчётом за {other} — вероятна ошибка привязки периода при загрузке",
                         "{period} hisoboti ko‘rsatkichlari {other} hisoboti bilan bir xil — yuklashda davr noto‘g‘ri bog‘langan bo‘lishi mumkin",
                         "the {period} filing's figures repeat the {other} filing — the period was likely mislabelled at upload"),
}


def unavailable_reason(problem: dict[str, Any] | None, period: str, lang: str) -> str | None:
    if not problem or problem.get("code") not in _UNAVAILABLE_TEXT:
        return None
    template = tr(lang, *_UNAVAILABLE_TEXT[problem["code"]])
    return template.format(period=period, other=problem.get("duplicate_of") or "")


def _catalog_no_cached_data(language: str, form: str, period: str,
                            problem: dict[str, Any] | None = None) -> str:
    if form == "Audition":
        return tr(language, "Аудиторский отчёт не содержит стандартизированной финансовой таблицы для этого анализа.",
                  "Auditorlik hisobotida ushbu tahlil uchun standartlashtirilgan moliyaviy jadval yo‘q.",
                  "An audit report has no standardized financial table for this analysis.")
    reason = unavailable_reason(problem, period, language)
    if reason:
        return tr(language, f"Анализ не выполняется: {reason}.", f"Tahlil bajarilmaydi: {reason}.",
                  f"No analysis: {reason}.")
    return tr(language, f"Подтверждённые финансовые данные за {period} ещё не загружены.",
              f"{period} uchun tasdiqlangan moliyaviy ma’lumotlar hali yuklanmagan.",
              f"Verified financial data for {period} has not been loaded yet.")
