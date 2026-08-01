"""The sixty-four checks (ТЗ v1.3 §12.3).

Each one recomputes something from the raw inputs and compares it with what the
system published. A finding carries the rule, the security, both numbers, the
deviation, a sentence a person can read, and — required by §12.5 — the ``input``
that produced it, so a developer can reproduce the calculation locally in one
command and turn the finding into a test in five minutes.

The six groups are sectioned below. CND runs on price history and FIN/MUL on
statements, so the two sets are independent and a runner may execute them
concurrently without lengthening the pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Iterable, Sequence

from audit import independent as ind
from audit.rules import BLOCKING, INFO, RULES_BY_CODE, WARNING


@dataclass
class AuditContext:
    """Everything a check may look at — raw sources plus what was published."""
    board: list[dict[str, Any]] = field(default_factory=list)
    securities: dict[str, dict[str, Any]] = field(default_factory=dict)
    financials: dict[str, dict[str, Any]] = field(default_factory=dict)
    ratios: dict[str, dict[str, Any]] = field(default_factory=dict)
    listings: dict[str, dict[str, Any]] = field(default_factory=dict)
    stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    history: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # What the API currently serves, i.e. what a reader would see.
    published_multiples: list[dict[str, Any]] = field(default_factory=list)
    published_map: dict[str, Any] = field(default_factory=dict)
    published_summary: dict[str, Any] = field(default_factory=dict)
    published_catalog: dict[str, Any] = field(default_factory=dict)
    # {ticker: {months: absolute-metrics block}} for XSC-03.
    published_metrics_by_period: dict[str, dict[int, Any]] = field(default_factory=dict)
    # The MA windows the server declares, which both chart modes must obey.
    published_ma_windows: dict[str, Any] = field(default_factory=dict)
    # Дополнение 1: the bond contour and the reporting catalog.
    published_bonds: list[dict[str, Any]] = field(default_factory=list)
    bond_references: dict[str, dict[str, Any]] = field(default_factory=dict)
    bond_coupons: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    published_catalog_reports: dict[str, Any] = field(default_factory=dict)
    source_reports: list[dict[str, Any]] = field(default_factory=list)
    parse_queue: list[dict[str, Any]] | None = None
    previous_counters: dict[str, Any] = field(default_factory=dict)
    previous_tiers: dict[str, str] = field(default_factory=dict)
    today: date | None = None


@dataclass
class Finding:
    rule_code: str
    message: str
    ticker: str | None = None
    metric: str | None = None
    expected: float | None = None
    actual: float | None = None
    deviation: float | None = None
    input: dict[str, Any] = field(default_factory=dict)

    @property
    def severity(self) -> str:
        rule = RULES_BY_CODE.get(self.rule_code)
        return rule.severity if rule else WARNING


Check = Callable[[AuditContext], Iterable[Finding]]
_REGISTRY: dict[str, Check] = {}


def check(code: str) -> Callable[[Check], Check]:
    def wrap(fn: Check) -> Check:
        assert code in RULES_BY_CODE, f"unknown rule {code}"
        _REGISTRY[code] = fn
        return fn
    return wrap


def registry() -> dict[str, Check]:
    return dict(_REGISTRY)


def _pub_by_ticker(ctx: AuditContext) -> dict[str, dict[str, Any]]:
    return {str(r.get("ticker") or "").upper(): r for r in ctx.published_multiples}


def _value(metric: Any) -> float | None:
    return ind.num((metric or {}).get("value")) if isinstance(metric, dict) else ind.num(metric)


def _board_by_ticker(ctx: AuditContext) -> dict[str, dict[str, Any]]:
    return {str(r.get("ticker") or "").upper(): r for r in ctx.board}


# ===========================================================================
# FIN — does the statement parse into something that can be true?
# ===========================================================================

@check("FIN-01")
def fin_01(ctx: AuditContext):
    tol = ind.threshold("audit.balance_tolerance_pct", 1.0)
    for ticker, fin in ctx.financials.items():
        rat = ctx.ratios.get(ticker) or {}
        assets = ind.num(rat.get("total_assets"))
        equity = ind.num(rat.get("total_equity"))
        liabilities = ind.num(fin.get("total_liabilities"))
        if None in (assets, equity, liabilities) or assets <= 0:
            continue
        gap = ind.relative_gap(assets, liabilities + equity)
        if gap is not None and gap > tol:
            yield Finding("FIN-01", "баланс не сходится: активы ≠ обязательства + капитал",
                          ticker, "balance", assets, liabilities + equity, gap,
                          {"assets": assets, "liabilities": liabilities, "equity": equity})


@check("FIN-02")
def fin_02(ctx: AuditContext):
    tol = ind.threshold("audit.balance_tolerance_pct", 1.0)
    for ticker, fin in ctx.financials.items():
        a = ind.num(fin.get("total_assets"))
        b = ind.num((ctx.ratios.get(ticker) or {}).get("total_assets"))
        gap = ind.relative_gap(a, b)
        if gap is not None and gap > tol:
            yield Finding("FIN-02", "активы в отчётности и в коэффициентах расходятся",
                          ticker, "total_assets", a, b, gap, {"statement": a, "indicators": b})


@check("FIN-03")
def fin_03(ctx: AuditContext):
    limit = ind.threshold("financials.half_year_vs_annual_max", 5)
    for ticker, fin in ctx.financials.items():
        annual = fin.get("annual") or {}
        rev, annual_rev = ind.num(fin.get("revenue")), ind.num(annual.get("revenue"))
        months = ind.num(fin.get("period_months")) or 12
        if rev is None or annual_rev is None or annual_rev <= 0 or months >= 12:
            continue
        scaled = rev * 12.0 / months
        ratio = scaled / annual_rev
        if ratio > limit or ratio < 1.0 / limit:
            yield Finding("FIN-03", "выручка периода не согласуется с годовой",
                          ticker, "revenue", annual_rev, scaled, ratio,
                          {"revenue": rev, "months": months, "annual_revenue": annual_rev})


@check("FIN-04")
def fin_04(ctx: AuditContext):
    for ticker, fin in ctx.financials.items():
        rev, gross = ind.num(fin.get("revenue")), ind.num(fin.get("gross_profit"))
        if rev is None or gross is None or rev <= 0:
            continue
        if abs(gross) > rev:
            yield Finding("FIN-04", "валовая прибыль больше выручки", ticker, "gross_profit",
                          rev, gross, abs(gross) / rev, {"revenue": rev, "gross_profit": gross})


@check("FIN-05")
def fin_05(ctx: AuditContext):
    tol = ind.threshold("audit.net_vs_gross_tolerance_pct", 5.0) / 100.0
    for ticker, fin in ctx.financials.items():
        gross, net = ind.num(fin.get("gross_profit")), ind.num(fin.get("net_income"))
        if gross is None or net is None or gross <= 0 or net <= 0:
            continue
        if net > gross * (1 + tol):
            yield Finding("FIN-05", "чистая прибыль больше валовой", ticker, "net_income",
                          gross, net, net / gross, {"gross_profit": gross, "net_income": net})


@check("FIN-06")
def fin_06(ctx: AuditContext):
    """The unit-scale check — the most frequent and least visible parsing error.

    The source hands over a figure in thousands of sums instead of sums and the
    whole statement is a thousand times too large. Compared against the sector's
    median revenue, that is unmissable; compared against nothing, it is invisible.
    """
    limit = ind.threshold("audit.unit_scale_max_ratio", 1000.0)
    by_sector: dict[str, list[tuple[str, float]]] = {}
    for ticker, fin in ctx.financials.items():
        rev = ind.num(fin.get("revenue"))
        if rev is None or rev <= 0:
            continue
        sector = str((ctx.securities.get(ticker) or {}).get("sector") or "прочее")
        by_sector.setdefault(sector, []).append((ticker, rev))
    for sector, rows in by_sector.items():
        if len(rows) < 4:
            continue
        values = sorted(v for _, v in rows)
        median = values[len(values) // 2]
        if median <= 0:
            continue
        for ticker, rev in rows:
            ratio = max(rev / median, median / rev)
            if ratio > limit:
                yield Finding("FIN-06", "масштаб единиц отличается от сектора на порядки",
                              ticker, "revenue", median, rev, ratio,
                              {"revenue": rev, "sector": sector, "sector_median": median})


@check("FIN-07")
def fin_07(ctx: AuditContext):
    for ticker, fin in ctx.financials.items():
        months = ind.num(fin.get("period_months"))
        rev = ind.num(fin.get("revenue"))
        annual_rev = ind.num((fin.get("annual") or {}).get("revenue"))
        if months is None or rev is None or annual_rev is None or months >= 12:
            continue
        if rev > annual_rev:
            yield Finding("FIN-07", "накопительный период больше годового", ticker, "revenue",
                          annual_rev, rev, rev / annual_rev if annual_rev else None,
                          {"months": months, "revenue": rev, "annual_revenue": annual_rev})


@check("FIN-08")
def fin_08(ctx: AuditContext):
    limit = ind.threshold("audit.stale_report_months", 18)
    for ticker, fin in ctx.financials.items():
        year, quarter = fin.get("year"), fin.get("quarter") or 0
        label = f"{year}Q{quarter}" if quarter else str(year or "")
        age = ind.months_between(label, ctx.today)
        if age is not None and age > limit:
            yield Finding("FIN-08", f"отчётность старше {limit} месяцев", ticker, "period",
                          limit, age, age - limit, {"period": label, "age_months": age})


@check("FIN-09")
def fin_09(ctx: AuditContext):
    for ticker, fin in ctx.financials.items():
        months = ind.num(fin.get("period_months"))
        if not fin.get("annual") and months is not None and months < 12:
            yield Finding("FIN-09", "нет ни одного годового отчёта", ticker, "annual",
                          None, None, None, {"period_months": months})


@check("FIN-10")
def fin_10(ctx: AuditContext):
    board = _board_by_ticker(ctx)
    for ticker, fin in ctx.financials.items():
        rev = ind.num(fin.get("revenue"))
        cap = ind.num((board.get(ticker) or {}).get("market_cap"))
        if rev is not None and rev == 0 and cap and cap > 0:
            yield Finding("FIN-10", "выручка равна нулю при ненулевой капитализации",
                          ticker, "revenue", None, 0.0, None, {"market_cap": cap})


@check("FIN-11")
def fin_11(ctx: AuditContext):
    for ticker, rat in ctx.ratios.items():
        equity = ind.num(rat.get("total_equity"))
        if equity is not None and equity <= 0:
            yield Finding("FIN-11", "собственный капитал не положителен", ticker,
                          "total_equity", None, equity, None, {"equity": equity})


@check("FIN-12")
def fin_12(ctx: AuditContext):
    for ticker, fin in ctx.financials.items():
        rat = ctx.ratios.get(ticker)
        if not rat or not fin.get("year"):
            continue
        ratio_year = str(rat.get("period") or "")[:4]
        if ratio_year.isdigit() and int(ratio_year) != int(fin["year"]):
            yield Finding("FIN-12", "период отчётности и период коэффициентов не совпадают",
                          ticker, "period", float(fin["year"]), float(ratio_year), None,
                          {"statement_year": fin["year"], "indicators_period": rat.get("period")})


@check("FIN-13")
def fin_13(ctx: AuditContext):
    required = ("revenue", "net_income", "total_liabilities")
    minimum = ind.threshold("audit.required_field_coverage_min", 1.0)
    for ticker, fin in ctx.financials.items():
        present = sum(1 for f in required if ind.num(fin.get(f)) is not None)
        cov = present / len(required)
        if cov < minimum:
            missing = [f for f in required if ind.num(fin.get(f)) is None]
            yield Finding("FIN-13", "обязательные поля отчётности заполнены не полностью",
                          ticker, "coverage", minimum, cov, minimum - cov, {"missing": missing})


@check("FIN-14")
def fin_14(ctx: AuditContext):
    seen: dict[tuple[str, Any, Any], int] = {}
    for ticker, fin in ctx.financials.items():
        key = (ticker, fin.get("year"), fin.get("quarter"))
        seen[key] = seen.get(key, 0) + 1
    for (ticker, year, quarter), count in seen.items():
        if count > 1:
            yield Finding("FIN-14", "дубль отчётности за один период", ticker, "period",
                          1.0, float(count), None, {"year": year, "quarter": quarter})


@check("FIN-15")
def fin_15(ctx: AuditContext):
    for ticker, fin in ctx.financials.items():
        rev = ind.num(fin.get("revenue"))
        if rev is not None and rev < 0:
            yield Finding("FIN-15", "выручка отрицательна", ticker, "revenue", None, rev,
                          None, {"revenue": rev})


# ===========================================================================
# MUL — does the published multiple survive being recomputed?
# ===========================================================================

@check("MUL-01")
def mul_01(ctx: AuditContext):
    tol = ind.threshold("audit.recompute_tolerance_pct", 0.5)
    for row in ctx.published_multiples:
        published = _value(row.get("pe"))
        if published is None:
            continue
        cap = _value(row.get("market_cap_issuer"))
        net = ind.num((row.get("earnings") or {}).get("net_income"))
        if net is None:
            fin = ctx.financials.get(str(row.get("ticker") or "").upper()) or {}
            net = ind.num((fin.get("annual") or {}).get("net_income")) or ind.num(fin.get("net_income"))
        mine = ind.price_earnings(cap, net)
        gap = ind.relative_gap(mine, published)
        if gap is not None and gap > tol:
            yield Finding("MUL-01", "независимый пересчёт P/E не совпал с опубликованным",
                          row.get("ticker"), "pe", mine, published, gap,
                          {"market_cap_issuer": cap, "net_income": net})


@check("MUL-02")
def mul_02(ctx: AuditContext):
    tol = ind.threshold("audit.recompute_tolerance_pct", 0.5)
    for row in ctx.published_multiples:
        published = _value(row.get("pb"))
        if published is None:
            continue
        cap = _value(row.get("market_cap_issuer"))
        equity = ind.num((ctx.ratios.get(str(row.get("ticker") or "").upper()) or {})
                         .get("total_equity"))
        mine = ind.price_book(cap, equity)
        gap = ind.relative_gap(mine, published)
        if gap is not None and gap > tol:
            yield Finding("MUL-02", "независимый пересчёт P/B не совпал с опубликованным",
                          row.get("ticker"), "pb", mine, published, gap,
                          {"market_cap_issuer": cap, "equity": equity})


@check("MUL-03")
def mul_03(ctx: AuditContext):
    tol = ind.threshold("audit.market_cap_tolerance_pct", 0.1)
    for row in ctx.board:
        cap = ind.num(row.get("market_cap"))
        mine = ind.market_cap(row.get("last_price"), row.get("shares_outstanding"))
        gap = ind.relative_gap(mine, cap)
        if gap is not None and gap > tol:
            yield Finding("MUL-03", "капитализация не равна цене, умноженной на число бумаг",
                          row.get("ticker"), "market_cap", mine, cap, gap,
                          {"last_price": row.get("last_price"),
                           "shares_outstanding": row.get("shares_outstanding")})


@check("MUL-04")
def mul_04(ctx: AuditContext):
    """The rule the whole group exists for: one issuer, one set of multiples."""
    by_issuer: dict[str, list[dict[str, Any]]] = {}
    for row in ctx.published_multiples:
        by_issuer.setdefault(str(row.get("issuer") or row.get("ticker")), []).append(row)
    for issuer, rows in by_issuer.items():
        if len(rows) < 2:
            continue
        for metric in ("pe", "pb", "roe", "roa", "net_margin", "debt_to_equity"):
            values = {str(r.get("ticker")): _value(r.get(metric)) for r in rows}
            distinct = {round(v, 6) for v in values.values() if v is not None}
            if len(distinct) > 1:
                yield Finding("MUL-04", f"{metric} различается у классов одного эмитента",
                              ", ".join(values), metric, min(distinct), max(distinct),
                              max(distinct) - min(distinct), {"issuer": issuer, "values": values})


@check("MUL-05")
def mul_05(ctx: AuditContext):
    limit = ind.threshold("multiples.cap_vs_price_shares_max", 1.5)
    for row in ctx.board:
        cap = ind.num(row.get("market_cap"))
        implied = ind.market_cap(row.get("last_price"), row.get("shares_outstanding"))
        if cap is None or implied is None or implied <= 0:
            continue
        ratio = cap / implied
        if ratio > limit or ratio < 1.0 / limit:
            yield Finding("MUL-05", "капитализация класса не согласована с ценой и числом акций",
                          row.get("ticker"), "market_cap", implied, cap, ratio,
                          {"last_price": row.get("last_price"),
                           "shares_outstanding": row.get("shares_outstanding"),
                           "looks_like_thousands": ratio > 100 or ratio < 0.01})


@check("MUL-06")
def mul_06(ctx: AuditContext):
    tol = ind.threshold("audit.pb_identity_tolerance_pct", 5.0)
    for row in ctx.published_multiples:
        pe, pb = _value(row.get("pe")), _value(row.get("pb"))
        roe = _value(row.get("roe"))
        if None in (pe, pb, roe) or pe <= 0:
            continue
        implied = pe * roe / 100.0
        gap = ind.relative_gap(implied, pb)
        if gap is not None and gap > tol:
            yield Finding("MUL-06", "P/B не равен P/E × ROE", row.get("ticker"), "pb",
                          implied, pb, gap, {"pe": pe, "roe": roe, "pb": pb})


def _range_rule(code: str, metric: str, threshold_key: str, label: str):
    @check(code)
    def _inner(ctx: AuditContext, _m=metric, _t=threshold_key, _l=label, _c=code):
        bounds = ind.threshold(_t) or []
        if len(bounds) != 2:
            return
        low, high = float(bounds[0]), float(bounds[1])
        for row in ctx.published_multiples:
            value = _value(row.get(_m))
            if value is None:
                continue
            if not (low <= value <= high):
                yield Finding(_c, f"{_l} опубликован вне допустимого диапазона",
                              row.get("ticker"), _m, None, value, None,
                              {"value": value, "allowed": [low, high]})
    return _inner


_range_rule("MUL-07", "pe", "multiples.pe_range", "P/E")
_range_rule("MUL-08", "pb", "multiples.pb_range", "P/B")


@check("MUL-09")
def mul_09(ctx: AuditContext):
    limit = ind.threshold("multiples.roe_abs_max", 100)
    for row in ctx.published_multiples:
        roe = _value(row.get("roe"))
        if roe is not None and abs(roe) > limit:
            yield Finding("MUL-09", "ROE опубликован за пределами разумного", row.get("ticker"),
                          "roe", limit, roe, abs(roe) - limit, {"roe": roe})


@check("MUL-10")
def mul_10(ctx: AuditContext):
    for row in ctx.published_multiples:
        pe = _value(row.get("pe"))
        ticker = str(row.get("ticker") or "").upper()
        fin = ctx.financials.get(ticker) or {}
        net = ind.num((fin.get("annual") or {}).get("net_income"))
        if net is None:
            net = ind.num(fin.get("net_income"))
        if net is not None and net <= 0 and pe is not None:
            yield Finding("MUL-10", "при убытке опубликовано число вместо статуса «убыток»",
                          ticker, "pe", None, pe, None, {"net_income": net, "pe": pe})


@check("MUL-11")
def mul_11(ctx: AuditContext):
    limit = ind.threshold("audit.stale_report_months", 18)
    for row in ctx.published_multiples:
        if _value(row.get("pe")) is None:
            continue
        period = (row.get("pe") or {}).get("base_period") or row.get("base_period")
        if not period:
            yield Finding("MUL-11", "у P/E не указан период базы", row.get("ticker"), "pe",
                          None, None, None, {})
            continue
        age = ind.months_between(period, ctx.today)
        if age is not None and age > limit:
            yield Finding("MUL-11", "база P/E старше допустимого", row.get("ticker"), "pe",
                          limit, age, age - limit, {"base_period": period})


@check("MUL-12")
def mul_12(ctx: AuditContext):
    rows = ctx.published_multiples
    if not rows:
        return
    limit = ind.threshold("audit.suppressed_share_max", 0.35)
    suppressed = [r for r in rows if _value(r.get("pe")) is None and _value(r.get("pb")) is None]
    share = len(suppressed) / len(rows)
    if share > limit:
        yield Finding("MUL-12", "доля бумаг без публикуемых мультипликаторов выше порога",
                      None, "suppressed_share", limit, share, share - limit,
                      {"suppressed": len(suppressed), "total": len(rows)})


# ===========================================================================
# MKT — the board, its tops and its totals
# ===========================================================================

@check("MKT-01")
def mkt_01(ctx: AuditContext):
    tol = ind.threshold("audit.change_tolerance_pp", 0.01)
    published = {str(t.get("ticker") or "").upper(): t
                 for t in (ctx.published_map.get("tiles") or [])}
    for row in ctx.board:
        ticker = str(row.get("ticker") or "").upper()
        mine = ind.day_change(row.get("last_price"), row.get("close_price"))
        theirs = ind.num((published.get(ticker) or {}).get("change_pct"))
        if mine is None and theirs is None:
            continue
        if mine is None or theirs is None:
            yield Finding("MKT-01", "изменение посчитано на одной стороне и отсутствует на другой",
                          ticker, "change_pct", mine, theirs, None,
                          {"last_price": row.get("last_price"), "prev_close": row.get("close_price")})
        elif abs(mine - theirs) > tol:
            yield Finding("MKT-01", "независимый пересчёт дневного изменения не совпал",
                          ticker, "change_pct", mine, theirs, abs(mine - theirs),
                          {"last_price": row.get("last_price"), "prev_close": row.get("close_price")})


@check("MKT-02")
def mkt_02(ctx: AuditContext):
    floor = ind.threshold("market_map.min_trades_confident", 5)
    tiles = [t for t in (ctx.published_map.get("tiles") or [])
             if t.get("change_pct") is not None]
    ranked = sorted(tiles, key=lambda t: -t["change_pct"])[:5] + \
        sorted(tiles, key=lambda t: t["change_pct"])[:5]
    for tile in ranked:
        trades = ind.num(tile.get("trades"))
        if trades is not None and trades < floor and tile.get("confidence") != "low":
            yield Finding("MKT-02", "бумага в топе держится на единичных сделках и не помечена",
                          tile.get("ticker"), "change_pct", floor, trades, None,
                          {"trades": trades, "quantity": tile.get("quantity"),
                           "turnover": tile.get("turnover"), "change_pct": tile.get("change_pct")})


@check("MKT-03")
def mkt_03(ctx: AuditContext):
    for tile in ctx.published_map.get("tiles") or []:
        traded = (ind.num(tile.get("trades")) or 0) > 0 or (ind.num(tile.get("turnover")) or 0) > 0
        if traded and tile.get("last_price") is None:
            yield Finding("MKT-03", "есть сделки, но нет последней цены", tile.get("ticker"),
                          "last_price", None, None, None,
                          {"trades": tile.get("trades"), "turnover": tile.get("turnover")})
        if tile.get("change_pct") is not None and ind.num(tile.get("change_pct")) == -100.0:
            yield Finding("MKT-03", "изменение равно минус 100 % — признак отсутствующей цены",
                          tile.get("ticker"), "change_pct", None, -100.0, None, {})


@check("MKT-04")
def mkt_04(ctx: AuditContext):
    for tile in ctx.published_map.get("tiles") or []:
        if tile.get("status") != "ok" and tile.get("change_pct") is not None:
            yield Finding("MKT-04", "плитка без сделок несёт изменение цены", tile.get("ticker"),
                          "change_pct", None, ind.num(tile.get("change_pct")), None,
                          {"status": tile.get("status")})


@check("MKT-05")
def mkt_05(ctx: AuditContext):
    board = _board_by_ticker(ctx)
    for tile in ctx.published_map.get("tiles") or []:
        price = ind.num(tile.get("last_price"))
        if price is None or price >= 0.01:
            continue
        row = board.get(str(tile.get("ticker") or "").upper()) or {}
        mine = ind.day_change(row.get("last_price"), row.get("close_price"))
        shown = ind.num(tile.get("change_pct"))
        if mine and abs(mine) > 0 and shown == 0.0:
            yield Finding("MKT-05", "изменение обнулено округлением у бумаги с ценой ниже 0,01",
                          tile.get("ticker"), "change_pct", mine, 0.0, abs(mine),
                          {"last_price": row.get("last_price"), "prev_close": row.get("close_price")})


@check("MKT-06")
def mkt_06(ctx: AuditContext):
    pub = _pub_by_ticker(ctx)
    tiles = [t for t in (ctx.published_map.get("tiles") or []) if t.get("change_pct") is not None]
    top = sorted(tiles, key=lambda t: -t["change_pct"])[:5]
    seen: dict[str, str] = {}
    for tile in top:
        issuer = str((pub.get(str(tile.get("ticker") or "").upper()) or {}).get("issuer") or "")
        if issuer and issuer in seen:
            yield Finding("MKT-06", "два класса одного эмитента в топе без пометки",
                          tile.get("ticker"), "top", None, None, None,
                          {"issuer": issuer, "other": seen[issuer]})
        elif issuer:
            seen[issuer] = str(tile.get("ticker"))


@check("MKT-07")
def mkt_07(ctx: AuditContext):
    summary, counts = ctx.published_summary, ctx.published_map.get("counts") or {}
    if not summary or not counts:
        return
    total = ind.num(counts.get("tiles"))
    parts = sum(ind.num(summary.get(k)) or 0 for k in ("up", "down", "flat"))
    untraded = (ind.num(counts.get("not_traded")) or 0) + (ind.num(counts.get("inactive")) or 0) \
        + (ind.num(counts.get("no_price")) or 0)
    if total is not None and abs(parts + untraded - total) > 0.5:
        yield Finding("MKT-07", "сумма счётчиков не равна числу бумаг", None, "counters",
                      total, parts + untraded, abs(parts + untraded - total),
                      {"up_down_flat": parts, "untraded": untraded, "tiles": total})


@check("MKT-08")
def mkt_08(ctx: AuditContext):
    tol = ind.threshold("audit.turnover_tolerance_pct", 0.5)
    published = ind.num((ctx.published_summary or {}).get("turnover_today"))
    mine = sum((ind.num(t.get("turnover")) or 0.0)
               for t in (ctx.published_map.get("tiles") or []))
    gap = ind.relative_gap(mine, published)
    if gap is not None and gap > tol:
        yield Finding("MKT-08", "оборот в шапке не равен сумме оборотов по бумагам", None,
                      "turnover_today", mine, published, gap, {"tiles_sum": mine})


@check("MKT-09")
def mkt_09(ctx: AuditContext):
    tol = ind.threshold("audit.market_cap_tolerance_pct", 0.1)
    cap = (ctx.published_summary or {}).get("market_cap") or {}
    published = ind.num(cap.get("value"))
    if published is None:
        return
    mine = 0.0
    bond_caps = 0.0
    for row in ctx.board:
        value = ind.num(row.get("market_cap"))
        if value is None or value <= 0:
            continue
        ticker = str(row.get("ticker") or "").upper()
        meta = ctx.securities.get(ticker) or {}
        is_bond = str(row.get("type") or meta.get("type") or "").lower() == "bond"
        if is_bond:
            bond_caps += value
        elif not row.get("inactive"):
            mine += value
    gap = ind.relative_gap(mine, published)
    if gap is not None and gap > tol:
        yield Finding("MKT-09", "капитализация рынка не равна сумме активных акций", None,
                      "market_cap", mine, published, gap, {"independent_sum": mine})
    if bond_caps > 0:
        yield Finding("MKT-09", "у облигаций рассчитана капитализация", None, "market_cap",
                      0.0, bond_caps, bond_caps, {"bond_market_cap": bond_caps})


@check("MKT-10")
def mkt_10(ctx: AuditContext):
    cap = (ctx.published_summary or {}).get("market_cap") or {}
    excluded = (cap.get("excluded") or {}).get("inactive_listings") or {}
    inactive = [r for r in ctx.board if r.get("inactive") and ind.num(r.get("market_cap"))]
    if inactive and not excluded.get("instruments"):
        yield Finding("MKT-10", "неактивные листинги не выделены в капитализации", None,
                      "market_cap", float(len(inactive)), 0.0, None,
                      {"inactive_with_cap": [r.get("ticker") for r in inactive][:20]})


@check("MKT-11")
def mkt_11(ctx: AuditContext):
    for entry in (ctx.published_catalog.get("discrepancies") or []):
        if entry.get("field") == "sector":
            yield Finding("MKT-11", "сектор бумаги различается между справочниками",
                          entry.get("ticker"), "sector", None, None, None,
                          {"values": entry.get("values")})


@check("MKT-12")
def mkt_12(ctx: AuditContext):
    tiles_by_sector: dict[str, list[dict[str, Any]]] = {}
    for tile in ctx.published_map.get("tiles") or []:
        tiles_by_sector.setdefault(tile.get("sector") or "прочее", []).append(tile)
    for sector in ctx.published_map.get("sectors") or []:
        rows = tiles_by_sector.get(sector.get("name"), [])
        mine = ind.weighted_change(rows)
        theirs = ind.num(sector.get("change_pct"))
        gap = ind.relative_gap(mine, theirs)
        if mine is None and theirs is None:
            continue
        if gap is None or gap > 0.5:
            yield Finding("MKT-12", "агрегат сектора не совпал с независимым пересчётом",
                          sector.get("name"), "sector_change", mine, theirs, gap,
                          {"tiles_counted": sector.get("tiles_counted"),
                           "weighting": sector.get("weighting")})


@check("MKT-13")
def mkt_13(ctx: AuditContext):
    """CSV export must carry the same numbers as the screen.

    The export is produced by the browser from the rows it holds, so the check
    that can be made server-side is that every published row carries the fields
    the export writes. A row missing one exports an empty cell where the screen
    shows a figure.
    """
    pub = _pub_by_ticker(ctx)
    for tile in ctx.published_map.get("tiles") or []:
        ticker = str(tile.get("ticker") or "").upper()
        # A bond carries no claim on earnings and therefore has no multiples
        # row by design — its absence there is the rule working, not a gap.
        is_bond = str(tile.get("type")
                      or (ctx.securities.get(ticker) or {}).get("type") or "").lower() == "bond"
        if tile.get("status") == "ok" and not is_bond and ticker not in pub:
            yield Finding("MKT-13", "бумага есть на карте, но отсутствует в наборе экспорта",
                          ticker, "export", None, None, None, {"type": tile.get("type")})


@check("MKT-14")
def mkt_14(ctx: AuditContext):
    tiles = [t for t in (ctx.published_map.get("tiles") or []) if t.get("change_pct") is not None]
    grouped: dict[float, list[str]] = {}
    for tile in tiles:
        grouped.setdefault(round(float(tile["change_pct"]), 6), []).append(str(tile.get("ticker")))
    for value, tickers in grouped.items():
        if len(tickers) > 1 and tickers != sorted(tickers):
            yield Finding("MKT-14", "порядок бумаг с равным изменением не детерминирован",
                          ", ".join(tickers), "sort", None, value, None, {"tickers": tickers})


# ===========================================================================
# CND — candles, history and the charts
# ===========================================================================

@check("CND-01")
def cnd_01(ctx: AuditContext):
    for ticker, raw in ctx.history.items():
        bad = [p for p in ind.series(raw) if not ind.ohlc_ok(p)]
        if bad:
            first = bad[0]
            yield Finding("CND-01", "нарушен порядок OHLC", ticker, "ohlc", None, None,
                          float(len(bad)),
                          {"points": len(bad), "example": {k: first.get(k) for k in
                                                           ("open", "high", "low", "close")},
                           "date": str(first["d"])})


@check("CND-02")
def cnd_02(ctx: AuditContext):
    limit = ind.threshold("quality.flat_share_max", 0.5)
    for ticker, raw in ctx.history.items():
        points = ind.series(raw)
        share = ind.flat_share(points)
        if share is not None and share > limit:
            yield Finding("CND-02", "доля свечей без внутридневного диапазона выше порога",
                          ticker, "flat_share", limit, share, share - limit,
                          {"points": len(points), "flat_share": share})


@check("CND-03")
def cnd_03(ctx: AuditContext):
    limit = ind.threshold("quality.coverage_min", 0.6)
    for ticker, raw in ctx.history.items():
        points = ind.series(raw)
        cov = ind.coverage(points)
        if cov is not None and cov < limit:
            yield Finding("CND-03", "покрытие торговых дней ниже порога", ticker, "coverage",
                          limit, cov, limit - cov, {"points": len(points), "coverage": cov})


@check("CND-04")
def cnd_04(ctx: AuditContext):
    warn = ind.threshold("audit.median_gap_warn_days", 5)
    for ticker, raw in ctx.history.items():
        points = ind.series(raw)
        spans = ind.gaps(points)
        if not spans:
            continue
        median = sorted(spans)[len(spans) // 2]
        if median > warn:
            yield Finding("CND-04", "медианный разрыв между точками велик", ticker, "median_gap",
                          warn, float(median), float(median - warn), {"points": len(points)})


@check("CND-05")
def cnd_05(ctx: AuditContext):
    for ticker, raw in ctx.history.items():
        spans = ind.gaps(ind.series(raw))
        if spans and max(spans) > 30:
            yield Finding("CND-05", "в истории есть длинный разрыв", ticker, "max_gap",
                          None, float(max(spans)), None, {"max_gap_days": max(spans)})


@check("CND-06")
def cnd_06(ctx: AuditContext):
    """The MA window the server DECLARES must be a moving average of ~20 days.

    Two wrong ways to write this check. Measuring the configured calendar window
    against the data is circular — that span is bounded by the window and can
    never exceed the limit. Measuring what averaging twenty display buckets
    WOULD cover is worse: it reports a property of the data as though it were a
    property of the application, and fires on securities whose chart is already
    correct. An auditor that cries about fixed behaviour teaches people to
    ignore it.

    What can be audited is the contract: the server publishes the window the
    chart must use, and that number has to be a 20-day average — not 133 days
    wearing its label.
    """
    limit = ind.threshold("audit.ma20_max_calendar_days", 45)
    declared = ctx.published_ma_windows or {}
    window = ind.num(declared.get("ma20"))
    if window is None:
        yield Finding("CND-06", "сервер не объявляет окно MA20 — график волен выбрать своё",
                      None, "ma20_window", limit, None, None, {"declared": declared})
        return
    if window > limit:
        yield Finding("CND-06", "объявленное окно MA20 шире допустимого", None, "ma20_window",
                      limit, window, window - limit, {"declared_ma20_days": window})


@check("CND-07")
def cnd_07_declared(ctx: AuditContext):
    """One rule for both chart modes — observable as one declared window.

    The defect was that "MA20" meant twenty daily points on a line chart and
    twenty weekly candles on a candle chart of the same security: 25 calendar
    days against 134, on 72 of 72 securities. It cannot recur while both modes
    read one number from the server, so what the auditor checks is that the
    number exists and is single.
    """
    declared = ctx.published_ma_windows or {}
    ma20, ma50 = ind.num(declared.get("ma20")), ind.num(declared.get("ma50"))
    if ma20 is None or ma50 is None:
        yield Finding("CND-07", "окна скользящих средних объявлены не полностью", None,
                      "ma_windows", None, None, None, {"declared": declared})
        return
    if ma50 <= ma20:
        yield Finding("CND-07", "MA50 не длиннее MA20 — окна перепутаны", None, "ma_windows",
                      ma20, ma50, ma20 - ma50, {"ma20": ma20, "ma50": ma50})


@check("CND-08")
def cnd_08(ctx: AuditContext):
    for ticker, raw in ctx.history.items():
        points = ind.series(raw)
        if len(points) < 30:
            continue
        weeks = {p["d"].isocalendar()[:2] for p in points}
        if len(weeks) < 2:
            yield Finding("CND-08", "агрегация не разделяет календарные периоды", ticker,
                          "buckets", None, float(len(weeks)), None, {"points": len(points)})


@check("CND-09")
def cnd_09(ctx: AuditContext):
    spike = ind.threshold("audit.spike_change_pct", 15.0)
    max_trades = ind.threshold("audit.spike_max_trades", 3)
    for tile in ctx.published_map.get("tiles") or []:
        change = ind.num(tile.get("change_pct"))
        trades = ind.num(tile.get("trades"))
        if change is None or trades is None:
            continue
        if abs(change) > spike and trades < max_trades and tile.get("confidence") != "low":
            yield Finding("CND-09", "резкий скачок цены на единичной сделке не помечен",
                          tile.get("ticker"), "change_pct", spike, change, abs(change) - spike,
                          {"trades": trades, "change_pct": change})


@check("CND-10")
def cnd_10(ctx: AuditContext):
    for ticker, raw in ctx.history.items():
        invented = [p for p in ind.series(raw)
                    if (p.get("volume") or 0) == 0 and (p.get("turnover") or 0) == 0
                    and p.get("open") is not None and p["open"] != p["close"]]
        if invented:
            yield Finding("CND-10", "в истории есть точка без сделок, но с движением цены",
                          ticker, "history", None, float(len(invented)), None,
                          {"points": len(invented), "first": str(invented[0]["d"])})


@check("CND-11")
def cnd_11(ctx: AuditContext):
    for ticker, raw in ctx.history.items():
        if not raw:
            yield Finding("CND-11", "история по тикеру пуста — проверьте ключ запроса",
                          ticker, "history", None, 0.0, None, {})


@check("CND-12")
def cnd_12(ctx: AuditContext):
    for ticker, previous in (ctx.previous_tiers or {}).items():
        points = ind.series(ctx.history.get(ticker) or [])
        if not points:
            continue
        share = ind.flat_share(points)
        cov = ind.coverage(points)
        if share is None or cov is None:
            continue
        now = "full" if (share <= ind.threshold("quality.flat_share_max", 0.5)
                         and cov >= ind.threshold("quality.coverage_min", 0.6)) else "sparse"
        if previous and now != previous:
            yield Finding("CND-12", "классификация качества изменилась", ticker, "data_tier",
                          None, None, None, {"previous": previous, "now": now})


# ===========================================================================
# CAT — one universe
# ===========================================================================

@check("CAT-01")
def cat_01(ctx: AuditContext):
    counts = ctx.published_catalog.get("source_counts") or {}
    present = {k: v for k, v in counts.items() if v}
    if len(set(present.values())) > 1:
        yield Finding("CAT-01", "справочники расходятся по числу инструментов", None,
                      "catalog", None, None, None, {"counts": present})


@check("CAT-02")
def cat_02(ctx: AuditContext):
    for item in ctx.published_catalog.get("items") or []:
        if not item.get("sector") or not item.get("name"):
            yield Finding("CAT-02", "у бумаги нет эмитента или сектора", item.get("ticker"),
                          "catalog", None, None, None,
                          {"sector": item.get("sector"), "name": item.get("name")})


@check("CAT-03")
def cat_03(ctx: AuditContext):
    seen_isin: dict[str, str] = {}
    for item in ctx.published_catalog.get("items") or []:
        isin = str(item.get("isin") or "").upper()
        if not isin:
            continue
        if isin in seen_isin:
            yield Finding("CAT-03", "ISIN встречается у двух тикеров", item.get("ticker"),
                          "isin", None, None, None, {"isin": isin, "other": seen_isin[isin]})
        else:
            seen_isin[isin] = str(item.get("ticker"))


@check("CAT-04")
def cat_04(ctx: AuditContext):
    known = {str(i.get("ticker") or "").upper() for i in (ctx.published_catalog.get("items") or [])}
    for row in ctx.board:
        ticker = str(row.get("ticker") or "").upper()
        traded = (ind.num(row.get("trade_count")) or 0) > 0
        if traded and ticker not in known:
            yield Finding("CAT-04", "бумага торговалась, но отсутствует в каталоге", ticker,
                          "catalog", None, None, None, {"trades": row.get("trade_count")})


@check("CAT-05")
def cat_05(ctx: AuditContext):
    by_issuer: dict[str, list[dict[str, Any]]] = {}
    for row in ctx.published_multiples:
        by_issuer.setdefault(str(row.get("issuer") or ""), []).append(row)
    for issuer, rows in by_issuer.items():
        classes = {str(r.get("share_class")) for r in rows}
        if classes == {"preferred"}:
            yield Finding("CAT-05", "привилегированный класс без обыкновенного",
                          ", ".join(str(r.get("ticker")) for r in rows), "issuer",
                          None, None, None, {"issuer": issuer})


@check("CAT-06")
def cat_06(ctx: AuditContext):
    for item in ctx.published_catalog.get("items") or []:
        if item.get("is_active") and not item.get("shares_outstanding"):
            yield Finding("CAT-06", "не заполнено количество бумаг в выпуске", item.get("ticker"),
                          "shares_outstanding", None, None, None, {})


# ===========================================================================
# XSC — the screens must agree with each other
# ===========================================================================

@check("XSC-01")
def xsc_01(ctx: AuditContext):
    board = _board_by_ticker(ctx)
    for tile in ctx.published_map.get("tiles") or []:
        ticker = str(tile.get("ticker") or "").upper()
        a = ind.num(tile.get("last_price"))
        b = ind.num((board.get(ticker) or {}).get("last_price"))
        gap = ind.relative_gap(a, b)
        if (a is None) != (b is None) or (gap is not None and gap > 0.0001):
            yield Finding("XSC-01", "последняя цена различается между картой и таблицей",
                          ticker, "last_price", b, a, gap, {"map": a, "table": b})


@check("XSC-02")
def xsc_02(ctx: AuditContext):
    board = _board_by_ticker(ctx)
    for tile in ctx.published_map.get("tiles") or []:
        ticker = str(tile.get("ticker") or "").upper()
        row = board.get(ticker) or {}
        mine = ind.day_change(row.get("last_price"), row.get("close_price"))
        shown = ind.num(tile.get("change_pct"))
        if mine is None and shown is None:
            continue
        if mine is None or shown is None or abs(mine - shown) > 0.01:
            yield Finding("XSC-02", "дневное изменение различается между картой и таблицей",
                          ticker, "change_pct", mine, shown,
                          None if None in (mine, shown) else abs(mine - shown), {})


@check("XSC-03")
def xsc_03(ctx: AuditContext):
    """The automatic form of the ТЗ's main invariant.

    Ask for a security's metrics under each of the six periods and confirm the
    absolute block comes back byte-identical. This one test closes the most
    widespread defect in the registry: YTD moved on 83 of 84 securities and
    changed sign on 46 of them.
    """
    for ticker, by_period in (ctx.published_metrics_by_period or {}).items():
        blocks = list(by_period.items())
        if len(blocks) < 2:
            continue
        reference_months, reference = blocks[0]
        for months, block in blocks[1:]:
            if block != reference:
                differing = sorted(k for k in set(list(block) + list(reference))
                                   if block.get(k) != reference.get(k))
                yield Finding("XSC-03", "абсолютные метрики изменились при смене периода",
                              ticker, ", ".join(differing) or "absolute", None, None, None,
                              {"period_a": reference_months, "period_b": months,
                               "metrics": differing})
                break


@check("XSC-04")
def xsc_04(ctx: AuditContext):
    board = _board_by_ticker(ctx)
    for row in ctx.published_multiples:
        ticker = str(row.get("ticker") or "").upper()
        a = ind.num(row.get("market_cap_class"))
        b = ind.num((board.get(ticker) or {}).get("market_cap"))
        gap = ind.relative_gap(a, b)
        if gap is not None and gap > 0.1:
            yield Finding("XSC-04", "капитализация в мультипликаторах и на доске различается",
                          ticker, "market_cap", b, a, gap, {})


@check("XSC-05")
def xsc_05(ctx: AuditContext):
    header = ind.num((ctx.published_summary or {}).get("instruments"))
    rows = ind.num((ctx.published_map.get("counts") or {}).get("tiles"))
    if header is not None and rows is not None and abs(header - rows) > 0.5:
        yield Finding("XSC-05", "число инструментов в шапке не равно числу строк", None,
                      "instruments", rows, header, abs(header - rows), {})


# ===========================================================================
# BND — the bond contour (Дополнение 1 §А.7)
# ===========================================================================

def _bond_tickers(ctx: AuditContext) -> set[str]:
    out = set()
    for row in ctx.board:
        ticker = str(row.get("ticker") or "").upper()
        meta = ctx.securities.get(ticker) or {}
        if str(row.get("type") or meta.get("type") or "").lower() == "bond":
            out.add(ticker)
    return out


@check("BND-01")
def bnd_01(ctx: AuditContext):
    """A bond whose class says `ordinary` falls into the equity branches of the
    code — which is how nine issues came to carry an equity capitalisation."""
    for row in ctx.board:
        ticker = str(row.get("ticker") or "").upper()
        meta = ctx.securities.get(ticker) or {}
        if str(row.get("type") or meta.get("type") or "").lower() != "bond":
            continue
        declared = str(row.get("share_type") or meta.get("share_type") or "").lower()
        if declared and not declared.startswith("bond"):
            yield Finding("BND-01", "у облигации класс инструмента не bond", ticker,
                          "share_class", None, None, None, {"share_type": declared})


@check("BND-02")
def bnd_02(ctx: AuditContext):
    """Equity multiples on a debt instrument are not empty — they are undefined."""
    bonds = _bond_tickers(ctx)
    for row in ctx.published_multiples:
        ticker = str(row.get("ticker") or "").upper()
        if ticker not in bonds:
            continue
        for metric in ("pe", "pb", "roe"):
            if _value(row.get(metric)) is not None:
                yield Finding("BND-02", f"у облигации опубликован {metric}", ticker, metric,
                              None, _value(row.get(metric)), None, {})


@check("BND-03")
def bnd_03(ctx: AuditContext):
    """Issue value may never be summed into the equity market's capitalisation."""
    cap = ctx.published_summary.get("market_cap") or {}
    total = ind.num(cap.get("value"))
    if total is None:
        return
    issue_value = 0.0
    tickers: list[str] = []
    for row in ctx.board:
        ticker = str(row.get("ticker") or "").upper()
        if ticker not in _bond_tickers(ctx):
            continue
        value = ind.num(row.get("market_cap"))
        if value:
            issue_value += value
            tickers.append(ticker)
    if issue_value <= 0:
        return
    reported = ind.num(((cap.get("excluded") or {}).get("bonds") or {}).get("amount")) or 0.0
    if abs(reported - issue_value) > max(1.0, issue_value * 0.001):
        yield Finding("BND-03", "стоимость выпусков не исключена из капитализации акций",
                      None, "market_cap", issue_value, reported, abs(issue_value - reported),
                      {"bond_tickers": tickers[:20], "issue_value": issue_value})


