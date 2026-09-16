"""Which balance-sheet line the xlsx parse reads for cash and obligations.

The board's figures come from the structured-JSON reconciler, but this parse is
not a dead second opinion: prod re-derives a stale row from the report Excel in
the background on every market load, so a disagreement here surfaces later as a
figure that changes on its own. Both selectors must name the same two lines —
«Денежные средства на расчетном счете (5100)» and the published obligations
subtotal — and the cases below are the ones where a naive read picks another.
"""
from __future__ import annotations

import pytest

import reports_catalog as rc


def _sheet(rows: list[tuple[str, list]]) -> dict:
    return {"sheets": [{"table_rows": [{"label": label, "numeric_values": nums}
                                       for label, nums in rows]}]}


# Cells as the parser hands them over: [line code, opening balance, period end].
def _row(code: str, label: str, end: float, begin: float = 0.0) -> tuple[str, list]:
    return (label, [float(code), begin, end])


class TestCashLine:
    def test_the_settlement_account_wins_over_the_roll_up(self) -> None:
        balance = _sheet([
            _row("320", "Денежные средства, всего (стр.330+340+350+360), в том числе:",
                 1_181_472_863.0),
            _row("330", "Денежные средства в кассе (5000)", 2_210_190.0),
            _row("340", "Денежные средства на расчетном счете (5100)", 48_214_510.0),
            _row("350", "Денежные средства в иностранной валюте (5200)", 608_537_783.0),
        ])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["cash"] == 48_214_510.0

    def test_an_account_emptied_by_the_reporting_date_reads_zero(self) -> None:
        # Not the opening balance beside it: that is a sum the issuer no longer has.
        balance = _sheet([
            _row("340", "Денежные средства на расчетном счете (5100)", 0.0, 27_377_071.98),
        ])
        assert rc.compute_financial_ratios(None, balance)["source_values"]["cash"] == 0.0

    def test_a_zero_account_beside_a_filled_breakdown_stays_zero(self) -> None:
        # SANE 2026 Q2: the operating account is empty and the money sits in
        # equivalents — a real position, not a gap in the filing.
        balance = _sheet([
            _row("320", "Денежные средства, всего (стр.330+340+350+360)", 490_000.0),
            _row("330", "Денежные средства в кассе (5000)", 0.0),
            _row("340", "Денежные средства на расчетном счете (5100)", 0.0, 103_006.0),
            _row("360", "Денежные средства и эквиваленты (5500, 5800, 5700)", 490_000.0),
        ])
        assert rc.compute_financial_ratios(None, balance)["source_values"]["cash"] == 0.0

    def test_a_roll_up_with_no_breakdown_at_all_stands_in(self) -> None:
        # AGMK 2026 Q2: 688 238 787 in cash and not one of the accounts under it
        # filled in. Serving 0 there would say the company banks nothing.
        balance = _sheet([
            _row("320", "Денежные средства, всего (стр.330+340+350+360)", 688_238_787.0),
            _row("330", "Денежные средства в кассе (5000)", 0.0),
            _row("340", "Денежные средства на расчетном счете (5100)", 0.0),
            _row("350", "Денежные средства в иностранной валюте (5200)", 0.0),
            _row("360", "Денежные средства и эквиваленты (5500, 5800, 5700)", 0.0),
        ])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["cash"] == 688_238_787.0

    def test_a_bank_form_falls_back_to_its_own_cash_line(self) -> None:
        balance = _sheet([("Кассовая наличность и другие платежные документы",
                           [2_611_622_842.0, 2_455_155_322.0])])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["cash"] == 2_455_155_322.0


