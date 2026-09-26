from __future__ import annotations



from financial_corrections import correction_periods_for
from functools import partial
from typing import Any
import logging
import asyncio
import re
import reports_catalog as catalog_store




logger = logging.getLogger(__name__)


class FinancialDataUnavailable(RuntimeError):
    """The statement sources could not be assembled for this issuer."""


def duplicate_filed_years(series: dict[str, Any], periods: Any,
                          annual_years: set[str]) -> list[str]:
    """Annual periods that are another year's copy — the ones to drop.

    `catalog_financials` is written by upsert and pruned by nothing, so a filing
    once catalogued under one year and later under another leaves the first
    behind. The ghost is bit-identical to its neighbour on every filed line —
    BECM and UZHM both show 2025 and 2024 agreeing to the sum on revenue, gross
    profit, operating income, net profit, cash and liabilities, which is not
    something two trading years do — and it made the page state «Рост г/г
    0.00%» for a year that was never filed.

    What separates the ghost from the real year is the report registry: one of
    the pair has an annual filing behind it and the other does not. Measured
    across all 100 tickers, five rows match — BECM, BECMP, METQ, UZHM and UQEQ
    — and for UQEQ it is the NEWER year that is unsupported, which is why the
    rule is "keep the one with the filing" and not "keep the newest".

    Pairs where BOTH years have a filing are left alone: BNGPP 2022/2021 and
    UZNGP 2023/2022/2021 are identical too, but nothing here can say which of
    two filed years is wrong, and guessing is worse than publishing the source.
    """
    filed_money = [f for f, e in series.items() if e.get("filed") and e.get("money")]
    ordered = sorted(periods, reverse=True)
    ghosts: list[str] = []
    for a, b in zip(ordered, ordered[1:]):
        if a in ghosts or b in ghosts:
            continue
        pair = [(series[f]["values"].get(a), series[f]["values"].get(b)) for f in filed_money]
        both = [(x, y) for x, y in pair if x is not None and y is not None]
        # Three lines, not one: a single matching figure between two years is a
        # coincidence that happens, and dropping a year on it would lose data.
        if len(both) < 3 or not all(x == y for x, y in both):
            continue
        if a in annual_years and b not in annual_years:
            ghosts.append(b)
        elif b in annual_years and a not in annual_years:
            ghosts.append(a)
    return ghosts


# The income-statement lines a quarterly filing states as a RUNNING TOTAL from
# 1 January (NSBU form 2 is cumulative — a Q2 revenue is six months of revenue)
# versus the balance lines, which are a snapshot of the quarter's last day.
# The distinction decides everything below: flows are differenced into
# three-month figures, stocks are served as filed.
QUARTER_FLOW_FIELDS = {"revenue": "net_revenue", "gross_profit": "gross_profit",
                       "operating_income": "operating_income", "operating_expenses": "operating_expenses",
                       "net_income": "net_profit"}


QUARTER_STOCK_FIELDS = {"cash": "cash", "total_liabilities": "total_liabilities",
                        "total_assets": "total_assets", "total_equity": "total_equity"}


