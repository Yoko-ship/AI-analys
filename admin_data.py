"""admin_data.py — the screens that make a wrong multiple debuggable.

The panel could say *«аудит нашёл 11 расхождений»* and nothing else: which
filing went into the number, which line of which form, what the numerator
actually was. So every disagreement between a published multiple and a
recomputation was investigated by hand, in the database, from scratch.

Four screens close that, and the first two are deliberately in this order:

**«Отчёты» — what the pipeline took in.** One row per stored statement, with
the period it describes, how many months of activity that is, whether another
row claims the same period, and whether this is the row the multiples were
computed from. Half of the defects found so far were not errors of formula but
of *which record reached it*, and while the record's status is invisible every
fix to the calculation is made blind.

**«Эмитент» — the calculation, line by line.** The twelve-month base laid out
as an accountant's worksheet: each component with its period, its months and
its value, the sign it enters with, and the arithmetic spelled out. Beside it
the capitalisation by share class, the balance the denominators come from, and
every validation that ran. Where the panel and the shop window disagree, the
disagreement is visible without a query.

Two more sit beside them. **«Правила»** states the parameters the calculation
reads and the line the panel must not cross — the panel holds thresholds and
exceptions, the code holds the computation, because a formula edited in a panel
is a change with no test and no history. **«Источник»** answers the other half
of "why is this number missing": who was due to file, who did, and who has gone
quiet — a fact about the ISSUER, not about our collector, and the basis of a
public disclosure index.

Nothing here recomputes anything of its own. It reads the SAME functions the
market screen publishes from — ``fundamentals.twelve_month_flows``,
``balance_snapshot``, ``issuer_multiples`` — because a second implementation
would eventually disagree with the first and the panel would be reporting its
own bug. The auditor is the independent recomputation, and it lives in
``audit/`` behind its own import rule.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Sequence

import fundamentals
from formulas import thresholds

logger = logging.getLogger(__name__)

# A record is worth an operator's attention when one of these is true. Each is
# measured, never guessed: an empty list means the intake is clean, and that is
# the normal state.
FLAG_TITLES = {
    "duplicate_period": "дубль периода",
    "no_period": "период не определён",
    "bad_quarter": "номер квартала вне 1–4",
    "future_year": "период в будущем",
    "premature_annual": "годовой за незакрытый год",
    "balance_gap": "баланс не сходится",
    "zero_row": "все суммы нулевые",
}

# Why a stored row never reaches the calculation. The read path
# (``reports_catalog.get_all_financials``) drops these in SQL, silently — this
# screen exists to make the silence visible, so the reasons are spelled the same
# way here and pinned to that path by a test.
INELIGIBLE = ("bad_quarter", "future_year", "premature_annual", "no_period")


def period_status(year: Any, quarter: Any, last_fiscal_year: int) -> list[str]:
    """Why (if at all) this period is not eligible for the calculation.

    Mirrors the eligibility predicate of ``get_all_financials``:
    a quarter outside 1–4 is a corrupt source period («2025Q7», which at
    quarter = 7 outranked every real one); a period stamped beyond the current
    calendar year cannot be a filing that exists yet, and a single mis-stamped
    row otherwise wins «latest» forever and shadows the issuer's real figures;
    an annual for a fiscal year that has not ended is openinfo's in-progress
    placeholder.
    """
    y, q = _num(year), _num(quarter)
    if y is None:
        return ["no_period"]
    y, q = int(y), int(q or 0)
    out: list[str] = []
    if not 0 <= q <= 4:
        out.append("bad_quarter")
    if y > last_fiscal_year + 1:
        out.append("future_year")
    if q == 0 and y > last_fiscal_year:
        out.append("premature_annual")
    return out


def _num(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _period_key(row: dict[str, Any]) -> tuple[int, int] | None:
    year = _num(row.get("year"))
    if year is None:
        return None
    return int(year), int(_num(row.get("quarter")) or 0)


# ---------------------------------------------------------------------------
# Screen 01 — what the pipeline took in
# ---------------------------------------------------------------------------

def report_intake(rows: Sequence[dict[str, Any]], last_fiscal_year: int,
                  used_by_ticker: dict[str, tuple[int, int] | None] | None = None,
                  ) -> dict[str, Any]:
    """Every stored statement, with the status of the RECORD, not the issuer.

    ``rows`` are raw ``catalog_financials`` rows (thousands of UZS, unscaled —
    the screen prints what is stored, not what the market screen divides by).
    ``used_by_ticker`` names the period each ticker's multiples were actually
    computed from, so a row can say whether it is the one that counted.

    Three states, and the difference between them is the whole point of the
    screen: **used** is the row the published numbers rest on; **superseded**
    is a perfectly good record that a newer period outranks, which is normal
    and not a defect; **ineligible** is a record the read path drops in SQL,
    silently, and those are the ones an operator has never been able to see.
    """
    used_by_ticker = used_by_ticker or {}
    seen: dict[tuple[str, int, int], int] = {}
    for row in rows:
        key = _period_key(row)
        if key is None:
            continue
        one = (str(row.get("ticker") or "").upper(), *key)
        seen[one] = seen.get(one, 0) + 1

    out: list[dict[str, Any]] = []
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        key = _period_key(row)
        flags = period_status(row.get("year"), row.get("quarter"), last_fiscal_year)
        if key is not None and seen.get((ticker, *key), 0) > 1:
            flags.append("duplicate_period")
        money = [_num(row.get(f)) for f in
                 ("revenue", "net_income", "total_assets", "total_equity")]
        if all(v in (None, 0) for v in money):
            flags.append("zero_row")
        assets, equity = _num(row.get("total_assets")), _num(row.get("total_equity"))
        liabilities = _num(row.get("total_liabilities"))
        # Капитал + обязательства = активы, допуск 0,1% — the balance either
        # closes or the row is not a balance sheet.
        if assets and equity is not None and liabilities is not None:
            if abs((equity + liabilities) - assets) / abs(assets) > 0.001:
                flags.append("balance_gap")
        used = used_by_ticker.get(ticker)
        eligible = not any(f in INELIGIBLE for f in flags)
        state = ("ineligible" if not eligible
                 else "used" if (key is not None and used is not None and key == used)
                 else "superseded")
        out.append({
            "ticker": ticker,
            "form": row.get("form"),
            "org_type": row.get("org_type"),
            "report_id": row.get("report_id"),
            "year": None if key is None else key[0],
            "quarter": None if key is None else key[1],
            "period": fundamentals.period_label(row) if key is not None else None,
            "months": fundamentals.period_months(row) if key is not None else None,
            "updated_at": row.get("updated_at"),
            "has_balance": bool(row.get("balance_period")),
            "revenue": _num(row.get("revenue")),
            "net_income": _num(row.get("net_income")),
            "total_assets": assets,
            "total_equity": equity,
            "state": state,
            "flags": flags,
        })
    # Ineligible first, then the rows that carry a flag anyway, then the rest.
    rank = {"ineligible": 0, "used": 1, "superseded": 2}
    out.sort(key=lambda r: (rank[r["state"]], not r["flags"], r["ticker"],
                            -(r["year"] or 0), -(r["quarter"] or 0)))
    counts: dict[str, int] = {}
    for row in out:
        for flag in row["flags"]:
            counts[flag] = counts.get(flag, 0) + 1
    return {
        "count": len(out),
        "issuers": len({r["ticker"] for r in out}),
        "used": sum(1 for r in out if r["state"] == "used"),
        "superseded": sum(1 for r in out if r["state"] == "superseded"),
        "ineligible": sum(1 for r in out if r["state"] == "ineligible"),
        "flagged": sum(1 for r in out if r["flags"]),
        "by_flag": [{"flag": k, "title": FLAG_TITLES.get(k, k), "count": v}
                    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])],
        "items": out,
    }


# ---------------------------------------------------------------------------
# Screen 02 — the calculation, line by line
# ---------------------------------------------------------------------------

def _component(label: str, sign: str, period: str | None, months: Any,
               values: dict[str, Any], dropped: bool = False,
               report_id: Any = None) -> dict[str, Any]:
    return {"label": label, "sign": sign, "period": period, "months": months,
            "report_id": report_id, "dropped": dropped,
            "net_income": _num(values.get("net_income")),
            "revenue": _num(values.get("revenue"))}


def ttm_ledger(fin: dict[str, Any] | None) -> dict[str, Any]:
    """The twelve-month base as a worksheet: every component, with its sign.

    ``TTM = годовая величина + YTD текущего года − YTD того же периода прошлого
    года``. The components are the three the read path attaches; which of them
    were actually used follows from the method the assembly reports, and a
    component that exists but did not enter is shown struck through rather than
    hidden — "why is this number the interim alone" is exactly the question the
    screen is for.
    """
    if not fin:
        return {"available": False, "reason": "нет отчётности",
                "components": [], "methods": {}, "result": {}}
    flows = fundamentals.twelve_month_flows(fin)
    method = flows["methods"].get("net_income") or flows["methods"].get("revenue")
    annual, prior = fin.get("annual") or None, fin.get("prior") or None
    row_period = fundamentals.period_label(fin)
    row_months = fundamentals.period_months(fin)

    components: list[dict[str, Any]] = []
    if annual:
        components.append(_component(
            "Годовой отчёт", "+", fundamentals.period_label(annual),
            fundamentals.period_months(annual), annual,
            dropped=(method != "ttm"), report_id=annual.get("report_id")))
    components.append(_component(
        "Текущий период", "+", row_period, row_months, fin,
        dropped=(method == "annual"), report_id=fin.get("report_id")))
    if prior:
        components.append(_component(
            "Сопоставимый период прошлого года", "−",
            fundamentals.period_label(prior), fundamentals.period_months(prior),
            prior, dropped=(method != "ttm"), report_id=prior.get("report_id")))

    explain = {
        "ttm": "годовая величина + текущий интервал − интервал прошлого года",
        "annual": "последний полный год целиком; сопоставимого периода в отчёте нет",
        "annualized": "интервал приведён к году (×12/мес.) — это ОЦЕНКА, годового отчёта нет",
    }.get(method, "база не собрана: не хватает входов")
    return {
        "available": True,
        "method": method,
        "method_note": explain,
        "estimate": bool(flows["estimate"]),
        "period": flows["period"],
        "months": flows["months"],
        "components": components,
        "methods": flows["methods"],
        "result": {k: _num(v) for k, v in flows["values"].items()},
    }


def issuer_ledger(key: str, classes: Sequence[dict[str, Any]],
                  fin: dict[str, Any] | None, ratio: dict[str, Any] | None,
                  today: date | None = None) -> dict[str, Any]:
    """One issuer's whole calculation, as the market screen performs it.

    Every block here is the OUTPUT of the published path, not a re-derivation:
    the same ``issuer_multiples`` the board calls, the same TTM assembly, the
    same balance snapshot. What the screen adds is the arithmetic between them
    — which class contributed which capitalisation, which period each component
    came from, which validation passed.
    """
    multiples = fundamentals.issuer_multiples(classes, fin, ratio, today=today)
    ledger = ttm_ledger(fin)
    snapshot = fundamentals.balance_snapshot(fin, ratio, today)
    cap = multiples.get("market_cap_issuer") or {}

    class_rows = []
    for cls in classes:
        class_rows.append({
            "ticker": cls.get("ticker"),
            "share_class": "preferred" if cls.get("is_preferred") else "ordinary",
            "market_cap": _num(cls.get("market_cap")),
            "shares_outstanding": _num(cls.get("shares_outstanding")),
            # A class with no cap is a class that has never traded: its price
            # would be the registry's nominal, and a capitalisation built on a
            # nominal is fiction. Saying so beats an unexplained blank.
            "counted": _num(cls.get("market_cap")) is not None,
        })

    # Numerator and denominator PER multiple, so a wrong number can be traced
    # to the side it came from without reading the formula's source.
    ni = ledger["result"].get("net_income") if ledger.get("available") else None
    revenue = ledger["result"].get("revenue") if ledger.get("available") else None
    inputs = {
        "pe": {"formula": "CAP / NI_TTM", "numerator": cap.get("value"), "denominator": ni},
        "pb": {"formula": "CAP / EQ_кон", "numerator": cap.get("value"),
               "denominator": snapshot.get("equity")},
        "ps": {"formula": "CAP / REV_TTM", "numerator": cap.get("value"), "denominator": revenue},
        "roe": {"formula": "NI_TTM / EQ_сред", "numerator": ni,
                "denominator": snapshot.get("equity_avg")},
        "roa": {"formula": "NI_TTM / A_сред", "numerator": ni,
                "denominator": snapshot.get("assets_avg")},
        "net_margin": {"formula": "NI_TTM / REV_TTM", "numerator": ni, "denominator": revenue},
    }
    for name, block in inputs.items():
        metric = multiples.get(name) or {}
        block["value"] = metric.get("value")
        block["status"] = metric.get("status")
        block["note"] = metric.get("note")

    checks = (multiples.get("checks") or {})
    return {
        "issuer": key,
        "classes": class_rows,
        "market_cap": {
            "value": cap.get("value"),
            "status": cap.get("status"),
            "note": cap.get("note"),
            "counted": sum(1 for c in class_rows if c["counted"]),
            "total": len(class_rows),
        },
        "form": {
            "org_type": multiples.get("org_type"),
            "base_period": multiples.get("base_period"),
            "base_months": multiples.get("base_months"),
            "balance_period": multiples.get("balance_period"),
        },
        "ttm": ledger,
        "balance": {
            "period": snapshot.get("period"),
            "source": snapshot.get("source"),
            "equity": snapshot.get("equity"),
            "equity_avg": snapshot.get("equity_avg"),
            "assets": snapshot.get("assets"),
            "assets_avg": snapshot.get("assets_avg"),
            "stale": bool(snapshot.get("stale")),
            # Правило: незаполненный остаток на начало приходит буквальным
            # нулём, и подстановка его в среднее удваивала показатель — ROE
            # ровно 2,00× у UZNF/TRSB/IPKY. Правило названо на экране, а не
            # спрятано в коде: равенство среднего и остатка на конец и ЕСТЬ
            # признак того, что начало периода не заполнено.
            "rule": ("остаток на начало не заполнен — знаменатель равен остатку "
                     "на конец периода"
                     if (snapshot.get("equity_avg") is not None
                         and snapshot.get("equity_avg") == snapshot.get("equity"))
                     else "среднее из остатков на начало и конец периода"),
        },
        "inputs": inputs,
        "validation": multiples.get("validation"),
        "shares_check": multiples.get("shares_check"),
        "checks": {"results": checks.get("results") or {}, "flags": checks.get("flags") or []},
        "multiples": {k: multiples.get(k) for k in
                      ("pe", "pb", "ps", "roe", "roa", "net_margin",
                       "equity_assets", "bvps")},
    }


# ---------------------------------------------------------------------------
# Screen 06 — the source, and who has not filed
# ---------------------------------------------------------------------------

# The filing window as the regulation sets it: the quarter closes, disclosure
# opens on the 25th of the following month and runs for 45 days. Anything after
# that is late — and «late» is a fact about the ISSUER, not about the collector,
# which is why the screen states it rather than treating the gap as a data
# problem of ours.
DISCLOSURE_OPENS_DAYS = 25
DISCLOSURE_WINDOW_DAYS = 45

_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _quarter_end(year: int, quarter: int) -> date:
    month, day = _QUARTER_END[quarter]
    return date(year, month, day)


def expected_period(today: date) -> tuple[int, int]:
    """The newest interim period whose disclosure window has opened."""
    year, quarter = today.year, (today.month - 1) // 3 + 1
    for _ in range(8):
        quarter -= 1
        if quarter < 1:
            year, quarter = year - 1, 4
        if (today - _quarter_end(year, quarter)).days >= DISCLOSURE_OPENS_DAYS:
            return year, quarter
    return today.year - 1, 4


def disclosure_calendar(latest_by_ticker: dict[str, tuple[int, int]],
                        today: date | None = None) -> dict[str, Any]:
    """Who was due to file, who did, and who has gone quiet.

    ``latest_by_ticker`` is the newest period each issuer has on file. The same
    list is the basis of a public disclosure index: an issuer that has filed
    nothing since 2019 is a fact about that issuer, and one worth publishing.
    """
    today = today or date.today()
    year, quarter = expected_period(today)
    due = _quarter_end(year, quarter) + timedelta(
        days=DISCLOSURE_OPENS_DAYS + DISCLOSURE_WINDOW_DAYS)
    overdue_days = max(0, (today - due).days)

    rows: list[dict[str, Any]] = []
    for ticker, period in sorted((latest_by_ticker or {}).items()):
        got_year, got_quarter = period
        filed = (got_year, got_quarter if got_quarter else 4) >= (year, quarter)
        latest = f"{got_year}A" if not got_quarter else f"{got_year}Q{got_quarter}"
        # How many whole quarters behind: an issuer one period late in an open
        # window is not the same thing as one that stopped filing in 2019, and
        # sorting them together hides the second behind the first.
        behind = (year - got_year) * 4 + (quarter - (got_quarter or 4))
        rows.append({
            "ticker": ticker,
            "expected": f"{year}Q{quarter}",
            "filed": filed,
            "latest": latest,
            "quarters_behind": 0 if filed else max(behind, 0),
            "overdue_days": 0 if filed else overdue_days,
            "state": ("сдан" if filed
                      else "молчит" if behind >= 4
                      else "просрочен" if overdue_days > 0
                      else "ожидается"),
        })
    rows.sort(key=lambda r: (r["filed"], -r["quarters_behind"], r["ticker"]))
    return {
        "expected": f"{year}Q{quarter}",
        "window_opens": (_quarter_end(year, quarter)
                         + timedelta(days=DISCLOSURE_OPENS_DAYS)).isoformat(),
        "window_closes": due.isoformat(),
        "overdue_days": overdue_days,
        "issuers": len(rows),
        "filed": sum(1 for r in rows if r["filed"]),
        "late": sum(1 for r in rows if r["state"] == "просрочен"),
        "silent": sum(1 for r in rows if r["state"] == "молчит"),
        "items": rows,
    }


# ---------------------------------------------------------------------------
# Screen 05 — the parameters that are configuration, not code
# ---------------------------------------------------------------------------

def rule_book() -> dict[str, Any]:
    """The thresholds the calculation reads, and where each one is decided.

    The line the panel must not cross: **it shows parameters and exceptions,
    the code holds the computation.** Formulas, the NSBU form parsers and the
    choice of reporting period change through a pull request with the
    validations run — not through a form on this screen — because a formula
    edited in a panel is a change with no test and no history.
    """
    cfg = thresholds()
    multiples, financials = cfg.get("multiples") or {}, cfg.get("financials") or {}
    rows = [
        ("Возраст годового отчёта, дн.", financials.get("report_max_age_days"), "код",
         "старше — мультипликаторы не публикуются (V4); судится САМЫЙ СТАРЫЙ период, "
         "на который опирается база, а не последняя поданная строка"),
        ("Диапазон P/E", _range(multiples.get("pe_range")), "код",
         "вне диапазона печатается «н/зн»: значение остаётся в подсказке, "
         "в сортировках и выгрузках считается отсутствующим"),
        ("Диапазон P/B", _range(multiples.get("pb_range")), "код", ""),
        ("Диапазон P/S", _range(multiples.get("ps_range")), "код", ""),
        ("|ROE| не более, %", multiples.get("roe_abs_max"), "код", ""),
        ("|Маржа| не более, %", multiples.get("margin_abs_max"), "код", ""),
        ("Допуск тождеств", multiples.get("identity_tolerance"), "код",
         "расхождение сверх порога снимает только те мультипликаторы, которые "
         "на нём построены, а не всю строку"),
        ("Допуск сходимости баланса", financials.get("balance_identity_tolerance"), "код",
         "капитал + обязательства = активы"),
        ("Капитализация против цены × бумаг, раз", multiples.get("cap_vs_price_shares_max"),
         "код", ""),
    ]
    return {
        "boundary": {
            "panel": ["пороги", "диапазоны", "допуски", "флаги показателей",
                      "справочники тикеров", "правила показа", "ручные переопределения"],
            "code": ["формулы", "парсеры форм НСБУ", "выбор отчётного периода",
                     "сборка TTM"],
            "why": ("Формула, изменённая в панели, — это изменение без теста и "
                    "без истории. Поэтому вычисление живёт в коде и меняется "
                    "через PR с прогоном валидаций."),
        },
        "thresholds": [{"name": n, "value": v, "owner": o, "note": note}
                       for n, v, o, note in rows if v is not None],
    }


def _range(bounds: Any) -> str | None:
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
        return None
    return f"{bounds[0]} … {bounds[1]}"
