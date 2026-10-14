"""Write the company analysis in six blocks, every word chosen from a figure.

Structure (specification «AI-анализ отчётности», 2026-10-12): a one-sentence
headline with a verdict line, «Главное», «Результаты», «Баланс»,
«Устойчивость», «Риски и что смотреть дальше» and one footnote.  Each
sentence records what it states — the lines it describes, the movement kind,
the tier of its verb and whether it printed a percent — so the publication
checks in ``sector_text_checks`` can test the words against the numbers.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from decimal import Decimal

import financial_analysis.sector_vocabulary as vocab
from financial_analysis.sector_calculations import CLIENT_LIABILITIES

BANKS = frozenset({"bank", "microfinance_bank", "microfinance"})

# Which line carries the period's scale, and which lines may be named in the
# list of main changes, for each family of templates.
TOP_LINE = {"bank": ("interest_income", "net_revenue_before_operating_expenses"),
            "insurance": ("insurance_premiums", "revenue"),
            "fund": ("dividend_income",),
            "general": ("revenue",)}

KEY_CANDIDATES = {
    "general": ("revenue", "gross_profit", "operating_income", "net_income", "cost_of_sales", "period_expenses",
                "total_assets", "total_liabilities", "total_equity", "cash", "receivables", "inventories",
                "fixed_assets", "construction_in_progress", "current_liabilities", "long_term_investments"),
    "bank": ("interest_income", "interest_expenses", "net_interest_income_before_provisions", "operating_expenses",
             "credit_loss_provisions", "net_income", "total_assets", "loan_portfolio", "customer_funds",
             "total_equity", "cash", "due_from_banks", "borrowings", "loan_reserves"),
    "insurance": ("insurance_premiums", "revenue", "insurance_service_result", "insurance_service_cost",
                  "operating_income", "net_income", "total_assets", "net_insurance_reserves", "total_equity",
                  "receivables", "cash", "long_term_investments", "other_liabilities"),
    "fund": ("net_income", "unrealized_fair_value_gain", "dividend_income", "portfolio_fair_value", "total_assets"),
}

RESULT_LINES = {
    "general": ("revenue", "cost_of_sales", "gross_profit", "period_expenses", "operating_income", "net_income",
                "financial_income", "financial_expenses"),
    "bank": ("interest_income", "interest_expenses", "net_interest_income_before_provisions", "noninterest_income",
             "operating_expenses", "credit_loss_provisions", "net_income", "fee_income"),
    "insurance": ("insurance_premiums", "revenue", "insurance_service_cost", "insurance_service_result",
                  "operating_income", "net_income", "financial_income", "financial_expenses"),
    "fund": ("dividend_income", "unrealized_fair_value_gain", "management_expenses", "net_income"),
}

# A cost compared with the income it is paid from: «расходы росли быстрее выручки».
PACE_PAIRS = {
    "general": (("cost_of_sales", "revenue"), ("period_expenses", "revenue")),
    "bank": (("interest_expenses", "interest_income"), ("operating_expenses", "net_revenue_before_operating_expenses")),
    "insurance": (("insurance_service_cost", "revenue"),),
    "fund": (),
}

# A line is named «крупнейшая статья» only when it is at least a quarter of
# the assets; below that the disclosed lines do not cover the balance sheet.
LARGEST_SHARE = Decimal(25)

LIABILITY_LINES = {
    "general": ("current_liabilities", "long_term_liabilities"),
    "bank": ("customer_funds", "borrowings"),
    "insurance": (),
    "fund": ("accounts_payable",),
}

ASSET_LINES = {
    "general": ("fixed_assets", "construction_in_progress", "long_term_investments", "inventories", "receivables",
                "cash", "short_term_investments"),
    "bank": ("loan_portfolio", "due_from_banks", "central_bank_balances", "cash"),
    "insurance": ("long_term_investments", "receivables", "cash", "fixed_assets", "construction_in_progress"),
    "fund": ("portfolio_fair_value", "cash", "dividends_receivable"),
}

# Lines whose change explains a total: (child, sign of its effect on the parent).
DRIVERS = {
    "total_assets": [(code, 1) for code in ("cash", "receivables", "inventories", "fixed_assets", "construction_in_progress",
                                             "long_term_investments", "short_term_investments", "loan_portfolio",
                                             "central_bank_balances", "due_from_banks", "portfolio_fair_value")],
    "total_liabilities": [(code, 1) for code in ("current_liabilities", "long_term_liabilities", "customer_funds", "borrowings",
                                                  "net_insurance_reserves", "other_liabilities", "accounts_payable")],
    "total_equity": [("retained_earnings", 1), ("share_capital", 1), ("additional_capital", 1)],
    "customer_funds": [("demand_deposits", 1), ("savings_deposits", 1), ("term_deposits", 1)],
    "net_income": [("operating_income", 1), ("financial_income", 1), ("financial_expenses", -1),
                   ("net_interest_income_before_provisions", 1), ("credit_loss_provisions", -1), ("noninterest_income", 1),
                   ("operating_expenses", -1), ("insurance_service_result", 1)],
    "operating_income": [("gross_profit", 1), ("period_expenses", -1)],
    "gross_profit": [("revenue", 1), ("cost_of_sales", -1)],
    "net_interest_income_before_provisions": [("interest_income", 1), ("interest_expenses", -1)],
    "insurance_service_result": [("revenue", 1), ("insurance_service_cost", -1)],
}

# Lines whose fall is good news: a cost going down is not a deterioration.
COSTS = frozenset({"cost_of_sales", "period_expenses", "financial_expenses", "interest_expenses", "operating_expenses",
                   "credit_loss_provisions", "insurance_service_cost", "management_expenses", "expenses", "fx_expenses",
                   "noninterest_expenses", "fee_expenses", "total_liabilities", "current_liabilities", "loan_reserves"})


def family(template):
    if template in BANKS:
        return "bank"
    if template == "insurance":
        return "insurance"
    if template == "investment_fund_ifrs_annual":
        return "fund"
    return "general"


# Who «ends the period with a loss»: (Russian noun, gender), Uzbek, English.
SUBJECTS = {"bank": (("Банк", "m"), "Bank", "The bank"), "insurance": (("Компания", "f"), "Kompaniya", "The company"),
            "fund": (("Фонд", "m"), "Fond", "The fund"), "general": (("Компания", "f"), "Kompaniya", "The company")}

PLAIN_VERBS = {
    "ru": {"up": [("grow", "{вырос|выросла|выросло|выросли}"), ("increase", "{увеличился|увеличилась|увеличилось|увеличились}")],
           "down": [("decline", "{снизился|снизилась|снизилось|снизились}"), ("shrink", "{сократился|сократилась|сократилось|сократились}")]},
    "uz": {"up": [("grow", "o‘sdi"), ("increase", "oshdi")], "down": [("decline", "kamaydi"), ("shrink", "qisqardi")]},
    "en": {"up": [("grow", "rose"), ("increase", "increased")], "down": [("decline", "fell"), ("shrink", "declined")]},
}


@dataclass
class Sentence:
    text: str
    metrics: tuple = ()
    kind: str = "statement"
    tier: str | None = None
    direction: str | None = None
    pct: Decimal | None = None
    percent_shown: bool = False
    evaluative: bool = False
    # Lines whose percent change the sentence prints (the headline's clauses).
    percent_codes: tuple = ()


@dataclass
class Paragraph:
    lang: str
    sentences: list = field(default_factory=list)
    lemmas: set = field(default_factory=set)

    def verb(self, direction, tier, pct, ratio, gender):
        table, doubles, half_again = vocab.VERBS[self.lang]
        options = []
        if tier == vocab.TIER_MULTIPLE and ratio is not None:
            for whole in (2, 3):
                if (direction, whole) in doubles and vocab.near(ratio, Decimal(whole)):
                    options.append(doubles[(direction, whole)])
        if tier == vocab.TIER_SHARP and direction == "up" and pct is not None and pct < 55:
            options.append(half_again)
        options += table[(direction if tier != vocab.TIER_STABLE else "flat", tier)]
        lemma, template = next(((l, t) for l, t in options if l not in self.lemmas), options[0])
        self.lemmas.add(lemma)
        text = template.replace("{p}", vocab.percent(pct, self.lang) if pct is not None else "")
        text = text.replace("{x}", vocab.times(ratio, self.lang) if ratio is not None else "")
        return vocab.gendered(text, gender), "{p}" in template

    def plain_verb(self, direction, gender):
        """A verb without a percent, for a move stated as two amounts."""
        options = PLAIN_VERBS[self.lang][direction]
        lemma, template = next(((l, t) for l, t in options if l not in self.lemmas), options[0])
        self.lemmas.add(lemma)
        return vocab.gendered(template, gender) if self.lang == "ru" else template

    def add(self, sentence):
        if sentence and sentence.text:
            self.sentences.append(sentence)
        return sentence

    @property
    def text(self):
        return " ".join(s.text for s in self.sentences)


class FactView:
    """The traceable facts of a filing with their comparison bases."""

    def __init__(self, filing, evidence):
        self.filing, self.evidence = filing, evidence
        self.lang = filing.lang if filing.lang in vocab.LANGS else "ru"
        self.family = family(filing.template)
        self.facts = {code: fact for code, fact in evidence.by_code.items() if code in vocab.NAMES}
        assets = self.value("total_assets")
        self.assets = assets if assets is not None and assets > 0 else None
        self.top = next((code for code in TOP_LINE[self.family] if self.value(code) is not None), None)

    # -------------------------------------------------------------- facts
    def value(self, code):
        fact = self.facts.get(code)
        return Decimal(str(fact["value"])) if fact and fact.get("value") is not None else None

    def base(self, code):
        fact = self.facts.get(code)
        return Decimal(str(fact["previous"])) if fact and fact.get("previous") is not None else None

    def basis(self, code):
        return (self.facts.get(code) or {}).get("comparison_basis") or "previous"

    def comparison_date(self, code):
        """The date a line's comparison figure stands at (ISO), if known."""
        return (self.facts.get(code) or {}).get("previous_date")

    def floor(self, code):
        """Smallest base a percent may be taken from (spec «Проценты»)."""
        if self.basis(code) == "opening":
            return self.assets * Decimal("0.01") if self.assets else None
        top = self.value(self.top) if self.top else None
        if code in vocab.PROFIT_LIKE and top and top > 0:
            return top * Decimal("0.05")
        return self.assets * Decimal("0.01") if self.assets else None

    def move(self, code):
        if code not in self.facts:
            return {"kind": "none"}
        return vocab.classify(self.value(code), self.base(code), profit_like=code in vocab.PROFIT_LIKE, floor=self.floor(code))

    def tr(self, ru, uz, en):
        return vocab.pick(self.lang, ru, uz, en)

    def has_comparison(self):
        return any(self.base(code) is not None for code in self.facts)