@check("BND-04")
def bnd_04(ctx: AuditContext):
    for row in ctx.published_bonds:
        reference = row.get("reference") or {}
        if not reference.get("is_complete"):
            yield Finding("BND-04", "справочник выпуска не заполнен", row.get("ticker"),
                          "reference", None, None, None, {"missing": reference.get("missing")})


@check("BND-05")
def bnd_05(ctx: AuditContext):
    today = ctx.today or date.today()
    for row in ctx.published_bonds:
        reference = ctx.bond_references.get(str(row.get("ticker") or "").upper()) or {}
        maturity = ind.day(reference.get("maturity_date"))
        if maturity and maturity < today and row.get("status") == "ok":
            yield Finding("BND-05", "выпуск погашен, но торгуется и не помечен",
                          row.get("ticker"), "maturity_date", None, None, None,
                          {"maturity_date": str(maturity)})


@check("BND-06")
def bnd_06(ctx: AuditContext):
    bounds = ind.threshold("bonds.price_pct_range", [20, 200]) or [20, 200]
    for row in ctx.published_bonds:
        pct = _value(row.get("price_pct"))
        if pct is None:
            continue
        if not (float(bounds[0]) <= pct <= float(bounds[1])):
            yield Finding("BND-06", "цена далеко за пределами коридора от номинала",
                          row.get("ticker"), "price_pct", None, pct, None,
                          {"price_pct": pct, "allowed": bounds})


