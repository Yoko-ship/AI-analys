"""Form №1 subtotals are held to the formulas the form prints beside them.

The fixtures are the Form №1 rows of real filings, as the workbook parser emits
them. Every outcome below was found on the 2024–2026 filings of the board's
issuers: a closing cell copied from the opening column (MIQE 2026Q2), a digit
dropped from a total (BECM 2025Q2), and a total that no two of its witnesses
confirm (BECM 2025Q3).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

import catalogue.parsing as catalogue_parsing
import financial_analysis.balance_subtotals as balance_subtotals
import financial_analysis.sector_calculations as sector_calculations
import financial_analysis.sector_inputs as sector_inputs
import financial_analysis.sector_validation as sector_validation


FILINGS = json.loads((Path(__file__).parent / "fixtures" / "form1_subtotals.json").read_text(encoding="utf-8"))


def table(name):
    return {"sheets": [{"sheet": "Квартальный отчет АО рус", "table_rows": FILINGS[name]["rows"]}],
            "source_url": f"https://new-api.openinfo.uz/api/v2/reports/export-excel/?report_id={FILINGS[name]['report_id']}"}


def resolutions(name, targets=balance_subtotals.LIQUIDITY_LINES):
    rows = sector_inputs.source_line_pairs(table(name), "form1", balance_subtotals.ALL_CODES)
    return balance_subtotals.reconcile(rows, targets)


def synthetic(cells):
    """Form №1 rows from ``(code, label, opening, closing)``."""
    return {"sheets": [{"table_rows": [{"label": label, "numeric_values": [float(code), begin, end]}
                                       for code, label, begin, end in cells]}]}


class TestFormulaLabels:
    @pytest.mark.parametrize(("label", "terms"), [
        ("Итого по разделу II (стр.490+600)", ((1, "c490"), (1, "c600"))),
        ("Всего по активу баланса (стр.130+стр.390)", ((1, "c130"), (1, "c390"))),
        ("Итого по разделу I (стр.410+420+430-440+450+460+470)",
         ((1, "c410"), (1, "c420"), (1, "c430"), (-1, "c440"), (1, "c450"), (1, "c460"), (1, "c470"))),
        ("Остаточная (балансовая) стоимость (стр. 010-011)", ((1, "c010"), (-1, "c011"))),
        # The form's own typo, a doubled plus, is still one formula.
        ("Текущие обязательства,всего (стр.610+630+640+650+660+670+680+690+700+710+720+ +730+740+750+760)",
         tuple((1, f"c{n}") for n in (610, 630, 640, 650, 660, 670, 680, 690, 700, 710, 720, 730, 740, 750, 760))),
    ])
    def test_a_printed_formula_is_read_with_its_signs(self, label, terms):
        assert balance_subtotals.label_formula(label) == terms

    @pytest.mark.parametrize("label", ["Денежные средства на расчетном счете (5100)", "Сумма износа (0200)", None])
    def test_an_account_code_is_not_a_formula(self, label):
        assert balance_subtotals.label_formula(label) is None


class TestRealFilings:
    def test_a_closing_cell_copied_from_the_opening_column_is_repaired(self):
        # MIQE 2026Q2 стр.600: 5 417 547 at both dates; 610…760 and 770 − 490
        # each give 27 299 593.
        c600 = resolutions("MIQE_2026Q2")["c600"]
        assert c600["current"]["status"] == "repaired"
        assert c600["current"]["filed"] == Decimal("5417547")
        assert c600["current"]["value"] == Decimal("27299593")
        assert c600["previous"]["status"] == "consistent"

    def test_a_total_with_a_dropped_digit_is_repaired(self):
        # BECM 2025Q2 стр.140: 18 369 306 filed, 183 669 304 by its parts and
        # 183 669 308 from стр.390 — the parts' rounding, not a disagreement.
        c140 = resolutions("BECM_2025Q2")["c140"]["current"]
        assert c140["status"] == "repaired"
        assert c140["value"] in {Decimal("183669304"), Decimal("183669308")}

    def test_a_total_no_two_witnesses_confirm_is_withheld(self):
        # BECM 2025Q3 стр.600: 12 027 698 filed, 100 485 795 by its parts,
        # 120 276 699 from 770 − 490. Nothing on the form says which is right.
        c600 = resolutions("BECM_2025Q3")["c600"]["current"]
        assert c600["status"] == "conflict"
        assert c600["value"] is None

    def test_a_hundred_thousand_typo_is_found_on_the_line_that_carries_it(self):
        # JASM 2026Q1, opening column: стр.320 is 100 below its accounts and
        # below what стр.390 leaves for it. Read against the filed 320, the
        # receivables (210) would look 100 too high; once 320 is repaired
        # they add up as filed.
        checked = resolutions("JASM_2026Q1")
        assert checked["c320"]["previous"]["status"] == "repaired"
        assert checked["c320"]["previous"]["value"] - checked["c320"]["previous"]["filed"] == 100
        assert checked["c210"]["previous"]["status"] == "consistent"

    def test_a_repaired_line_confirms_the_line_beside_it(self):
        # QZSM 2024Q1 left its receivables (210) at nought. Read against that
        # nought, стр.390 implies stocks 156 bn above the 546 bn filed; once
        # 210 is repaired from its own accounts, the filed stocks add up.
        checked = resolutions("QZSM_2024Q1")
        assert checked["c210"]["current"]["status"] == "repaired"
        assert checked["c210"]["current"]["value"] == Decimal("156070090")
        assert checked["c140"]["current"]["status"] == "consistent"
        values = catalogue_parsing.compute_financial_ratios(None, table("QZSM_2024Q1"))["source_values"]
        assert values["inventories"] == 546_416_344.0

    def test_a_nought_total_is_not_a_witness(self):
        # UZAL 2025Q3 files «Всего по активу» as 0; 400 − 130 would put its
        # current assets at −6.4 trn UZS. Its current assets disagree with their own
        # parts as well, so they are withheld — on the parts alone.
        c390 = resolutions("UZAL_2025Q3")["c390"]["current"]
        assert list(c390["witnesses"]) == ["parts"]
        assert c390["status"] == "conflict"

    def test_a_difference_below_the_published_precision_keeps_the_filed_total(self):
        # UZTL 2024Q3 opening stocks: three amounts 1 000–3 000 apart on 769 bn.
        c140 = resolutions("UZTL_2024Q3")["c140"]["previous"]
        assert c140["status"] == "immaterial"
        assert c140["value"] == c140["filed"] == Decimal("769007516")

    def test_a_filing_that_adds_up_is_left_as_filed(self):
        checked = resolutions("KVTS_2026Q2")
        assert {columns[c]["status"] for columns in checked.values() for c in columns} == {"consistent"}
        assert all(columns[c]["value"] == columns[c]["filed"] for columns in checked.values() for c in columns)


class TestWitnessRules:
    def test_parts_off_by_their_rounding_still_confirm_the_total(self):
        rows = sector_inputs.source_line_pairs(synthetic([
            (140, "Товарно-материальные запасы, всего (стр.150+160+170+180)", 0.0, 1003.0),
            (150, "Производственные запасы", 0.0, 500.0),
            (160, "Незавершенное производство", 0.0, 500.0),
            (170, "Готовая продукция", 0.0, 1.0),
            (180, "Товары", 0.0, 0.0),
        ]), "form1", balance_subtotals.ALL_CODES)
        assert balance_subtotals.reconcile(rows, ("c140",))["c140"]["current"]["status"] == "consistent"

    def test_a_breakdown_left_at_nought_does_not_contradict_its_total(self):
        rows = sector_inputs.source_line_pairs(synthetic([
            (600, "Текущие обязательства,всего (стр.610+630)", 0.0, 900.0),
            (610, "Задолженность поставщикам", 0.0, 0.0),
            (630, "Задолженность дочерним", 0.0, 0.0),
        ]), "form1", balance_subtotals.ALL_CODES)
        assert balance_subtotals.reconcile(rows, ("c600",))["c600"]["current"]["status"] == "unverified"

    def test_one_witness_against_the_filed_cell_is_a_conflict_not_a_repair(self):
        rows = sector_inputs.source_line_pairs(synthetic([
            (490, "Долгосрочные обязательства, всего", 0.0, 0.0),
            (600, "Текущие обязательства, всего", 0.0, 900.0),
            (770, "Итого по разделу II (стр.490+600)", 0.0, 2700.0),
        ]), "form1", balance_subtotals.ALL_CODES)
        resolution = balance_subtotals.reconcile(rows, ("c600",))["c600"]["current"]
        assert (resolution["status"], resolution["value"]) == ("conflict", None)


class TestCatalogueParse:
    def test_the_board_reads_the_repaired_current_liabilities(self):
        values = catalogue_parsing.compute_financial_ratios(None, table("MIQE_2026Q2"))["source_values"]
        assert values["current_liabilities"] == 27_299_593.0
        assert values["current_assets"] == 64_526_485.0
        # 2.36, not the 11.91 the copied cell made of it.
        assert round(values["current_assets"] / values["current_liabilities"], 2) == 2.36

    def test_a_withheld_total_leaves_the_field_empty(self):
        values = catalogue_parsing.compute_financial_ratios(None, table("BECM_2025Q3"))["source_values"]
        assert values["current_liabilities"] is None
        assert values["current_assets"] is not None

    def test_a_consistent_filing_parses_as_before(self, monkeypatch):
        after = catalogue_parsing.compute_financial_ratios(None, table("KVTS_2026Q2"))["source_values"]
        monkeypatch.setattr(catalogue_parsing, "_current_section_check", lambda _table: {})
        assert catalogue_parsing.compute_financial_ratios(None, table("KVTS_2026Q2"))["source_values"] == after

    def test_another_forms_line_of_the_same_number_is_not_read(self, monkeypatch):
        # The bank and insurance forms number other lines 600 and 390; a
        # reconciliation of their line 600 must not become current liabilities.
        before = catalogue_parsing.compute_financial_ratios(None, table("KVTS_2026Q2"))["source_values"]
        monkeypatch.setattr(catalogue_parsing, "_current_section_check", lambda _table: {
            "current_liabilities": {"status": "repaired", "filed": Decimal("1"), "value": Decimal("2"),
                                    "label": "Начисленные проценты к оплате"}})
        values = catalogue_parsing.compute_financial_ratios(None, table("KVTS_2026Q2"))["source_values"]
        assert values["current_liabilities"] == before["current_liabilities"]

    def test_a_nought_stock_is_read_as_nought(self):
        # ODMP files no stocks; the selector used to read that as no line at
        # all, and a quick ratio needs the nought.
        balance = synthetic([
            (140, "Товарно-материальные запасы, всего (стр.150+160+170+180), в том числе:", 0.0, 0.0),
            (150, "Производственные запасы (1000, 1100, 1500, 1600)", 0.0, 0.0),
            (160, "Незавершенное производство", 0.0, 0.0),
            (170, "Готовая продукция", 0.0, 0.0),
            (180, "Товары", 0.0, 0.0),
        ])
        assert catalogue_parsing.compute_financial_ratios(None, balance)["source_values"]["inventories"] == 0.0


class TestAnalysisInputs:
    def snapshot(self):
        return {"organization_type": "non_financial", "standard": "nsbu", "period": "2026Q2"}

    def test_the_analysis_lines_carry_the_repaired_amount_and_the_filed_one(self):
        values, _previous, opening, lines = sector_inputs.prepare_inputs(self.snapshot(), {"balance": table("MIQE_2026Q2")})
        row = lines["form1:c600"]
        assert Decimal(row["raw_current"]) == 27_299_593
        assert Decimal(row["filed_current"]) == 5_417_547
        assert row["reconciliation"]["current"]["status"] == "repaired"
        assert Decimal(values["current_liabilities"]) == 27_299_593
        assert Decimal(opening["current_liabilities"]) == 5_417_547

    def test_absolute_liquidity_is_read_off_the_repaired_line(self):
        *_, lines = sector_inputs.prepare_inputs(self.snapshot(), {"balance": table("MIQE_2026Q2")})
        ratio = next(r for r in sector_calculations.enterprise_ratios(lines, "non_financial", "nsbu", "2026Q2")
                     if r["metric"] == "absolute_liquidity")
        assert ratio["denominator_value"] == 27_299_593.0
        assert round(ratio["value"], 4) == 0.0164

    def test_lines_prepared_once_are_not_changed_by_a_second_pass(self):
        *_, lines = sector_inputs.prepare_inputs(self.snapshot(), {"balance": table("MIQE_2026Q2")})
        again = sector_inputs.prepare_inputs({**self.snapshot(), "source_lines": lines, "control_lines_prepared": True},
                                             {"balance": table("MIQE_2026Q2")})[3]
        assert again["form1:c600"] == lines["form1:c600"]

    def test_the_report_states_what_it_repaired_and_what_it_withheld(self):
        *_, lines = sector_inputs.prepare_inputs(self.snapshot(), {"balance": table("MIQE_2026Q2")})
        notes = sector_validation.subtotal_notes(lines, "ru")
        assert [(n["code"], n["severity"], n["lines"]) for n in notes] == [
            ("FORM1_SUBTOTAL_REPAIRED", "warning", ["form1:c600"])]
        assert "600" in notes[0]["message"]
        *_, withheld = sector_inputs.prepare_inputs(self.snapshot(), {"balance": table("BECM_2025Q3")})
        assert "FORM1_SUBTOTAL_CONFLICT" in {n["code"] for n in sector_validation.subtotal_notes(withheld, "en")}


class TestStoredCurrentSection:
    def stored(self):
        import catalogue.storage as catalogue_storage
        conn = catalogue_storage.get_catalog_conn()
        try:
            row = conn.execute("SELECT current_assets, current_liabilities, inventories FROM catalog_financials "
                               "WHERE ticker='MIQE' AND year=2026 AND quarter=2").fetchone()
            return tuple(row[k] for k in ("current_assets", "current_liabilities", "inventories"))
        finally:
            conn.close()

    @pytest.fixture(autouse=True)
    def catalogue(self, tmp_path, monkeypatch):
        import catalogue.financial_store as catalogue_financial_store
        monkeypatch.setenv("CATALOG_DB_PATH", str(tmp_path / "catalog.db"))
        self.store = catalogue_financial_store
        # What the old parse stored: the cell copied from the opening column.
        self.store.upsert_financials_cache("MIQE", "NSBU", 2026, 2, {
            "revenue": 1.0, "current_assets": 64_526_485.0, "current_liabilities": 5_417_547.0, "inventories": 3_651_771.0})

    def test_a_withheld_line_clears_what_the_old_parse_read_off_it(self):
        self.store.upsert_financials_cache("MIQE", "NSBU", 2026, 2, {
            "revenue": 1.0, "current_assets": 64_526_485.0, "current_liabilities": None, "inventories": 3_651_771.0})
        assert self.stored() == (64_526_485.0, None, 3_651_771.0)

    def test_a_form_without_a_current_section_keeps_the_stored_one(self):
        self.store.upsert_financials_cache("MIQE", "NSBU", 2026, 2, {"revenue": 1.0})
        assert self.stored() == (64_526_485.0, 5_417_547.0, 3_651_771.0)

    def test_the_pushed_rows_follow_the_same_rule(self):
        self.store.bulk_upsert_financials([{"ticker": "MIQE", "year": 2026, "quarter": 2, "revenue": 1.0,
                                            "current_assets": 64_526_485.0, "current_liabilities": 27_299_593.0,
                                            "inventories": 3_651_771.0}])
        assert self.stored() == (64_526_485.0, 27_299_593.0, 3_651_771.0)
        self.store.bulk_upsert_financials([{"ticker": "MIQE", "year": 2026, "quarter": 2, "revenue": 1.0,
                                            "current_assets": 64_526_485.0, "inventories": 3_651_771.0}])
        assert self.stored() == (64_526_485.0, None, 3_651_771.0)


def test_kvts_2020_glued_opening_cell_cannot_replace_closing_liabilities():
    source=json.loads((Path(__file__).parent/'fixtures/kvts_2020_balance.json').read_text())
    values=catalogue_parsing.compute_financial_ratios(None,source)['source_values']
    assert values['total_assets']==914358452
    assert values['total_equity']==354518181
    assert values['total_liabilities']==559840271
    assert values['total_assets']==values['total_equity']+values['total_liabilities']
