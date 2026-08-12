"""The annual-year clamp on the accounting-report sync path.

openinfo stamps many annuals with the upload season's year rather than the
fiscal year (fleet-wide, most issuers' FY2019 annual is labeled "2020"; several
carry impossible "FY2026" labels). A period cannot end after the report carrying
it was published — reports_catalog._effective_annual_year enforces the same
invariant period_year_quarter already applies on the unified-feed path.
"""

import reports_catalog as rc


class TestEffectiveAnnualYear:
    def test_an_upload_season_label_clamps_to_the_prior_fiscal_year(self):
        # TRSB's FY2022 annual: labeled 2023, published 2023-05-23.
        assert rc._effective_annual_year(2023, "2023-05-23T15:54:34") == 2022

    def test_the_universal_fy2019_mislabel_clamps(self):
        # HMKB record 189: labeled 2020, published 2020-10-13 → FY2019.
        assert rc._effective_annual_year(2020, "2020-10-13T18:09:49") == 2019

    def test_an_impossible_future_label_clamps(self):
        # BIOK record 6007: labeled 2026, published 2026-07-07 → FY2025.
        assert rc._effective_annual_year(2026, "2026-07-07T11:07:17") == 2025

    def test_a_late_filing_keeps_its_earlier_label(self):
        # AGMKP filed its FY2021 annual in 2023; the label is correct and a
        # clamp that moved years FORWARD would corrupt it.
        assert rc._effective_annual_year(2021, "2023-05-16T08:28:06") == 2021

    def test_a_correct_label_in_season_is_untouched(self):
        assert rc._effective_annual_year(2024, "2025-06-09T09:45:57") == 2024

    def test_no_publication_date_keeps_the_label(self):
        assert rc._effective_annual_year(2018, None) == 2018
        assert rc._effective_annual_year(2018, "") == 2018

    def test_garbage_publication_date_keeps_the_label(self):
        assert rc._effective_annual_year(2018, "n/a") == 2018

    def test_the_corrupted_grbk_upload_is_excluded_from_ingestion(self):
        # Record 261's income statement is a copy of the 2016 filing under a
        # 2022 label — no relabel makes it true, it must not be ingested.
        assert ("11", "261") in rc._ANNUAL_RECORD_EXCLUSIONS
