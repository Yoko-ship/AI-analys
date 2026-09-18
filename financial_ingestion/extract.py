"""Bounded text/OCR extraction into review candidates, never public figures."""
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import pdfplumber
import pypdfium2

from . import documents, store, validation

PARSER_VERSION = "bank-pdf-draft-v1"
MAX_PAGES = 16
MAX_OCR_PAGES = 8


def review_entries():
    import ifrs_financials
    additional = json.loads(Path(__file__).with_name("reviewed_pilots.json").read_text())
    if additional.get("schema_version") != 1:
        raise ValueError("Unknown pipeline review schema")
    entries = ifrs_financials.reviews() + additional["reports"]
    keys = [(str(e["org_id"]), e["year"], e["scope"], e.get("role", "PRIMARY")) for e in entries]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate review issuer/period/perimeter/role")
    return entries


def processor_version():
    # A new reviewed entry or a parser upgrade creates new extraction jobs for
    # already downloaded files. No manual deletion/reset of old jobs is needed.
    return PARSER_VERSION + ":" + store.digest(review_entries())[:16]


def _usable(text):
    return bool(re.search(r"statement of financial|отчет о финансов|отчёт о финансов|total assets|итого актив", text, re.I))


def page_texts(payload, *, ocr=False):
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        count = len(pdf.pages)
        if count > 500:
            raise ValueError("PDF page limit exceeded")
        pages = {i + 1: page.extract_text() or "" for i, page in enumerate(pdf.pages[:MAX_PAGES])}
    evidence = {"page_count": count, "ocr_pages": [], "ocr_errors": [], "text_pages": list(pages)}
    if not ocr:
        return pages, evidence
    if not shutil.which("tesseract"):
        evidence["ocr_errors"].append("OCR_UNAVAILABLE")
        return pages, evidence
    # Statement pages are usually after the opinion. Corrupt OCR layers can
    # be long but meaningless; character count alone is not a quality check.
    order = [1, *range(7, 13), *range(2, 7), *range(13, MAX_PAGES + 1)]
    pdf = pypdfium2.PdfDocument(payload)
    deadline = time.monotonic() + 240
    try:
        with tempfile.TemporaryDirectory(prefix="ifrs-ocr-") as scratch:
            for number in order:
                if number > count or number not in pages or _usable(pages[number]):
                    continue
                if len(evidence["ocr_pages"]) >= MAX_OCR_PAGES or time.monotonic() > deadline:
                    break
                page = pdf[number - 1]
                width, height = page.get_size()
                if width * height > 2_000_000:
                    evidence["ocr_errors"].append(f"PAGE_DIMENSION_LIMIT:{number}")
                    page.close()
                    continue
                path = Path(scratch) / f"page-{number}.png"
                bitmap = page.render(scale=2)
                bitmap.to_pil().save(path)
                bitmap.close()
                page.close()
                evidence["ocr_pages"].append(number)
                try:
                    output = subprocess.run(["tesseract", str(path), "stdout", "-l", "eng+rus", "--psm", "6"],
                                            capture_output=True, text=True, timeout=30, check=True)
                    pages[number] = output.stdout[:40000]
                except (subprocess.SubprocessError, OSError) as exc:
                    evidence["ocr_errors"].append(f"OCR_FAILED:{number}:{type(exc).__name__}")
    finally:
        pdf.close()
    return pages, evidence


LABELS = {
    "total_assets": r"(?:total assets|итого актив(?:ы|ов)|всего актив(?:ы|ов))",
    "total_liabilities": r"(?:total liabilities|итого обязательств(?:а)?|всего обязательств(?:а)?)",
    "total_equity": r"(?:total equity|итого (?:собственный )?капитал)",
    "cash": r"(?:cash and cash equivalents|денежные средства и их эквиваленты)",
    "interest_income": r"(?:interest income|процентные доходы)",
    "interest_expense": r"(?:interest expense|процентные расходы)",
    "operating_income": r"(?:operating (?:income|\(loss\)/income)|операционные доходы)",
    "operating_expenses": r"(?:operating expenses|операционные расходы)",
    "net_income": r"(?:(?:profit|loss|\(loss\)/profit) for the year|прибыль за год|убыток за год)",
}