@check("BND-07")
def bnd_07(ctx: AuditContext):
    for ticker, coupons in (ctx.bond_coupons or {}).items():
        periods = []
        for coupon in coupons:
            start, end = ind.day(coupon.get("period_from")), ind.day(coupon.get("period_to"))
            if start and end:
                periods.append((start, end, coupon.get("coupon_no")))
        periods.sort()
        for (_a_start, a_end, a_no), (b_start, _b_end, b_no) in zip(periods, periods[1:]):
            if b_start < a_end:
                yield Finding("BND-07", "купонные периоды пересекаются", ticker, "coupons",
                              None, None, None, {"coupons": [a_no, b_no]})
            elif (b_start - a_end).days > 1:
                yield Finding("BND-07", "между купонными периодами разрыв", ticker, "coupons",
                              None, float((b_start - a_end).days), None,
                              {"coupons": [a_no, b_no], "gap_days": (b_start - a_end).days})


@check("BND-08")
def bnd_08(ctx: AuditContext):
    for row in ctx.published_bonds:
        if (row.get("ytm") or {}).get("status") == "not_converged":
            yield Finding("BND-08", "доходность к погашению не сошлась", row.get("ticker"),
                          "ytm", None, None, None, {})


@check("BND-09")
def bnd_09(ctx: AuditContext):
    for row in ctx.published_bonds:
        accrued = _value(row.get("accrued"))
        reference = ctx.bond_references.get(str(row.get("ticker") or "").upper()) or {}
        nominal, rate = ind.num(reference.get("nominal")), ind.num(reference.get("coupon_rate"))
        freq = ind.num(reference.get("coupon_freq")) or 1
        if accrued is None or nominal is None or rate is None:
            continue
        period_coupon = nominal * rate / 100.0 / freq
        if accrued > period_coupon * 1.001:
            yield Finding("BND-09", "НКД превышает купон за период", row.get("ticker"),
                          "accrued", period_coupon, accrued, accrued - period_coupon, {})


