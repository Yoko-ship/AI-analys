"""The ГЦБ primary market and the base curve it builds.

The fiscal agent publishes every placement — tenor, maturity, placed volume,
weighted-average rate. Those rows are the only public curve of the UZS market,
and every corporate bond's G-spread is its yield read against them. The tests
pin three things: the Bitrix grid parser reads the page by its own column
titles, the curve takes each tenor's FRESHEST auction and refuses to
extrapolate, and the new risk metrics stay inert without their inputs.
"""
from __future__ import annotations

from datetime import date

import pytest

import bonds
import gov_bonds_collector as gc


def _cell(prop: str, value: str) -> str:
    return (f'<td class="main-grid-cell main-grid-cell-left" data-column-id="{prop}"'
            f'data-editable="true"style="" ><div class="main-grid-cell-inner">'
            f'<span class="main-grid-cell-content" data-prevent-default="true" >{value}</span>'
            f'</div></td>')


def _head(prop: str, title: str) -> str:
    return (f'<th class="main-grid-cell-head" data-name="{prop}"data-sort-by="{prop}">'
            f'<div class="main-grid-head-container"><span class="main-grid-head-title">'
            f'{title}</span></div></th>')


PAGE = (
    '<table><tr class="main-grid-row-head">'
    + _head("PROPERTY_1", "Дата размещения")
    + _head("PROPERTY_2", "Идентификационный номер")
    + _head("PROPERTY_3", "ISIN код")
    + _head("PROPERTY_4", "Объем выпуска (млрд. сум)")
    + _head("PROPERTY_5", "Срок обращения (дней)")
    + _head("PROPERTY_6", "Дата погашения облигаций")
    + _head("PROPERTY_7", "Вид дохода по обязательствам")
    + _head("PROPERTY_8", "Число дилеров")
    + _head("PROPERTY_9", "Количество размещенных ГЦБ")
    + _head("PROPERTY_10", "Сумма размещения (млрд. сум)")
    + _head("PROPERTY_11", "Средневзвешенная процентная ставка")
    + _head("PROPERTY_12", "Минимальная процентная ставка")
    + _head("PROPERTY_13", "Максимальная процентная ставка")
    + '</tr>'
    + '<tr class="main-grid-row main-grid-row-body" data-id="1" >'
    + _cell("PROPERTY_1", "06.08.2026") + _cell("PROPERTY_2", "28046UMFS")
    + _cell("PROPERTY_3", "UZA000006363") + _cell("PROPERTY_4", "3000")
    + _cell("PROPERTY_5", "1095") + _cell("PROPERTY_6", "05.08.2029")
    + _cell("PROPERTY_7", "Купон") + _cell("PROPERTY_8", "3")
    + _cell("PROPERTY_9", "600000") + _cell("PROPERTY_10", "611.73")
    + _cell("PROPERTY_11", "12.28") + _cell("PROPERTY_12", "12.19")
    + _cell("PROPERTY_13", "12.35")
    + '</tr>'
    + '<tr class="main-grid-row main-grid-row-body" data-id="2" >'
    + _cell("PROPERTY_1", "06.08.2026") + _cell("PROPERTY_2", "24138UMFS")
    + _cell("PROPERTY_3", "UZA000006355") + _cell("PROPERTY_4", "1000")
    + _cell("PROPERTY_5", "364") + _cell("PROPERTY_6", "05.08.2027")
    + _cell("PROPERTY_7", "Дисконт") + _cell("PROPERTY_8", "2")
    + _cell("PROPERTY_9", "340000") + _cell("PROPERTY_10", "304.26")
    + _cell("PROPERTY_11", "11.89") + _cell("PROPERTY_12", "11.64")
    + _cell("PROPERTY_13", "12.00")
    + '</tr></table>'
)