def derive_quarterly_series(cumulative: dict[str, Any],
                            annual: dict[str, Any], *,
                            issues: list[dict[str, Any]] | None = None) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Discrete three-month columns out of NSBU's cumulative quarterly filings.

    This is the standard presentation for comparing quarters — every terminal
    prints Q2 as the three months of Q2, not as «за 6 месяцев» — and it is the
    only one on which a same-quarter-last-year comparison means anything. The
    arithmetic is the one every data vendor applies to running totals:

      Q1 = the Q1 filing;  Qn = filing(Qn) − filing(Qn−1);
      Q4 = the annual filing − the nine-month filing,

    Usually the annual is the Q4 disclosure. An explicitly filed cumulative Q4
    (some banks publish one) is also accepted; a separately filed annual wins.
    A quarter whose predecessor was never filed yields no
    figure rather than a running total masquerading as three months: a six-month
    sum in a column of quarters is exactly the «full year beside a quarter»
    defect _period_months exists to stop.

    Balance-sheet lines (cash, obligations) are snapshots and pass through
    untouched; the year-end snapshot doubles as Q4's.

    Restatements can make a derived quarter negative on lines that are usually
    positive. That is faithful: the two filings really do disagree by that
    amount, and inventing a floor would hide the restatement.

    Returns (periods newest-first, {field: {period: value}}) in the store's own
    unit (thousands of UZS); the endpoint owns the scale contract, as everywhere.
    """
    from decimal import Decimal

    def difference(current: Any, previous: Any) -> float | None:
        if current is None or previous is None:
            return None
        return float(Decimal(str(current)) - Decimal(str(previous)))

    cum: dict[tuple[int, int], dict[str, Any]] = {}
    for p, fields in (cumulative or {}).items():
        m = re.fullmatch(r"(\d{4})Q([1-4])", str(p))
        # A row where every figure is zero-or-missing is an empty filing, the
        # quarterly cousin of the zero-balance-sheet annual purged above.
        if m and any(fields.get(k) for k in (*QUARTER_FLOW_FIELDS, *QUARTER_STOCK_FIELDS)):
            cum[(int(m.group(1)), int(m.group(2)))] = dict(fields)

    # THE WITNESS LINE. A running total of revenue cannot decrease — sales are
    # not returnable in the aggregate — so within one year the cumulative
    # revenue points, annual included, must form a non-decreasing chain. Where
    # they do not, one of the filings misstates its period, and differencing it
    # would print an impossible figure as a fact: TNBN's «Q1 2023» carries
    # 932 B against a 585 B half-year — three months larger than six — and the
    # subtraction served a revenue of −347 B; SQBN's empty 2024 annual (revenue
    # zero against a 8 018 B nine-month) would have made Q4 −8 T. Measured
    # fleet-wide: 14 ticker-years of 832 are inconsistent.
    #
    # The chain itself says which filing is the odd one out: keep the longest
    # non-decreasing run (preferring the later filings on a tie — the annual
    # anchors the tail, and a later filing is the better-corrected one) and
    # drop the INCOME lines of what falls outside it. The whole statement is
    # suspect, not just its revenue, so every flow goes; the balance snapshot
    # stays — it is a statement of some real date even when mislabelled.
    def keep_consistent(points: list[tuple[int, float]]) -> set[int]:
        n = len(points)
        best: tuple[int, tuple[int, ...]] = (0, ())
        for mask in range(1 << n):
            idx = tuple(i for i in range(n) if mask >> i & 1)
            vals = [points[i][1] for i in idx]
            if any(b < a for a, b in zip(vals, vals[1:])):
                continue
            best = max(best, (len(idx), idx))
        return {points[i][0] for i in best[1]}

    annual_q4_ok: dict[int, bool] = {}
    for year in {y for y, _ in cum}:
        a_rev = ((annual or {}).get(str(year)) or {}).get("revenue")
        points = [(q, cum[(year, q)]["revenue"]) for q in (1, 2, 3)
                  if (year, q) in cum and cum[(year, q)].get("revenue") is not None]
        if a_rev is not None:
            points.append((4, a_rev))
        annual_q4_ok[year] = True
        if len(points) < 2:
            continue
        for q in {q for q, _ in points} - keep_consistent(points):
            if issues is not None:
                issues.append({"period": f"{year}Q{q}", "code": "INCONSISTENT_CUMULATIVE_INCOME",
                               "fields": list(QUARTER_FLOW_FIELDS.values())})
            if q == 4:
                annual_q4_ok[year] = False
            else:
                for src in QUARTER_FLOW_FIELDS:
                    cum[(year, q)].pop(src, None)

    series: dict[str, dict[str, Any]] = {}
    periods: set[str] = set()

    def put(name: str, year: int, q: int, value: Any) -> None:
        if value is None:
            return
        period = f"{year}Q{q}"
        series.setdefault(name, {})[period] = value
        periods.add(period)

    for (year, q), fields in cum.items():
        for src, name in QUARTER_FLOW_FIELDS.items():
            v = fields.get(src)
            if v is None:
                continue
            prev = 0.0 if q == 1 else cum.get((year, q - 1), {}).get(src)
            if prev is None and issues is not None:
                issues.append({"period": f"{year}Q{q}", "code": "MISSING_COMPARATIVE_INPUT",
                               "field": name, "required_period": f"{year}Q{q - 1}"})
            put(name, year, q, difference(v, prev))
        for src, name in QUARTER_STOCK_FIELDS.items():
            put(name, year, q, fields.get(src))

    # Q4 exists only where the year filed quarterlies at all: synthesising a
    # lone Q4 for an annual-only issuer would dress the annual view up as a
    # quarterly one.
    for year in {y for y, _ in cum}:
        a = (annual or {}).get(str(year))
        if not a:
            continue
        # An annual the witness rejected contributes NOTHING — its balance is
        # as unsupported as its income (SQBN 2024 files zeros on both sides,
        # and a 0 in the Q4 cash column beside trillions reads as a figure).
        if not annual_q4_ok.get(year, True):
            continue
        q3 = cum.get((year, 3), {})
        for src, name in QUARTER_FLOW_FIELDS.items():
            v, nine = a.get(src), q3.get(src)
            if v is not None and nine is None and issues is not None:
                issues.append({"period": f"{year}Q4", "code": "MISSING_COMPARATIVE_INPUT",
                               "field": name, "required_period": f"{year}Q3"})
            put(name, year, 4, difference(v, nine))
        for src, name in QUARTER_STOCK_FIELDS.items():
            put(name, year, 4, a.get(src))

    return sorted(periods, reverse=True), series


def _fill_equity_by_identity(series: dict[str, dict[str, Any]]) -> None:
    """Close the Капитал holes the sources leave, by the balance identity.

    On every published balance assets = liabilities + equity, so a period that
    states the first two states the third — the 2015-style «—» beside two
    filled lines is a presentation gap, not a missing fact (customer,
    2026-08-16). Only periods with no equity of their own are filled: a figure
    the feed or a filing carries always wins, including a filed zero.
    """
    assets = (series.get("total_assets") or {}).get("values", {})
    liab = (series.get("total_liabilities") or {}).get("values", {})
    entry = series.get("total_equity")
    have = (entry or {}).get("values", {})
    gap = {p: assets[p] - liab[p] for p in assets if p in liab and p not in have}
    if not gap:
        return
    if entry is None:
        entry = series["total_equity"] = {"unit": "UZS", "money": True,
                                          "derived": True, "values": {}}
    entry["values"].update(gap)


async def financial_passport(ticker: str, period: str, field: str, form: str='NSBU', scope: str | None=None) -> dict[str, Any]:
    """Evidence passport for a value shown in the issuer financial table.

    The endpoint deliberately returns an explicit state for calculated and
    legacy values.  A number without a safe report link is not presented as if
    it had one merely because a report exists for the same issuer and year.
    """
    form = str(form or 'NSBU').strip().upper()
    if form not in {'NSBU', 'MSFO'}:
        raise ValueError('form must be NSBU or MSFO')
    if scope not in {None, 'consolidated', 'separate'} or (scope is not None and form != 'MSFO'):
        raise ValueError('scope must be consolidated or separate and requires MSFO')
    loop = asyncio.get_running_loop()
    if scope is not None:
        from financial_ingestion.publication import passport
        result = await loop.run_in_executor(None, partial(passport, ticker, period, field, scope=scope))
    else:
        result = await loop.run_in_executor(None, partial(catalog_store.get_financial_value_passport, ticker, period, field, form))
    return {'ok': True, 'ticker': ticker.strip().upper(), 'contract_version': 'financial-passport-v1', **result}


async def financial_series(ticker: str, freq: str='annual', form: str='NSBU', scope: str | None=None) -> dict[str, Any]:
    """The issuer's annual series — one row per indicator, one column per year.

    Reads the `financial_indicators` fact store, which is where openinfo's
    published indicators and the NSBU-derived ones both land, and which already
    holds nine to eleven years for most issuers. It was serving nobody: the
    Финансы tab showed a single period's ratios out of the reports cache.

    **Absolute sums are scaled here, coefficients are not.** The store keeps
    money in thousands of UZS (see NSBU_THOUSANDS_UZS); a raw read would print a
    10.5-trillion revenue as ten billion, beside a market cap in full UZS on the
    same page. That is the ~1000x class of defect this contract exists to stop,
    so the field list is pinned by a test.

    A period can carry the same field twice — openinfo publishes an indicator
    and the NSBU pass derives it. The newest write wins, which is the derived
    one when it exists: it is computed from the filing this platform parsed.
    """
    ticker = ticker.strip().upper()
    standard = str(form or 'NSBU').strip().upper()
    if standard not in {'NSBU', 'MSFO'}:
        raise ValueError('form must be NSBU or MSFO')
    if scope not in {None, 'consolidated', 'separate'} or (scope is not None and standard != 'MSFO'):
        raise ValueError('scope must be consolidated or separate and requires MSFO')
    loop = asyncio.get_running_loop()
    scope_info = {}
    if standard == 'MSFO':
        from financial_ingestion.publication import scopes as published_scopes, series as snapshot_series, snapshots as published_snapshots
        available_scopes = await loop.run_in_executor(None, partial(published_scopes, ticker))
        default_snapshots = await loop.run_in_executor(None, partial(published_snapshots, ticker)) if scope is None else []
        scope_info = {'scope': scope or (default_snapshots[0]['scope'] if default_snapshots else None), 'available_scopes': available_scopes}
        if scope is not None:
            quarterly = str(freq or '').lower().startswith('q')
            values = await loop.run_in_executor(None, partial(snapshot_series, ticker, quarterly=quarterly, scope=scope)) or {}
            entries = {}
            gaps = []
            for period, fields in values.items():
                for field, value in fields.items():
                    name = {'net_income': 'net_profit', 'revenue': 'net_revenue'}.get(field, field)
                    entries.setdefault(name, {'unit': 'UZS', 'money': True, 'filed': True, 'values': {}})['values'][period] = value * 1000
                missing = [f for f in ('total_assets', 'total_equity', 'total_liabilities', 'net_income', 'interest_income') if fields.get(f) is None]
                if missing:
                    gaps.append({'period': period, 'code': 'MISSING_FINANCIAL_FIELDS', 'fields': missing})
            from financial_ingestion.store import public_status
            ingestion = await loop.run_in_executor(None, partial(public_status, ticker))
            return {'ok': True, 'ticker': ticker, 'currency': 'UZS', 'standard': standard, 'freq': 'quarterly' if quarterly else 'annual', **scope_info, 'period_basis': 'cumulative_ytd' if quarterly else 'annual', 'periods': sorted(values, reverse=True), 'series': entries, 'data_gaps': gaps, 'ingestion': ingestion, 'availability': 'NO_PARSED_FINANCIALS' if not entries else 'PARTIAL' if gaps or ingestion.get('status') == 'PARTIAL' else 'AVAILABLE', 'reason': None if entries else 'No reviewed figures have been published for this accounting scope and frequency.'}
    if str(freq or '').lower().startswith('q'):
        if standard != 'NSBU':
            from financial_ingestion.publication import series as snapshot_series
            cumulative = await loop.run_in_executor(None, partial(snapshot_series, ticker, quarterly=True)) or {}
            entries = {}
            for period, fields in cumulative.items():
                for field, value in fields.items():
                    name = {'net_income': 'net_profit', 'revenue': 'net_revenue'}.get(field, field)
                    entries.setdefault(name, {'unit': 'UZS', 'money': True, 'filed': True, 'values': {}})['values'][period] = value * 1000
            gaps = []
            for period, fields in cumulative.items():
                missing = [key for key in ('total_assets', 'total_equity', 'net_income', 'interest_income') if fields.get(key) is None]
                if missing:
                    gaps.append({'period': period, 'code': 'MISSING_FINANCIAL_FIELDS', 'fields': missing})
            from financial_ingestion.store import public_status
            ingestion = await loop.run_in_executor(None, public_status, ticker)
            return {'ok': True, 'ticker': ticker, 'currency': 'UZS', 'standard': standard, 'freq': 'quarterly', 'periods': sorted(cumulative, reverse=True), **scope_info, 'series': entries, 'availability': 'NO_QUARTERLY_IFRS' if not entries else 'PARTIAL' if gaps or ingestion.get('status') == 'PARTIAL' else 'AVAILABLE', 'period_basis': 'cumulative_ytd', 'data_gaps': gaps, 'ingestion': ingestion, 'reason': 'Flows cover January through the stated period end; they are not standalone three-month figures.' if entries else 'No reviewed interim IFRS figures have been published.'}
        try:
            cumulative = await loop.run_in_executor(None, partial(catalog_store.get_financials_series_quarterly, ticker, standard))
            annual = await loop.run_in_executor(None, partial(catalog_store.get_financials_series, ticker, standard))
            sibling = ticker[:-1] if ticker.endswith('P') else f'{ticker}P'
            if sibling and sibling != ticker:
                sib_cum = await loop.run_in_executor(None, partial(catalog_store.get_financials_series_quarterly, sibling, standard))
                for period, fields in (sib_cum or {}).items():
                    merged = dict(fields)
                    merged.update(cumulative.get(period) or {})
                    cumulative[period] = merged
                sib_annual = await loop.run_in_executor(None, partial(catalog_store.get_financials_series, sibling, standard))
                for period, fields in (sib_annual or {}).items():
                    merged = dict(fields)
                    merged.update(annual.get(period) or {})
                    annual[period] = merged
            data_gaps: list[dict[str, Any]] = []
            q_periods, raw = derive_quarterly_series(cumulative, annual, issues=data_gaps)
            import data_quality
            held_periods = await loop.run_in_executor(None, partial(data_quality.held_public_periods, ticker, standard))
            if held_periods:
                data_gaps.extend(({'period': p, 'code': 'UNDER_REVIEW'} for p in sorted(held_periods)))
                q_periods = [period for period in q_periods if period not in held_periods]
                raw = {name: {period: value for period, value in values.items() if period not in held_periods} for name, values in raw.items()}
            series: dict[str, dict[str, Any]] = {name: {'unit': 'UZS', 'money': True, 'values': {p: v * catalog_store.NSBU_THOUSANDS_UZS for p, v in values.items()}} for name, values in raw.items()}
            gp = raw.get('gross_profit') or {}
            oi = raw.get('operating_income') or {}
            reported_opex = raw.get('operating_expenses') or {}
            fallback_opex = {p: gp[p] - oi[p] for p in gp if p in oi}
            opex = {**fallback_opex, **reported_opex}
            if opex:
                series['operating_expenses'] = {'unit': 'UZS', 'money': True, 'derived': bool(fallback_opex), 'filed': bool(reported_opex), 'values': {p: v * catalog_store.NSBU_THOUSANDS_UZS for p, v in opex.items()}}
            rev = raw.get('net_revenue') or {}
            prof = raw.get('net_profit') or {}
            margin = {p: round(prof[p] / rev[p] * 100.0, 4) for p in rev if rev.get(p) and p in prof}
            if margin:
                series['net_margin'] = {'unit': '%', 'money': False, 'derived': True, 'values': margin}
            _fill_equity_by_identity(series)
            for p in q_periods:
                missing = [field for field in ('net_revenue', 'net_profit', 'total_assets', 'total_equity', 'total_liabilities') if (series.get(field) or {}).get('values', {}).get(p) is None]
                if missing:
                    data_gaps.append({'period': p, 'code': 'MISSING_FINANCIAL_FIELDS', 'fields': missing})
            return {'ok': True, 'ticker': ticker, 'currency': 'UZS', 'standard': standard, 'freq': 'quarterly', 'periods': q_periods, 'series': series, 'availability': 'NO_PARSED_FINANCIALS' if not series else 'PARTIAL' if data_gaps else 'AVAILABLE', 'data_gaps': data_gaps}
        except Exception as exc:
            logger.exception('company quarterly financials failed for %s', ticker)
            raise FinancialDataUnavailable(str(exc)) from exc
    try:
        index = await loop.run_in_executor(None, partial(catalog_store.get_company_index, ticker))
        org_id = (index or {}).get('org_id')
        sibling = ticker[:-1] if ticker.endswith('P') else f'{ticker}P'
        if not org_id and sibling and (sibling != ticker):
            alt = await loop.run_in_executor(None, partial(catalog_store.get_company_index, sibling))
            org_id = (alt or {}).get('org_id')
        if not org_id:
            return {'ok': True, 'ticker': ticker, 'org_id': None, 'currency': 'UZS', 'standard': standard, 'periods': [], 'series': {}}
        facts = await loop.run_in_executor(None, partial(catalog_store.get_facts, org_id, 'financial_indicators')) if standard == 'NSBU' else []
        series: dict[str, dict[str, Any]] = {}
        periods: set[str] = set()
        last_fy = catalog_store._latest_complete_fiscal_year()
        for f in facts:
            value = f.get('value_num')
            period = str(f.get('period') or '').strip()
            if value is None or len(period) != 4 or (not period.isdigit()):
                continue
            if int(period) > last_fy:
                continue
            field = f['field']
            money = field in catalog_store.FACT_MONEY_FIELDS
            share = field in catalog_store.FACT_SHARE_FIELDS
            unit = 'UZS' if money else '%' if share or field in catalog_store.FACT_PERCENT_FIELDS else None
            entry = series.setdefault(field, {'unit': unit, 'money': money, 'values': {}})
            scaled = value * catalog_store.NSBU_THOUSANDS_UZS if money else round(value * 100.0, 6) if share else value
            entry['values'][period] = scaled
            periods.add(period)
        purged_empty: set[str] = set()
        for period in list(periods):
            assets = (series.get('total_assets') or {}).get('values', {}).get(period)
            equity = (series.get('total_equity') or {}).get('values', {}).get(period)
            revenue = (series.get('net_revenue') or {}).get('values', {}).get(period)
            money = [e['values'][period] for f, e in series.items() if e['money'] and period in e['values']]
            empty = (assets == 0 and not equity and not revenue) or (money and not any(money))
            if empty:
                purged_empty.add(period)
                periods.discard(period)
                for entry in series.values():
                    entry['values'].pop(period, None)
        series = {f: e for f, e in series.items() if e['values']}
        FILED = {'revenue': 'net_revenue', 'net_income': 'net_profit', 'interest_income': 'interest_income', 'interest_expense': 'interest_expense', 'gross_profit': 'gross_profit', 'operating_income': 'operating_income', 'operating_expenses': 'operating_expenses', 'total_liabilities': 'total_liabilities', 'cash': 'cash', 'total_assets': 'total_assets', 'total_equity': 'total_equity', 'roe': 'roe', 'roa': 'roa', 'debt_ratio': 'debt_ratio', 'debt_to_equity': 'debt_to_equity'}
        filed = await loop.run_in_executor(None, partial(catalog_store.get_financials_series, ticker, standard))
        if sibling and sibling != ticker:
            filed_sib = await loop.run_in_executor(None, partial(catalog_store.get_financials_series, sibling, standard))
            filed = filed or {}
            for period, fields in (filed_sib or {}).items():
                merged = dict(fields)
                merged.update(filed.get(period) or {})
                filed[period] = merged
        for period, fields in (filed or {}).items():
            if len(period) != 4 or not period.isdigit() or int(period) > last_fy:
                continue
            for src, name in FILED.items():
                if fields.get(src) is None:
                    continue
                money = name in catalog_store.FACT_MONEY_FIELDS or src in catalog_store.FIN_MONEY_FIELDS
                unit = 'UZS' if money else '%' if name in catalog_store.FACT_PERCENT_FIELDS else None
                entry = series.setdefault(name, {'unit': unit, 'money': money, 'values': {}})
                entry['unit'], entry['money'] = (unit, money)
                entry['values'][period] = fields[src] * catalog_store.NSBU_THOUSANDS_UZS if money else fields[src]
                entry['filed'] = True
                periods.add(period)
        correction_tickers = {ticker}
        if sibling and sibling != ticker:
            correction_tickers.add(sibling)
        reviewed_annuals = {period[:4] for correction_ticker in correction_tickers for period in (correction_periods_for(correction_ticker) if standard == 'NSBU' else {}) if period.endswith('Q4')}
        for period in purged_empty - reviewed_annuals & periods:
            periods.discard(period)
            for entry in series.values():
                entry['values'].pop(period, None)
        series = {f: e for f, e in series.items() if e['values']}
        annual_years = {str(r.get('year')) for r in await loop.run_in_executor(None, partial(catalog_store.get_company_reports, ticker)) or [] if r.get('report_form') == standard and r.get('period_type') == 'annual' and (not r.get('quarter')) and r.get('year')}
        data_gaps = [{'period': p, 'code': 'EMPTY_SOURCE_FILING'} for p in sorted(purged_empty - reviewed_annuals, reverse=True)]
        for ghost in duplicate_filed_years(series, periods, annual_years):
            data_gaps.append({'period': ghost, 'code': 'UNSUPPORTED_DUPLICATE_PERIOD'})
            logger.info('financials %s: dropping %s — identical to its neighbour on every filed line and with no annual filing of its own', ticker, ghost)
            periods.discard(ghost)
            for entry in series.values():
                entry['values'].pop(ghost, None)
        series = {f: e for f, e in series.items() if e['values']}
        gp = (series.get('gross_profit') or {}).get('values', {})
        oi = (series.get('operating_income') or {}).get('values', {})
        reported_opex = (series.get('operating_expenses') or {}).get('values', {})
        fallback_opex = {p: gp[p] - oi[p] for p in gp if p in oi}
        opex = {**fallback_opex, **reported_opex}
        if opex:
            series['operating_expenses'] = {'unit': 'UZS', 'money': True, 'derived': bool(set(fallback_opex) - set(reported_opex)), 'filed': bool(reported_opex), 'values': opex}
        rev = (series.get('net_revenue') or {}).get('values', {})
        prof = (series.get('net_profit') or {}).get('values', {})
        derived = {p: round(prof[p] / rev[p] * 100.0, 4) for p in rev if rev.get(p) and p in prof}
        if derived:
            series['net_margin'] = {'unit': '%', 'money': False, 'derived': True, 'values': derived}
        _fill_equity_by_identity(series)
        for p in sorted(annual_years - periods, reverse=True):
            if int(p) <= last_fy and (not any((gap['period'] == p for gap in data_gaps))):
                data_gaps.append({'period': p, 'code': 'REPORT_NOT_PARSED'})
        for p in sorted(periods, reverse=True):
            bank_reports = ((index or {}).get('availability') or {}).get('NSBU') or {}
            bank_ifrs = standard == 'MSFO' and ('interest_income' in series or any(('org_type=bank' in str(report.get(link) or '') for reports in bank_reports.values() for report in reports for link in ('excel_url', 'excel_url_form1'))))
            top_line = 'interest_income' if bank_ifrs else 'net_revenue'
            missing = [field for field in (top_line, 'net_profit', 'total_assets', 'total_equity', 'total_liabilities') if (series.get(field) or {}).get('values', {}).get(p) is None]
            if missing:
                data_gaps.append({'period': p, 'code': 'MISSING_FINANCIAL_FIELDS', 'fields': missing})
        ingestion = None
        if standard == 'MSFO':
            from financial_ingestion.store import public_status
            ingestion = await loop.run_in_executor(None, partial(public_status, ticker))
        return {'ok': True, 'ticker': ticker, 'org_id': org_id, 'currency': 'UZS', 'standard': standard, **scope_info, 'periods': sorted(periods, reverse=True), 'series': series, 'availability': 'NO_PARSED_FINANCIALS' if not series else 'PARTIAL' if data_gaps or (ingestion or {}).get('status') == 'PARTIAL' else 'AVAILABLE', 'reports_available': bool(annual_years), 'data_gaps': data_gaps, **({'ingestion': ingestion} if ingestion is not None else {})}
    except Exception as exc:
        logger.exception('company financials failed for %s', ticker)
        raise FinancialDataUnavailable(str(exc)) from exc