@check("BND-10")
def bnd_10(ctx: AuditContext):
    """Recompute the yield by bisection — a different method from production's
    Newton iteration, which is the point of checking it at all."""
    tol = ind.threshold("audit.ytm_tolerance", 0.05)
    for row in ctx.published_bonds:
        published = _value(row.get("ytm"))
        flows = row.get("cashflows")
        dirty = _value(row.get("dirty"))
        if published is None or not flows or not dirty:
            continue
        mine = ind.ytm_bisection([(float(t), float(c)) for t, c in flows], float(dirty))
        if mine is None:
            continue
        if abs(mine - published) > tol:
            yield Finding("BND-10", "независимый пересчёт доходности не совпал",
                          row.get("ticker"), "ytm", mine, published, abs(mine - published),
                          {"dirty": dirty, "cashflows": flows[:8]})


@check("BND-11")
def bnd_11(ctx: AuditContext):
    for row in ctx.published_bonds:
        traded = (ind.num(row.get("trades")) or 0) > 0 or (ind.num(row.get("turnover")) or 0) > 0
        if traded and row.get("price") is None:
            yield Finding("BND-11", "есть сделки, но нет цены", row.get("ticker"), "price",
                          None, None, None,
                          {"trades": row.get("trades"), "turnover": row.get("turnover")})


