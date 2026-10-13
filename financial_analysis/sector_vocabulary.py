"""The fixed vocabulary of the company analysis: a word is chosen from a figure.

The rules follow the «AI-анализ отчётности» specification (2026-10-12):
the size of a change picks the verb, a share picks the fraction, and the
relation between two figures picks the connective.  Nothing here reads a
filing; it only turns numbers that the writer already holds into words, so
every word can be checked against the number it came from.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP
from decimal import Decimal
import re

LANGS = ("ru", "uz", "en")
MINUS = "−"
THOUSAND = Decimal(1000)

# Change tiers, by the absolute percent change against the comparison base.
# Growth of +100% or more and a fall of 50% or more are stated as a multiple.
TIER_STABLE, TIER_SLIGHT, TIER_NORMAL, TIER_SIGNIFICANT, TIER_SHARP, TIER_MULTIPLE = (
    "stable", "slight", "normal", "significant", "sharp", "multiple")


EXTREME_MULTIPLE = Decimal(100)


def tier_of(pct):
    """Tier of a percent change; a fall of half or more is a multiple."""
    pct = Decimal(pct)
    size = abs(pct)
    if pct >= 100 or pct <= -50:
        return TIER_MULTIPLE
    if size >= 50:
        return TIER_SHARP
    if size >= 15:
        return TIER_SIGNIFICANT
    if size >= 5:
        return TIER_NORMAL
    if size >= 1:
        return TIER_SLIGHT
    return TIER_STABLE


def classify(current, previous, *, profit_like=False, floor=None):
    """How a figure moved against its comparison base.

    ``kind`` is one of: ``none`` (no base), ``zero_both``, ``from_zero``,
    ``to_zero``, ``to_loss``, ``to_profit``, ``loss_narrowed``,
    ``loss_widened``, ``sign_change``, ``tiny_base`` or ``trend``.  Only a
    ``trend`` may be stated as a percent; every other kind is stated as the
    two amounts, because a percent of zero, of a sign change or of a
    negligible base says nothing (the «−116%» and «+10 427%» of the old text).
    ``floor`` is the smallest base, in the figure's own unit, that a percent
    may be taken from.
    """
    if current is None or previous is None:
        return {"kind": "none"}
    current, previous = Decimal(str(current)), Decimal(str(previous))
    result = {"current": current, "previous": previous, "delta": current - previous,
              "direction": "up" if current > previous else "down" if current < previous else "flat"}
    if current == 0 and previous == 0:
        return {**result, "kind": "zero_both"}
    if profit_like and (current < 0 or previous < 0) and current != 0 and previous != 0:
        if previous > 0 > current:
            return {**result, "kind": "to_loss"}
        if previous < 0 < current:
            return {**result, "kind": "to_profit"}
        return {**result, "kind": "loss_narrowed" if abs(current) <= abs(previous) else "loss_widened"}
    if current * previous < 0:
        return {**result, "kind": "sign_change"}
    if previous == 0:
        return {**result, "kind": "from_zero"}
    if current == 0:
        return {**result, "kind": "to_zero"}
    if floor is not None and abs(previous) < Decimal(str(floor)):
        return {**result, "kind": "tiny_base"}
    pct = (current - previous) / abs(previous) * 100
    tier = tier_of(pct)
    direction = "flat" if tier == TIER_STABLE else result["direction"]
    ratio = None
    if tier == TIER_MULTIPLE:
        ratio = current / previous if direction == "up" else previous / current
        # «в 13 296 раз» reads as noise: past a hundredfold the two amounts
        # say more than the multiple, as with a negligible base.
        if ratio >= EXTREME_MULTIPLE:
            return {**result, "kind": "extreme"}
    return {**result, "kind": "trend", "pct": pct, "tier": tier, "direction": direction, "ratio": ratio}


def pick(lang, ru, uz, en):
    return (ru, uz, en)[LANGS.index(lang) if lang in LANGS else 0]


# ---------------------------------------------------------------- numbers

_SCALES = (
    (Decimal(10) ** 12, ("трлн сум", "trln so‘m", "trn")),
    (Decimal(10) ** 9, ("млрд сум", "mlrd so‘m", "bn")),
    (Decimal(10) ** 6, ("млн сум", "mln so‘m", "mn")),
)


def _decimals_for(value):
    """Decimals that leave three significant figures in ``value``."""
    value = abs(value)
    if value == 0:
        return 0
    exponent = value.adjusted()
    return max(0, 2 - exponent)


def _plain(value, decimals, lang):
    quantum = Decimal(1).scaleb(-decimals)
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    text = f"{abs(rounded):,.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if lang == "en":
        whole, _, fraction = text.partition(".")
    else:
        whole, _, fraction = text.partition(".")
        whole = whole.replace(",", " ")
    text = whole + ((("." if lang == "en" else ",") + fraction) if fraction else "")
    return (MINUS if rounded < 0 else "") + text


def _scale(amount):
    size = abs(amount)
    for index, (factor, _) in enumerate(_SCALES):
        if size >= factor or index == len(_SCALES) - 1:
            scaled = amount / factor
            # 999.6 млн rounds to «1000 млн»; state it on the next scale.
            if index and abs(scaled.quantize(Decimal(1).scaleb(-_decimals_for(scaled)), rounding=ROUND_HALF_UP)) >= 1000:
                return _SCALES[index - 1]
            return _SCALES[index]
    return _SCALES[-1]


def _with_unit(number_text, units, lang):
    unit = pick(lang, *units)
    return f"UZS {number_text}{unit}" if lang == "en" else f"{number_text} {unit}"


def money(thousands, lang):
    """A reported amount in thousand sum, stated at scale with three figures."""
    amount = Decimal(str(thousands)) * THOUSAND
    if amount == 0:
        return pick(lang, "0 сум", "0 so‘m", "UZS 0")
    factor, units = _scale(amount)
    scaled = amount / factor
    return _with_unit(_plain(scaled, _decimals_for(scaled), lang), units, lang)


def money_pair(first, second, lang):
    """Two amounts on one scale: «с 0,2 до 20,1 млрд сум».

    The larger amount sets the scale and the precision, so the two figures
    are read against each other; the smaller one keeps at least one
    significant figure.  Returns (first_text, second_text, unit_text).
    """
    first_amount, second_amount = Decimal(str(first)) * THOUSAND, Decimal(str(second)) * THOUSAND
    larger = max(abs(first_amount), abs(second_amount))
    if larger == 0:
        zero = money(0, lang)
        return zero, zero, ""
    factor, units = _scale(larger)
    big = larger / factor
    decimals = _decimals_for(big)
    texts = []
    for amount in (first_amount, second_amount):
        scaled = amount / factor
        own = decimals
        while own < 6 and scaled != 0 and scaled.quantize(Decimal(1).scaleb(-own), rounding=ROUND_HALF_UP) == 0:
            own += 1
        texts.append(_plain(scaled, own, lang) if amount != 0 else "0")
    return texts[0], texts[1], pick(lang, *units)


def percent(value, lang):
    """One decimal below 10%, none from 10%: «4,9%», «16%»."""
    value = abs(Decimal(str(value)))
    decimals = 1 if value < 10 else 0
    return _plain(value, decimals, lang) + "%"


def share_percent(value, lang):
    value = Decimal(str(value))
    return _plain(value, 1 if abs(value) < 10 else 0, lang) + "%"


def times(ratio, lang):
    """A multiple: «в 3,4 раза», «в 12 раз»; «3,4 baravar»; «3.4-fold»."""
    ratio = abs(Decimal(str(ratio)))
    decimals = 1 if ratio < 10 else 0
    text = _plain(ratio, decimals, lang)
    if lang == "en":
        return f"{text}-fold"
    if lang == "uz":
        return f"{text} baravar"
    if "," in text:
        word = "раза"
    else:
        whole = int(text.replace(" ", ""))
        word = "раза" if whole % 10 in (2, 3, 4) and whole % 100 not in (12, 13, 14) else "раз"
    return f"в {text} {word}"


def times_capped(ratio, lang):
    """A ratio of two levels; past a hundredfold only «более чем в 100 раз»."""
    if Decimal(str(ratio)) >= EXTREME_MULTIPLE:
        return pick(lang, "более чем в 100 раз", "100 baravardan ko‘proq", "more than 100 times")
    return times(ratio, lang)


def signed_change(move, lang):
    """«+9%», «−34%» or «в 2,3 раза» for a trend; None for anything else."""
    if move.get("kind") != "trend":
        return None
    if move["tier"] == TIER_MULTIPLE:
        return times(move["ratio"], lang)
    return ("+" if move["pct"] > 0 else MINUS) + percent(move["pct"], lang)


def near(ratio, target, tolerance=Decimal("0.05")):
    return abs(Decimal(str(ratio)) - target) <= tolerance


def points(value, lang):
    value = abs(Decimal(str(value)))
    text = _plain(value, 1 if value < 10 else 0, lang)
    return pick(lang, f"{text} п.п.", f"{text} f.p.", f"{text} pp")


# ---------------------------------------------------------------- shares

_RU_ACCUSATIVE = {"почти половина": "почти половину", "подавляющая часть": "подавляющую часть",
                  "большая часть": "большую часть", "небольшая доля": "небольшую долю"}


def share_phrase(share, lang, case="nom"):
    """A share of a whole in words (section 2 of the vocabulary).

    Russian needs the accusative after «составляет»: «почти половину».
    """
    text = _share_phrase(share, lang)
    if lang == "ru" and case == "acc":
        for nominative, accusative in _RU_ACCUSATIVE.items():
            if text.startswith(nominative):
                return accusative + text[len(nominative):]
    if lang == "uz" and case == "acc":
        # The suffix goes on the word, not after a bracket: «kichik ulushni (11%)».
        if text.endswith(")") and " (" in text:
            head, _, tail = text.partition(" (")
            return f"{head}ni ({tail}"
        return text + "ni"
    return text


def _share_phrase(share, lang):
    share = Decimal(str(share))
    if share >= 97:
        # «почти все» needs the whole in the plural nominative, which the
        # writer never uses; «подавляющая часть активов» always reads.
        return pick(lang, "подавляющая часть", "deyarli barchasi", "almost all")
    if share >= 90:
        return pick(lang, "подавляющая часть", "mutlaq katta qismi", "the vast majority")
    if share >= 78 and share <= 82:
        return pick(lang, "около четырёх пятых", "beshdan to‘rt qismiga yaqini", "about four fifths")
    if share >= 73 and share <= 77:
        return pick(lang, "три четверти", "to‘rtdan uch qismi", "three quarters")
    if share >= 70:
        return pick(lang, "большая часть", "katta qismi", "most")
    if share >= 63:
        return pick(lang, "около двух третей", "uchdan ikki qismiga yaqini", "about two thirds")
    if share >= 55:
        return pick(lang, "более половины", "yarmidan ko‘pi", "more than half")
    if share > 51:
        return pick(lang, "чуть больше половины", "yarmidan sal ko‘pi", "just over half")
    if share >= 49:
        return pick(lang, "около половины", "qariyb yarmi", "about half")
    if share >= 45:
        return pick(lang, "почти половина", "deyarli yarmi", "almost half")
    if share >= 37:
        return pick(lang, "более трети", "uchdan biridan ko‘pi", "more than a third")
    if share >= 30:
        return pick(lang, "около трети", "uchdan bir qismiga yaqini", "about a third")
    if share >= 23 and share <= 27:
        return pick(lang, "четверть", "to‘rtdan bir qismi", "a quarter")
    if share >= 18 and share <= 22:
        return pick(lang, "около пятой части", "beshdan bir qismiga yaqini", "about a fifth")
    if share >= 15:
        return pick(lang, f"около {share_percent(share, lang)}", f"taxminan {share_percent(share, lang)}", f"about {share_percent(share, lang)}")
    if share >= 9 and share <= 11:
        return pick(lang, "около десятой части", "o‘ndan bir qismiga yaqini", "about a tenth")
    if share >= 5:
        return pick(lang, f"небольшая доля ({share_percent(share, lang)})", f"kichik ulush ({share_percent(share, lang)})", f"a small share ({share_percent(share, lang)})")
    return pick(lang, "менее 5%", "5% dan kam", "less than 5%")


# ---------------------------------------------------------------- words

# Prose names: Russian (nominative, genitive, gender m/f/n/pl), Uzbek, English
# (noun, plural).  A line without a name here is never written into prose.
NAMES = {
    "revenue": (("выручка", "выручки", "f"), "tushum", ("revenue", False)),
    "cost_of_sales": (("себестоимость", "себестоимости", "f"), "tannarx", ("cost of sales", False)),
    "gross_profit": (("валовая прибыль", "валовой прибыли", "f"), "yalpi foyda", ("gross profit", False)),
    "period_expenses": (("расходы периода", "расходов периода", "pl"), "davr xarajatlari", ("period expenses", True)),
    "operating_income": (("операционная прибыль", "операционной прибыли", "f"), "operatsion foyda", ("operating profit", False)),
    "financial_income": (("финансовые доходы", "финансовых доходов", "pl"), "moliyaviy daromadlar", ("finance income", False)),
    "financial_expenses": (("финансовые расходы", "финансовых расходов", "pl"), "moliyaviy xarajatlar", ("finance costs", True)),
    "fx_income": (("курсовые доходы", "курсовых доходов", "pl"), "kurs farqi daromadlari", ("foreign-exchange gains", True)),
    "fx_expenses": (("курсовые расходы", "курсовых расходов", "pl"), "kurs farqi xarajatlari", ("foreign-exchange losses", True)),
    "profit_before_tax": (("прибыль до налога", "прибыли до налога", "f"), "soliqqacha foyda", ("profit before tax", False)),
    "net_income": (("чистая прибыль", "чистой прибыли", "f"), "sof foyda", ("net profit", False)),
    "tax": (("налог на прибыль", "налога на прибыль", "m"), "foyda solig‘i", ("income tax", False)),
    "total_assets": (("активы", "активов", "pl"), "aktivlar", ("total assets", True)),
    "total_equity": (("собственный капитал", "собственного капитала", "m"), "o‘z kapitali", ("equity", False)),
    "total_liabilities": (("обязательства", "обязательств", "pl"), "majburiyatlar", ("liabilities", True)),
    "cash": (("денежные средства", "денежных средств", "pl"), "pul mablag‘lari", ("cash", False)),
    "receivables": (("дебиторская задолженность", "дебиторской задолженности", "f"), "debitorlik qarzi", ("receivables", True)),
    "inventories": (("запасы", "запасов", "pl"), "zaxiralar", ("inventories", True)),
    "current_liabilities": (("текущие обязательства", "текущих обязательств", "pl"), "joriy majburiyatlar", ("current liabilities", True)),
    "long_term_liabilities": (("долгосрочные обязательства", "долгосрочных обязательств", "pl"), "uzoq muddatli majburiyatlar", ("long-term liabilities", True)),
    "fixed_assets": (("основные средства", "основных средств", "pl"), "asosiy vositalar", ("fixed assets", True)),
    "construction_in_progress": (("незавершённое строительство", "незавершённого строительства", "n"), "tugallanmagan qurilish", ("construction in progress", False)),
    "long_term_investments": (("долгосрочные инвестиции", "долгосрочных инвестиций", "pl"), "uzoq muddatli investitsiyalar", ("long-term investments", True)),
    "short_term_investments": (("краткосрочные инвестиции", "краткосрочных инвестиций", "pl"), "qisqa muddatli investitsiyalar", ("short-term investments", True)),
    "share_capital": (("уставный капитал", "уставного капитала", "m"), "ustav kapitali", ("share capital", False)),
    "additional_capital": (("добавленный капитал", "добавленного капитала", "m"), "qo‘shilgan kapital", ("additional capital", False)),
    "retained_earnings": (("нераспределённая прибыль", "нераспределённой прибыли", "f"), "taqsimlanmagan foyda", ("retained earnings", True)),
    "interest_income": (("процентные доходы", "процентных доходов", "pl"), "foizli daromadlar", ("interest income", False)),
    "interest_expenses": (("процентные расходы", "процентных расходов", "pl"), "foizli xarajatlar", ("interest expense", False)),
    "noninterest_income": (("непроцентные доходы", "непроцентных доходов", "pl"), "foizsiz daromadlar", ("non-interest income", False)),
    "noninterest_expenses": (("непроцентные расходы", "непроцентных расходов", "pl"), "foizsiz xarajatlar", ("non-interest expense", False)),
    "net_revenue_before_operating_expenses": (("чистый доход до операционных расходов", "чистого дохода до операционных расходов", "m"), "operatsion xarajatlargacha sof daromad", ("net revenue before operating expenses", False)),
    "operating_expenses": (("операционные расходы", "операционных расходов", "pl"), "operatsion xarajatlar", ("operating expenses", True)),
    "central_bank_balances": (("средства в ЦБ", "средств в ЦБ", "pl"), "Markaziy bankdagi mablag‘lar", ("central bank balances", True)),
    "loan_portfolio": (("кредитный портфель", "кредитного портфеля", "m"), "kredit portfeli", ("loan portfolio", False)),
    "customer_funds": (("средства клиентов", "средств клиентов", "pl"), "mijozlar mablag‘lari", ("customer funds", True)),
    "borrowings": (("заёмные средства", "заёмных средств", "pl"), "qarz mablag‘lari", ("borrowings", True)),
    "loan_reserves": (("резервы по кредитам", "резервов по кредитам", "pl"), "kredit zaxiralari", ("loan-loss reserves", True)),
    "due_from_banks": (("средства в других банках", "средств в других банках", "pl"), "boshqa banklardagi mablag‘lar", ("balances with other banks", True)),
    "demand_deposits": (("депозиты до востребования", "депозитов до востребования", "pl"), "talab qilinguncha depozitlar", ("demand deposits", True)),
    "savings_deposits": (("сберегательные депозиты", "сберегательных депозитов", "pl"), "jamg‘arma depozitlari", ("savings deposits", True)),
    "term_deposits": (("срочные депозиты", "срочных депозитов", "pl"), "muddatli depozitlar", ("term deposits", True)),
    "net_interest_income_before_provisions": (("чистый процентный доход", "чистого процентного дохода", "m"), "sof foizli daromad", ("net interest income", False)),
    "credit_loss_provisions": (("отчисления в резервы", "отчислений в резервы", "pl"), "zaxiralarga ajratmalar", ("credit-loss provisions", True)),
    "fee_income": (("комиссионные доходы", "комиссионных доходов", "pl"), "komission daromadlar", ("fee income", False)),
    "fee_expenses": (("комиссионные расходы", "комиссионных расходов", "pl"), "komission xarajatlar", ("fee expense", False)),
    "insurance_premiums": (("страховые премии", "страховых премий", "pl"), "sug‘urta mukofotlari", ("insurance premiums", True)),
    "insurance_claims": (("страховые выплаты", "страховых выплат", "pl"), "sug‘urta to‘lovlari", ("insurance claims", True)),
    "expenses": (("расходы", "расходов", "pl"), "xarajatlar", ("expenses", True)),
    "gross_insurance_reserves": (("валовые страховые резервы", "валовых страховых резервов", "pl"), "yalpi sug‘urta zaxiralari", ("gross insurance reserves", True)),
    "reinsurer_share_in_reserves": (("доля перестраховщиков в резервах", "доли перестраховщиков в резервах", "f"), "qayta sug‘urtalovchilarning zaxiralardagi ulushi", ("reinsurers' share of reserves", False)),
    "net_insurance_reserves": (("чистые страховые резервы", "чистых страховых резервов", "pl"), "sof sug‘urta zaxiralari", ("net insurance reserves", True)),
    "other_liabilities": (("прочие обязательства", "прочих обязательств", "pl"), "boshqa majburiyatlar", ("other liabilities", True)),
    "ceded_premiums": (("премии, переданные перестраховщикам", "премий, переданных перестраховщикам", "pl"), "qayta sug‘urtaga berilgan mukofotlar", ("premiums ceded to reinsurers", True)),
    "insurance_service_cost": (("расходы на страховые услуги", "расходов на страховые услуги", "pl"), "sug‘urta xizmatlari xarajatlari", ("insurance service costs", True)),
    "insurance_service_result": (("результат от страховых услуг", "результата от страховых услуг", "m"), "sug‘urta xizmatlari natijasi", ("insurance service result", False)),
    "unrealized_fair_value_gain": (("нереализованная переоценка", "нереализованной переоценки", "f"), "realizatsiya qilinmagan qayta baholash", ("unrealised revaluation", False)),
    "dividend_income": (("дивидендный доход", "дивидендного дохода", "m"), "dividend daromadi", ("dividend income", False)),
    "management_expenses": (("расходы управляющего", "расходов управляющего", "pl"), "boshqaruvchi xarajatlari", ("management expenses", True)),
    "portfolio_fair_value": (("инвестиционный портфель", "инвестиционного портфеля", "m"), "investitsiya portfeli", ("investment portfolio", False)),
    "dividends_receivable": (("дивиденды к получению", "дивидендов к получению", "pl"), "olinadigan dividendlar", ("dividends receivable", True)),
    "accounts_payable": (("кредиторская задолженность", "кредиторской задолженности", "f"), "kreditorlik qarzi", ("accounts payable", True)),
    "level3_investments": (("инвестиции уровня 3", "инвестиций уровня 3", "pl"), "3-darajali investitsiyalar", ("level 3 investments", True)),
    "largest_holding": (("крупнейшая позиция", "крупнейшей позиции", "f"), "eng yirik pozitsiya", ("largest holding", False)),
    "top5_holdings": (("пять крупнейших позиций", "пяти крупнейших позиций", "pl"), "beshta eng yirik pozitsiya", ("five largest holdings", True)),
    "own_cash": (("собственные денежные средства", "собственных денежных средств", "pl"), "o‘z pul mablag‘lari", ("own cash", False)),
    "client_cash": (("деньги клиентов", "денег клиентов", "pl"), "mijozlar puli", ("client cash", False)),
    "settlement_liabilities": (("расчётные обязательства", "расчётных обязательств", "pl"), "hisob-kitob majburiyatlari", ("settlement liabilities", True)),
}

# An insurer's «revenue» line is its net insurance-service revenue.
INSURANCE_REVENUE = (("чистая выручка от страховых услуг", "чистой выручки от страховых услуг", "f"), "sug‘urta xizmatlaridan sof tushum", ("net insurance-service revenue", False))

# A result that changes sign is named as a result, and a loss as a loss.
RESULT_NAMES = {
    "net_income": (("чистый результат", "m"), "sof natija", "the net result", ("чистый убыток", "sof zarar", "the net loss")),
    "operating_income": (("операционный результат", "m"), "operatsion natija", "the operating result", ("операционный убыток", "operatsion zarar", "the operating loss")),
    "gross_profit": (("валовой результат", "m"), "yalpi natija", "the gross result", ("валовой убыток", "yalpi zarar", "the gross loss")),
    "profit_before_tax": (("результат до налога", "m"), "soliqqacha natija", "the pre-tax result", ("убыток до налога", "soliqqacha zarar", "the pre-tax loss")),
    "insurance_service_result": (("результат от страховых услуг", "m"), "sug‘urta xizmatlari natijasi", "the insurance service result", ("убыток от страховых услуг", "sug‘urta xizmatlari zarari", "the insurance service loss")),
    "net_interest_income_before_provisions": (("чистый процентный результат", "m"), "sof foizli natija", "the net interest result", ("чистый процентный убыток", "sof foizli zarar", "the net interest loss")),
    "retained_earnings": (("нераспределённый результат", "m"), "taqsimlanmagan natija", "retained earnings", ("непокрытый убыток", "qoplanmagan zarar", "the accumulated deficit")),
}
PROFIT_LIKE = frozenset(RESULT_NAMES)

_GENDER = {"m": 0, "f": 1, "n": 2, "pl": 3}


def gendered(text, gender):
    """Resolve «{вырос|выросла|выросло|выросли}» for a gender.

    A two-form «{was|were}» (English number) takes the second form for the
    plural and the first otherwise.
    """
    index = _GENDER.get(gender, 0)

    def form(match):
        forms = match.group(1).split("|")
        if len(forms) == 2:
            return forms[1] if index == 3 else forms[0]
        return forms[index]
    return re.sub(r"\{([^{}|]*\|[^{}]*)\}", form, text)


def capital(text):
    return text[:1].upper() + text[1:] if text else text


# Verbs by direction and tier.  Each entry is (lemma, template); the lemma
# keeps one verb from appearing twice in a paragraph.  {p} is a percent and
# {x} a multiple.
RU_VERBS = {
    ("up", TIER_MULTIPLE): [("grow", "{вырос|выросла|выросло|выросли} {x}"), ("increase", "{увеличился|увеличилась|увеличилось|увеличились} {x}")],
    ("up", TIER_SHARP): [("grow", "резко {вырос|выросла|выросло|выросли} на {p}"), ("jump", "{совершил|совершила|совершило|совершили} скачок на {p}"), ("increase", "резко {увеличился|увеличилась|увеличилось|увеличились} на {p}")],
    ("up", TIER_SIGNIFICANT): [("grow", "значительно {вырос|выросла|выросло|выросли} на {p}"), ("increase", "заметно {увеличился|увеличилась|увеличилось|увеличились} на {p}"), ("add", "существенно {прибавил|прибавила|прибавило|прибавили} {p}")],
    ("up", TIER_NORMAL): [("grow", "{вырос|выросла|выросло|выросли} на {p}"), ("increase", "{увеличился|увеличилась|увеличилось|увеличились} на {p}"), ("add", "{прибавил|прибавила|прибавило|прибавили} {p}")],
    ("up", TIER_SLIGHT): [("grow", "немного {вырос|выросла|выросло|выросли} на {p}"), ("increase", "умеренно {увеличился|увеличилась|увеличилось|увеличились} на {p}"), ("add", "слегка {прибавил|прибавила|прибавило|прибавили} {p}")],
    ("down", TIER_MULTIPLE): [("shrink", "{сократился|сократилась|сократилось|сократились} {x}"), ("fall", "{упал|упала|упало|упали} {x}")],
    ("down", TIER_SIGNIFICANT): [("decline", "значительно {снизился|снизилась|снизилось|снизились} на {p}"), ("shrink", "заметно {сократился|сократилась|сократилось|сократились} на {p}"), ("decrease", "существенно {уменьшился|уменьшилась|уменьшилось|уменьшились} на {p}")],
    ("down", TIER_NORMAL): [("decline", "{снизился|снизилась|снизилось|снизились} на {p}"), ("shrink", "{сократился|сократилась|сократилось|сократились} на {p}"), ("decrease", "{уменьшился|уменьшилась|уменьшилось|уменьшились} на {p}")],
    ("down", TIER_SLIGHT): [("decline", "немного {снизился|снизилась|снизилось|снизились} на {p}"), ("shrink", "слегка {сократился|сократилась|сократилось|сократились} на {p}"), ("decrease", "незначительно {уменьшился|уменьшилась|уменьшилось|уменьшились} на {p}")],
    ("flat", TIER_STABLE): [("stay", "{остался|осталась|осталось|остались} практически {неизменным|неизменной|неизменным|неизменными}"), ("keep", "{сохранился|сохранилась|сохранилось|сохранились} на прежнем уровне"), ("settle", "{стабилизировался|стабилизировалась|стабилизировалось|стабилизировались}")],
}
RU_DOUBLE = {("up", 2): ("double", "{удвоился|удвоилась|удвоилось|удвоились}"), ("up", 3): ("triple", "{утроился|утроилась|утроилось|утроились}"),
             ("down", 2): ("fall", "{упал|упала|упало|упали} вдвое")}
RU_HALF_AGAIN = ("increase", "{увеличился|увеличилась|увеличилось|увеличились} в полтора раза")

UZ_VERBS = {
    ("up", TIER_MULTIPLE): [("grow", "{x} o‘sdi"), ("increase", "{x} oshdi")],
    ("up", TIER_SHARP): [("grow", "{p}ga keskin o‘sdi"), ("jump", "{p}ga sakrab o‘sdi"), ("increase", "{p}ga keskin oshdi")],
    ("up", TIER_SIGNIFICANT): [("grow", "{p}ga sezilarli o‘sdi"), ("increase", "{p}ga ancha oshdi"), ("add", "{p}ga salmoqli ko‘paydi")],
    ("up", TIER_NORMAL): [("grow", "{p}ga o‘sdi"), ("increase", "{p}ga oshdi"), ("add", "{p}ga ko‘paydi")],
    ("up", TIER_SLIGHT): [("grow", "{p}ga biroz o‘sdi"), ("increase", "{p}ga mo‘tadil oshdi"), ("add", "{p}ga ozgina ko‘paydi")],
    ("down", TIER_MULTIPLE): [("shrink", "{x} kamaydi"), ("fall", "{x} qisqardi")],
    ("down", TIER_SIGNIFICANT): [("decline", "{p}ga sezilarli kamaydi"), ("shrink", "{p}ga ancha qisqardi"), ("decrease", "{p}ga salmoqli pasaydi")],
    ("down", TIER_NORMAL): [("decline", "{p}ga kamaydi"), ("shrink", "{p}ga qisqardi"), ("decrease", "{p}ga pasaydi")],
    ("down", TIER_SLIGHT): [("decline", "{p}ga biroz kamaydi"), ("shrink", "{p}ga ozgina qisqardi"), ("decrease", "{p}ga sal pasaydi")],
    ("flat", TIER_STABLE): [("stay", "deyarli o‘zgarmadi"), ("keep", "avvalgi darajada saqlandi"), ("settle", "o‘zgarishsiz qoldi")],
}
UZ_DOUBLE = {("up", 2): ("double", "ikki baravar oshdi"), ("up", 3): ("triple", "uch baravar oshdi"), ("down", 2): ("fall", "ikki baravar kamaydi")}
UZ_HALF_AGAIN = ("increase", "bir yarim baravar oshdi")

EN_VERBS = {
    ("up", TIER_MULTIPLE): [("grow", "grew {x}"), ("increase", "increased {x}")],
    ("up", TIER_SHARP): [("grow", "rose sharply by {p}"), ("jump", "jumped {p}"), ("increase", "increased sharply by {p}")],
    ("up", TIER_SIGNIFICANT): [("grow", "rose significantly by {p}"), ("increase", "increased markedly by {p}"), ("add", "grew substantially by {p}")],
    ("up", TIER_NORMAL): [("grow", "rose {p}"), ("increase", "increased {p}"), ("add", "grew {p}")],
    ("up", TIER_SLIGHT): [("grow", "edged up {p}"), ("increase", "rose slightly by {p}"), ("add", "increased modestly by {p}")],
    ("down", TIER_MULTIPLE): [("shrink", "shrank {x}"), ("fall", "fell {x}")],
    ("down", TIER_SIGNIFICANT): [("decline", "fell significantly by {p}"), ("shrink", "declined markedly by {p}"), ("decrease", "decreased substantially by {p}")],
    ("down", TIER_NORMAL): [("decline", "fell {p}"), ("shrink", "declined {p}"), ("decrease", "decreased {p}")],
    ("down", TIER_SLIGHT): [("decline", "edged down {p}"), ("shrink", "dipped {p}"), ("decrease", "decreased slightly by {p}")],
    ("flat", TIER_STABLE): [("stay", "{was|were} virtually unchanged"), ("keep", "held at the previous level"), ("settle", "stabilised")],
}
EN_DOUBLE = {("up", 2): ("double", "doubled"), ("up", 3): ("triple", "tripled"), ("down", 2): ("fall", "halved")}
EN_HALF_AGAIN = ("increase", "increased by half")

VERBS = {"ru": (RU_VERBS, RU_DOUBLE, RU_HALF_AGAIN), "uz": (UZ_VERBS, UZ_DOUBLE, UZ_HALF_AGAIN), "en": (EN_VERBS, EN_DOUBLE, EN_HALF_AGAIN)}

# The tier a verb template belongs to, so the text check can read it back.
VERB_TIERS = {}
for _lang, (_table, _double, _half) in VERBS.items():
    for (_direction, _tier), _entries in _table.items():
        for _lemma, _template in _entries:
            VERB_TIERS.setdefault(_lang, []).append((_template, _direction, _tier))
    for (_direction, _), (_lemma, _template) in _double.items():
        VERB_TIERS[_lang].append((_template, _direction, TIER_MULTIPLE))
    VERB_TIERS[_lang].append((_half[1], "up", TIER_SHARP))

VERDICT_WORDS = {
    "positive": ("улучшение", "yaxshilanish", "improving"),
    "mixed": ("смешанно", "aralash", "mixed"),
    "negative": ("ухудшение", "yomonlashish", "deteriorating"),
    "attention": ("требует внимания", "e’tibor talab qiladi", "needs attention"),
    "no_signal": ("без динамики", "dinamikasiz", "no comparison"),
}

BLOCK_TITLES = {
    "key_points": ("Главное", "Asosiy", "Key points"),
    "results": ("Результаты", "Natijalar", "Results"),
    "balance": ("Баланс", "Balans", "Balance sheet"),
    "strength": ("Устойчивость", "Barqarorlik", "Financial strength"),
    "risks": ("Риски и что смотреть дальше", "Xatarlar va nimani kuzatish kerak", "Risks and what to watch"),
}

# Phrases that the specification removes from the text, with the Uzbek and
# English forms the generator used to print, and words that may appear only
# when a sector signal fired.
BANNED_PHRASES = (
    "Аналитический профиль", "важно оценить не перечень долей", "следует оценивать вместе",
    "Разница между темпами показывает", "Точную операционную причину", "Картина смешанная",
    "Недостаточно сопоставимых данных", "тыс. сум", "ming so‘m", "thousand UZS",
    "Natijalar aralash", "The picture is mixed", "Financial trends are mixed",
    "Analytical profile", "Analitik profil", "катастроф", "взлёт", "взлет до небес", "catastroph", "skyrocket",
)
EVALUATIVE_WORDS = ("устойчив", "тревожн", "запас прочности", "barqaror", "xavotirli", "resilient", "alarming", "safety margin")
