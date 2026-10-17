"""A filing with no usable statement is refused when it is loaded
(docs/catalog-terminal/02-data.md, R-D1). The cases are the real ones."""
import catalogue.fields as catalogue_fields
import catalogue.parsing as catalogue_parsing

# Thousands of UZS, as the parser returns them.
SQBN_2024_JUNK = {"revenue": 1.0, "net_income": 13.0, "total_assets": None}
UZNGP_2021_JUNK = {"revenue": 10.0, "net_income": 270.0, "total_assets": 400.0, "total_equity": -370.0}
KSCM_2021_ZEROS = {"revenue": 0.0, "net_income": 0.0, "total_assets": 0.0, "total_equity": 0.0}
# The smallest real period production serves (UZNF's first quarter as a fund).
UZNF_2025Q1 = {"total_assets": 20_682.0, "total_equity": 20_000.0, "net_income": 150.0}
ORGS_NO_BALANCE = {"revenue": 5_400_000.0, "net_income": 310_000.0, "total_assets": 0.0,
                   "total_liabilities": 0.0, "total_equity": 0.0, "cash": 0.0}


def test_line_numbers_typed_in_as_amounts_are_refused():
    assert catalogue_fields.filing_problem(SQBN_2024_JUNK) == {"code": "implausible_scale"}
    assert catalogue_fields.filing_problem(UZNGP_2021_JUNK) == {"code": "implausible_scale"}


def test_an_all_nought_filing_is_refused():
    assert catalogue_fields.filing_problem(KSCM_2021_ZEROS) == {"code": "empty_filing"}


def test_the_smallest_real_filing_passes():
    assert catalogue_fields.filing_problem(UZNF_2025Q1) is None


def test_a_nought_balance_keeps_the_income_statement():
    values, problem = catalogue_fields.usable_filing(ORGS_NO_BALANCE)
    assert problem == {"code": "no_balance"}
    assert values["revenue"] == 5_400_000.0 and values["net_income"] == 310_000.0
    assert values["total_assets"] is None and values["total_equity"] is None and values["cash"] is None


def test_the_loader_wrapper_drops_every_amount_of_a_junk_filing(monkeypatch):
    monkeypatch.setattr(catalogue_parsing, "compute_financial_ratios",
                        lambda *a: {"source_values": dict(UZNGP_2021_JUNK), "metrics": {"ROA": 67.5}})
    result = catalogue_parsing.compute_filing_values({}, {})
    assert result["source_problem"] == {"code": "implausible_scale"}
    assert all(result["source_values"].get(k) is None for k in catalogue_fields.FIN_MONEY_FIELDS)
    assert result["metrics"] == {"ROA": None}


def test_the_loader_wrapper_leaves_a_real_filing_alone(monkeypatch):
    real = {"source_values": dict(UZNF_2025Q1), "metrics": {"ROA": 0.7}}
    monkeypatch.setattr(catalogue_parsing, "compute_financial_ratios", lambda *a: real)
    assert catalogue_parsing.compute_filing_values({}, {}) is real
