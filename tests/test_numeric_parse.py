"""Separator rules for published amounts — the 1000x class of bug.

The regression this pins: ``_safe_report_number`` turned "1,234,567" into
1234.567, and that figure flowed into every served Excel/PDF cell and into P/E.
"""
from __future__ import annotations

import pytest

from numeric_parse import parse_decimal


class TestCommaGrouping:
    """Rule 2: a repeated separator is a thousands mark, never a decimal point."""

    @pytest.mark.parametrize(("text", "expected"), [
        ("1,234,567", 1_234_567.0),
        ("12,345,678", 12_345_678.0),
        ("123,456,789", 123_456_789.0),
        ("1,234,567,890", 1_234_567_890.0),
        ("1.234.567", 1_234_567.0),
        ("999,999", 999_999.0),
    ])
    def test_grouped_integers(self, text: str, expected: float) -> None:
        assert parse_decimal(text) == expected

    def test_the_exact_regression(self) -> None:
        # Was 1234.567 — a 1000x understatement that made P/E read 1000x high.
        assert parse_decimal("1,234,567") == pytest.approx(1_234_567.0)


class TestMixedSeparators:
    """Rule 1: with both present the rightmost separator is the decimal point."""

    @pytest.mark.parametrize(("text", "expected"), [
        ("1,234,567.89", 1_234_567.89),
        ("1.234.567,89", 1_234_567.89),
        ("1 234 567,89", 1_234_567.89),
        ("1 234 567.89", 1_234_567.89),
        ("12.345,6", 12_345.6),
        ("12,345.6", 12_345.6),
    ])
    def test_mixed(self, text: str, expected: float) -> None:
        assert parse_decimal(text) == pytest.approx(expected)


class TestSpaceGrouping:
    @pytest.mark.parametrize(("text", "expected"), [
        ("1 234 567", 1_234_567.0),
        ("1\xa0234\xa0567", 1_234_567.0),
        ("1 234 567", 1_234_567.0),
        ("2 291 908 931", 2_291_908_931.0),
    ])
    def test_spaces(self, text: str, expected: float) -> None:
        assert parse_decimal(text) == expected


class TestDecimalComma:
    """A lone separator with a non-3-digit tail is always a decimal point."""

    @pytest.mark.parametrize(("text", "expected"), [
        ("1,5", 1.5),
        ("12,34", 12.34),
        ("0,05", 0.05),
        ("952,2", 952.2),
        ("4757,9", 4757.9),
        ("1234,56", 1234.56),
    ])
    def test_decimal_comma(self, text: str, expected: float) -> None:
        assert parse_decimal(text) == pytest.approx(expected)

    def test_lone_dot_is_a_decimal_point(self) -> None:
        # Prices from the exchange board: 1.234 is one and a bit, not 1234.
        assert parse_decimal("1.234") == pytest.approx(1.234)
        assert parse_decimal("12345.67") == pytest.approx(12345.67)

    def test_group_sep_declares_the_ambiguous_shape(self) -> None:
        assert parse_decimal("1,234", group_sep=",") == 1234.0
        assert parse_decimal("1,234", group_sep="") == pytest.approx(1.234)
        assert parse_decimal("1.234", group_sep=".") == 1234.0


class TestSigns:
    @pytest.mark.parametrize(("text", "expected"), [
        ("(1 234)", -1234.0),
        ("(1,234,567)", -1_234_567.0),
        ("-1 234 567", -1_234_567.0),
        ("−12,5", -12.5),          # U+2212 needs pre-normalisation by the caller
        ("1 234-", -1234.0),
        ("+1 234", 1234.0),
    ])
    def test_signs(self, text: str, expected: float) -> None:
        got = parse_decimal(text.replace("−", "-"))
        assert got == pytest.approx(expected)


class TestNonNumbers:
    @pytest.mark.parametrize("text", ["", "   ", "-", "—", "–", "n/a", None])
    def test_blank_and_dashes(self, text) -> None:
        assert parse_decimal(text) is None

    @pytest.mark.parametrize("text", [
        "стр. 180",            # a line-code label, NOT the number 180
        "Код стр",
        "Чистая прибыль",
        "2024-2025",           # a period range
        "n/a",
    ])
    def test_strict_rejects_labels(self, text: str) -> None:
        assert parse_decimal(text, strip_non_numeric=False) is None

    def test_lenient_mode_extracts_from_html_cells(self) -> None:
        # uzse.uz board cells carry unit suffixes; that path opts into stripping.
        assert parse_decimal("1 234 567 UZS", strip_non_numeric=True) == 1_234_567.0
        assert parse_decimal("12 345,67 сум", strip_non_numeric=True) == pytest.approx(12_345.67)

    def test_booleans_are_not_numbers(self) -> None:
        assert parse_decimal(True) is None
        assert parse_decimal(False) is None

    def test_numeric_passthrough(self) -> None:
        assert parse_decimal(1234) == 1234.0
        assert parse_decimal(-12.5) == pytest.approx(-12.5)

    def test_absurd_magnitudes_are_rejected(self) -> None:
        assert parse_decimal(1e31) is None
        assert parse_decimal("1" + "0" * 40) is None


class TestPercent:
    def test_percent_is_stripped_to_the_bare_number(self) -> None:
        assert parse_decimal("12,5%") == pytest.approx(12.5)
        assert parse_decimal("-3,2%") == pytest.approx(-3.2)


class TestCallerContracts:
    """The two production callers keep the behaviour their sources need."""

    def test_openinfo_report_cells(self) -> None:
        from collectors.openinfo.cells import _safe_report_number

        assert _safe_report_number("1,234,567") == 1_234_567.0
        assert _safe_report_number("1 234 567,89") == pytest.approx(1_234_567.89)
        assert _safe_report_number("(1,234)") == -1234.0
        assert _safe_report_number("стр. 180") is None
        assert _safe_report_number(None) is None

    def test_uzse_board_cells(self) -> None:
        from uzse_parser import _parse_number

        assert _parse_number("1,234,567") == 1_234_567.0
        assert _parse_number("12 345,67") == pytest.approx(12_345.67)
        assert _parse_number("1.234") == pytest.approx(1.234)
        assert _parse_number("") is None

    def test_reconciler_figures(self) -> None:
        from openinfo_reconcile import _num

        assert _num("1,234,567") == 1_234_567.0
        assert _num(None) is None
        assert _num("None") is None
        assert _num("-") is None