@check("BND-12")
def bnd_12(ctx: AuditContext):
    for row in ctx.published_bonds:
        if not row.get("day_count_basis"):
            yield Finding("BND-12", "в ответе не указан базис расчёта дней", row.get("ticker"),
                          "day_count_basis", None, None, None, {})


# ===========================================================================
# SRC — the reporting catalog as a provenance layer (Дополнение 1 §Б.8)
# ===========================================================================

@check("SRC-01")
def src_01(ctx: AuditContext):
    summary = ctx.published_catalog_reports or {}
    if not summary:
        return
    header = ind.num(summary.get("issuers"))
    listed = len(summary.get("items") or [])
    if header is not None and abs(header - listed) > 0.5:
        yield Finding("SRC-01", "счётчик в шапке не равен длине списка", None, "issuers",
                      float(listed), header, abs(header - listed), {})


@check("SRC-02")
def src_02(ctx: AuditContext):
    summary = ctx.published_catalog_reports or {}
    if not summary:
        return
    header = ind.num(summary.get("reports_total"))
    per_issuer = sum(ind.num(i.get("reports")) or 0 for i in (summary.get("items") or []))
    if header is not None and abs(header - per_issuer) > 0.5:
        yield Finding("SRC-02", "сумма отчётов по эмитентам не равна общей", None,
                      "reports_total", per_issuer, header, abs(header - per_issuer), {})


