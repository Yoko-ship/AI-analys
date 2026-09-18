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
MAX_DISCOVERED_PAGES = 32


def statement_page_numbers(texts):
    """Find appendix statements in annual brochures without fixed pagination."""
    selected = set(range(1, min(len(texts), MAX_PAGES) + 1))
    additional = set()
    for number, text in texts.items():
        # A short standalone section divider differs from a contents page or
        # an incidental IFRS reference in a management discussion.
        divider = len(text) < 500 and bool(re.search(
            r'\bifrs\s+report\b|отч[её]т\s+по\s+мсфо', text, re.I))
        heading = statements.section_kind(text) is not None
        if divider or heading:
            additional.update(range(number, min(len(texts), number + (MAX_PAGES if divider else 2)) + 1))
    selected.update(sorted(additional - selected)[:MAX_DISCOVERED_PAGES])
    return sorted(selected)


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


def deskew_image(image):
    """Estimate a small scan rotation from text-row alignment, without OCR values."""
    import numpy as np
    from PIL import ImageOps
    image = ImageOps.autocontrast(image.convert('L'))
    width, height = image.size
    # Scanner bindings and page edges must not dominate the angle estimate.
    sample = image.crop((int(width*.04), int(height*.03), int(width*.97), int(height*.96)))
    sample.thumbnail((800,1100))
    def score(angle):
        pixels = np.asarray(sample.rotate(float(angle), fillcolor=255))
        rows = (pixels < 140).sum(axis=1).astype(float)
        return float((rows * rows).sum())
    angle = float(max(np.arange(-2,2.01,.2), key=score))
    return image.rotate(angle, fillcolor=255), round(angle,2)