class Writer(FactView):
    def __init__(self, filing, evidence, assessment):
        super().__init__(filing, evidence)
        self.assessment = assessment
        self.described = set()
        self.shares_stated = set()
        # Lines whose percent change the headline printed: the body adds their
        # amount and driver, never the same percent a second time.
        self.percent_stated = set()

    # -------------------------------------------------------------- names
    def names(self, code):
        if code == "revenue" and self.family == "insurance":
            return vocab.INSURANCE_REVENUE
        return vocab.NAMES[code]

    def nom(self, code):
        ru, uz, en = self.names(code)
        return self.tr(ru[0], uz, en[0])

    def gen(self, code):
        ru, uz, en = self.names(code)
        return self.tr(ru[1], uz, en[0])

    def gender(self, code):
        """Russian gender; in English «pl» marks a plural noun for verb number."""
        if self.lang == "en":
            return "pl" if self.plural(code) else "m"
        return self.names(code)[0][2]

    def plural(self, code):
        return self.names(code)[2][1]

    def money(self, value):
        return vocab.money(value, self.lang)

    def pair(self, first, second):
        a, b, unit = vocab.money_pair(first, second, self.lang)
        if self.lang == "en":
            return f"UZS {a}{unit}", f"UZS {b}{unit}"
        return a, f"{b} {unit}".strip()

    def ago(self, code):
        if self.basis(code) == "opening":
            date = self.comparison_date(code)
            if date and date != f"{self.filing.year - 1}-12-31":
                when = vocab.balance_date(date, self.lang)
                return self.tr(f"на {when}", f"{when} holatiga", f"at {when}")
            return self.tr("на начало года", "yil boshida", "at the start of the year")
        return self.tr("годом ранее", "bir yil oldin", "a year earlier")

    # -------------------------------------------------------------- sentences
    def change(self, paragraph, code, *, driver=False, tail=True, pace_with=None):
        """One sentence on how a line moved, or None when it has no base."""
        move = self.move(code)
        kind = move["kind"]
        if kind in {"none", "zero_both"}:
            return None
        name, gender = vocab.capital(self.nom(code)), self.gender(code)
        current, previous = move["current"], move["previous"]
        sentence = Sentence("", (code,), kind, direction=move.get("direction"))
        if code == "credit_loss_provisions" and current < 0:
            # A credit-loss line that the form's own arithmetic shows as a
            # release is a recovery of reserves, not «отчисления −X».
            released = self.money(-current)
            prior = ""
            if previous > 0:
                prior = self.tr(f"; {self.ago(code)} отчисления составили {self.money(previous)}",
                                f"; {self.ago(code)} ajratmalar {self.money(previous)} bo‘lgan",
                                f"; {self.ago(code)} provisions were {self.money(previous)}")
            sentence.text = self.tr(f"Резервы восстановлены на {released}: это добавило к прибыли{prior}.",
                                    f"Zaxiralar {released}ga tiklandi: bu foydaga qo‘shildi{prior}.",
                                    f"Reserves of {released} were released, adding to profit{prior}.")
            self.described.add(code)
            return paragraph.add(sentence)
        if kind == "trend" and code in self.percent_stated and move["tier"] != vocab.TIER_STABLE:
            # The headline gave the percent; here the amount it came to.
            verb = paragraph.plain_verb(move["direction"], gender)
            amount = self.money(current)
            text = self.tr(f"{name} {verb} до {amount}", f"{name} {amount}gacha {verb}", f"{name} {verb} to {amount}")
        elif kind == "trend":
            verb, shown = paragraph.verb(move["direction"], move["tier"], move["pct"], move.get("ratio"), gender)
            sentence.tier, sentence.pct, sentence.percent_shown = move["tier"], move["pct"], shown
            amount = self.money(current)
            if move["tier"] == vocab.TIER_STABLE:
                end = self.tr(f" — {amount}", f" — {amount}", f" at {amount}")
            else:
                end = self.tr(f" — до {amount}", f" — {amount}gacha", f" to {amount}")
            text = f"{name} {verb}" + (end if tail else "")
        elif kind in {"to_loss", "to_profit", "loss_narrowed", "loss_widened"}:
            text = self.sign_text(code, kind, current, previous)
        elif kind in {"tiny_base", "extreme"}:
            a, b = self.pair(previous, current)
            verb = paragraph.plain_verb("up" if current > previous else "down", gender)
            text = self.tr(f"{name} {verb} с {a} до {b}", f"{name} {a}dan {b}gacha {verb}", f"{name} {verb} from {a} to {b}")
        elif kind == "sign_change":
            a, b = self.pair(previous, current)
            if self.lang == "ru":
                text = f"{name} " + vocab.gendered("{изменился|изменилась|изменилось|изменились}", gender) + f" с {a} до {b}"
            elif self.lang == "uz":
                text = f"{name} {a}dan {b}gacha o‘zgardi"
            else:
                text = f"{name} moved from {a} to {b}"
        elif kind == "from_zero":
            text = self.tr(f"{name}: {self.money(current)} против нуля {self.ago(code)}",
                           f"{name}: {self.money(current)}, {self.ago(code)} nol edi",
                           f"{name}: {self.money(current)}, against zero {self.ago(code)}")
        else:  # to_zero
            text = self.tr(f"{name}: ноль против {self.money(previous)} {self.ago(code)}",
                           f"{name}: nol, {self.ago(code)} {self.money(previous)} edi",
                           f"{name} fell to zero from {self.money(previous)} {self.ago(code)}")
        if pace_with:
            text += pace_with
        if driver:
            text += self.driver_clause(code, move)
        sentence.text = text + "."
        self.described.add(code)
        return paragraph.add(sentence)

    def sign_text(self, code, kind, current, previous):
        ru, uz, en, losses = vocab.RESULT_NAMES[code]
        loss_ru, loss_uz, loss_en = losses
        now, before = self.money(abs(current)), self.money(abs(previous))
        ago = self.ago(code)
        (subject_ru, gender), subject_uz, subject_en = SUBJECTS[self.family]
        if code == "net_income" and kind == "to_loss":
            return self.tr(f"{subject_ru} " + vocab.gendered("{завершил|завершила|завершило|завершили}", gender) + f" период с чистым убытком {now} после прибыли {before} {ago}",
                           f"{subject_uz} davrni {now} sof zarar bilan yakunladi, {ago} {before} foyda bo‘lgan",
                           f"{subject_en} ended the period with a net loss of {now} after a profit of {before} {ago}")
        if code == "net_income" and kind == "to_profit":
            return self.tr(f"{subject_ru} " + vocab.gendered("{вышел|вышла|вышло|вышли}", gender) + f" в прибыль: {now} после убытка {before} {ago}",
                           f"{subject_uz} foydaga chiqdi: {now}, {ago} {before} zarar bo‘lgan",
                           f"{subject_en} returned to profit: {now} after a loss of {before} {ago}")
        if kind == "to_loss":
            return self.tr(f"{vocab.capital(ru[0])} сменился убытком {now} после прибыли {before} {ago}",
                           f"{vocab.capital(uz)} zararga o‘tdi: {now}, {ago} {before} foyda bo‘lgan",
                           f"{vocab.capital(en)} turned to a loss of {now} from a profit of {before} {ago}")
        if kind == "to_profit":
            return self.tr(f"{vocab.capital(ru[0])} вышел в плюс: прибыль {now} после убытка {before} {ago}",
                           f"{vocab.capital(uz)} foydaga chiqdi: {now}, {ago} {before} zarar bo‘lgan",
                           f"{vocab.capital(en)} turned positive: a profit of {now} after a loss of {before} {ago}")
        a, b = self.pair(abs(previous), abs(current))
        narrowed = kind == "loss_narrowed"
        return self.tr(f"{vocab.capital(loss_ru)} {'сократился' if narrowed else 'вырос'} с {a} до {b}",
                       f"{vocab.capital(loss_uz)} {a}dan {b}gacha {'qisqardi' if narrowed else 'oshdi'}",
                       f"{vocab.capital(loss_en)} {'narrowed' if narrowed else 'widened'} from {a} to {b}")

    def driver_clause(self, code, move):
        """«за счёт …» only when one line gave more than half of the change."""
        delta = move.get("delta")
        if not delta:
            return ""
        best = None
        for child, sign in DRIVERS.get(code, ()):
            child_now, child_before = self.value(child), self.base(child)
            if child_now is None or child_before is None or self.basis(child) != self.basis(code):
                continue
            effect = (child_now - child_before) * sign
            if effect * delta > 0 and abs(effect) > abs(delta) / 2 and (best is None or abs(effect) > abs(best[1])):
                best = (child, effect, child_now - child_before)
        if not best:
            return ""
        child, _, child_delta = best
        amount = self.money(abs(child_delta))
        rise = child_delta > 0
        self.described.add(child)
        return self.tr(f", за счёт {'роста' if rise else 'снижения'} {self.gen(child)} на {amount}",
                       f", asosan {self.nom(child)} {amount}ga {'o‘sgani' if rise else 'kamaygani'} hisobiga",
                       f", driven by a {amount} {'rise' if rise else 'fall'} in {self.nom(child)}")

    def level(self, paragraph, code):
        value = self.value(code)
        if value is None:
            return None
        name = vocab.capital(self.nom(code))
        text = self.tr(f"{name} за период — {self.money(value)}.", f"{name} davr uchun — {self.money(value)}.",
                       f"{name} for the period: {self.money(value)}.") if self.basis(code) == "previous" else \
            self.tr(f"{name} на отчётную дату — {self.money(value)}.", f"{name} hisobot sanasida — {self.money(value)}.",
                    f"{name} at the reporting date: {self.money(value)}.")
        self.described.add(code)
        return paragraph.add(Sentence(text, (code,), "level"))

    def share_of(self, part, whole):
        part, whole = self.value(part) if isinstance(part, str) else part, self.value(whole) if isinstance(whole, str) else whole
        if part is None or whole is None or whole <= 0 or part < 0:
            return None
        return part / whole * 100

    def opening_share(self, part, whole):
        p, w = self.base(part), self.base(whole)
        if p is None or w is None or w <= 0 or p < 0 or self.basis(part) != "opening":
            return None
        return p / w * 100

    def share_shift(self, part, whole, sentence=False):
        """«доля выросла с 12% до 18%» when the share moved 2 p.p. or more."""
        now, before = self.share_of(part, whole), self.opening_share(part, whole)
        if now is None or before is None or abs(now - before) < 2:
            return ""
        up = now > before
        a, b = vocab.share_percent(before, self.lang), vocab.share_percent(now, self.lang)
        if sentence:
            whole_ru = {"total_assets": "активов", "total_liabilities": "обязательств"}.get(whole, "")
            return self.tr(f"Доля {self.gen(part)} {'выросла' if up else 'снизилась'} с {a} до {b} {whole_ru}".rstrip(),
                           f"{vocab.capital(self.nom(part))} ulushi {a}dan {b}gacha {'oshdi' if up else 'kamaydi'}",
                           f"The share of {self.nom(part)} {'rose' if up else 'fell'} from {a} to {b} of {self.nom(whole)}")
        return self.tr(f"; доля {'выросла' if up else 'снизилась'} с {a} до {b}",
                       f"; ulushi {a}dan {b}gacha {'oshdi' if up else 'kamaydi'}",
                       f"; {'their' if self.plural(part) else 'its'} share {'rose' if up else 'fell'} from {a} to {b}")

    # -------------------------------------------------------------- headline and verdict
    def good(self, code, move):
        kind = move["kind"]
        if kind in {"to_profit", "loss_narrowed"}:
            return True
        if kind in {"to_loss", "loss_widened"}:
            return False
        direction = move.get("direction")
        if direction == "flat" or direction is None:
            return None
        return (direction == "up") != (code in COSTS)

    def headline(self):
        lang = self.lang
        bottom = "net_income" if "net_income" in self.facts else "operating_income" if "operating_income" in self.facts else None
        codes = [code for code in dict.fromkeys((self.top, bottom))
                 if code and self.move(code)["kind"] not in {"none", "zero_both"}]
        paragraph = Paragraph(lang)
        clauses = []
        for code in codes:
            # Two clauses name their movements without amounts, so the list
            # below can still state them; a lone clause or a move stated as
            # amounts is the full statement, and is not repeated below.
            alone = len(codes) == 1
            sentence = self.change(paragraph, code, tail=alone)
            if self.move(code)["kind"] == "trend" and not alone:
                self.described.discard(code)
            if sentence is not None and sentence.kind == "trend" and sentence.tier != vocab.TIER_STABLE:
                self.percent_stated.add(code)
            clauses.append((code, sentence))
        if not clauses:
            return self.snapshot_headline(paragraph)
        if len(clauses) == 1:
            text = clauses[0][1].text.rstrip(".")
        else:
            (first_code, first), (second_code, second) = clauses
            agree = self.good(first_code, self.move(first_code)) == self.good(second_code, self.move(second_code))
            joint = self.tr(", и " if agree else ", но ", " va " if agree else ", ammo ", ", and " if agree else ", but ")
            second_text = second.text.rstrip(".")
            if second_text.startswith(("Компания", "Банк", "Фонд", "Kompaniya", "Bank", "Fond", "The company", "The bank", "The fund")) and lang != "uz":
                second_text = second_text[:1].lower() + second_text[1:]
            elif not second_text.startswith(("Markaziy", "ЦБ")):
                second_text = second_text[:1].lower() + second_text[1:]
            text = first.text.rstrip(".") + joint + second_text
        margin = self.share_of("net_income", self.top) if self.top == "revenue" and (self.value("net_income") or 0) > 0 else None
        if margin is not None:
            extra = self.tr(f", при чистой марже {vocab.share_percent(margin, lang)}",
                            f", sof marja — {vocab.share_percent(margin, lang)}",
                            f", with a net margin of {vocab.share_percent(margin, lang)}")
            if len((text + extra).split()) <= 30:
                text += extra
        return text + ".", tuple(code for code, _ in clauses)

    def snapshot_headline(self, paragraph=None):
        """No result has a comparison: the result on the date, and the balance move if there is one."""
        period = self.filing.period_text
        parts = []
        for code in ("net_income", self.top, "total_assets", "total_equity"):
            if code and self.value(code) is not None and code not in [c for c, _ in parts] and len(parts) < 2:
                parts.append((code, self.money(self.value(code))))
        assets = self.move("total_assets")
        if paragraph is not None and assets["kind"] == "trend" and parts and parts[0][0] != "total_assets":
            code, amount = parts[0]
            self.described.add(code)
            clause = self.change(paragraph, "total_assets", tail=False)
            self.described.discard("total_assets")
            if clause.tier != vocab.TIER_STABLE:
                self.percent_stated.add("total_assets")
            return self.tr(f"{vocab.capital(self.nom(code))} за {period} — {amount}, а " + clause.text[:1].lower() + clause.text[1:],
                           f"{period} uchun {self.nom(code)} — {amount}, " + clause.text[:1].lower() + clause.text[1:],
                           f"{vocab.capital(self.nom(code))} for {period}: {amount}, while " + clause.text[:1].lower() + clause.text[1:]), (code, "total_assets")
        self.described.update(code for code, _ in parts)
        if not parts:
            return self.tr(f"Отчётность за {period} опубликована.", f"{period} uchun hisobot e’lon qilingan.", f"The {period} filing is published."), ()
        body = ", ".join(f"{self.nom(code)} — {amount}" if self.lang != "en" else f"{self.nom(code)} {amount}" for code, amount in parts)
        return self.tr(f"За {period}: {body}.", f"{period} yakunlari: {body}.", f"For {period}: {body}."), tuple(code for code, _ in parts)

    def verdict_line(self):
        status = self.assessment.verdict_status
        word = vocab.pick(self.lang, *vocab.VERDICT_WORDS[status])
        reason = self.assessment.verdict_reason or ""
        return self.tr(f"Вердикт: {word} — {reason}.", f"Xulosa: {word} — {reason}.", f"Verdict: {word} — {reason}.")

    # -------------------------------------------------------------- blocks
    def key_points(self):
        """3–5 points ordered by |change in sum| / assets; fired signals always in."""
        candidates = []
        for code in KEY_CANDIDATES[self.family]:
            if code in self.described:
                continue
            move = self.move(code)
            if move["kind"] in {"none", "zero_both"}:
                continue
            if move["kind"] == "trend" and move["tier"] == vocab.TIER_STABLE and code not in {"total_assets", "net_income"}:
                continue
            weight = abs(move["delta"]) / self.assets if self.assets else Decimal(0)
            candidates.append((weight, code))
        candidates.sort(key=lambda item: item[0], reverse=True)
        available = {code for _, code in candidates}
        # A fired signal is always in the list; the rest is filled by weight.
        forced = list(dict.fromkeys(s["metric_code"] for s in [*self.hard_flags(), *self.assessment.negatives]
                                    if s["metric_code"] in available))[:5]
        order = {code: index for index, (_, code) in enumerate(candidates)}
        rest = [code for _, code in candidates if code not in forced]
        paragraph = Paragraph(self.lang)
        written = []
        # Fired signals first, then by weight, until five points stand; a line
        # already named as the driver of a larger one is not listed twice.
        for code in forced + rest:
            if len(written) >= 5:
                break
            if code in self.described:
                continue
            written.append(code)
            self.change(Paragraph(self.lang), code, driver=True, pace_with=self.pace_clause(code))
            self.described.discard(code)
            for child, _ in DRIVERS.get(code, ()):
                self.described.discard(child)
        for code in sorted(written, key=lambda code: order[code]):
            self.change(paragraph, code, driver=True, pace_with=self.pace_clause(code))
        if len(paragraph.sentences) < 3:
            self.structure_points(paragraph)
        return paragraph

    def pace_clause(self, code):
        """«— быстрее выручки (+9%)» for a working-capital line flagged against sales."""
        for signal in self.assessment.negatives:
            if signal["code"] == f"{code}_outpace_revenue":
                move = self.move("revenue")
                pace = vocab.signed_change(move, self.lang)
                if not pace:
                    continue
                if move.get("direction") == "down":
                    # Paces of opposite sign are not compared: a line growing
                    # while revenue falls is not «faster» than it.
                    if move.get("tier") == vocab.TIER_MULTIPLE:
                        return self.tr(f", хотя выручка сократилась {pace}", f", tushum esa {pace} kamaydi", f", while revenue fell {pace}")
                    return self.tr(f", хотя выручка снизилась ({pace})", f", tushum esa kamaydi ({pace})", f", while revenue fell ({pace})")
                if move.get("tier") == vocab.TIER_MULTIPLE:
                    # «быстрее выручки (в 2,2 раза)» read as a fall (KASU): a
                    # multiple carries its direction in words.
                    return self.tr(f", быстрее выручки (она выросла {pace})", f", tushumdan tezroq (u {pace} o‘sdi)", f", faster than revenue (up {pace})")
                return self.tr(f", быстрее выручки ({pace})", f", tushumdan tezroq ({pace})", f", faster than revenue ({pace})")
        return ""

    def structure_points(self, paragraph):
        """Without a comparison, the main points are the structure on the date."""
        assets = [code for code in ASSET_LINES[self.family] if self.share_of(code, "total_assets")]
        if assets and self.assets:
            largest = max(assets, key=lambda code: self.value(code))
            if self.share_of(largest, "total_assets") >= LARGEST_SHARE and largest not in {s.metrics[0] for s in paragraph.sentences if s.metrics}:
                self.shares_stated.add(largest)
                share = vocab.share_phrase(self.share_of(largest, "total_assets"), self.lang)
                paragraph.add(Sentence(self.tr(f"Крупнейшая статья активов — {self.nom(largest)}: {share} активов.",
                                               f"Eng yirik aktiv moddasi — {self.nom(largest)}: aktivlarning {share}.",
                                               f"The largest asset is {self.nom(largest)}: {share} of total assets."), (largest,), "share"))
        for code in ("net_income", self.top):
            if code and len(paragraph.sentences) < 3 and code not in self.described and self.value(code) is not None:
                self.level(paragraph, code)
        equity_share = self.share_of("total_equity", "total_assets")
        if len(paragraph.sentences) < 3 and equity_share is not None:
            self.shares_stated.add("equity_share")
            paragraph.add(Sentence(self.tr(f"Собственный капитал составляет {vocab.share_phrase(equity_share, 'ru', 'acc')} активов.",
                                           f"O‘z kapitali aktivlarning {vocab.share_phrase(equity_share, 'uz', 'acc')} tashkil etadi.",
                                           f"Equity makes up {vocab.share_phrase(equity_share, 'en')} of total assets."), ("total_equity",), "share"))

    def results(self):
        paragraph = Paragraph(self.lang)
        if self.top == "revenue" and self.move("revenue")["kind"] == "zero_both":
            paragraph.add(Sentence(self.tr("Выручки не было ни в этом периоде, ни годом ранее.",
                                           "Bu davrda ham, bir yil oldin ham tushum bo‘lmagan.",
                                           "There was no revenue in this period or a year earlier."), ("revenue",), "level"))
        lines = [code for code in RESULT_LINES[self.family] if code in self.facts]
        for code in lines:
            if code in self.described or len(paragraph.sentences) >= 6:
                continue
            if self.move(code)["kind"] == "none":
                self.level(paragraph, code)
            elif self.move(code)["kind"] != "zero_both":
                self.change(paragraph, code)
        paces = [(cost, sentence) for cost, income in PACE_PAIRS[self.family] for sentence in [self.pace(cost, income)] if sentence]
        for _, sentence in paces[:2]:
            paragraph.add(sentence)
        used_margins = set()
        for pace in (paces[:2] or [None]):
            margin = self.margin_sentence(pace, skip=used_margins)
            if margin:
                paragraph.add(margin)
        bridge = self.profit_bridge()
        for sentence in self.sector_result_facts():
            # The bridge states the finance costs in amounts; their share of
            # operating profit beside it would say the same thing twice.
            if not (bridge and sentence.kind == "finance_share"):
                paragraph.add(sentence)
        paragraph.add(bridge)
        return paragraph

    def profit_bridge(self):
        """What lies between the operating and the net result, when it is material."""
        operating, net = self.value("operating_income"), self.value("net_income")
        if operating is None or net is None or operating == 0 or abs(operating - net) < abs(operating) * Decimal("0.1"):
            return None
        parts, explained = [], Decimal(0)
        for code, sign, ru, uz, en in (("financial_income", 1, "финансовые доходы", "moliyaviy daromadlar", "finance income"),
                                       ("financial_expenses", -1, "финансовые расходы", "moliyaviy xarajatlar", "finance costs"),
                                       ("tax", -1, "налог на прибыль", "foyda solig‘i", "income tax")):
            value = self.value(code)
            if value and abs(value) >= abs(operating - net) * Decimal("0.05"):
                explained += sign * abs(value)
                parts.append(f"{self.tr(ru, uz, en)} — {self.money(abs(value))}" if self.lang != "en" else f"{en} {self.money(abs(value))}")
        # Named only when the listed lines account for most of the gap; a gap
        # made of lines the filing does not disclose is not explained by them.
        gap = net - operating
        if not parts or explained * gap <= 0 or abs(explained) < abs(gap) / 2:
            return None
        listed = ", ".join(parts)
        result = lambda value, ru_profit, ru_loss, uz_profit, uz_loss, en_profit, en_loss: (
            self.tr(ru_profit, uz_profit, en_profit) if value > 0 else self.tr(ru_loss, uz_loss, en_loss)) + f" {self.money(abs(value))}"
        first = result(operating, "операционной прибылью", "операционным убытком", "operatsion foyda", "operatsion zarar", "operating profit of", "an operating loss of")
        second = result(net, "чистой прибылью", "чистым убытком", "sof foyda", "sof zarar", "net profit of", "a net loss of")
        return Sentence(self.tr(f"Между {first} и {second} стоят {listed}.", f"{vocab.capital(first)} va {second} orasida: {listed}.",
                                f"Between {first} and {second} stand {listed}."), (), "bridge")

    def pace(self, cost, income):
        """Paces first, then their relation; only when they differ by more than 5 p.p."""
        a, b = self.move(cost), self.move(income)
        if a["kind"] != "trend" or b["kind"] != "trend" or abs(a["pct"] - b["pct"]) <= 5:
            return None
        if a["tier"] == vocab.TIER_MULTIPLE or b["tier"] == vocab.TIER_MULTIPLE:
            return None
        # «Сначала темпы, потом их соотношение»: when both paces are already in
        # the text, the relation is stated without printing them again.
        stated = all(code in self.described or code in self.percent_stated for code in (cost, income))
        sign = lambda move: ("+" if move["pct"] > 0 else vocab.MINUS) + vocab.percent(move["pct"], self.lang)
        faster = abs(a["pct"]) > abs(b["pct"]) if (a["pct"] > 0) == (b["pct"] > 0) else None
        name, gender = vocab.capital(self.nom(cost)), self.gender(cost)
        if faster is None:
            text = self.tr(f"{name} и {self.nom(income)} двигались в разные стороны: {sign(a)} против {sign(b)}",
                           f"{name} va {self.nom(income)} turli yo‘nalishda o‘zgardi: {sign(a)} va {sign(b)}",
                           f"{name} and {self.nom(income)} moved in opposite directions: {sign(a)} against {sign(b)}")
        elif self.lang == "ru":
            verb = vocab.gendered("{рос|росла|росло|росли}" if a["pct"] > 0 else "{снижался|снижалась|снижалось|снижались}", gender)
            text = f"{name} {verb} {'быстрее' if faster else 'медленнее'}, чем {self.nom(income)}: {sign(a)} против {sign(b)}"
        elif self.lang == "uz":
            text = f"{name} {self.nom(income)}dan {'tezroq' if faster else 'sekinroq'} {'o‘sdi' if a['pct'] > 0 else 'kamaydi'}: {sign(a)} va {sign(b)}"
        else:
            text = f"{name} {'grew' if a['pct'] > 0 else 'fell'} {'faster' if faster else 'more slowly'} than {self.nom(income)}: {sign(a)} against {sign(b)}"
        if stated:
            text = text.split(":")[0]
        return Sentence(text + ".", (), "pace", percent_shown=not stated)

    MARGINS = (("gross_profit", "cost_of_sales", ("валовая маржа", "yalpi marja", "gross margin")),
               ("operating_income", "period_expenses", ("операционная маржа", "operatsion marja", "operating margin")),
               ("net_income", None, ("чистая маржа", "sof marja", "net margin")))

    def margin_sentence(self, pace=None, skip=None):
        """A margin shift of 1 p.p. or more; «в результате» only when the pace explains it."""
        if self.top != "revenue":
            return None
        skip = set() if skip is None else skip
        margins = sorted(self.MARGINS, key=lambda item: pace is None or item[1] != pace[0])
        for code, cost, (ru, uz, en) in margins:
            if code in skip:
                continue
            now = self.share_of(code, "revenue")
            before_part, before_whole = self.base(code), self.base("revenue")
            if now is None or before_part is None or not before_whole or before_whole <= 0 or before_part <= 0:
                continue
            before = before_part / before_whole * 100
            if not (0 < now <= 100 and 0 < before <= 100) or abs(now - before) < 1:
                continue
            up = now > before
            a, b = vocab.share_percent(before, self.lang), vocab.share_percent(now, self.lang)
            explained = False
            if pace and cost == pace[0]:
                cost_move, income_move = self.move(cost), self.move("revenue")
                cost_faster = cost_move["pct"] > income_move["pct"]
                explained = cost_faster != up
            lead = self.tr("В результате " if explained else "", "Natijada " if explained else "", "As a result, the " if explained else "The ")
            text = self.tr(f"{lead}{ru} {'выросла' if up else 'снизилась'} с {a} до {b}.",
                           f"{lead}{uz} {a}dan {b}gacha {'oshdi' if up else 'kamaydi'}.",
                           f"{lead}{en} {'rose' if up else 'fell'} from {a} to {b}.")
            skip.add(code)
            return Sentence(vocab.capital(text), (), "margin")
        return None

    def absorbs(self, part, whole, ru, uz, en):
        """«Процентные расходы забирают около половины процентных доходов» — a share of 5–100%."""
        share = self.share_of(part, whole)
        if share is None or not 5 <= share <= 100:
            return None
        return Sentence(self.tr(ru.format(acc=vocab.share_phrase(share, "ru", "acc")), uz.format(share=vocab.share_phrase(share, "uz", "acc")),
                                en.format(share=vocab.share_phrase(share, "en"))), (), "share")

    def sector_result_facts(self):
        out = []
        if self.family == "bank":
            out.append(self.absorbs("interest_expenses", "interest_income", "Процентные расходы забирают {acc} процентных доходов.",
                                    "Foizli xarajatlar foizli daromadlarning {share} tashkil etadi.", "Interest expense takes {share} of interest income."))
            # A charge matched by other income (a gross-up) is no measure of
            # credit risk; its share of interest income is not stated.
            if not any(signal["code"] == "provisions_offset_by_other_income" for signal in self.assessment.negatives):
                out.append(self.absorbs("credit_loss_provisions", "net_interest_income_before_provisions", "Отчисления в резервы забирают {acc} чистого процентного дохода.",
                                        "Zaxiralarga ajratmalar sof foizli daromadning {share} oladi.", "Credit-loss provisions take {share} of net interest income."))
            share = self.share_of("operating_expenses", "net_revenue_before_operating_expenses")
            if share is not None and share <= 100:
                out.append(Sentence(self.tr(f"Операционные расходы поглощают {vocab.share_phrase(share, 'ru', 'acc')} чистого дохода банка.",
                                            f"Operatsion xarajatlar bank sof daromadining {vocab.share_phrase(share, 'uz', 'acc')} tashkil etadi.",
                                            f"Operating expenses absorb {vocab.share_phrase(share, 'en')} of the bank's net revenue."), (), "share"))
        elif self.family == "general" and (self.value("operating_income") or 0) > 0:
            finance = self.absorbs("financial_expenses", "operating_income", "Финансовые расходы забирают {acc} операционной прибыли.",
                                   "Moliyaviy xarajatlar operatsion foydaning {share} oladi.", "Finance costs take {share} of operating profit.")
            if finance:
                finance.kind = "finance_share"
            out.append(finance)
        elif self.family == "insurance":
            ceded = self.share_of("ceded_premiums", "insurance_premiums")
            if ceded is not None and ceded <= 100:
                out.append(Sentence(self.tr(f"Перестраховщикам уходит {vocab.share_phrase(ceded, 'ru')} премий.",
                                            f"Mukofotlarning {vocab.share_phrase(ceded, 'uz')} qayta sug‘urtalovchilarga berilgan.",
                                            f"{vocab.capital(vocab.share_phrase(ceded, 'en'))} of premiums went to reinsurers."), (), "share"))
        elif self.family == "fund":
            share = self.share_of("unrealized_fair_value_gain", "net_income")
            if share is not None and share <= 100:
                out.append(Sentence(self.tr(f"Нереализованная переоценка формирует {vocab.share_phrase(share, 'ru', 'acc')} чистой прибыли.",
                                            f"Realizatsiya qilinmagan qayta baholash sof foydaning {vocab.share_phrase(share, 'uz', 'acc')} tashkil etadi.",
                                            f"Unrealised revaluation makes up {vocab.share_phrase(share, 'en')} of net profit."), (), "share"))
        return [sentence for sentence in out if sentence]

    def balance(self):
        """Structure and its shifts: lines of ≥5% of assets or a move of ≥2% of assets, four at most."""
        paragraph = Paragraph(self.lang)
        if not self.assets:
            return paragraph
        rows = []
        for code in ASSET_LINES[self.family]:
            share = self.share_of(code, "total_assets")
            move = self.move(code)
            moved = move.get("delta") is not None and abs(move["delta"]) >= self.assets * Decimal("0.02")
            if share is not None and (share >= 5 or moved):
                rows.append((share, code))
        rows.sort(reverse=True)
        variants = (self.tr("На долю {gen} приходится {share} активов", "Aktivlarning {share} {nom}ga to‘g‘ri keladi", "{Nom} {verb} {share} of total assets"),
                    self.tr("{Nom} {verb} {acc} активов", "{Nom} aktivlarning {acc} tashkil etadi", "{Nom} {verb2} {share} of total assets"))
        for index, (share, code) in enumerate(rows[:4]):
            phrase = vocab.share_phrase(share, self.lang)
            shift = self.share_shift(code, "total_assets", sentence=True)
            if code in self.shares_stated and not shift:
                pass
            elif shift:
                paragraph.add(Sentence(shift + ".", (), "share"))
            elif index == 0 and share >= LARGEST_SHARE:
                paragraph.add(Sentence(self.tr(f"Крупнейшая статья активов — {self.nom(code)}: {phrase} активов.",
                                               f"Eng yirik aktiv moddasi — {self.nom(code)}: aktivlarning {phrase}.",
                                               f"The largest asset is {self.nom(code)}: {phrase} of total assets."), (), "share"))
            else:
                template = variants[index % 2]
                verb = vocab.gendered("{составляет|составляет|составляет|составляют}", self.gender(code)) if self.lang == "ru" else \
                    ("make up" if self.plural(code) else "makes up")
                verb2 = "account for" if self.plural(code) else "accounts for"
                paragraph.add(Sentence(template.format(gen=self.gen(code), nom=self.nom(code), Nom=vocab.capital(self.nom(code)), share=phrase,
                                                       acc=vocab.share_phrase(share, self.lang, "acc"), verb=verb, verb2=verb2) + ".", (), "share"))
            self.shares_stated.add(code)
            move = self.move(code)
            if code not in self.described and move.get("delta") is not None and abs(move["delta"]) >= self.assets * Decimal("0.02"):
                self.change(paragraph, code)
        return [paragraph, self.liability_structure()]

    def liability_structure(self):
        """Where the money comes from: the largest liability lines, four at most."""
        paragraph = Paragraph(self.lang)
        liabilities = self.value("total_liabilities")
        if not liabilities or liabilities <= 0:
            return paragraph
        rows = sorted(((self.share_of(code, "total_liabilities"), code) for code in LIABILITY_LINES[self.family]
                       if self.share_of(code, "total_liabilities") is not None), reverse=True)
        for share, code in rows[:2]:
            if share < 5 or share > 100:
                continue
            shift = self.share_shift(code, "total_liabilities", sentence=True)
            verb = vocab.gendered("{формирует|формирует|формирует|формируют}", self.gender(code)) if self.lang == "ru" else \
                ("make up" if self.plural(code) else "makes up")
            text = self.tr(f"{vocab.capital(self.nom(code))} {verb} {vocab.share_phrase(share, 'ru', 'acc')} всех обязательств",
                           f"{vocab.capital(self.nom(code))} barcha majburiyatlarning {vocab.share_phrase(share, 'uz', 'acc')} tashkil etadi",
                           f"{vocab.capital(self.nom(code))} {verb} {vocab.share_phrase(share, 'en')} of all liabilities")
            paragraph.add(Sentence(text + (self.share_shift(code, "total_liabilities") if shift else "") + ".", (), "share"))
            move = self.move(code)
            if code not in self.described and self.assets and move.get("delta") is not None and abs(move["delta"]) >= self.assets * Decimal("0.02"):
                self.change(paragraph, code, driver=True)
        if self.family == "bank":
            deposits = sorted(((self.share_of(code, "customer_funds"), code) for code in ("term_deposits", "demand_deposits", "savings_deposits")
                               if self.share_of(code, "customer_funds") is not None), reverse=True)
            if deposits and deposits[0][0] <= 100:
                share, code = deposits[0]
                verb = vocab.gendered("{составляет|составляет|составляет|составляют}", self.gender(code)) if self.lang == "ru" else "make up"
                paragraph.add(Sentence(self.tr(f"Крупнейшая часть средств клиентов — {self.nom(code)}: {vocab.share_phrase(share, 'ru')}.",
                                               f"Mijozlar mablag‘larining eng katta qismi — {self.nom(code)}: {vocab.share_phrase(share, 'uz')}.",
                                               f"The largest part of customer funds is {self.nom(code)}: {vocab.share_phrase(share, 'en')}."), (), "share"))
        return paragraph

    def strength(self):
        paragraph = Paragraph(self.lang)
        lang = self.lang
        if self.family == "fund":
            assets, liabilities = self.value("total_assets"), self.value("total_liabilities")
            if assets is not None and liabilities is not None:
                nav = self.money(assets - liabilities)
                paragraph.add(Sentence(self.tr(f"Чистые активы фонда (NAV) — {nav}.", f"Fondning sof aktivlari (NAV) — {nav}.",
                                               f"Net asset value (NAV): {nav}."), (), "level"))
            largest = self.share_of("largest_holding", "portfolio_fair_value")
            if largest is not None and largest <= 100:
                paragraph.add(Sentence(self.tr(f"Крупнейшая позиция составляет {vocab.share_phrase(largest, 'ru', 'acc')} портфеля.",
                                               f"Eng yirik pozitsiya portfelning {vocab.share_phrase(largest, 'uz', 'acc')} tashkil etadi.",
                                               f"The largest holding makes up {vocab.share_phrase(largest, 'en')} of the portfolio."), (), "share"))
            for part, whole, ru, uz, en in (
                    ("level3_investments", "portfolio_fair_value", "Инвестиции уровня 3, оцениваемые по моделям, составляют {acc} портфеля.", "Modellar bo‘yicha baholanadigan 3-darajali investitsiyalar portfelning {share_acc} tashkil etadi.", "Level 3 investments, valued by models, make up {share} of the portfolio."),
                    ("top5_holdings", "portfolio_fair_value", "Пять крупнейших позиций формируют {acc} портфеля.", "Beshta eng yirik pozitsiya portfelning {share_acc} tashkil etadi.", "The five largest holdings make up {share} of the portfolio."),
                    ("total_liabilities", "total_assets", "Обязательства составляют {acc} активов фонда.", "Majburiyatlar fond aktivlarining {share_acc} tashkil etadi.", "Liabilities make up {share} of fund assets.")):
                share = self.share_of(part, whole)
                if share is not None and share <= 100:
                    paragraph.add(Sentence(self.tr(ru, uz, en).format(acc=vocab.share_phrase(share, lang, "acc"), share=vocab.share_phrase(share, lang),
                                                                         share_acc=vocab.share_phrase(share, lang, "acc")), (), "share"))
            for event in (self.filing.snapshot.get("fund_record") or {}).get("subsequent_events") or []:
                effect = vocab.decimal_or_none(event.get("estimated_nav_effect_mln_uzs"))
                if event.get("code") == "PORTFOLIO_SWAP" and effect is not None:
                    amount = self.money(effect * 1000)
                    kept = not event.get("changes_reported_nav")
                    paragraph.add(Sentence(self.tr(
                        f"После отчётной даты фонд обменял часть портфеля: оценочный эффект на NAV — {amount}" + (", отчётный NAV не изменён." if kept else "."),
                        f"Hisobot sanasidan keyin fond portfelning bir qismini almashtirdi: NAVga baholangan ta’sir — {amount}" + (", hisobotdagi NAV o‘zgarmagan." if kept else "."),
                        f"After the reporting date the fund swapped part of its portfolio: the estimated effect on NAV is {amount}" + ("; the reported NAV is unchanged." if kept else ".")), (), "statement"))
            return paragraph
        equity_share = self.share_of("total_equity", "total_assets")
        if equity_share is not None and "equity_share" not in self.shares_stated:
            shift = self.share_shift("total_equity", "total_assets")
            paragraph.add(Sentence(self.tr(f"Собственный капитал составляет {vocab.share_phrase(equity_share, 'ru', 'acc')} активов{shift}.",
                                           f"O‘z kapitali aktivlarning {vocab.share_phrase(equity_share, 'uz', 'acc')} tashkil etadi{shift}.",
                                           f"Equity makes up {vocab.share_phrase(equity_share, 'en')} of total assets{shift}."), (), "share"))
        if self.family == "bank":
            loans, funds = self.value("loan_portfolio"), self.value("customer_funds")
            if loans and funds and funds > 0:
                if loans > funds:
                    paragraph.add(Sentence(self.tr(f"Кредитный портфель превышает средства клиентов {vocab.times_capped(loans / funds, 'ru')}.",
                                                   f"Kredit portfeli mijozlar mablag‘laridan {vocab.times_capped(loans / funds, 'uz')} ko‘p.",
                                                   f"The loan portfolio exceeds customer funds {vocab.times_capped(loans / funds, 'en')}."), (), "ratio"))
                else:
                    paragraph.add(Sentence(self.tr(f"Кредитный портфель составляет {vocab.share_phrase(loans / funds * 100, 'ru', 'acc')} средств клиентов.",
                                                   f"Kredit portfeli mijozlar mablag‘larining {vocab.share_phrase(loans / funds * 100, 'uz', 'acc')} tashkil etadi.",
                                                   f"The loan portfolio equals {vocab.share_phrase(loans / funds * 100, 'en')} of customer funds."), (), "ratio"))
            liquid = [self.value(code) for code in ("cash", "central_bank_balances", "due_from_banks")]
            if funds and funds > 0 and all(item is not None for item in liquid):
                share = sum(liquid) / funds * 100
                if share <= 100:
                    paragraph.add(Sentence(self.tr(f"Денежные средства и остатки в ЦБ и других банках покрывают {vocab.share_phrase(share, 'ru', 'acc')} средств клиентов.",
                                                   f"Pul mablag‘lari hamda Markaziy bank va boshqa banklardagi qoldiqlar mijozlar mablag‘larining {vocab.share_phrase(share, 'uz', 'acc')} qoplaydi.",
                                                   f"Cash and balances with the central bank and other banks cover {vocab.share_phrase(share, 'en')} of customer funds."), (), "share"))
            reserves = self.share_of("loan_reserves", "loan_portfolio")
            if reserves is not None and reserves < Decimal("0.05"):
                # GRBK: 0.4 bn against 1.67 trn would print «0%».
                paragraph.add(Sentence(self.tr("Резервы по кредитам составляют менее 0,1% кредитного портфеля.",
                                               "Kredit zaxiralari kredit portfelining 0,1% dan kamini tashkil etadi.",
                                               "Loan-loss reserves are below 0.1% of the loan portfolio."), (), "share"))
            elif reserves is not None and reserves <= 100:
                paragraph.add(Sentence(self.tr(f"Резервы по кредитам равны {vocab.share_percent(reserves, 'ru')} кредитного портфеля.",
                                               f"Kredit zaxiralari kredit portfelining {vocab.share_percent(reserves, 'uz')}iga teng.",
                                               f"Loan-loss reserves equal {vocab.share_percent(reserves, 'en')} of the loan portfolio."), (), "share"))
        elif self.family == "insurance":
            ceded = self.share_of("reinsurer_share_in_reserves", "gross_insurance_reserves")
            if ceded is not None and ceded <= 100:
                paragraph.add(Sentence(self.tr(f"На перестраховщиков приходится {vocab.share_phrase(ceded, 'ru')} страховых резервов.",
                                               f"Sug‘urta zaxiralarining {vocab.share_phrase(ceded, 'uz')} qayta sug‘urtalovchilarga to‘g‘ri keladi.",
                                               f"Reinsurers carry {vocab.share_phrase(ceded, 'en')} of insurance reserves."), (), "share"))
            reserves = self.share_of("net_insurance_reserves", "total_liabilities")
            if reserves is not None and reserves <= 100:
                paragraph.add(Sentence(self.tr(f"Чистые страховые резервы формируют {vocab.share_phrase(reserves, 'ru', 'acc')} обязательств.",
                                               f"Sof sug‘urta zaxiralari majburiyatlarning {vocab.share_phrase(reserves, 'uz', 'acc')} tashkil etadi.",
                                               f"Net insurance reserves make up {vocab.share_phrase(reserves, 'en')} of liabilities."), (), "share"))
        else:
            liabilities, equity = self.value("total_liabilities"), self.value("total_equity")
            client = CLIENT_LIABILITIES.get(self.filing.template)
            held = self.value(client) if client else None
            own = ""
            if held is not None and liabilities and liabilities > 0 and 0 < held <= liabilities:
                # An exchange's participants' money is held for them, not owed
                # as its debt: it is stated, then left out of the leverage.
                paragraph.add(Sentence(self.tr(f"Средства участников торгов составляют {vocab.share_phrase(held / liabilities * 100, 'ru', 'acc')} обязательств.",
                                               f"Savdo ishtirokchilari mablag‘lari majburiyatlarning {vocab.share_phrase(held / liabilities * 100, 'uz', 'acc')} tashkil etadi.",
                                               f"Trading participants' funds make up {vocab.share_phrase(held / liabilities * 100, 'en')} of liabilities."), (), "share"))
                liabilities -= held
                own = self.tr("Без них на", "Ularsiz har", "Without them, each")
            # Below a tenth of a sum the ratio rounds to nothing; the equity share says it.
            if liabilities is not None and equity and equity > 0 and Decimal("0.1") <= liabilities / equity < 100:
                ratio = vocab._plain(liabilities / equity, 1 if liabilities / equity < 10 else 0, lang)
                lead = own or self.tr("На", "Har", "Each")
                paragraph.add(Sentence(self.tr(f"{lead} каждый сум капитала приходится {ratio} сум обязательств.",
                                               f"{lead} bir so‘m kapitalga {ratio} so‘m majburiyat to‘g‘ri keladi.",
                                               f"{lead} sum of equity carries {ratio} sum of liabilities."), (), "ratio"))
            cash, current = self.value("cash"), self.value("current_liabilities")
            if cash is not None and current and current > 0:
                if cash >= current:
                    paragraph.add(Sentence(self.tr(f"Денежные средства превышают текущие обязательства {vocab.times_capped(cash / current, 'ru')}.",
                                                   f"Pul mablag‘lari joriy majburiyatlardan {vocab.times_capped(cash / current, 'uz')} ko‘p.",
                                                   f"Cash exceeds current liabilities {vocab.times_capped(cash / current, 'en')}."), (), "ratio"))
                else:
                    paragraph.add(Sentence(self.tr(f"Денежные средства покрывают {vocab.share_phrase(cash / current * 100, 'ru', 'acc')} текущих обязательств.",
                                                   f"Pul mablag‘lari joriy majburiyatlarning {vocab.share_phrase(cash / current * 100, 'uz', 'acc')} qoplaydi.",
                                                   f"Cash covers {vocab.share_phrase(cash / current * 100, 'en')} of current liabilities."), (), "share"))
        for code in ("total_liabilities", "total_equity"):
            if code not in self.described and len(paragraph.sentences) < 5:
                self.change(paragraph, code, driver=True)
        retained, equity = self.value("retained_earnings"), self.value("total_equity")
        if retained is not None and equity and equity > 0:
            share = retained / equity * 100
            if 5 <= share <= 100:
                paragraph.add(Sentence(self.tr(f"Нераспределённая прибыль формирует {vocab.share_phrase(share, 'ru', 'acc')} собственного капитала.",
                                               f"Taqsimlanmagan foyda o‘z kapitalining {vocab.share_phrase(share, 'uz', 'acc')} tashkil etadi.",
                                               f"Retained earnings make up {vocab.share_phrase(share, 'en')} of equity."), (), "share"))
            elif retained < 0:
                paragraph.add(Sentence(self.tr(f"В капитале накоплен непокрытый убыток {self.money(-retained)}.",
                                               f"Kapitalda {self.money(-retained)} qoplanmagan zarar to‘plangan.",
                                               f"Equity carries an accumulated deficit of {self.money(-retained)}."), (), "level"))
        if self.family == "bank":
            pace = self.pace("loan_portfolio", "customer_funds")
            if pace:
                paragraph.add(pace)
        return paragraph

    def risks(self):
        """Up to three points, only from signals that fired; none — no block."""
        paragraph = Paragraph(self.lang)
        seen_codes, seen_lines = set(), set()
        signals = sorted([*self.hard_flags(), *self.assessment.negatives],
                         key=lambda s: RISK_PRIORITY.index(s["code"]) if s["code"] in RISK_PRIORITY else len(RISK_PRIORITY))
        for signal in signals:
            code = signal["code"]
            text = self.risk_text(signal)
            if not text or code in seen_codes or signal["metric_code"] in seen_lines or len(paragraph.sentences) >= 3:
                continue
            seen_codes.add(code)
            seen_lines.add(signal["metric_code"])
            paragraph.add(Sentence(self.tr(*text).format(**self.risk_values(signal)), (), "risk", evaluative=True))
        return paragraph

    def hard_flags(self):
        """The red flags that set «требует внимания»; capping risks are among the negatives."""
        return [flag for flag in self.assessment.red_flags if flag.get("effect", "attention") == "attention"]

    def risk_text(self, signal):
        """The sentence for a fired signal, in the variant its figures call for."""
        code = signal["code"]
        if code == "profit_quality" and self.filing.quality.get("driver") == "FX-driven":
            share = vocab.decimal_or_none(signal.get("share"))
            return RISK_TEXT["fx_exceeds_pretax"] if share is not None and share >= 100 else RISK_TEXT["fx_share_of_pretax"]
        if code.endswith("_outpace_revenue") and self.move("revenue").get("direction") == "down":
            # «Быстрее выручки» of a line that grows while revenue falls
            # compares paces of opposite sign (KASU, UZHM).
            return RISK_TEXT.get(code.replace("_outpace_revenue", "_against_falling_revenue"))
        return RISK_TEXT.get(code)

    def risk_values(self, signal):
        share = signal.get("share")
        source = vocab.pick(self.lang, *PROFIT_SOURCES.get(self.filing.quality.get("driver"), PROFIT_SOURCES["FX-driven"]))
        fx = vocab.decimal_or_none(self.filing.quality.get("net_fx_result_current"))
        return {"share": vocab.share_phrase(share, self.lang, "acc") if share is not None else "",
                "share_nom": vocab.share_phrase(share, self.lang) if share is not None else "",
                "amount": self.money(fx) if fx is not None else "", "source": source,
                **{key: self.money(self.value(code)) if self.value(code) is not None else ""
                   for key, code in (("provisions", "credit_loss_provisions"), ("other", "other_noninterest_income"))}}

    def footnote(self):
        snapshot = self.filing.snapshot
        # The date the balance comparison really stands at — the end of the
        # previous quarter for most bank forms — not 1 January by assumption.
        dates = sorted({self.comparison_date(c) for c in self.facts if self.basis(c) == "opening" and self.base(c) is not None} - {None})
        opening_date = ", ".join(vocab.balance_date(date, self.lang) for date in dates) or \
            vocab.balance_date(f"{self.filing.year - 1}-12-31", self.lang)
        previous = snapshot.get("previous_comparable_period")
        previous_text = period_name(previous, self.lang) if previous else None
        standard = {"nsbu": self.tr("НСБУ", "BHMS", "NSBU"), "ifrs": self.tr("МСФО", "MHXS", "IFRS")}.get(self.filing.standard, self.filing.standard.upper())
        scope = {"consolidated": self.tr("консолидированная отчётность", "konsolidatsiyalangan hisobot", "consolidated statements")}.get(
            snapshot.get("scope"), self.tr("отдельная отчётность", "alohida hisobot", "separate statements"))
        has_opening = any(self.basis(c) == "opening" and self.base(c) is not None for c in self.facts)
        has_previous = any(self.basis(c) == "previous" and self.base(c) is not None for c in self.facts)
        parts = []
        if has_opening:
            parts.append(self.tr(f"баланс — с {opening_date}", f"balans — {opening_date} bilan", f"balance sheet against {opening_date}"))
        if has_previous and previous_text:
            prior_year = str(previous)[:4]
            parts.append(self.tr(f"результаты — с тем же периодом {prior_year} года", f"natijalar — {prior_year}-yilning shu davri bilan", f"results against the same period of {prior_year}"))
        if parts:
            compared = self.tr("Сравнение: ", "Taqqoslash: ", "Compared: ") + "; ".join(parts) + "."
        else:
            compared = self.tr("Сопоставимого периода в отчётах эмитента нет; текст — срез на отчётную дату.",
                               "Emitent hisobotlarida taqqoslanadigan davr yo‘q; matn hisobot sanasidagi holatni aks ettiradi.",
                               "The issuer's filings have no comparable period; the text is a snapshot at the reporting date.")
        sources = snapshot.get("comparison_sources") or {}
        fallback = [period_name(item, self.lang, "acc") for item in (sources.get("previous_fallback"), sources.get("opening_fallback")) if item]
        notes = [compared]
        fallback = list(dict.fromkeys(fallback))
        if len(fallback) == 1:
            notes.append(self.tr(f"Сравнительные данные взяты из отчёта за {fallback[0]}.",
                                 f"Taqqoslama ma’lumotlar {fallback[0]} hisobotidan olingan.",
                                 f"Comparative figures come from the {fallback[0]} filing."))
        elif fallback:
            notes.append(self.tr(f"Сравнительные данные взяты из отчётов за {fallback[0]} и за {fallback[1]}.",
                                 f"Taqqoslama ma’lumotlar {fallback[0]} va {fallback[1]} hisobotlaridan olingan.",
                                 f"Comparative figures come from the {fallback[0]} and {fallback[1]} filings."))
        notes.append(self.tr(f"{standard}, {scope}. Причины изменений можно подтвердить только примечаниями к отчётности.",
                             f"{standard}, {scope}. O‘zgarishlar sababini faqat hisobotga izohlar tasdiqlaydi.",
                             f"{standard}, {scope}. The causes of the changes can only be confirmed by the notes to the statements."))
        if self.filing.template == "commodity_exchange":
            notes.append(self.tr("Денежные средства биржи могут включать средства клиентов.",
                                 "Birja pul mablag‘lari mijozlar mablag‘larini ham o‘z ichiga olishi mumkin.",
                                 "The exchange's cash may include client funds."))
        if self.family == "fund":
            notes.append(self.tr("Цена/NAV не рассчитывается до сверки количества и номинала акций.",
                                 "Aksiyalar soni va nominali tekshirilguncha narx/NAV hisoblanmaydi.",
                                 "Price/NAV is not calculated until the share count and nominal are reconciled."))
        if self.family == "bank":
            notes.append(self.tr("Нормативы ЦБ по этим данным не рассчитываются.",
                                 "Markaziy bank normativlari bu ma’lumotlar bo‘yicha hisoblanmaydi.",
                                 "Central bank prudential ratios are not calculated from these data."))
        return Sentence(" ".join(notes), (), "footnote")