class TestObligationsLine:
    def test_the_published_subtotal_beats_re_adding_the_parts(self) -> None:
        balance = _sheet([
            _row("490", "Долгосрочные обязательства, всего (стр.500+520)", 0.0, 9_000_000.0),
            _row("600", "Текущие обязательства, всего (стр.610+630)", 21_324_562.0),
            _row("770", "ИТОГО ПО II РАЗДЕЛУ (стр. 490+600)", 21_324_562.0),
        ])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["total_liabilities"] == 21_324_562.0

    def test_the_insurance_subtotal_is_found_through_its_spacing(self) -> None:
        balance = _sheet([
            _row("730", "Долгосрочные обязательства, всего (стр. 740 + 750)", 588_919.95),
            _row("930", "Текущие обязательства, всего (стр. 940+950)", 55_560_337.20),
            _row("1190", "Итого по разделу III (стр. 730 + 930)", 56_149_257.14),
        ])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["total_liabilities"] == 56_149_257.14

    def test_insurance_reserves_are_added_to_ordinary_liabilities(self) -> None:
        balance = _sheet([
            _row("490", "Всего по активу баланса (стр.130+480)", 346_556_015.4),
            _row("570", "Итого по разделу I (стр.500+510+520-530+540+550+560)", 146_745_491.4),
            _row("580", "Страховые резервы, всего (стр.590+600+610+620+630+640+650+660)", 301_088_114.6),
            _row("670", "Доля перестраховщиков в страховых резервах, Всего(стр.680+690+700+710)", 171_910_842.4),
            _row("720", "Итого по разделу II (стр.580-670)", 129_177_272.2),
            _row("1190", "Итого по разделу III (стр.730+930)", 70_633_251.8),
        ])

        out = rc.compute_financial_ratios(None, balance)
        source = out["source_values"]

        assert source["gross_insurance_reserves"] == pytest.approx(301_088_114.6)
        assert source["reinsurer_share_in_reserves"] == pytest.approx(171_910_842.4)
        assert source["net_insurance_reserves"] == pytest.approx(129_177_272.2)
        assert source["other_liabilities"] == pytest.approx(70_633_251.8)
        assert source["total_liabilities"] == pytest.approx(199_810_524.0)
        assert source["total_equity"] == pytest.approx(146_745_491.4)
        assert source["balance"]["assets_end"] == pytest.approx(346_556_015.4)

    def test_the_asset_side_subtotal_is_not_mistaken_for_it(self) -> None:
        balance = _sheet([
            _row("390", "ИТОГО ПО РАЗДЕЛУ II (стр. 140+190+200+210+320+370+380)",
                 4_570_266_623.0),
            _row("490", "Долгосрочные обязательства, всего (стр.500+520)", 5_468_406_669.0),
            _row("600", "Текущие обязательства, всего (стр.610+630)", 2_896_064_498.0),
            _row("770", "ИТОГО ПО II РАЗДЕЛУ (стр. 490+600)", 8_364_471_166.0),
        ])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["total_liabilities"] == 8_364_471_166.0

    def test_a_form_stating_its_total_outright_still_wins(self) -> None:
        balance = _sheet([("Итого обязательств", [97_442_300_703.0, 104_560_786_862.0])])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["total_liabilities"] == 104_560_786_862.0

    def test_without_any_total_the_parts_are_added_up(self) -> None:
        balance = _sheet([
            _row("490", "Долгосрочные обязательства, всего (стр.500+520)", 1000.0),
            _row("600", "Текущие обязательства, всего (стр.610+630)", 250.0),
        ])
        out = rc.compute_financial_ratios(None, balance)
        assert out["source_values"]["total_liabilities"] == 1250.0


class TestTheRowReaderItself:
    """`strict_period` is what keeps a real zero from becoming last year's figure."""

    @pytest.mark.parametrize(("cells", "expected"), [
        ([340.0, 663_180.0, 560_655.0], 560_655.0),   # ordinary code | begin | end
        ([340.0, 663_180.0, 0.0], 0.0),               # emptied by the reporting date
        ([663_180.0, 560_655.0], 560_655.0),          # no line-code cell
    ])
    def test_strict_reads_the_reporting_column_only(self, cells, expected) -> None:
        assert rc._row_value(cells, strict_period=True) == expected

    def test_a_total_may_still_fall_back_to_the_opening_column(self) -> None:
        # Filings that leave the whole period-end column empty: a subtotal of zero
        # beside a non-zero opening is an unfilled cell, not a company with no debt.
        assert rc._row_value([770.0, 1000.0, 0.0]) == 1000.0
