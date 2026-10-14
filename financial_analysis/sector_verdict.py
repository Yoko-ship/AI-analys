"""The verdict: one of five words, reached on three axes, with its reason.

Growth, profitability and stability are each compared with the same base the
text uses (results with the same period a year earlier, the balance with the
start of the year).  «Улучшение» — no axis worse; «Смешанно» — one axis
worse; «Ухудшение» — two or three worse; «Требует внимания» — a red flag
fired whatever the axes say; «Без динамики» — no comparison source at all.

The axes are then held to what the text reports: a bottom line the text
says fell is never «улучшение», one it says rose never «ухудшение», and a
fired risk of medium or high materiality — a sentence in «Риски» — caps the
verdict at «смешанно» and is named in the reason.
"""
from __future__ import annotations

from decimal import Decimal

import financial_analysis.sector_vocabulary as vocab
from financial_analysis.sector_writer import SUBJECTS
from financial_analysis.sector_writer import FactView
from financial_analysis.sector_calculations import CLIENT_LIABILITIES

# A move of less than 5% (the «немного» tier and below) is no change in an
# axis; a share of equity is judged by a shift of 2 percentage points.
AXIS_MOVE_PCT = Decimal(5)
EQUITY_SHARE_PP = Decimal(2)
# A margin moving by a full percentage point.
MARGIN_PP = Decimal(1)
# A loss that takes a quarter of the equity left at the period end.
LOSS_EQUITY_SHARE = Decimal(25)


def _trend_state(move, cost=False):
    kind = move["kind"]
    if kind in {"none", "zero_both", "sign_change"}:
        return None
    if kind in {"to_profit", "loss_narrowed"}:
        return "better"
    if kind in {"to_loss", "loss_widened"}:
        return "worse"
    if kind in {"from_zero", "tiny_base", "to_zero", "extreme"}:
        up = move["current"] > move["previous"]
        return "better" if up != cost else "worse"
    pct = move["pct"]
    if abs(pct) < AXIS_MOVE_PCT:
        return "same"
    return "better" if (pct > 0) != cost else "worse"


def operating_margin_shift(view):
    """Change of the operating margin in p.p., when both margins are readable."""
    if view.top != "revenue":
        return None
    income, revenue = view.value("operating_income"), view.value("revenue")
    income_before, revenue_before = view.base("operating_income"), view.base("revenue")
    if None in (income, revenue, income_before, revenue_before) or revenue <= 0 or revenue_before <= 0:
        return None
    now, before = income / revenue * 100, income_before / revenue_before * 100
    if not (-100 <= now <= 100 and -100 <= before <= 100):
        return None
    return now - before


def axes(view):
    result = {"growth": None, "profitability": None, "stability": None}
    if view.top:
        result["growth"] = _trend_state(view.move(view.top))
    profit = "net_income" if "net_income" in view.facts else "operating_income" if "operating_income" in view.facts else None
    margin = operating_margin_shift(view)
    if margin is not None:
        # Profitability is a margin, not an amount: net profit lifted by
        # exchange gains while the core margin shrinks is not «better».
        profit = "margin"
        result["profitability"] = "worse" if margin <= -MARGIN_PP else "better" if margin >= MARGIN_PP else "same"
    elif profit:
        result["profitability"] = _trend_state(view.move(profit))
    equity, assets = view.value("total_equity"), view.value("total_assets")
    equity_before, assets_before = view.base("total_equity"), view.base("total_assets")
    client = CLIENT_LIABILITIES.get(view.filing.template)
    if client and None not in (assets, assets_before, view.value(client), view.base(client)):
        # Money held for clients (an exchange's participants) is on both
        # sides of the balance sheet; the equity share is of the own assets.
        assets, assets_before = assets - view.value(client), assets_before - view.base(client)
    if None not in (equity, assets, equity_before, assets_before) and assets > 0 and assets_before > 0 \
            and view.basis("total_equity") == "opening":
        shift = equity / assets * 100 - equity_before / assets_before * 100
        equity_move = view.move("total_equity")
        if shift <= -EQUITY_SHARE_PP or (equity_move["kind"] == "trend" and equity_move["pct"] <= -AXIS_MOVE_PCT):
            result["stability"] = "worse"
        elif shift >= EQUITY_SHARE_PP:
            result["stability"] = "better"
        else:
            result["stability"] = "same"
    return result, profit


