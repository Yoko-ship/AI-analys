"""Reviewed period corrections for individually identified NSBU annual filings.

The ledger contains source metadata only. It neither changes financial values
nor guesses a fiscal year from an issuer's ticker or a publication date.
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


_LEDGER_PATH = Path(__file__).with_name("reviewed_nsbu_periods.json")
_RECORD_KEYS = {
    "org_id", "record_id", "labeled_year", "fiscal_year", "reviewed_by",
    "reviewed_at", "evidence",
}


def _validate_ledger(payload: Any) -> dict[tuple[str, str], dict[str, Any]]:
    """Reject malformed, duplicate, or unreviewed corrections before use."""
    if (not isinstance(payload, dict)
            or set(payload) != {"schema_version", "annual_periods"}
            or type(payload["schema_version"]) is not int
            or payload["schema_version"] != 1
            or not isinstance(payload["annual_periods"], list)):
        raise ValueError("Invalid reviewed NSBU period ledger schema")
    records: dict[tuple[str, str], dict[str, Any]] = {}
    for record in payload["annual_periods"]:
        if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
            raise ValueError("NSBU period correction must contain only reviewed period metadata")
        for field in ("org_id", "record_id"):
            if not isinstance(record[field], str) or not re.fullmatch(r"[1-9][0-9]*", record[field]):
                raise ValueError(f"Invalid NSBU period correction {field}")
        for field in ("labeled_year", "fiscal_year"):
            if type(record[field]) is not int or not 2000 <= record[field] <= 2100:
                raise ValueError(f"Invalid NSBU period correction {field}")
        if record["fiscal_year"] >= record["labeled_year"]:
            raise ValueError("Reviewed fiscal year must precede the source's mislabeled year")
        if not isinstance(record["reviewed_by"], str) or not record["reviewed_by"].strip():
            raise ValueError("NSBU period correction requires a reviewer")
        reviewed_at = record["reviewed_at"]
        if not isinstance(reviewed_at, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", reviewed_at):
            raise ValueError("NSBU period correction requires an ISO review date")
        date.fromisoformat(reviewed_at)
        if not isinstance(record["evidence"], list) or not record["evidence"]:
            raise ValueError("NSBU period correction requires source evidence")
        has_reviewed_document = False
        for evidence in record["evidence"]:
            if (not isinstance(evidence, dict)
                    or set(evidence) not in ({"url", "description"}, {"url", "description", "page", "sha256"})
                    or not isinstance(evidence["url"], str)
                    or not isinstance(evidence["description"], str)
                    or not evidence["description"].strip()):
                raise ValueError("Invalid NSBU period correction evidence")
            url = urlparse(evidence["url"])
            if (url.scheme != "https" or url.netloc not in {"openinfo.uz", "new-api.openinfo.uz"}
                    or not url.path or url.path == "/"):
                raise ValueError("NSBU period evidence must link to the OpenInfo source")
            if "sha256" in evidence:
                if (not isinstance(evidence["sha256"], str)
                        or not re.fullmatch(r"[0-9a-f]{64}", evidence["sha256"])
                        or type(evidence["page"]) is not int or evidence["page"] < 1):
                    raise ValueError("Reviewed NSBU document requires its SHA-256 and a positive page")
                has_reviewed_document = True
        if not has_reviewed_document:
            raise ValueError("NSBU period correction requires reviewed document bytes and page evidence")
        key = (record["org_id"], record["record_id"])
        if key in records:
            raise ValueError(f"Duplicate reviewed NSBU annual source: {key}")
        records[key] = record
    return records


@lru_cache(maxsize=1)
def _reviewed_annual_periods() -> dict[tuple[str, str], dict[str, Any]]:
    return _validate_ledger(json.loads(_LEDGER_PATH.read_text(encoding="utf-8")))


def resolve_annual_year(org_id: Any, record_id: Any, labeled_year: int) -> int | None:
    """Return a reviewed year only for the exact issuer, document and old label.

    A changed source label deliberately stops matching, so a later upstream
    correction is not silently overridden by stale review metadata.
    """
    if type(labeled_year) is not int:
        return None
    record = _reviewed_annual_periods().get((str(org_id), str(record_id)))
    if record is None or record["labeled_year"] != labeled_year:
        return None
    return record["fiscal_year"]