PROFIT_SOURCES = {"FX-driven": ("курсовыми разницами", "kurs farqlari", "exchange differences"),
                  "unrealized_revaluation": ("нереализованной переоценкой", "realizatsiya qilinmagan qayta baholash", "unrealised revaluation")}

# Which signal speaks for a line when several fired on it.
RISK_PRIORITY = ("negative_equity", "loss_consumes_equity", "net_loss", "negative_operating_result", "net_income_decline",
                 "profit_quality", "provisions_offset_by_other_income", "revenue_decline", "operating_income_decline", "receivables_outpace_revenue",
                 "inventories_outpace_revenue", "liabilities_outpace_equity", "claims_outpace_premiums")

RISK_TEXT = {
    "negative_equity": ("Собственный капитал отрицательный: обязательства превышают активы — это красный флаг для кредиторов и акционеров.",
                        "O‘z kapitali manfiy: majburiyatlar aktivlardan ko‘p — bu kreditorlar va aksiyadorlar uchun qizil bayroq.",
                        "Equity is negative: liabilities exceed assets — a red flag for creditors and shareholders."),
    "loss_consumes_equity": ("Убыток за период съел {share} собственного капитала; важно, остановится ли его рост в следующем отчёте.",
                             "Davr zarari o‘z kapitalining {share} yeb qo‘ydi; keyingi hisobotda uning o‘sishi to‘xtashi muhim.",
                             "The period's loss consumed {share} of equity; watch whether it stops growing in the next filing."),
    "net_loss": ("Период закрыт с убытком: смотреть, вернётся ли компания к прибыли в следующем отчёте.",
                 "Davr zarar bilan yopildi: keyingi hisobotda kompaniya foydaga qaytishini kuzatish kerak.",
                 "The period closed at a loss: watch whether the company returns to profit in the next filing."),
    "negative_operating_result": ("Основная деятельность убыточна: смотреть, покроет ли маржа расходы в следующем квартале.",
                                  "Asosiy faoliyat zararli: keyingi chorakda marja xarajatlarni qoplashini kuzatish kerak.",
                                  "Core operations are loss-making: watch whether the margin covers costs next quarter."),
    "net_income_decline": ("Чистая прибыль упала более чем на пятую часть: проверить, повторится ли спад в следующем периоде.",
                           "Sof foyda beshdan bir qismidan ko‘proq kamaydi: pasayish keyingi davrda takrorlanishini tekshirish kerak.",
                           "Net profit fell by more than a fifth: check whether the decline repeats next period."),
    "operating_income_decline": ("Операционная прибыль снижается: смотреть на динамику маржи в следующем отчёте.",
                                 "Operatsion foyda kamaymoqda: keyingi hisobotda marja dinamikasini kuzatish kerak.",
                                 "Operating profit is falling: watch the margin in the next filing."),
    "revenue_decline": ("Выручка упала более чем на пятую часть: смотреть, восстановятся ли продажи.",
                        "Tushum beshdan bir qismidan ko‘proq kamaydi: savdo tiklanishini kuzatish kerak.",
                        "Revenue fell by more than a fifth: watch whether sales recover."),
    "profit_quality": ("Прибыль во многом сформирована {source}, а не основной деятельностью: смотреть, повторится ли этот эффект.",
                       "Foyda asosan asosiy faoliyatdan emas, balki {source} hisobidan shakllangan: bu ta’sir takrorlanishini kuzatish kerak.",
                       "Profit comes largely from {source} rather than core operations: watch whether the effect repeats."),
    "provisions_offset_by_other_income": ("Отчисления в резервы ({provisions}) почти равны прочим непроцентным доходам ({other}): возможно, одна операция отражена дважды — смотреть примечания.",
                                          "Zaxiralarga ajratmalar ({provisions}) boshqa foizsiz daromadlarga ({other}) deyarli teng: bitta operatsiya ikki marta aks etgan bo‘lishi mumkin — izohlarni ko‘rish kerak.",
                                          "Credit-loss provisions ({provisions}) nearly equal other non-interest income ({other}): one operation may be booked twice — check the notes."),
    "fx_share_of_pretax": ("Чистый валютный доход — {share_nom} прибыли до налога: результат во многом зависит от курса, смотреть, повторится ли он.",
                           "Sof valyuta daromadi soliqqacha foydaning {share} tashkil etadi: natija ko‘p jihatdan valyuta kursiga bog‘liq, u takrorlanishini kuzatish kerak.",
                           "Net foreign-exchange income is {share_nom} of profit before tax: the result depends largely on the exchange rate; watch whether it repeats."),
    "fx_exceeds_pretax": ("Чистый валютный доход ({amount}) больше прибыли до налога: без него период закрылся бы убытком, результат зависит от курса.",
                          "Sof valyuta daromadi ({amount}) soliqqacha foydadan ko‘p: usiz davr zarar bilan yopilardi, natija valyuta kursiga bog‘liq.",
                          "Net foreign-exchange income ({amount}) exceeds profit before tax: without it the period would have closed at a loss; the result depends on the exchange rate."),
    "receivables_against_falling_revenue": ("Дебиторская задолженность растёт, хотя выручка снижается: смотреть, поступят ли деньги по ней.",
                                            "Tushum kamayayotgan bo‘lsa-da, debitorlik qarzi o‘smoqda: u bo‘yicha pul tushishini kuzatish kerak.",
                                            "Receivables are growing while revenue falls: watch whether they are collected."),
    "inventories_against_falling_revenue": ("Запасы растут, хотя выручка снижается: смотреть, будут ли они проданы.",
                                            "Tushum kamayayotgan bo‘lsa-da, zaxiralar o‘smoqda: ular sotilishini kuzatish kerak.",
                                            "Inventories are growing while revenue falls: watch whether they are sold."),
    "receivables_outpace_revenue": ("Дебиторская задолженность растёт быстрее выручки: часть продаж ещё не оплачена — смотреть на поступление денег.",
                                    "Debitorlik qarzi tushumdan tezroq o‘smoqda: savdoning bir qismi hali to‘lanmagan — pul tushumini kuzatish kerak.",
                                    "Receivables are growing faster than revenue: part of sales is still unpaid — watch cash collection."),
    "inventories_outpace_revenue": ("Запасы растут быстрее выручки: смотреть, будут ли они проданы.",
                                    "Zaxiralar tushumdan tezroq o‘smoqda: ular sotilishini kuzatish kerak.",
                                    "Inventories are growing faster than revenue: watch whether they are sold."),
    "liabilities_outpace_equity": ("Обязательства растут быстрее капитала — долговая нагрузка повышается.",
                                   "Majburiyatlar kapitaldan tezroq o‘smoqda — qarz yuki oshmoqda.",
                                   "Liabilities are growing faster than equity — leverage is rising."),
    "claims_outpace_premiums": ("Выплаты растут быстрее премий: смотреть на убыточность страхового портфеля.",
                                "To‘lovlar mukofotlardan tezroq o‘smoqda: sug‘urta portfelining zararliligini kuzatish kerak.",
                                "Claims are growing faster than premiums: watch the portfolio's loss ratio."),
}