def draft(pages, evidence):
    # Conservative proposals only. Notes, note numbers, ambiguous split columns
    # and multilingual layouts must still be checked by a reviewer.
    joined = "\n".join(pages.values())
    years = sorted(set(re.findall(r"\b20[0-3]\d\b", "\n".join(list(pages.values())[:2]))), reverse=True)
    year = int(years[0]) if len(years) == 1 else None
    scale = "1000000" if re.search(r"millions of.*(?:soum|sum)|миллион.*сум", joined, re.I) else (
        "1000" if re.search(r"thousands of.*(?:soum|sum)|тысяч.*(?:сум|УЗС)", joined, re.I) else None)
    scope = "consolidated" if re.search(r"consolidated|консолидирован", joined, re.I) else None
    standard = "MSFO" if re.search(r"IFRS|МСФО|International Financial Reporting", joined, re.I) else None
    figures = {}
    for number, text in pages.items():
        if not _usable(text):
            continue
        for line in text.splitlines():
            for field, label in LABELS.items():
                m = re.match(r"\s*(" + label + r")\s+(.*)$", line, re.I)
                if not m:
                    continue
                # Comma-grouped amounts are a narrow unambiguous draft format.
                # Space-grouped Russian tables are kept in page evidence for
                # review instead of concatenating multiple year columns.
                numbers = re.findall(r"(?<!\w)\(?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?", m[2])
                if len(numbers) != 2 or field in figures:
                    continue
                raw = numbers[0].replace(",", "")
                if raw.startswith("(") and raw.endswith(")"):
                    raw = "-" + raw[1:-1]
                figures[field] = {"raw_value": raw, "raw_label": m[1], "page": number, "column_year": year}
    return {"classification": {"standard": standard, "scope": scope, "currency": "UZS" if scale else None,
            "unit_scale": scale, "period_start": None, "period_end": None, "document_year": year,
            "role": "PRIMARY", "period_evidence": "Requires statement-date review", "unit_evidence": "Requires unit-header review",
            "issuer_evidence": None}, "figures": figures,
            "page_evidence": {str(n): text[:20000] for n, text in pages.items()}, "extraction": evidence}


def extract_job(job, *, ocr=False):
    c = store.connect()
    try:
        row = c.execute("SELECT v.*,s.org_id,s.url FROM ingest_versions v JOIN ingest_sources s ON s.id=v.source_id WHERE v.id=?",
                        (job["version_id"],)).fetchone()
        row = dict(row)
    finally:
        c.close()
    content = documents.read_artifact(row["sha"])
    entries = [e for e in review_entries() if str(e["org_id"]) == row["org_id"]
               and e["pdf_url"] == row["url"] and e["sha256"] == row["sha"]]
    proposals = []
    if entries:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            count = len(pdf.pages)
        for entry in entries:
            if count != entry["page_count"] or entry.get("review_method") != "visual-source-page-check":
                raise ValueError("Reviewed document identity/page count is invalid")
            proposals.append((validation.from_review(entry), count, entry))
    else:
        pages, evidence = page_texts(content, ocr=ocr)
        proposals.append((draft(pages, evidence), evidence["page_count"], None))
    result = []
    with store.transaction() as c:
        store.assert_lease(c, job)
        for payload, count, entry in proposals:
            payload["page_count"] = count
            checks = validation.validate(payload, page_count=count)
            candidate = store.digest([job["version_id"], job["processor"], payload])
            c.execute("INSERT INTO ingest_candidates VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                      (candidate, job["version_id"], job["processor"], store.encoded(payload), store.encoded(checks), store.now()))
            if entry and checks["valid"]:
                actor = "review-ledger:" + store.digest(entry)
                reason = "Visual source-page review " + entry.get("reviewed_at", "date not supplied")
                review = store.digest([candidate, actor, reason])
                c.execute("INSERT INTO ingest_reviews VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                          (review, candidate, actor, "APPROVED", reason, store.now()))
                store.event(c, candidate, "review.approved", actor=actor)
            result.append(candidate)
        store.finish(c, job, "SUCCEEDED" if entries and all(validation.validate(p, page_count=n)["valid"] for p, n, _ in proposals) else "NEEDS_REVIEW")
    return result
