"""Identity floors on the resolver fallbacks.

These endpoints are full-text search over filings, not identity lookups. Taking
their top row on faith is what produced the historic wrong-company ingestions:
a search for one issuer returns another's filing, its org id is cached under the
query, and every later lookup inherits the wrong company.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

import main
import openinfo_collector as oc


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class TestTicketNames:
    @pytest.mark.parametrize(("item", "expected"), [
        ({"organization_ticket_name": "AGMK,AGMKP"}, {"agmk", "agmkp"}),
        ({"organization_ticket_name": " HMKB , HMKBP "}, {"hmkb", "hmkbp"}),
        ({"ticket_name": "UZMK"}, {"uzmk"}),
        ({"organization_ticket_name": ""}, set()),
        ({}, set()),
    ])
    def test_parsing(self, item: dict, expected: set) -> None:
        assert main._ticket_names(item) == expected


class TestSecondaryIndexFloor:
    def _run(self, results: list[dict], query: str):
        payload = {"results": results}
        with patch.object(main.openinfo_http, "get", return_value=_FakeResponse(payload)), \
             patch.object(main, "_store_org_id_cache") as store:
            got = main._try_secondary_indexes(query)
        return got, store

    def test_an_unrelated_top_hit_is_rejected(self) -> None:
        # A search for KVTS returning Biokimyo's filing: no shared identity, so
        # the resolver must report failure rather than cache org 999 for KVTS.
        got, store = self._run(
            [{"organization": 999, "organization_name": "Акционерное общество Биокимё"}],
            "KVTS",
        )
        assert got is None
        store.assert_not_called()

    def test_an_exact_ticker_hit_is_accepted(self) -> None:
        got, store = self._run(
            [{"organization": 383, "organization_name": "O'zbekiston metallurgiya kombinati",
              "organization_ticket_name": "UZMK,UZMKP"}],
            "UZMK",
        )
        assert got == ("383", "O'zbekiston metallurgiya kombinati")
        store.assert_called_once()

    def test_the_best_candidate_wins_not_the_first(self) -> None:
        # The search engine ranked an unrelated issuer first; the ticker-carrying
        # row further down is the right answer.
        got, _ = self._run(
            [
                {"organization": 111, "organization_name": "Акционерное общество Прочее"},
                {"organization": 383, "organization_name": "O'zmetkombinat",
                 "organization_ticket_name": "UZMK"},
            ],
            "UZMK",
        )
        assert got is not None and got[0] == "383"

    def test_a_name_match_clears_the_floor(self) -> None:
        got, _ = self._run(
            [{"organization": 501, "organization_name": "Кварц"}],
            "Кварц",
        )
        assert got is not None and got[0] == "501"

    def test_generic_legal_words_alone_do_not_clear_the_floor(self) -> None:
        # "Акционерное общество" matches hundreds of issuers and carries no identity.
        got, store = self._run(
            [{"organization": 777, "organization_name": "Акционерное общество Совсем Другое"}],
            "Акционерное общество Кварц",
        )
        assert got is None
        store.assert_not_called()

    def test_empty_results_resolve_to_nothing(self) -> None:
        got, store = self._run([], "ANYTHING")
        assert got is None
        store.assert_not_called()


class TestReportDocumentsOrgFilter:
    def _fetch(self, results: list[dict], org_id: str | None):
        with patch.object(oc, "_json_get", return_value={"results": results}), \
             patch.object(oc, "_make_session", return_value=object()):
            return oc.fetch_report_documents("some company", org_id=org_id)

    def test_no_match_for_the_org_returns_nothing(self) -> None:
        # The regression: `if filtered:` fell through to the UNFILTERED page, so a
        # caller asking for org 100 got org 200's documents.
        out = self._fetch(
            [{"id": 1, "organization": 200, "organization_name": "Someone Else"}],
            org_id="100",
        )
        assert out["count"] == 0
        assert out["items"] == []

    def test_matching_documents_are_returned(self) -> None:
        out = self._fetch(
            [
                {"id": 1, "organization": 100, "organization_name": "Right Co"},
                {"id": 2, "organization": 200, "organization_name": "Wrong Co"},
            ],
            org_id="100",
        )
        assert out["count"] == 1
        assert out["items"][0]["organization_id"] == 100

    def test_without_an_org_id_nothing_is_filtered(self) -> None:
        out = self._fetch(
            [{"id": 1, "organization": 200, "organization_name": "Someone"}],
            org_id=None,
        )
        assert out["count"] == 1
