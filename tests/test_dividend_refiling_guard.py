"""Distinct valid dividend decisions must survive a reused payment window."""
import dividends


def test_a_new_valid_decision_is_not_a_correction_just_because_its_window_matches():
    # The calendar can describe two separate decisions within one payment
    # window. A shared window alone is not evidence that one supersedes another.
    common={'org_id':'issuer','ordinary_start':'2026-06-01','ordinary_end':'2026-08-31'}
    rows=[{**common,'filing_id':'1','decision_date':'2026-06-01','pub_date':'2026-06-02','ordinary_amount':100},
          {**common,'filing_id':'2','decision_date':'2026-06-15','pub_date':'2026-06-16','ordinary_amount':50}]
    kept,dropped=dividends.collapse_refilings(rows)
    assert len(kept)==2
    assert not dropped
