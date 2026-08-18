"""Which listings are preferred shares.

A ticker's shape is not its share class. The exchange's own ``share_type`` is the
answer wherever it is right, and where it is not the correction has to be a
decided fact about one named security — never a rule inferred from the ticker,
which is what mislabelled BNGP in the first place.
"""
from __future__ import annotations

import securities_catalog


class TestPreferredFlag:
    def test_the_feed_decides_when_it_is_right(self) -> None:
        assert securities_catalog._preferred_flag("preferred", "Hamkorbank ATB", "HMKBP") is True
        assert securities_catalog._preferred_flag("ordinary", "Hamkorbank ATB", "HMKB") is False

    def test_a_p_suffix_is_not_a_share_class(self) -> None:
        """BNGP is Buxoroneftgazparmalash's ORDINARY line — its preferred one is
        BNGPP. The old ticker-shape guess called it «Привилегированная»."""
        assert securities_catalog._preferred_flag(
            "ordinary", '"Buxoroneftgazparmalash" aksiyadorlik jamiyati', "BNGP") is False

    def test_the_name_catches_what_the_class_field_misses(self) -> None:
        """UZNGP carries share_type=ordinary under a name that says otherwise."""
        assert securities_catalog._preferred_flag(
            "ordinary", '"O\'zbekiston neftgaz" AJ (привилегированные)', "UZNGP") is True

    def test_uzinp_is_preferred_though_neither_field_says_so(self) -> None:
        """O'zbekinvest lists no ordinary line here, so the feed has nothing to
        contrast UZINP against and reports «ordinary»; the name carries no
        «привилегированные» either. Decided by the customer, 2026-08-18."""
        assert securities_catalog._preferred_flag(
            "ordinary",
            '"O\'zbekinvest" eksport-import sug\'urta kompanyasi" Aksiyadorlik jamiyati',
            "UZINP") is True

    def test_the_override_is_a_list_of_names_not_a_pattern(self) -> None:
        """Every entry costs one deliberate decision. If this set ever starts
        growing by rule, the rule belongs in the feed, not here."""
        assert securities_catalog._PREFERRED_OVERRIDE == {"UZINP"}

    def test_the_override_is_case_and_space_insensitive(self) -> None:
        assert securities_catalog._preferred_flag("ordinary", "x", " uzinp ") is True

    def test_a_missing_ticker_still_answers_from_the_feed(self) -> None:
        assert securities_catalog._preferred_flag("preferred", None, None) is True
        assert securities_catalog._preferred_flag(None, None, None) is False
