"""Conservative visible dividend contract, independent of a model's verdict.

This is a bounded vocabulary, not a general natural-language proof. Unknown or
ambiguous wording must be rewritten/reviewed; a payment window never proves a
completed payment. The same contract applies to dividend facts in news copy.
"""
from decimal import Decimal, InvalidOperation
import re

STATES = {
    "proposed": r"предлож(?:ен[аоы]?|или?|ила)|рекоменд(?:ован[аоы]?|овали)|(?:taklif|tavsiya)\s+(?:etildi|qilindi|etilgan|qilingan)|proposed|recommended",
    "approved": r"утвержден[аоы]?|утвердил[аи]?|одобрен[аоы]?|одобрил[аи]?|tasdiqlandi|tasdiqlangan|approved|declared",
    "paid": r"выплачен[аоы]?|выплатил[аи]?|перечислен[аоы]?|перечислил[аи]?|to'landi|to'langan|to'lab\s+beril(?:di|gan)|paid",
}
NEGATIVE = {
    "proposed": r"(?:taklif|tavsiya)\s+(?:etilmadi|qilinmadi)",
    "approved": r"tasdiqlanmadi|tasdiqlanmagan",
    "paid": r"to'lanmadi|to'lanmagan|выплата\s+не\s+подтверждена|payment\s+(?:is\s+)?(?:not\s+confirmed|unconfirmed)",
}
CLASSES = {
    "ordinary": r"(?:обыкновенн\w+|прост(?:ую|ая|ые|ых|ой|ым|ым[и]?))\s+акци\w+|oddiy\s+aksiya\w*|(?:ordinary|common)\s+shares?",
    "preferred": r"привилегированн\w+\s+акци\w+|imtiyozli\s+aksiya\w*|(?:preferred|preference)\s+shares?",
}
PER_SHARE = r"(?:на|за)\s+(?:одну\s+)?(?:\w+\s+)?акцию\b|\b(?:bir\s+)?(?:oddiy|imtiyozli)\s+aksiya\s+uchun\b|\bbir\s+(?:\w+\s+)?aksiya\b|\bper\s+(?:\w+\s+)?share\b|/share\b"
AMOUNT = re.compile(r"(?<![\w.,])(-?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?)\s*(uzs|usd|eur|сум|сўм|so'm|доллар\w*|евро)\b")
CURRENCY = {"uzs": "UZS", "сум": "UZS", "сўм": "UZS", "so'm": "UZS", "usd": "USD", "eur": "EUR", "евро": "EUR"}


def _text(value):
    value = re.sub(r"https?://\S+", "", value).casefold().replace("ё", "е")
    return re.sub("[‘’ʼʻ`´]", "'", value)


def _states(text):
    positive, negative = set(), set()
    for state, pattern in STATES.items():
        for match in re.finditer(r"\b(?:" + pattern + r")\b", text):
            negated = re.search(r"\b(?:не(?:\s+был[аои]?)?|not(?:\s+(?:yet|been))?|never(?:\s+been)?)\s*$", text[:match.start()])
            unconfirmed = re.match(r"\s+(?:не\s+подтвержден\w*|emas|deb\s+tasdiqlanmagan)\b", text[match.end():])
            (negative if negated or unconfirmed else positive).add(state)
        if re.search(r"\b(?:" + NEGATIVE[state] + r")\b", text):
            negative.add(state)
    return positive, negative


def check(item, evidence):
    amounts = [claim for claim in item["claims"] if claim["field"] == "dividend"]
    if not amounts and item["rubric"] != "dividend":
        for clause in re.split(r"[;!?\n]+|\.(?=\s+[A-ZА-ЯЁ])", item["title"] + "\n" + item["body"]):
            visible = _text(clause)
            states, _ = _states(visible)
            dividend = re.search(r"\b(?:дивиденд\w*|dividend\w*)\b", visible)
            if AMOUNT.search(visible) and (dividend or states and re.search(PER_SHARE, visible)):
                return ["A visible dividend amount requires its own checked dividend claim"]
        return []
    facts = []
    for claim in amounts:
        source = evidence.get(claim["evidence_id"])
        data = source["data"] if source else {}
        state, share_class = data.get("dividend_state"), data.get("share_class")
        unit = source["units"].get("dividend", "") if source else ""
        try:
            amount = Decimal(str(data.get("dividend")))
        except InvalidOperation:
            amount = Decimal("NaN")
        if (not isinstance(state, str) or state not in STATES or not isinstance(share_class, str) or share_class not in CLASSES
                or not amount.is_finite() or amount < 0
                or unit not in {"UZS/share", "USD/share", "EUR/share"}):
            return ["Dividend original requires a confirmed state, security class and finite amount per share"]
        facts.append((state, share_class, amount, unit.split("/")[0]))
    if not facts or len(set(facts)) != 1:
        return ["Dividend material needs one unambiguous state, security class and amount from the same original"]
    state, share_class, amount, currency = facts[0]
    text = _text(item["title"] + ". " + item["body"])
    positive, negative = _states(text)
    stages = list(STATES)
    if state not in positive or state in negative or any(stages.index(value) > stages.index(state) for value in positive):
        return ["Dividend wording does not match the original state; distinguish proposed, approved and paid"]
    displayed_classes = {key for key, pattern in CLASSES.items() if re.search(r"\b(?:" + pattern + r")\b", text)}
    if displayed_classes != {share_class}:
        return ["Dividend security class must be visible and match the original"]
    displayed_amounts = []
    for match in AMOUNT.finditer(text):
        value = Decimal(re.sub(r"\s", "", match[1]).replace(",", "."))
        if value == amount:
            displayed_amounts.append(CURRENCY.get(match[2], "USD" if match[2].startswith("доллар") else None))
    if not displayed_amounts or set(displayed_amounts) != {currency} or not re.search(PER_SHARE, text):
        return ["Dividend amount must be displayed in the original currency per share without a scale change"]
    return []
