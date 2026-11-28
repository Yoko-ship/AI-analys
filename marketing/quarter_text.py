"""Bounded RU/UZ/EN quarter wording checks; not a general prose verifier."""
from calendar import monthrange
from datetime import date
from decimal import Decimal, InvalidOperation
import re

from financial_analysis.sector_language import LABELS
from financial_analysis.sector_templates import balance_line

QUARTERS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "first": 1, "second": 2, "third": 3, "fourth": 4,
            **{str(number): number for number in range(1, 5)}}
QUARTER = re.compile(r"\bq([1-4])\b|\b(iv|iii|ii|i|[1-4])(?:[- ](?:й|го|ый))?[- ]*\b(?:квартал\w*|chorak\w*)\b|\b(first|second|third|fourth)\s+quarter\b|\bquarter\s+([1-4])\b")
QUARTER_WORD = re.compile(r"\b(?:квартал\w*|chorak\w*|quarter(?:ly)?)\b")
MONTHS = {"3": 3, "три": 3, "трех": 3, "three": 3, "uch": 3,
          "6": 6, "шесть": 6, "шести": 6, "six": 6, "olti": 6,
          "9": 9, "девять": 9, "девяти": 9, "nine": 9, "to'qqiz": 9,
          "12": 12, "двенадцать": 12, "двенадцати": 12, "twelve": 12, "o'n ikki": 12}
CUMULATIVE = re.compile(r"\b(" + "|".join(map(re.escape, MONTHS)) + r")[- ]*(?:месяц\w*|months?|oy)\b")
AMOUNT = re.compile(r"(?<![\w.,])(-?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?)\s*(тыс\.?|млн\.?|ming|mln\.?|thousand|million)?\s*(uzs|usd|eur|сум|сўм|so'm)\b")
ERROR = "Quarter wording must show the matching standalone original or the checked quarter difference, with its original unit"


def text(value):
    value = re.sub(r"https?://\S+", "", str(value)).casefold().replace("ё", "е")
    return re.sub("[‘’ʼʻ`´]", "'", value)


def aliases(field):
    values = [part.strip() for label in LABELS.get(field, (field,)) for part in re.sub(r"\([^)]*\)", "", label).split("/")]
    if field == "net_income":
        values.extend(["net profit", "чистой прибыли", "чистую прибыль"])
    return r"\b(?:" + "|".join(re.escape(text(value)) for value in sorted(set(values), key=len, reverse=True) if value) + r")\b"


def unit(value):
    value = text(value)
    currency = "UZS" if re.search(r"uzs|сум|сўм|so'm", value) else "USD" if "usd" in value else "EUR" if "eur" in value else None
    scale = 1_000_000 if re.search(r"million|млн|mln", value) else 1000 if re.search(r"thousand|тыс|ming", value) else 1
    return currency, scale


def _flow(field):
    return field in LABELS and not any(balance_line(field, template) for template in ("bank", "enterprise", "insurance", "investment_fund_ifrs_annual"))


def _values(rows, field, start, end):
    allowed = set()
    for row in rows:
        if row.get("period_start") == start and row.get("period") == end and field in row["data"]:
            try:
                currency, scale = unit(row["units"].get(field, ""))
                amount = Decimal(str(row["data"][field]))
                if currency and amount.is_finite():
                    allowed.add((amount * scale, currency))
            except InvalidOperation:
                pass
    return allowed


def _allowed(item, rows, field, year, quarter):
    start = date(year, (quarter - 1) * 3 + 1, 1).isoformat()
    end = date(year, quarter * 3, monthrange(year, quarter * 3)[1]).isoformat()
    allowed = _values(rows, field, start, end)
    calc = item.get("calculation") or {}
    if calc.get("operation") == "difference" and calc.get("field") == field and item["period"] == f"{year}Q{quarter}":
        left = next((row for row in rows if row["id"] == calc.get("left")), None)
        if left:
            try:
                currency, scale = unit(left["units"].get(field, ""))
                amount = Decimal(str(calc["value"]))
                if currency and amount.is_finite():
                    allowed.add((amount * scale, currency))
            except (InvalidOperation, KeyError):
                pass
        # checks.check_difference independently proves operands, periods and arithmetic.
    return allowed


def check(item, rows):
    if item["rubric"] != "quarterly":
        return []
    flows = {claim["field"] for claim in item["claims"] if _flow(claim["field"])}
    calculation_field = (item.get("calculation") or {}).get("field")
    if _flow(calculation_field):
        flows.add(calculation_field)
    known_flows = {field for field in LABELS if _flow(field)}
    clauses = re.split(r"[!?;\n]+|\.(?=\s+[A-ZА-ЯЁ])", item["title"] + "\n" + item["body"])
    for clause in clauses:
        clause = text(clause)
        markers = list(QUARTER.finditer(clause))
        quarters = {QUARTERS[next(value for value in match.groups() if value)] for match in markers}
        if not markers:
            markers = list(QUARTER_WORD.finditer(clause))
            if markers:
                quarters = {int(item["period"][-1])}
        if not quarters and not CUMULATIVE.search(clause):
            continue
        amounts = list(AMOUNT.finditer(clause))
        if not amounts:
            # A numeric financial statement still needs a unit. Strip only
            # period labels so a heading such as “Q3 2026 net income” is safe.
            unlabelled = re.sub(r"\b20\d{2}\b", "", CUMULATIVE.sub("", QUARTER.sub("", clause)))
            if re.search(r"\d", unlabelled) and any(re.search(aliases(field), clause) for field in known_flows):
                return [ERROR]
            continue
        years = {int(value) for value in re.findall(r"\b20\d{2}\b", clause)} or {int(item["period"][:4])}
        if len(quarters) > 1 or len(years) != 1:
            return [ERROR]
        names = sorted((match.start(), match.end(), field) for field in LABELS for match in re.finditer(aliases(field), clause))
        flow_names = [name for name in names if name[2] in known_flows]
        if not names:
            return [ERROR]  # An unnamed quarter amount has no unambiguous financial subject.
        for begin, finish, field in flow_names:
            if field not in flows:
                return [ERROR]
            next_name = min((other[0] for other in names if other[0] >= finish), default=len(clause))
            previous = max((other[1] for other in names if other[1] <= begin), default=0)
            candidates = [value for value in amounts if finish <= value.start() < next_name]
            if not candidates:
                candidates = [value for value in amounts if previous <= value.start() < begin]
            if len(candidates) != 1:
                return [ERROR]
            displayed = candidates[0]
            currency, scale = unit((displayed[2] or "") + " " + displayed[3])
            amount = Decimal(re.sub(r"\s", "", displayed[1]).replace(",", ".")) * scale
            year, quarter = next(iter(years)), next(iter(quarters)) if quarters else int(item["period"][-1])
            cumulative = {MONTHS[match[1]] for match in CUMULATIVE.finditer(clause[previous:next_name])}
            if len(cumulative) > 1:
                return [ERROR]
            if cumulative and all(marker.end() <= begin for marker in markers):
                # A Q3-analysis heading may discuss explicitly labeled nine-month
                # profit. The local financial phrase supplies the actual interval.
                month = next(iter(cumulative))
                allowed = _values(rows, field, date(year, 1, 1).isoformat(), date(year, month, monthrange(year, month)[1]).isoformat())
            else:
                allowed = _allowed(item, rows, field, year, quarter)
            if (amount, currency) not in allowed:
                return [ERROR]
    return []