# A period's name in each case it is used in.  Russian declines it: «из
# отчёта за I полугодие» (accusative after «за»), «данные I полугодия»
# (genitive); one table keeps the two from being mixed up again.
PERIOD_NAMES = {
    "ru": {"acc": {"": "{y} год", "1": "I квартал {y} года", "2": "I полугодие {y} года", "3": "9 месяцев {y} года", "4": "{y} год"},
           "gen": {"": "{y} года", "1": "I квартала {y} года", "2": "I полугодия {y} года", "3": "9 месяцев {y} года", "4": "{y} года"}},
    "uz": {"acc": {"": "{y} yil", "1": "{y} yil I chorak", "2": "{y} yil I yarim yillik", "3": "{y} yil 9 oy", "4": "{y} yil"}},
    "en": {"acc": {"": "FY {y}", "1": "Q1 {y}", "2": "H1 {y}", "3": "9M {y}", "4": "FY {y}"}},
}


def period_name(period, lang, case="gen"):
    """A period's name in a case: «I полугодие 2025 года» (acc), «I полугодия 2025 года» (gen)."""
    text = str(period or "")
    year = text[:4]
    quarter = text[5:] if "Q" in text else ""
    cases = PERIOD_NAMES.get(lang, PERIOD_NAMES["ru"])
    template = (cases.get(case) or cases["acc"]).get(quarter)
    return template.format(y=year) if template else text


