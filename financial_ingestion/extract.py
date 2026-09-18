"""Bounded text/OCR extraction into review candidates, never public figures."""
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

import pdfplumber
import pypdfium2

from . import documents, layout, statements, store, validation

PARSER_VERSION = "bank-pdf-draft-v3-" + statements.VERSION
MAX_PAGES = 16
MAX_OCR_PAGES = 8


def review_entries():
    import ifrs_financials
    entries = list(ifrs_financials.reviews())
    for name in ("reviewed_pilots.json", "reviewed_banks.json"):
        additional = json.loads(Path(__file__).with_name(name).read_text())
        if additional.get("schema_version") != 1:
            raise ValueError("Unknown pipeline review schema")
        entries.extend(additional["reports"])
    keys = [(str(e["org_id"]), e.get("period_end", str(e["year"])), e["scope"], e.get("role", "PRIMARY")) for e in entries]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate review issuer/period/perimeter/role")
    return entries


def processor_version():
    # A new reviewed entry or a parser upgrade creates new extraction jobs for
    # already downloaded files. No manual deletion/reset of old jobs is needed.
    return PARSER_VERSION + ":" + store.digest(review_entries())[:16]


def _usable(text):
    return bool(re.search(r"statement of (?:financial|profit|income)|отч[её]т о (?:финансов|прибыл)|total assets|итого актив|interest income|процентные доходы", text, re.I))


def page_texts(payload, *, ocr=False):
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        count = len(pdf.pages)
        if count > 500:
            raise ValueError("PDF page limit exceeded")
        pages = {i + 1: layout.word_lines(page.extract_words()) for i, page in enumerate(pdf.pages[:MAX_PAGES])}
    evidence = {"page_count": count, "ocr_pages": [], "ocr_errors": [], "text_pages": list(pages)}
    if not ocr:
        return pages, evidence
    if not shutil.which("tesseract"):
        evidence["ocr_errors"].append("OCR_UNAVAILABLE")
        return pages, evidence
    # Locate statement pages from their content. Report pagination varies:
    # statements can precede the opinion or start after a long audit report.
    # A cheap OCR survey finds them; only the strongest pages get high resolution.
    native = statements.proposals(pages, evidence)
    problem_pages = set()
    for proposal in native:
        for number in proposal["statement_pages"]:
            count_fields = sum(f["page"] == number for f in proposal["figures"].values())
            if count_fields < 4:
                problem_pages.add(number)
        for issue in proposal["extraction"]["issues"]:
            if issue.startswith("AMBIGUOUS_CELLS:"):
                problem_pages.add(int(issue.split(":")[1]))
    pdf = pypdfium2.PdfDocument(payload)
    deadline = time.monotonic() + 240
    evidence["ocr_survey_pages"] = []
    try:
        with tempfile.TemporaryDirectory(prefix="ifrs-ocr-") as scratch:
            def recognize(number, scale, timeout):
                page = pdf[number - 1]
                try:
                    width, height = page.get_size()
                    if width * height > 2_000_000:
                        evidence["ocr_errors"].append(f"PAGE_DIMENSION_LIMIT:{number}")
                        return None
                    path = Path(scratch) / f"page-{number}.png"
                    bitmap = page.render(scale=scale)
                    try:
                        bitmap.to_pil().save(path)
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    output = subprocess.run(["tesseract", path.name, "stdout", "-l", "eng+rus", "--psm", "6", "tsv"],
                                            capture_output=True, text=True, errors="replace", cwd=scratch,
                                            timeout=min(timeout, remaining), check=True,
                                            env={**os.environ, "OMP_THREAD_LIMIT": "1"})
                    return layout.tsv_text(output.stdout)[:40000]
                except (subprocess.SubprocessError, OSError) as exc:
                    evidence["ocr_errors"].append(f"OCR_FAILED:{number}:{type(exc).__name__}")
                    return None

            targets = []
            for number in pages:
                if time.monotonic() >= deadline:
                    break
                if _usable(pages[number]) and number not in problem_pages:
                    continue
                survey = recognize(number, 1.5, 12)
                if survey is None:
                    continue
                evidence["ocr_survey_pages"].append(number)
                # Keep native evidence when the survey has found no statement.
                if _usable(survey) or not pages[number].strip():
                    pages[number] = survey
                labels = sum(statements.row_label(line) is not None for line in statements.statement_lines(survey))
                heading = bool(re.search(r"statement of (?:financial|profit|income)|отч[её]т о (?:финансов|прибыл)", survey, re.I))
                score = labels + 3 * heading
                if score or number in problem_pages:
                    targets.append((score, number))
            for _, number in sorted(targets, key=lambda item: (-item[0], item[1]))[:MAX_OCR_PAGES]:
                if time.monotonic() >= deadline:
                    break
                refined = recognize(number, 3, 30)
                evidence["ocr_pages"].append(number)
                if refined is not None:
                    pages[number] = refined
            if time.monotonic() >= deadline:
                evidence["ocr_errors"].append("OCR_TIME_BUDGET_EXCEEDED")
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
        # A new issuer/report does not need a checked-in review or ticker rule
        # to extract every dated statement column. Historical ledger entries
        # above remain immutable review evidence for the previous recovery.
        parsed = statements.proposals(pages, evidence)
        proposals.extend((payload, evidence["page_count"], None)
                         for payload in parsed or [draft(pages, evidence)])
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