@check("SRC-03")
def src_03(ctx: AuditContext):
    """Every published figure must name the report it came from.

    Until it does, "where did this revenue come from" has no answer, and that
    gap is where the whole FIN group of defects grew.
    """
    for ticker, fin in ctx.financials.items():
        if fin and not fin.get("report_id"):
            yield Finding("SRC-03", "у публикуемого числа нет ссылки на отчёт", ticker,
                          "report_id", None, None, None,
                          {"year": fin.get("year"), "quarter": fin.get("quarter")})


@check("SRC-04")
def src_04(ctx: AuditContext):
    for report in ctx.source_reports or []:
        used = (report.get("used_by") or {}).get("financials")
        if report.get("state") in ("rejected", "parse_failed") and used:
            yield Finding("SRC-04", "отклонённый отчёт используется в публикуемых числах",
                          report.get("org_id"), "report", None, None, None,
                          {"report_id": report.get("id"), "state": report.get("state")})


@check("SRC-05")
def src_05(ctx: AuditContext):
    summary = ctx.published_catalog_reports or {}
    hours = ind.num(summary.get("staleness_hours"))
    limit = ind.num(summary.get("staleness_warn_hours")) or 24.0
    if hours is not None and hours > limit:
        yield Finding("SRC-05", "каталог отчётности устарел", None, "staleness_hours",
                      limit, hours, hours - limit, {"last_sync": summary.get("last_sync")})