class TestParser:
    def test_rows_are_read_by_the_pages_own_column_titles(self):
        rows = gc.parse_auction_rows(PAGE, "https://example/fa")
        assert len(rows) == 2
        coupon, discount = rows
        assert coupon["sec_id"] == "28046UMFS"
        assert coupon["auction_date"] == "2026-08-06"
        assert coupon["maturity_date"] == "2029-08-05"
        assert coupon["term_days"] == 1095
        assert coupon["income_type"] == "coupon"
        assert coupon["wavg_rate"] == pytest.approx(12.28)
        assert coupon["placed_value"] == pytest.approx(611.73)
        assert discount["income_type"] == "discount"
        assert discount["source_url"] == "https://example/fa"

    def test_property_numbers_do_not_matter_titles_do(self):
        """A site rebuild renumbers PROPERTY_* — the parse must survive it."""
        renumbered = PAGE.replace("PROPERTY_1", "PROPERTY_9101").replace(
            "PROPERTY_2", "PROPERTY_9102")
        rows = gc.parse_auction_rows(renumbered)
        assert rows and rows[0]["sec_id"] == "28046UMFS"
        assert rows[0]["auction_date"] == "2026-08-06"

    def test_a_page_without_the_grid_parses_to_nothing(self):
        assert gc.parse_auction_rows("<html><body>404</body></html>") == []


def _auction(day: str, term: int, rate: float, sec_id: str = "X") -> dict:
    return {"auction_date": day, "term_days": term, "wavg_rate": rate,
            "sec_id": sec_id, "isin": None}


class TestCurve:
    TODAY = date(2026, 8, 14)

    def test_freshest_auction_per_tenor_wins(self):
        points = bonds.gov_curve_points([
            _auction("2026-07-02", 364, 12.01, "old364"),
            _auction("2026-08-06", 364, 11.89, "new364"),
            _auction("2026-08-06", 1095, 12.28, "new1095"),
        ], today=self.TODAY)
        assert [(p["term_days"], p["rate"]) for p in points] == [(364, 11.89), (1095, 12.28)]
        assert points[0]["sec_id"] == "new364"

    def test_an_auction_outside_the_window_is_not_the_curve(self):
        """A rate from another monetary regime must not pose as current."""
        points = bonds.gov_curve_points(
            [_auction("2025-01-09", 182, 13.9)], today=self.TODAY)
        assert points == []

    def test_interpolation_is_linear_and_clamped(self):
        points = [{"term_days": 364, "rate": 11.89}, {"term_days": 1095, "rate": 12.28}]
        mid_days = (364 + 1095) / 2
        mid = bonds.gov_curve_yield(mid_days / 365.0, points)
        assert mid == pytest.approx((11.89 + 12.28) / 2)
        # Clamped, not extrapolated: beyond the auctioned tenors there is no
        # market evidence to extend a straight line into.
        assert bonds.gov_curve_yield(0.1, points) == pytest.approx(11.89)
        assert bonds.gov_curve_yield(10.0, points) == pytest.approx(12.28)
        assert bonds.gov_curve_yield(None, points) is None
        assert bonds.gov_curve_yield(2.0, []) is None

    def test_g_spread_names_the_curve_it_was_read_against(self):
        points = [{"term_days": 364, "rate": 12.0}, {"term_days": 1095, "rate": 12.0}]
        spread = bonds.g_spread(20.0, 2.0, points)
        assert spread["status"] == "ok"
        assert spread["value"] == pytest.approx(8.0)
        assert spread["curve_rate"] == pytest.approx(12.0)

    def test_without_a_curve_the_spread_says_so(self):
        spread = bonds.g_spread(20.0, 2.0, [])
        assert spread["value"] is None
        assert spread["status"] == "no_curve"


class TestRiskMetrics:
    def test_convexity_and_bpv_positive_for_a_plain_bond(self):
        flows = [(0.5, 10.0), (1.0, 110.0)]
        cvx = bonds.convexity(flows, 100.0, 12.0)
        assert cvx["status"] == "ok" and cvx["value"] > 0
        assert bonds.bpv(1.8, 100_000.0)["value"] == pytest.approx(18.0)

    def test_inert_without_inputs(self):
        assert bonds.convexity([], 100.0, 12.0)["value"] is None
        assert bonds.bpv(None, 100.0)["value"] is None
        assert bonds.bpv(1.8, None)["value"] is None

    def test_bond_row_carries_the_new_metrics_only_with_a_complete_reference(self):
        row = bonds.bond_row({"ticker": "ACMT2B5", "type": "bond",
                              "last_price": 100_000.0, "close_price": 100_000.0})
        for field in ("convexity", "bpv", "g_spread"):
            assert row[field]["value"] is None
            assert row[field]["status"] == bonds.STATUS_NO_REFERENCE
