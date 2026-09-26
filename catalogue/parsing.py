"""Extract statement amounts and calculate filed financial ratios without I/O."""
from __future__ import annotations
from typing import Any

import re


_LABEL_PATTERNS: dict[str, list[str]] = {

    "noninterest_income": ["итого беспроцентных доходов", "всего беспроцентных доходов"],

    "revenue": ["выруч", "реализац", "revenue", "sales", "daromad", "tushum"],

    "net_income": ["чистая прибыл", "чистый доход", "чистый убыт",

                   "net income", "net profit", "net loss", "sof foyda"],

    # Commercial form №1 totals assets as "Всего по активу баланса (стр.130+390)"

    # (uz: "balans aktivi bo'yicha jami") — neither contains "итого актив".

    "total_assets": ["итого актив", "total asset", "всего актив", "jami aktiv",

                     "по активу баланса", "balans aktivi"],

    "equity": ["собственный капитал", "итого капитал", "капитал и резерв",

               "total equity", "equity", "o'z kapitali", "kapital"],

    "total_liabilities": ["итого обязательств", "всего обязательств",

                          "total liabilit", "majburiyat"],

    # Commercial NSBU balance has no single "итого обязательств" line — liabilities

    # split into long-term (стр.490) + current (стр.600); summed as a fallback.

    "lt_liabilities": ["долгосрочные обязательства"],

    "cur_liabilities": ["текущие обязательства", "краткосрочные обязательства"],

    # Товарно-материальные запасы, всего — стр.140 on the jsc form, стр.140 on the

    # insurance one (a shorter roll-up: стр.150+160). The quick ratio is the

    # current ratio less this line, so it is read from the same balance rather

    # than left to the indicator feed, which publishes neither for 39 issuers.

    "inventories": ["товарно-материальные запасы", "tovar-moddiy zaxira",

                    "tovar-modiy zaxira"],

    # Валовая прибыль (форма №2): "Валовая прибыль (убыток) от реализации ..."

    "gross_profit": ["валовая прибыл", "валовой доход", "валовая выручка",

                     "gross profit", "yalpi foyda"],

    # Наличность в кассе (форма №1, баланс) = «Денежные средства на расчетном

    # счете (5100)», стр. 340 в форме АО / 430 в страховой форме — операционный

    # остаток на банковском счете, а НЕ свод «Денежные средства, всего», куда

    # входят касса (5000), валютные счета (5200) и эквиваленты (5500/5600/5700).

    "cash_account": ["расчетном счете", "расчётном счёте", "расчетном счёте",

                     "расчетный счет", "расчётный счёт", "(5100)",

                     "hisob-kitob schyot", "settlement account"],

    # Свод — запасной вариант для форм без строки 5100 (банковская форма её не

    # публикует: там «Кассовая наличность и другие платежные документы»).

    "cash": ["денежные средства", "денежных средств", "наличность", "касса",

             "cash and cash", "cash equivalent", "pul mablag", "kassa"],

    # Операционный доход = прибыль (убыток) от основной деятельности (форма №2,

    # стр. 100). Паттерны требуют "прибыль/убыток", чтобы не поймать стр. 090

    # "Прочие доходы от основной деятельности".

    "operating_income": ["прибыль (убыток) от основной деятельности",

                         "прибыль от основной деятельности",

                         "убыток от основной деятельности",

                         "операционная прибыл", "операционный доход",

                         "operating income", "operating profit"],

    # The bank form has no «выручка» line at all. Its top line, and the one the

    # reconciler (openinfo_reconcile) already serves as bank revenue, is total

    # interest income — «Всего процентные доходы» on the Excel form, «Итого

    # процентных доходов» in the structured JSON. A second-tier key: consulted

    # only when "revenue" itself finds nothing, so no commercial form can reach it.

    "revenue_bank": ["всего процентные доходы", "всего процентных доходов",

                     "итого процентных доходов", "итого процентные доходы",

                     "total interest income"],

    # The bank income statement has no «валовая прибыль» or «прибыль от основной

    # деятельности» either, but it files the same tiers under its own names:

    #   «6. ЧИСТЫЙ ДОХОД ДО ОПЕРАЦИОННЫХ РАСХОДОВ»   — income after funding

    #     costs, before running costs: the gross-profit tier;

    #   «9. ЧИСТАЯ ПРИБЫЛЬ ДО УПЛАТЫ НАЛОГОВ …»      — line 6 less operating

    #     expenses and non-credit losses: the operating-result tier.

    # So the derived «операционные расходы» (gross − operating) reproduces the

    # form's own «з. Итого операционных расходов» exactly when line 8 is nought

    # (HMKB 2022: 1 735 075 932 − 903 084 643 = 831 991 289, the filed line 7з).

    # Second-tier keys like revenue_bank: consulted only when the commercial

    # patterns found nothing, so no jsc/insurance form can reach them.

    "gross_profit_bank": ["чистый доход до операционных расходов",

                          "чистые доходы до операционных расходов",

                          "net income before operating expenses"],

    "operating_income_bank": ["чистая прибыль до уплаты налогов",

                              "чистая прибыль (убытки) до уплаты налогов",

                              "net profit before taxes",

                              "net profit before taxes and other adjustments"],

    "operating_expenses_bank": ["итого операционных расходов",

                                "total operating expenses"],

    "operating_expenses_jsc": ["расходы периода", "period expenses"],

}