@check("SRC-06")
def src_06(ctx: AuditContext):
    for issuer in (ctx.published_catalog_reports or {}).get("items") or []:
        if not issuer.get("synced_at"):
            yield Finding("SRC-06", "эмитент ни разу не синхронизирован", issuer.get("org_id"),
                          "synced_at", None, None, None, {"name": issuer.get("name")})


@check("SRC-07")
def src_07(ctx: AuditContext):
    """A bond series must show its ISSUER's filings, not a zero."""
    for issuer in (ctx.published_catalog_reports or {}).get("items") or []:
        if (ind.num(issuer.get("reports")) or 0) == 0 and issuer.get("org_id"):
            yield Finding("SRC-07", "у эмитента ноль отчётов при наличии бумаг",
                          issuer.get("org_id"), "reports", None, 0.0, None,
                          {"name": issuer.get("name")})


@check("SRC-08")
def src_08(ctx: AuditContext):
    if ctx.parse_queue is None:
        return
    current = len(ctx.parse_queue)
    previous = ind.num((ctx.previous_counters or {}).get("parse_queue"))
    if previous is not None and current > previous:
        yield Finding("SRC-08", "очередь неразобранных отчётов выросла", None, "parse_queue",
                      previous, float(current), current - previous, {})


@check("SRC-09")
def src_09(ctx: AuditContext):
    for report in ctx.source_reports or []:
        if report.get("state") in ("published", "validated") and not (
                report.get("pdf_url") or report.get("excel_url")):
            yield Finding("SRC-09", "у опубликованного отчёта нет ссылки на первоисточник",
                          report.get("org_id"), "pdf_url", None, None, None,
                          {"report_id": report.get("id")})


@check("SRC-10")
def src_10(ctx: AuditContext):
    """The unit scale recorded at parse time must match what is published.

    This is the FIN-06 defect caught one layer earlier: the parser knows it read
    a figure in thousands, and if publication forgets that, the two disagree by
    exactly a thousand.
    """
    for report in ctx.source_reports or []:
        ticker = str(report.get("ticker") or "").upper()
        published_row = ctx.financials.get(ticker) or {}
        for figure in report.get("figures") or []:
            scale = ind.num(figure.get("unit_scale")) or 1.0
            parsed = ind.num(figure.get("value"))
            published = ind.num(published_row.get(figure.get("field")))
            if published is None or not parsed:
                continue
            implied = published / parsed
            if abs(implied - scale) > max(0.01, scale * 0.01):
                yield Finding("SRC-10", "масштаб единиц при публикации не совпал с разбором",
                              ticker, figure.get("field"), scale, implied,
                              abs(implied - scale), {"report_id": report.get("id")})