def red_flags(view):
    """General red flags; sector templates add their own to this list."""
    flags = []
    equity, net = view.value("total_equity"), view.value("net_income")
    if equity is not None and equity < 0:
        flags.append({"code": "negative_equity", "metric_code": "total_equity", "materiality": "high"})
    elif equity and equity > 0 and net is not None and net < 0 and -net / equity * 100 >= LOSS_EQUITY_SHARE:
        # Published as JSON: a float, not the Decimal it was computed in.
        flags.append({"code": "loss_consumes_equity", "metric_code": "net_income", "materiality": "high",
                      "share": float(-net / equity * 100)})
    return flags


def _phrase(view, axis, state, profit_code):
    lang = view.lang
    if axis == "growth":
        ru, uz, en = vocab.NAMES[view.top] if not (view.top == "revenue" and view.family == "insurance") else vocab.INSURANCE_REVENUE
        name, gender, plural = vocab.pick(lang, ru[0], uz, en[0]), ru[2], en[1]
        if state == "better":
            return vocab.pick(lang, f"{name} {'растут' if gender == 'pl' else 'растёт'}", f"{name} o‘smoqda", f"{name} {'are' if plural else 'is'} growing")
        if state == "worse":
            return vocab.pick(lang, f"{name} {'снижаются' if gender == 'pl' else 'снижается'}", f"{name} kamaymoqda", f"{name} {'are' if plural else 'is'} falling")
        return vocab.pick(lang, f"{name} на уровне прошлого года", f"{name} o‘tgan yil darajasida", f"{name} {'are' if plural else 'is'} flat")
    if axis == "profitability" and profit_code == "margin":
        if state == "better":
            return vocab.pick(lang, "маржа растёт", "marja oshmoqda", "the margin is rising")
        if state == "worse":
            return vocab.pick(lang, "маржа снижается", "marja kamaymoqda", "the margin is falling")
        return vocab.pick(lang, "маржа на прежнем уровне", "marja avvalgi darajada", "the margin is flat")
    if axis == "profitability":
        kind = view.move(profit_code)["kind"]
        if state == "better":
            if kind == "to_profit":
                (subject, gender), subject_uz, subject_en = SUBJECTS[view.family]
                return vocab.pick(lang, f"{subject.lower()} " + vocab.gendered("{вышел|вышла|вышло|вышли}", gender) + " в прибыль",
                                  f"{subject_uz.lower()} foydaga chiqdi", f"{subject_en.lower()} returned to profit")
            if kind == "loss_narrowed":
                return vocab.pick(lang, "убыток сокращается", "zarar qisqarmoqda", "the loss is narrowing")
            return vocab.pick(lang, "прибыль растёт", "foyda o‘smoqda", "profit is growing")
        if state == "worse":
            if kind == "to_loss":
                return vocab.pick(lang, "получен убыток", "zarar ko‘rildi", "a loss was posted")
            if kind == "loss_widened":
                return vocab.pick(lang, "убыток растёт", "zarar oshmoqda", "the loss is widening")
            return vocab.pick(lang, "прибыль снижается", "foyda kamaymoqda", "profit is falling")
        return vocab.pick(lang, "прибыль на прежнем уровне", "foyda avvalgi darajada", "profit is flat")
    if state == "better":
        return vocab.pick(lang, "доля капитала растёт", "kapital ulushi oshmoqda", "the equity share is rising")
    if state == "worse":
        return vocab.pick(lang, "доля капитала снижается", "kapital ulushi kamaymoqda", "the equity share is falling")
    return vocab.pick(lang, "структура капитала прежняя", "kapital tuzilmasi o‘zgarmagan", "the capital structure is unchanged")


def bottom_line(view):
    """The line the verdict reads as «прибыль»: net income, else operating income."""
    return "net_income" if "net_income" in view.facts else "operating_income" if "operating_income" in view.facts else None


def profit_direction(view):
    """Which way the bottom line moved, as the text words it: up, down or None.

    A move the vocabulary calls «практически не изменилась» (under 1%) is no
    direction; a narrowed loss is up and a widened one down.
    """
    code = bottom_line(view)
    move = view.move(code) if code else {"kind": "none"}
    kind = move["kind"]
    if kind in {"none", "zero_both", "sign_change"}:
        return None
    if kind in {"to_profit", "loss_narrowed"}:
        return "up"
    if kind in {"to_loss", "loss_widened"}:
        return "down"
    direction = move.get("direction")
    return direction if direction in {"up", "down"} else None