_LABEL_EXCLUSIONS: dict[str, list[str]] = {
    "net_income": ["до операционных", "до уплаты", "до налогообложения",
                   "до введения", "до оценки", "before tax", "qadar"],
}


def _row_value(nums: list, strict_period: bool = False) -> float | None:

    """Pick the reporting-period amount from a parsed row's numeric cells.



    Several NSBU Excel layouts occur in the wild, but they all lay their period

    columns out OLDEST → NEWEST left-to-right, exactly as openinfo exports them:

      * bank/vertical forms → ``[amount]`` (single period; the line number lives

        in the label) or ``[prior, current]`` (begin-of-year | end-of-period);

      * commercial form №1 (balance) → ``[line_code, begin, end]``

        (header: «На начало отчётного периода» | «На конец отчётного периода»);

      * commercial form №2 (fin. results) → ``[line_code, prev_income,

        prev_expense, cur_income, cur_expense]``

        (header: «За соответствующий период прошлого года» | «За отчётный период»).



    The reporting-period figure is therefore the LATER column-group, never the

    first. A naive "first numeric after the code" grab returns last year's / the

    opening balance — the exact off-by-one-period bug this guards against.



    We drop a leading cell that is clearly a line code (a small integer, either

    dwarfed >100× by the value after it or sitting ahead of ≥2 more cells), then,

    when the remaining cells split into two equal period halves, read the first

    non-zero amount from the SECOND (reporting) half. We fall back to the first

    half only when the reporting half is entirely zero (e.g. a period that has

    not been reported yet).

    """

    vals: list[float] = []

    for n in nums:

        try:

            f = float(n)

        except (TypeError, ValueError):

            continue

        if f != f:  # NaN (blank cell captured as NaN) — skip so it can't shift the split

            continue

        vals.append(f)

    if not vals:

        return None

    # Detect a leading NSBU line-code cell (010, 030, 320 …): a small integer.

    # In the multi-column commercial layout (code + period pairs) the first cell

    # is ALWAYS the code, so drop it even when the amounts are zero (e.g. a fund

    # with no revenue → [10,0,0,0,0], must not return "10"). In a 2-cell layout

    # it's ambiguous, so only drop when the code is dwarfed by the value after it.

    first_is_code = (

        len(vals) >= 2

        and vals[0].is_integer()

        and 0 < vals[0] < 10000

        and (len(vals) >= 3 or abs(vals[1]) > abs(vals[0]) * 100)

    )

    rest = vals[1:] if first_is_code else vals

    # Bank income statements have one signed amount. Zero is a published value,

    # not a missing period: BRBN's 2024 gross profit and 2021/2023 pre-tax profit

    # were all lost by the generic first-nonzero selection below.

    if len(rest) == 1:

        return rest[0]



    def _first_nonzero(seq: list[float]) -> float | None:

        for v in seq:

            if abs(v) > 0.0001:

                return v

        return None



    def _half_value(half: list[float]) -> float | None:

        # A 2-cell half in the commercial form №2 layout is an income|expense

        # COLUMN PAIR, not two candidate values: a loss sits as a positive

        # number in the expense column. Reading "first non-zero" there returns

        # a loss with a plus sign — so read the pair as income − expense.

        if len(half) == 2:

            income, expense = half

            if abs(income) <= 0.0001 and abs(expense) <= 0.0001:

                return None

            return income - expense

        return _first_nonzero(half)



    # Period columns run oldest → newest, so the reporting period is the second

    # half of the value cells (form №2 prior|current income/expense pairs; form №1

    # and bank forms begin|end / prior|current). Prefer it; fall back if it's zero.

    if len(rest) >= 2 and len(rest) % 2 == 0:

        reporting = _half_value(rest[len(rest) // 2:])

        if reporting is not None:

            return reporting

        # A single balance ACCOUNT can legitimately end the period at zero — a

        # settlement account emptied, a loan repaid — and there the fallback would

        # publish the OPENING balance as the closing one. Only a total is safe to

        # fall back on, so the caller says which it is asking for.

        if strict_period:

            return 0.0

        return _half_value(rest[:len(rest) // 2])

    return _first_nonzero(rest)


def _strict_balance_row_value(row: dict) -> float | None:
    """Explicit closing column; neither blank nor zero falls back to opening."""
    from financial_analysis.sector_numbers import decimal, number
    original = row.get("source_cells")
    if original:
        candidates = [(i, decimal(v)) for i, v in enumerate(original)]
        code_index = next((i for i, v in candidates if v is not None and v == int(v) and 0 < v < 2000), None)
        if code_index is None or len(original) <= code_index + 2:
            return None
        return number(original[code_index + 2])
    nums = row.get("numeric_values") or []
    return number(nums[-1]) if len(nums) in (2, 3) else None


def _extract_metric(rows: list[dict], key: str, strict_period: bool = False) -> float | None:

    patterns = _LABEL_PATTERNS.get(key, [])

    excludes = _LABEL_EXCLUSIONS.get(key, ())

    for row in rows:

        label = str(row.get("label") or "").lower()

        if any(p in label for p in patterns):

            if any(x in label for x in excludes):

                continue

            if key == "operating_expenses_jsc":

                v = _commercial_period_expenses(row)

            else:

                v = _strict_balance_row_value(row) if strict_period else _row_value(row.get("numeric_values") or [])

            if v is not None:

                return v

    return None


def _squash(label: Any) -> str:
    return re.sub(r"\s+", "", str(label or "").lower().replace("ё", "е"))


_LIABILITIES_SECTION_FORMULAS = ("490+600", "730+930")


_CURRENT_ASSETS_SECTION_FORMULAS = ("140+190+200+210+320+370+380",
                                    "140+170+180+190+410+460+470")


_INSURANCE_EQUITY_FORMULAS = ("500+510+520-530+540+550+560",)


_INSURANCE_GROSS_RESERVE_FORMULAS = ("590+600+610+620+630+640+650+660",)


_INSURANCE_REINSURER_SHARE_FORMULAS = ("680+690+700+710",)


_INSURANCE_NET_RESERVE_FORMULAS = ("580-670",)


def _extract_formula_total(rows: list[dict], formulas: tuple[str, ...]) -> float | None:
    """Read a reporting-date total identified by its NSBU line formula."""
    for row in rows:
        squashed = _squash(row.get("label"))
        if any(formula in squashed for formula in formulas):
            value = _strict_balance_row_value(row)
            if value is not None:
                return value
    return None


def _extract_current_assets(rows: list[dict]) -> float | None:
    """«Итого по разделу II» of the ASSET side — the current-assets subtotal."""
    for row in rows:
        squashed = _squash(row.get("label"))
        if "итого" in squashed and any(f in squashed for f in _CURRENT_ASSETS_SECTION_FORMULAS):
            value = _row_value(row.get("numeric_values") or [])
            if value is not None:
                return value
    return None


def _extract_liabilities_total(rows: list[dict], strict_period: bool = False) -> float | None:
    """The obligations total the issuer itself published, if the form prints one.

    Preferred over re-adding «Долгосрочные обязательства, всего» and «Текущие
    обязательства, всего»: where the two disagree it is the published total that
    satisfies assets = equity + liabilities, because an unfilled or stale part
    cell is what the parts carry (KVTS 2026Q2, MIQE 2026Q2, Uzum Sarmoya 2026Q2 —
    the last of which had NO obligations at all on the board).
    """
    for row in rows:
        squashed = _squash(row.get("label"))
        if "итого" in squashed and any(f in squashed for f in _LIABILITIES_SECTION_FORMULAS):
            v = _strict_balance_row_value(row) if strict_period else _row_value(row.get("numeric_values") or [])
            if v is not None:
                return v
    return None


_CASH_ACCOUNT_CODES = ("(5000)", "(5100)", "(5200)", "(5500")


def _extract_cash(rows: list[dict]) -> float | None:
    """«Наличность в кассе» — the settlement account (5100), where it is filled in.

    A zero on стр.5100 beside a non-zero sibling account is a real balance: the
    company ended the period with its operating account empty and its money in
    foreign currency or in equivalents. A zero beside siblings that are ALL zero,
    under a non-zero roll-up, is an issuer who filed only the total (AGMK 2026 Q2:
    «Денежные средства, всего» 688 238 787, every account under it at nought) —
    there is no 5100 figure in that filing, so the roll-up stands in. The bank
    form, which has no settlement-account line at all, always takes that path.
    """
    account = _extract_metric(rows, "cash_account", strict_period=True)
    if account:
        return account
    patterns = _LABEL_PATTERNS["cash_account"]
    others = [r for r in rows
              if not any(p in str(r.get("label") or "").lower() for p in patterns)]
    if account is not None:
        siblings = [_row_value(r.get("numeric_values") or [], strict_period=True)
                    for r in others
                    if any(c in str(r.get("label") or "") for c in _CASH_ACCOUNT_CODES)]
        if any(siblings):
            return account  # the breakdown is filled in; the account is simply empty
    # The roll-up (or, on the bank form, its own cash line) — never the settlement
    # account's own opening balance, which is why it is looked up without that row.
    roll_up = _extract_metric(others, "cash")
    return roll_up if roll_up is not None else account


def _gather_rows(excel_data: dict | None) -> list[dict]:
    if not excel_data:
        return []
    rows: list[dict] = []
    for sheet in (excel_data.get("sheets") or []):
        rows.extend(sheet.get("table_rows") or [])
    return rows


def extract_insurance_balance(balance_data: dict | None) -> dict[str, float | None]:
    """Extract the four-section economic balance from an insurance NSBU form.

    The published ``Итого по разделу III`` is only ordinary liabilities.  Net
    insurance reserves are a separate liability section and must be added back
    for ``assets = equity + liabilities``.  Gross reserves and the reinsurer's
    share remain separate evidence fields; neither is silently netted away.
    """
    rows = _gather_rows(balance_data)
    gross = _extract_formula_total(rows, _INSURANCE_GROSS_RESERVE_FORMULAS)
    reinsurer_share = _extract_formula_total(rows, _INSURANCE_REINSURER_SHARE_FORMULAS)
    filed_net = _extract_formula_total(rows, _INSURANCE_NET_RESERVE_FORMULAS)
    calculated_net = (
        gross - reinsurer_share
        if gross is not None and reinsurer_share is not None
        else None
    )
    net = calculated_net if calculated_net is not None else filed_net
    other_liabilities = _extract_liabilities_total(rows, strict_period=True)
    total_liabilities = (
        net + other_liabilities
        if net is not None and other_liabilities is not None
        else None
    )
    return {
        "total_assets": _extract_metric(rows, "total_assets", strict_period=True),
        "total_equity": _extract_formula_total(rows, _INSURANCE_EQUITY_FORMULAS),
        "gross_insurance_reserves": gross,
        "reinsurer_share_in_reserves": reinsurer_share,
        "net_insurance_reserves": net,
        "filed_net_insurance_reserves": filed_net,
        "other_liabilities": other_liabilities,
        "total_liabilities": total_liabilities,
    }


def compute_financial_ratios(income_data: dict | None, balance_data: dict | None) -> dict[str, Any]:

    income_rows = _gather_rows(income_data)

    balance_rows = _gather_rows(balance_data)

    all_rows = income_rows + balance_rows



    revenue = _extract_metric(income_rows or all_rows, "revenue")

    if revenue is None:

        # Bank form: no «выручка» line exists — total interest income is the

        # top line, exactly the figure the reconciler serves as bank revenue.

        revenue = _extract_metric(income_rows or all_rows, "revenue_bank")

    net_income = _extract_metric(income_rows or all_rows, "net_income")

    gross_profit = _extract_metric(income_rows or all_rows, "gross_profit")

    operating_income = _extract_metric(income_rows or all_rows, "operating_income")

    # Commercial form 2 line 040 is an income/expense pair, so the shared row

    # parser retains its expense sign. A reported current zero must not borrow

    # last year's expense and break the cumulative-quarter subtraction.

    operating_expenses = _extract_metric(income_rows or all_rows, "operating_expenses_jsc", strict_period=True)

    if operating_expenses is None:

        operating_expenses = _extract_metric(income_rows or all_rows, "operating_expenses_bank")

    if gross_profit is None:

        gross_profit = _extract_metric(income_rows or all_rows, "gross_profit_bank")

    if operating_income is None:

        operating_income = _extract_metric(income_rows or all_rows, "operating_income_bank")

    total_assets = _extract_metric(balance_rows or all_rows, "total_assets")

    equity = _extract_metric(balance_rows or all_rows, "equity")

    total_liabilities = _extract_metric(balance_rows or all_rows, "total_liabilities")

    if total_liabilities is None:

        total_liabilities = _extract_liabilities_total(balance_rows or all_rows)

    if total_liabilities is None:

        lt = _extract_metric(balance_rows or all_rows, "lt_liabilities")

        cur = _extract_metric(balance_rows or all_rows, "cur_liabilities")

        if lt is not None or cur is not None:

            total_liabilities = (lt or 0.0) + (cur or 0.0)

    insurance_balance = extract_insurance_balance(balance_data or income_data)

    if insurance_balance.get("gross_insurance_reserves") is not None:

        # Insurance liabilities are ordinary liabilities PLUS net technical

        # reserves.  The old parser exposed only section III, making UZAS Q1

        # 2026 miss 129.18bn UZS of obligations and fail its balance identity.

        total_assets = insurance_balance.get("total_assets")

        equity = insurance_balance.get("total_equity")

        total_liabilities = insurance_balance.get("total_liabilities")



    # Commercial form №1 labels its equity total only "Итого по разделу I" — the

    # same words as the assets-section total, so no label pattern can pick it out.

    # On a published balance the identity assets = equity + liabilities holds, so

    # take equity as the difference instead.

    if equity is None and total_assets is not None and total_liabilities is not None:

        equity = total_assets - total_liabilities

    cash = _extract_cash(balance_rows or all_rows)

    # The current section of the balance. openinfo's indicator feed publishes a

    # liquidity ratio for 56 of the 95 issuers on the board and an asset turnover

    # for the same 56, so those two columns and ROCE were simply blank for the

    # rest — while the balance every one of them files states the lines they are

    # built from. Read here, stored beside the headline sums, and turned into

    # coefficients at read time where the feed is silent.

    current_assets = _extract_current_assets(balance_rows or all_rows)

    current_liabilities = _extract_metric(balance_rows or all_rows, "cur_liabilities")

    inventories = _extract_metric(balance_rows or all_rows, "inventories")



    def _safe_ratio(num: float | None, den: float | None) -> float | None:

        if num is None or den is None or den == 0:

            return None

        return round(num / den * 100, 2)



    def _safe_div(num: float | None, den: float | None) -> float | None:

        if num is None or den is None or den == 0:

            return None

        return round(num / den, 4)



    metrics: dict[str, Any] = {

        "ROA": _safe_ratio(net_income, total_assets),

        "ROE": _safe_ratio(net_income, equity),

        "net_margin": _safe_ratio(net_income, revenue),

        "debt_ratio": _safe_ratio(total_liabilities, total_assets),

        "debt_to_equity": _safe_div(total_liabilities, equity),

    }



    balance_block: dict[str, Any] = {

        "assets_end": total_assets,

        "equity_end": equity,

    }

    if insurance_balance.get("gross_insurance_reserves") is not None:

        for key in (

            "gross_insurance_reserves", "reinsurer_share_in_reserves",

            "net_insurance_reserves", "other_liabilities",

        ):

            balance_block[key] = insurance_balance.get(key)



    source_rows: dict[str, Any] = {

        "revenue": revenue,

        "noninterest_income": _extract_metric(income_rows or all_rows, "noninterest_income"),

        "net_income": net_income,

        "gross_profit": gross_profit,

        "operating_income": operating_income,

        "operating_expenses": operating_expenses,

        "cash": cash,

        "total_assets": total_assets,

        "equity": equity,

        # The cache column's own name, beside the parser's historical "equity":

        # the collectors build their push rows straight off FIN_MONEY_FIELDS.

        "total_equity": equity,

        "total_liabilities": total_liabilities,

        "current_assets": current_assets,

        "current_liabilities": current_liabilities,

        "inventories": inventories,

        "gross_insurance_reserves": insurance_balance.get("gross_insurance_reserves"),

        "reinsurer_share_in_reserves": insurance_balance.get("reinsurer_share_in_reserves"),

        "net_insurance_reserves": insurance_balance.get("net_insurance_reserves"),

        "other_liabilities": insurance_balance.get("other_liabilities"),

        "balance": balance_block,

    }



    return {"metrics": metrics, "source_values": source_rows}


def _commercial_period_expenses(row: dict) -> float | None:
    """Read form 2 line 040's current income minus expense, including zero.

    Its four amount columns are prior income/expense then current income/expense.
    The strict balance reader's closing column is the prior expense here.
    Preserve source positions so an empty cell cannot shift period selection.
    """
    from financial_analysis.sector_numbers import number

    original = row.get("source_cells")
    if original:
        code_index = next((i for i, value in enumerate(original) if number(value) == 40), None)
        if code_index is None or len(original) < code_index + 5:
            return None
        income = number(original[code_index + 3])
        expense = number(original[code_index + 4])
        if income is None and expense is None:
            return None
        return (income or 0.0) - (expense or 0.0)
    nums = row.get("numeric_values") or []
    # Legacy snapshots omit source_cells. Accept only a complete form 2 pair
    # layout; shorter numeric lists cannot identify the current period safely.
    if len(nums) == 5 and number(nums[0]) == 40:
        return _row_value(nums, strict_period=True)
    return None