def page_texts(payload, *, ocr=False):
    with pdfplumber.open(io.BytesIO(payload)) as pdf:
        count = len(pdf.pages)
        if count > 500:
            raise ValueError("PDF page limit exceeded")
        native = {}
        for i, page in enumerate(pdf.pages):
            native[i + 1] = layout.word_lines(page.extract_words())
            page.close()  # Brochure discovery must not retain every page's objects.
        pages = {number: native[number] for number in statement_page_numbers(native)}
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
    parsed_pages = {number for proposal in native for number in proposal['statement_pages']}
    # Recognizable labels do not make a broken text layer usable: missing
    # year digits can prevent the page from producing any proposal at all.
    for number, text in pages.items():
        if number not in parsed_pages and sum(statements.row_label(line) is not None
                for line in statements.statement_lines(text)) >= 2:
            problem_pages.add(number)
    for proposal in native:
        if {'BALANCE_MISMATCH', 'INCOME_MISMATCH', 'INCOME_RECONCILIATION_INVALID'} & set(
                validation.validate(proposal, page_count=count)['errors']):
            problem_pages.update(proposal['statement_pages'])
        for number in proposal["statement_pages"]:
            count_fields = sum(f["page"] == number for f in proposal["figures"].values())
            if count_fields < 4 or not proposal['classification']['unit_scale']:
                problem_pages.add(number)
        for issue in proposal["extraction"]["issues"]:
            if issue.startswith("AMBIGUOUS_CELLS:"):
                problem_pages.add(int(issue.split(":")[1]))
    pdf = pypdfium2.PdfDocument(payload)
    deadline = time.monotonic() + 240
    evidence["ocr_survey_pages"] = []
    def quality(number, text):
        candidates = [p for p in statements.proposals({**pages,number:text}, evidence)
                      if number in p['statement_pages']]
        mismatches = sum(bool({'BALANCE_MISMATCH', 'INCOME_MISMATCH', 'INCOME_RECONCILIATION_INVALID'} & set(validation.validate(p, page_count=evidence['page_count'])['errors']))
                         for p in candidates)
        return (sum(f['page']==number for p in candidates for f in p['figures'].values()) - 8*mismatches,
                sum(bool(p.get('income_reconciliation')) for p in candidates),
                sum(bool(p['classification']['unit_scale']) for p in candidates))

    def complete(number):
        candidates = [p for p in statements.proposals(pages, evidence) if number in p['statement_pages']]
        return bool(candidates) and all(
            sum(f['page']==number for f in p['figures'].values()) >=
                (4 if p['figures'].get('total_assets',{}).get('page')==number else 5)
            and not {'BALANCE_MISMATCH', 'INCOME_MISMATCH', 'INCOME_RECONCILIATION_INVALID'} & set(validation.validate(p, page_count=evidence['page_count'])['errors'])
            for p in candidates)

    def retain(number, text):
        old = pages[number]
        if (not old.strip() or quality(number,text) > quality(number,old)
                or (statements.is_ifrs(text) and not statements.is_ifrs(old) and not _usable(old))):
            pages[number] = text
    try:
        with tempfile.TemporaryDirectory(prefix="ifrs-ocr-") as scratch:
            def recognize(number, scale, timeout, *, psm=None, crop=False, tiles=False, threshold=None, language=None):
                page = pdf[number - 1]
                try:
                    width, height = page.get_size()
                    if width * height > 2_000_000:
                        evidence["ocr_errors"].append(f"PAGE_DIMENSION_LIMIT:{number}")
                        return None
                    path = Path(scratch) / f"page-{number}.png"
                    bitmap = page.render(scale=scale)
                    try:
                        rendered = bitmap.to_pil()
                        if crop:
                            w,h = rendered.size
                            rendered = rendered.crop((int(w*(.08 if threshold else .04)),int(h*.03),int(w*.97),int(h*.96)))
                        if scale >= 3:
                            rendered, angle = deskew_image(rendered)
                            evidence.setdefault('ocr_rotations', {})[str(number)] = angle
                        if threshold is not None:
                            rendered = rendered.point(lambda pixel: 255 if pixel > threshold else 0)
                        rendered.save(path)
                    finally:
                        bitmap.close()
                finally:
                    page.close()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    mode = psm or ('3' if scale >= 3 else '6')
                    language = language or ('rus+eng' if tiles else 'eng+rus')
                    evidence.setdefault('ocr_attempts', []).append({'page':number,'scale':scale,'psm':mode,'crop_margins':crop,'tiles':4 if tiles else 1,'language':language,'threshold':threshold})
                    if tiles:
                        # Smaller text regions help segmentation of dense scanned
                        # tables. Preserve original coordinates and exclude overlap
                        # duplicates before reconstructing financial columns.
                        words = []
                        width, height = rendered.size
                        for index in range(4):
                            remaining = deadline - time.monotonic()
                            if remaining <= 0:
                                return None  # Never retain a partial page.
                            core = (height * index / 4, height * (index + 1) / 4)
                            top = max(0, int(core[0]) - 60)
                            bottom = min(height, int(core[1]) + 60)
                            rendered.crop((0, top, width, bottom)).save(path)
                            output = subprocess.run(["tesseract", path.name, "stdout", "-l", language, "--psm", mode, "tsv"],
                                                    capture_output=True, text=True, errors="replace", cwd=scratch,
                                                    timeout=min(timeout, remaining), check=True,
                                                    env={**os.environ, "OMP_THREAD_LIMIT": "1"})
                            words.extend(layout.tsv_words(output.stdout, top_offset=top, core=core))
                        return layout.word_lines(words)[:40000]
                    output = subprocess.run(["tesseract", path.name, "stdout", "-l", language, "--psm", mode, "tsv"],
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
                retain(number, survey)
                labels = sum(statements.row_label(line) is not None for line in statements.statement_lines(survey))
                heading = bool(re.search(r"statement of (?:financial|profit|income)|отч[её]т о (?:финансов|прибыл)", survey, re.I))
                score = labels + 3 * heading + int(statements.is_ifrs(survey))
                if score or number in problem_pages:
                    targets.append((score, number))
            for _, number in sorted(targets, key=lambda item: (-item[0], item[1]))[:MAX_OCR_PAGES]:
                if time.monotonic() >= deadline:
                    break
                refined = recognize(number, 3, 30)
                evidence["ocr_pages"].append(number)
                if refined is not None:
                    retain(number, refined)
                # Binder marks and ruled tables can defeat one segmentation
                # mode. Try bounded alternatives only while a statement is
                # incomplete; retain the strongest whole-page extraction.
                for mode,scale,crop,tiles in (('3',3,True,False),('6',4,False,True),('6',3,True,False),('3',4,False,False),('3',4,True,False)):
                    if complete(number) or time.monotonic() >= deadline:
                        break
                    alternative = recognize(number, scale, 30, psm=mode, crop=crop, tiles=tiles)
                    if alternative is not None:
                        retain(number, alternative)
                if not complete(number) and time.monotonic() < deadline:
                    # A single-language, high-contrast pass can retain faint
                    # zero dashes that multilingual segmentation discards.
                    text = pages[number]
                    language = 'rus' if len(re.findall('[а-яё]', text, re.I)) > len(re.findall('[a-z]', text, re.I)) else 'eng'
                    alternative = recognize(number, 4, 30, psm='6', crop=True, threshold=210, language=language)
                    if alternative is not None:
                        retain(number, alternative)
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
        # An annual attachment can be an exact copy of a catalog PDF. Reuse
        # only the same issuer, bytes and processor; a parser upgrade must run
        # again. Prefer an already reviewed extraction over an unreviewed one.
        cached = c.execute(
            "SELECT x.*,r.id AS approved_review FROM ingest_candidates x "
            "JOIN ingest_versions v ON v.id=x.version_id JOIN ingest_sources s ON s.id=v.source_id "
            "LEFT JOIN ingest_reviews r ON r.candidate_id=x.id AND r.decision='APPROVED' "
            "WHERE s.org_id=? AND v.sha=? AND x.processor=? AND x.version_id<>? "
            "ORDER BY CASE WHEN r.id IS NULL THEN 1 ELSE 0 END,x.created_at DESC,x.id",
            (row['org_id'], row['sha'], job['processor'], job['version_id'])).fetchall()
    finally:
        c.close()
    content = documents.read_artifact(row["sha"])
    entries = [e for e in review_entries() if str(e["org_id"]) == row["org_id"]
               and e["sha256"] == row["sha"]]
    proposals = []
    reused_reviews = {}
    if cached:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            count = len(pdf.pages)
        seen = set()
        for candidate in cached:
            if candidate['version_id'] != cached[0]['version_id'] or candidate['id'] in seen:
                continue
            seen.add(candidate['id'])
            payload = json.loads(candidate['payload_json'])
            if payload.get('page_count') != count:
                raise ValueError('Cached extraction page count does not match original')
            proposals.append((payload, count, None))
            if candidate['approved_review']:
                reused_reviews[store.digest(payload)] = candidate['approved_review']
    elif entries:
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
            elif checks['valid'] and store.digest(payload) in reused_reviews:
                original = reused_reviews[store.digest(payload)]
                actor = 'verified-content-reuse:' + original
                reason = 'Same issuer, immutable PDF hash and extraction version as approved review ' + original
                review = store.digest([candidate, actor, reason])
                c.execute('INSERT INTO ingest_reviews VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING',
                          (review, candidate, actor, 'APPROVED', reason, store.now()))
                store.event(c, candidate, 'review.reused', actor=actor, original_review=original, sha=row['sha'])
            result.append(candidate)
        approved = all((entry or store.digest(payload) in reused_reviews) and validation.validate(payload, page_count=count)['valid']
                       for payload, count, entry in proposals)
        store.finish(c, job, "SUCCEEDED" if approved else "NEEDS_REVIEW")
    return result