# A fired risk, in the four to eight words the verdict line has for it.
RISK_REASONS = {
    "net_loss": ("период закрыт с убытком", "davr zarar bilan yopildi", "the period closed at a loss"),
    "negative_operating_result": ("основная деятельность убыточна", "asosiy faoliyat zararli", "core operations are loss-making"),
    "net_income_decline": ("прибыль упала более чем на пятую часть", "foyda beshdan biridan ko‘proq kamaydi", "profit fell by more than a fifth"),
    "operating_income_decline": ("операционная прибыль снижается", "operatsion foyda kamaymoqda", "operating profit is falling"),
    "revenue_decline": ("выручка упала более чем на пятую часть", "tushum beshdan biridan ko‘proq kamaydi", "revenue fell by more than a fifth"),
    "profit_quality": ("прибыль во многом валютная", "foyda asosan valyuta hisobidan", "profit comes largely from FX"),
    "profit_quality_revaluation": ("прибыль во многом из переоценки", "foyda asosan qayta baholashdan", "profit comes largely from revaluation"),
    "receivables_outpace_revenue": ("дебиторка растёт быстрее выручки", "debitorlik tushumdan tezroq o‘smoqda", "receivables outpace revenue"),
    "inventories_outpace_revenue": ("запасы растут быстрее выручки", "zaxiralar tushumdan tezroq o‘smoqda", "inventories outpace revenue"),
    "receivables_against_falling_revenue": ("дебиторка растёт при падении выручки", "tushum kamayganda debitorlik o‘smoqda", "receivables grow as revenue falls"),
    "inventories_against_falling_revenue": ("запасы растут при падении выручки", "tushum kamayganda zaxiralar o‘smoqda", "inventories grow as revenue falls"),
    "liabilities_outpace_equity": ("обязательства растут быстрее капитала", "majburiyatlar kapitaldan tezroq o‘smoqda", "liabilities outpace equity"),
    "claims_outpace_premiums": ("выплаты растут быстрее премий", "to‘lovlar mukofotlardan tezroq o‘smoqda", "claims outpace premiums"),
    "provisions_offset_by_other_income": ("резервы перекрыты прочими доходами", "zaxiralar boshqa daromadlar bilan yopilgan", "provisions are offset by other income"),
}

# Which risks keep the verdict from «улучшение»: every risk of medium or high
# materiality the text reports.  A positive word over a paragraph of risks
# was the contradiction the audit found in 16 analyses.
CAPPING_MATERIALITY = frozenset({"medium", "high"})


def _risk_reason(view, signal):
    code = signal["code"]
    if code == "profit_quality" and view.filing.quality.get("driver") == "unrealized_revaluation":
        code = "profit_quality_revaluation"
    if code.endswith("_outpace_revenue") and view.move("revenue").get("direction") == "down":
        code = code.replace("_outpace_revenue", "_against_falling_revenue")
    return vocab.pick(view.lang, *RISK_REASONS[code]) if code in RISK_REASONS else None


