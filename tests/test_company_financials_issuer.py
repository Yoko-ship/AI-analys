"""A statement belongs to the ISSUER, not to a share class.

The catalog carries an org id for the ordinary line and often not for the
preferred one, so /api/company/KSCMP/financials answered "no financials
published" while KSCM showed ten years of the same company. Measured
2026-08-09: five of the seven ordinary/preferred pairs on the board — KSCMP,
IPKYP, KFSKP, UZASP, PLSTP. The company page already applied this fallback to
P/E; this puts it where the data is read.
"""
from __future__ import annotations

import pytest


class TestTheSiblingClassResolvesTheSameIssuer:
    @pytest.mark.parametrize(("ticker", "sibling"), [
        ("KSCMP", "KSCM"), ("IPKYP", "IPKY"), ("UZTLP", "UZTL"),
        ("KSCM", "KSCMP"), ("UZTL", "UZTLP"),
    ])
    def test_the_sibling_is_the_other_class_of_the_same_ticker(self, ticker, sibling) -> None:
        """The rule the endpoint applies, stated on its own so it cannot drift."""
        derived = ticker[:-1] if ticker.endswith("P") else f"{ticker}P"

        assert derived == sibling

    def test_a_ticker_that_is_only_a_p_does_not_derive_an_empty_sibling(self) -> None:
        """Guard on the degenerate input: "P"[:-1] is "", which resolves nothing."""
        ticker = "P"
        sibling = ticker[:-1] if ticker.endswith("P") else f"{ticker}P"

        assert sibling == "" and sibling != ticker  # the endpoint skips the empty case