def write(filing, evidence, assessment):
    """Return the six blocks and the footnote as report sections."""
    writer = Writer(filing, evidence, assessment)
    lang = writer.lang
    headline, headline_codes = writer.headline()
    verdict = writer.verdict_line()
    # The headline names its lines without amounts, so the list below may
    # still state them with the amount and the driver.
    blocks = [("key_points", writer.key_points()), ("results", writer.results()), ("balance", writer.balance()),
              ("strength", writer.strength()), ("risks", writer.risks())]
    sections = [{"id": "headline", "number": "", "title": None, "style": "lead", "text": f"{headline} {verdict}",
                 "blocks": [{"text": headline}, {"text": verdict, "style": "verdict"}],
                 "sentences": [Sentence(headline, headline_codes, "headline", percent_codes=tuple(sorted(writer.percent_stated))),
                               Sentence(verdict, (), "verdict")]}]
    number = 0
    for block_id, paragraphs in blocks:
        paragraphs = [p for p in (paragraphs if isinstance(paragraphs, list) else [paragraphs]) if p.sentences]
        if not paragraphs:
            continue
        number += 1
        title = vocab.pick(lang, *vocab.BLOCK_TITLES[block_id])
        sentences = [s for p in paragraphs for s in p.sentences]
        if block_id == "key_points":
            items = [{"text": s.text} for s in sentences]
            sections.append({"id": block_id, "number": f"{number:02d}", "title": title, "style": "list",
                             "text": " ".join(s.text for s in sentences), "blocks": items, "sentences": sentences})
        else:
            sections.append({"id": block_id, "number": f"{number:02d}", "title": title, "text": " ".join(p.text for p in paragraphs),
                             "blocks": [{"text": p.text} for p in paragraphs], "sentences": sentences})
    footnote = writer.footnote()
    sections.append({"id": "footnote", "number": "", "title": None, "style": "footnote", "text": footnote.text,
                     "blocks": [{"text": footnote.text, "style": "footnote"}], "sentences": [footnote]})
    return {"headline": headline, "verdict_line": verdict, "card_text": f"{headline} {verdict}",
            "sections": sections, "key_points": blocks[0][1].sentences}