def verdict(filing, evidence, risks=()):
    """The verdict on the three axes, held to the profit and to the risks.

    ``risks`` are the fired negative signals.  On top of the axes: a fall in
    the bottom line is never «улучшение», a rise never «ухудшение», and a
    medium or high risk the text reports caps the verdict at «смешанно» with
    the risk named in the reason.  Red flags that need attention remain the
    only way to «требует внимания»; every flag the verdict weighed is listed
    with its effect.
    """
    if not filing.publishable:
        return {"status": "no_signal", "reason": None, "axes": {}, "red_flags": []}
    from financial_analysis.sector_writer import RISK_PRIORITY
    view = FactView(filing, evidence)
    lang = view.lang
    states, profit_code = axes(view)
    flags = [{**flag, "effect": "attention"} for flag in red_flags(view)] if filing.publishable else []
    capping = sorted((s for s in risks if s.get("materiality") in CAPPING_MATERIALITY and s.get("direction", "negative") == "negative"),
                     key=lambda s: RISK_PRIORITY.index(s["code"]) if s["code"] in RISK_PRIORITY else len(RISK_PRIORITY))
    caps = [{"code": s["code"], "metric_code": s.get("metric_code"), "materiality": s["materiality"], "effect": "caps_at_mixed",
             "signal_id": s.get("id")} for s in capping]
    known = {axis: state for axis, state in states.items() if state is not None}
    if flags:
        status = "attention"
        flag = flags[0]
        if flag["code"] == "negative_equity":
            reason = vocab.pick(lang, "собственный капитал отрицательный", "o‘z kapitali manfiy", "equity is negative")
        else:
            share = vocab.share_phrase(flag["share"], lang, "acc")
            reason = vocab.pick(lang, f"убыток съел {share} капитала", f"zarar kapitalning {share} yeb qo‘ydi", f"the loss consumed {share} of equity")
    elif not known or not view.has_comparison():
        status = "no_signal"
        reason = vocab.pick(lang, "нет сопоставимого периода", "taqqoslanadigan davr yo‘q", "no comparable period")
    else:
        worse = [axis for axis, state in known.items() if state == "worse"]
        better = [axis for axis, state in known.items() if state == "better"]
        same = [axis for axis, state in known.items() if state == "same"]
        status = "positive" if not worse else "mixed" if len(worse) == 1 else "negative"
        phrase = lambda axis: _phrase(view, axis, known[axis], profit_code)
        if status == "positive" and {"growth", "profitability"} <= set(better) and profit_code != "margin" \
                and view.move(profit_code)["kind"] != "to_profit" and view.move(profit_code).get("current", 0) > 0:
            top = vocab.INSURANCE_REVENUE if view.top == "revenue" and view.family == "insurance" else vocab.NAMES[view.top]
            reason = vocab.pick(lang, f"растут и {top[0][0]}, и прибыль", f"{top[1]} ham, foyda ham o‘smoqda", f"both {top[2][0]} and profit are growing")
        elif status == "positive" and not better:
            # «Улучшение» means no axis is worse; say exactly that.
            reason = vocab.pick(lang, "ни один показатель не хуже прошлого года", "hech bir ko‘rsatkich o‘tgan yildan yomon emas",
                                "no measure is worse than a year ago")
        elif status == "positive":
            reason = ", ".join(phrase(axis) for axis in (better + same)[:2])
        elif status == "mixed":
            good = (better + same)[:1]
            joint = vocab.pick(lang, ", но ", ", ammo ", ", but ")
            reason = (phrase(good[0]) + joint + phrase(worse[0])) if good else phrase(worse[0])
        else:
            reason = vocab.pick(lang, " и ", " va ", " and ").join(phrase(axis) for axis in worse[:2])
        joint = vocab.pick(lang, ", но ", ", ammo ", ", but ")
        good_phrase = phrase(better[0]) if better else (phrase(same[0]) if same else None)
        direction = profit_direction(view)
        if status == "positive" and direction == "down":
            # ORFI −4.2%: inside the axis's ±5% band, but the text says the
            # profit fell; «улучшение» beside it contradicts the text.
            status = "mixed"
            # The bottom line in the words its own move takes: «прибыль
            # снижается», «убыток растёт», «получен убыток».
            falling = _phrase(view, "profitability", "worse", bottom_line(view))
            positive = [axis for axis in better if axis != "profitability"]
            lead = phrase(positive[0]) if positive else None
            reason = (lead + joint + falling) if lead else falling
        elif status == "negative" and direction == "up":
            # OHDN +24.9%: revenue and the equity share fell, profit rose.
            status = "mixed"
            rising = _phrase(view, "profitability", "better", bottom_line(view))
            reason = rising + joint + phrase(worse[0])
        if status == "positive" and capping:
            # The cap never depends on a phrase: a risk added later without an
            # entry in RISK_REASONS still holds the verdict at «смешанно».
            named = next((text for text in (_risk_reason(view, s) for s in capping) if text), None) \
                or vocab.pick(lang, "в отчёте есть риски", "hisobotda xavflar bor", "the report shows risks")
            status = "mixed"
            reason = (good_phrase + joint + named) if good_phrase else named
    return {"status": status, "reason": reason, "axes": states, "red_flags": flags + caps}
