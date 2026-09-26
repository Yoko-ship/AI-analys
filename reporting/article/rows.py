"""Normalize spreadsheet rows and select meaningful statement entries."""

from __future__ import annotations
import re
from reporting.article.labels import (
    _article_supplemental_label_is_noise,
    _asset_article_specs,
    _clean_article_label,
    _income_article_specs,
    _is_total_report_label,
    _liability_article_specs,
    _normalize_article_label_key,
)
from reporting.numbers import _safe_float


def _excel_rows_for_article(company_data: dict | None, report_form_filter: str | None = None) -> list[dict]:
    if not isinstance(company_data, dict):
        return []
    all_reports = ((company_data.get("excel_reports") or {}).get("items") or [])
    if report_form_filter:
        filtered = [r for r in all_reports if (r.get("report_form") or "") == report_form_filter]
        # IFRS (MSFO) and Audit (Audition) reports are PDF-only on openinfo.uz and rarely
        # have Excel files. Fall back to NAS (NSBU) Excel data so the analysis still works.
        reports = filtered if filtered else [r for r in all_reports if (r.get("report_form") or "") == "NSBU"]
    else:
        reports = all_reports
    rows: list[dict] = []
    for report_index, report in enumerate(reports):
        for sheet in report.get("sheets") or []:
            sheet_name = str(sheet.get("sheet") or "")
            statement_section = None
            reporting_date = None
            for row in sorted(sheet.get("table_rows") or [], key=lambda item: int(item.get("row") or 0)):
                label = str(row.get("label") or "").strip()
                if not label:
                    continue
                lowered = label.lower()
                if "дата отчетности" in lowered:
                    for value in row.get("values") or []:
                        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
                        if match:
                            reporting_date = match.group(0)
                            break
                if "отчет о финансовых результатах" in lowered or "форма № 2" in lowered:
                    statement_section = "income_statement"
                elif "обязательства и собственный капитал" in lowered or lowered == "обязательства" or lowered == "собственный капитал":
                    statement_section = "liabilities_equity"
                elif lowered == "активы" or lowered.endswith(" активы"):
                    statement_section = "assets"
                elif "бухгалтерский баланс" in lowered or "форма № 1" in lowered:
                    statement_section = None
                rows.append({
                    **row,
                    "label": label,
                    "statement_section": statement_section,
                    "reporting_date": reporting_date,
                    "sheet": sheet_name,
                    "report_index": report_index,
                    "report_id": report.get("report_id"),
                    "published_at": report.get("published_at"),
                    "period_type": report.get("period_type"),
                    "report_form": report.get("report_form"),
                    "title": report.get("title"),
                })
    return rows


def _article_row_kind(row: dict) -> str:
    section = str(row.get("statement_section") or "").strip()
    if section in {"assets", "liabilities_equity", "income_statement"}:
        return section
    raw_kind = str(row.get("kind") or "").strip()
    if raw_kind in {"assets", "liabilities_equity", "income_statement"}:
        return raw_kind
    text = " ".join(
        str(row.get(key) or "").lower()
        for key in ("label", "sheet", "report_form", "title")
    )
    if any(token in text for token in (
        "форма 2", "form2", "финансов", "прибы", "убыт", "доход", "расход",
        "выруч", "себесто", "income", "profit", "loss",
    )):
        return "income_statement"
    if any(token in text for token in (
        "пассив", "обязатель", "капитал", "депозит", "вклад", "заем", "заём",
        "кредитор", "резерв", "устав", "liabil", "equity",
    )):
        return "liabilities_equity"
    if any(token in text for token in (
        "актив", "касс", "цбру", "к получению", "инвести", "кредит", "лизинг",
        "основн", "денеж", "дебитор", "запас", "имуществ", "asset",
    )):
        return "assets"
    return str(row.get("kind") or "financial_row")


def _article_amount_cells(row: dict) -> list[dict]:
    cells = row.get("numeric_cells") or []
    if not cells:
        cells = [
            {"index": index, "value": value}
            for index, value in enumerate(row.get("numeric_values") or [])
        ]
    cleaned = []
    for cell in cells:
        value = _safe_float(cell.get("value") if isinstance(cell, dict) else None)
        if value is None:
            continue
        cleaned.append({"index": int(cell.get("index", len(cleaned))), "value": value})
    return cleaned


def _article_amount_pair(row: dict) -> tuple[float, float] | None:
    """Return ``(current, prior)`` amounts for a row's period columns.

    openinfo lays period columns out OLDEST → NEWEST left-to-right (prior year /
    opening balance first, reporting period / closing balance last), so the
    reporting-period figure is the LAST value cell and the comparison the first.
    """
    cells = _article_amount_cells(row)
    large = [cell for cell in cells if abs(cell["value"]) >= 1000]
    source = large if len(large) >= 2 else cells
    if len(source) < 2:
        return None
    source = sorted(source, key=lambda item: item["index"])
    return source[-1]["value"], source[0]["value"]


def _article_current_amount(row: dict) -> float | None:
    preferred_index = row.get("_article_value_cell_index")
    if preferred_index is not None:
        try:
            preferred_index = int(preferred_index)
        except (TypeError, ValueError):
            preferred_index = None
    if preferred_index is not None:
        for cell in _article_amount_cells(row):
            if int(cell.get("index") or 0) == preferred_index:
                return cell["value"]

    pair = _article_amount_pair(row)
    if pair:
        return pair[0]
    cells = _article_amount_cells(row)
    large = [cell for cell in cells if abs(cell["value"]) >= 1000]
    if large:
        return sorted(large, key=lambda item: item["index"])[0]["value"]
    return cells[0]["value"] if cells else None


def _find_excel_amount(
    rows: list[dict],
    *keywords: str,
    kind_filter: str | None = None,
) -> tuple[float | None, float | None]:
    """Return (current, prior) amounts for the first Excel row whose label contains ALL keywords."""
    kws = [kw.lower() for kw in keywords]
    for row in rows:
        label = (row.get("label") or "").lower()
        if kind_filter and str(row.get("article_kind") or "") != kind_filter:
            continue
        if all(kw in label for kw in kws):
            pair = _article_amount_pair(row)
            if pair:
                return pair[0], pair[1]
            cur = _article_current_amount(row)
            return cur, None
    return None, None


def _bank_ratios_from_excel(
    excel_rows: list[dict],
    total_assets: float | None,
    interest_income: float | None,
    interest_expense: float | None,
) -> dict:
    """Compute bank-specific ratios that require raw Excel row data (NSBOU forms 1 & 2)."""
    result: dict = {}
    if not excel_rows:
        return result

    # ── First-line liquidity: (Cash + Due-from-CBU) / Total Assets ────────
    cash_cur, _ = _find_excel_amount(excel_rows, "касс", kind_filter="assets")
    cbu_cur, _ = _find_excel_amount(excel_rows, "цбру", kind_filter="assets")
    if cbu_cur is None:
        cbu_cur, _ = _find_excel_amount(excel_rows, "получен", "цбру")
    if (cash_cur is not None or cbu_cur is not None) and total_assets:
        first_line = ((cash_cur or 0.0) + (cbu_cur or 0.0)) / total_assets * 100
        result["first_line_liquidity_pct"] = round(first_line, 2)

    # ── Coverage ratio: Loan-loss reserve / Gross loans (current & prior) ─
    llr_cur, llr_prior = _find_excel_amount(excel_rows, "резерв", "потер")
    gross_cur, gross_prior = _find_excel_amount(excel_rows, "брутто")
    if gross_cur is None:
        gross_cur, gross_prior = _find_excel_amount(excel_rows, "кредит", "брутто")
    if llr_cur is not None and gross_cur and gross_cur > 0:
        result["coverage_ratio_current_pct"] = round(abs(llr_cur) / gross_cur * 100, 2)
    if llr_prior is not None and gross_prior and gross_prior > 0:
        result["coverage_ratio_prior_pct"] = round(abs(llr_prior) / gross_prior * 100, 2)

    # ── Reserve burden: provision expense / interest income ───────────────
    prov_cur, _ = _find_excel_amount(excel_rows, "резерв", "убыт", kind_filter="income_statement")
    if prov_cur is None:
        prov_cur, _ = _find_excel_amount(excel_rows, "резерв", "кредит", kind_filter="income_statement")
    if prov_cur is not None and interest_income and interest_income > 0:
        result["reserve_burden_pct"] = round(abs(prov_cur) / interest_income * 100, 2)

    # ── Interest income coverage: interest income / interest expense ───────
    if interest_income and interest_expense and interest_expense > 0:
        result["interest_income_coverage"] = round(interest_income / abs(interest_expense), 3)

    # ── Non-interest income share: non-int income / (int + non-int income) ─
    non_int_cur, _ = _find_excel_amount(excel_rows, "беспроцентн", "доход", kind_filter="income_statement")
    if non_int_cur is None:
        non_int_cur, _ = _find_excel_amount(excel_rows, "непроцентн", "доход", kind_filter="income_statement")
    if non_int_cur is not None and interest_income and interest_income > 0:
        total_income = interest_income + abs(non_int_cur)
        if total_income > 0:
            result["non_interest_share_pct"] = round(abs(non_int_cur) / total_income * 100, 2)

    return result


def _article_report_rows(rows: list[dict], report_index: int | None) -> list[dict]:
    if report_index is None:
        return []
    return [row for row in rows if int(row.get("report_index") or 0) == int(report_index)]


def _article_row_material_amount(row: dict) -> float | None:
    current = _article_current_amount(row)
    if current is not None and not _article_amount_is_zero(current):
        return current
    large = [
        cell["value"]
        for cell in _article_amount_cells(row)
        if abs(cell["value"]) >= 1000
    ]
    return large[0] if large else current


def _article_report_has_meaningful_data(rows: list[dict], report_index: int | None) -> bool:
    nonzero = 0
    for row in _article_report_rows(rows, report_index):
        label = _clean_article_label(row.get("label"))
        if _article_supplemental_label_is_noise(label):
            continue
        current = _article_row_material_amount(row)
        if current is None or _article_amount_is_zero(current):
            continue
        nonzero += 1
        if _is_total_report_label(label) or nonzero >= 2:
            return True
    return False


def _article_preferred_value_cell_index(rows: list[dict], report_index: int | None) -> int | None:
    counts: dict[int, int] = {}
    for row in _article_report_rows(rows, report_index):
        if row.get("article_kind") not in {"assets", "liabilities_equity", "income_statement"}:
            continue
        label = _clean_article_label(row.get("label"))
        if _article_supplemental_label_is_noise(label):
            continue
        for cell in _article_amount_cells(row):
            value = cell["value"]
            if _article_amount_is_zero(value) or abs(value) < 1000:
                continue
            index = int(cell.get("index") or 0)
            counts[index] = counts.get(index, 0) + 1
    if not counts:
        return None

    repeated_indices = [index for index, count in counts.items() if count >= 2]
    # Period columns run oldest → newest, so the reporting-period value lives in
    # the later half of the value columns (form №2 prior|current income/expense
    # pairs; form №1/bank forms begin|end). Return that group's leftmost (primary)
    # column, NOT the overall leftmost — which would be last year / the opening.
    candidates = sorted(repeated_indices or counts)
    reporting = candidates[len(candidates) // 2:]
    return reporting[0] if reporting else None


def _article_apply_preferred_value_cell(rows: list[dict], report_index: int | None) -> None:
    preferred_index = _article_preferred_value_cell_index(rows, report_index)
    if preferred_index is None:
        return
    for row in _article_report_rows(rows, report_index):
        row["_article_value_cell_index"] = preferred_index


def _article_rows_for_report(rows: list[dict], report_index: int | None) -> list[dict]:
    return _article_report_rows(rows, report_index)


def _article_line_code(label: str) -> str:
    text = str(label or "").strip().lower()
    match = re.match(r"^(\d+)\s*[\.\)]?", text)
    if match:
        return f"n:{match.group(1)}"
    match = re.match(r"^([a-zа-яё])\s*[\.\)]", text)
    if match:
        return f"l:{match.group(1)}:{_normalize_article_label_key(text)}"
    return _normalize_article_label_key(text)


def _article_row_lookup(rows: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for row in rows:
        amount = _article_current_amount(row)
        if amount is None:
            continue
        label = str(row.get("label") or "")
        for key in {_article_line_code(label), _normalize_article_label_key(label)}:
            if key and key not in lookup:
                lookup[key] = row
    return lookup


def _article_matching_row(row: dict, lookup: dict[str, dict]) -> dict | None:
    label = str(row.get("label") or "")
    for key in (_article_line_code(label), _normalize_article_label_key(label)):
        if key and key in lookup:
            return lookup[key]
    return None


def _article_current_previous_amounts(
    row: dict,
    previous_row: dict | None = None,
    *,
    force_previous_row: bool = False,
) -> tuple[float | None, float | None]:
    current = _article_current_amount(row)
    if force_previous_row:
        previous = _article_current_amount(previous_row or {}) if previous_row else None
        return current, previous
    pair = _article_amount_pair(row)
    if pair:
        return pair[0], pair[1]
    previous = _article_current_amount(previous_row or {}) if previous_row else None
    return current, previous


def _article_amount_is_zero(value: float | None) -> bool:
    return value is None or abs(value) < 0.5


def _article_is_zero_noise(label: str, current: float | None, previous: float | None = None) -> bool:
    if _is_total_report_label(label):
        return False
    return _article_amount_is_zero(current) and _article_amount_is_zero(previous)


def _article_spec_score(row: dict, spec: dict) -> int | None:
    label = _clean_article_label(row.get("label"))
    lowered = label.lower()
    normalized = _normalize_article_label_key(label)
    code = _article_line_code(label)

    excludes = [str(item).lower() for item in spec.get("exclude") or []]
    if any(item and item in lowered for item in excludes):
        return None

    keywords = [str(item).lower() for item in spec.get("keywords") or []]
    if any(item and item not in lowered for item in keywords):
        return None

    any_groups = spec.get("any_keywords") or []
    for group in any_groups:
        group_keywords = [str(item).lower() for item in group or []]
        if group_keywords and not any(item in lowered for item in group_keywords):
            return None

    line_codes = set(spec.get("line_codes") or [])
    score = 0
    if line_codes:
        if code in line_codes:
            score += 100
        elif spec.get("line_code_required"):
            return None

    exact = str(spec.get("exact") or "").strip().lower()
    if exact and lowered == exact:
        score += 120

    normalized_contains = [str(item).lower() for item in spec.get("normalized_contains") or []]
    if any(item and item not in normalized for item in normalized_contains):
        return None
    score += len(keywords) * 8 + len(any_groups) * 4 + len(normalized_contains) * 5
    if not (keywords or any_groups or normalized_contains or line_codes or exact):
        return None
    if spec.get("prefer_total") and _is_total_report_label(label):
        score += 20
    if spec.get("prefer_clean") and any(token in lowered for token in ("чист", "нетто")):
        score += 12
    if spec.get("prefer_gross") and any(token in lowered for token in ("брутто", "gross")):
        score += 12
    return score


def _article_select_row(rows: list[dict], spec: dict) -> dict | None:
    best: tuple[int, int, dict] | None = None
    for index, row in enumerate(rows):
        current = _article_current_amount(row)
        if current is None:
            continue
        score = _article_spec_score(row, spec)
        if score is None:
            continue
        if not spec.get("keep_zero") and _article_is_zero_noise(str(row.get("label") or ""), current, None):
            score -= 15
        candidate = (score, -index, row)
        if best is None or candidate > best:
            best = candidate
    return best[2] if best else None


def _article_entry_from_spec(
    spec: dict,
    current_rows: list[dict],
    previous_lookup: dict[str, dict],
    used_labels: set[str],
    *,
    force_previous_row: bool = False,
) -> dict | None:
    source_label = ""
    source_labels: list[str] = []
    if spec.get("aggregate"):
        current_total = 0.0
        previous_total = 0.0
        has_current = False
        has_previous = False
        for part in spec.get("aggregate") or []:
            row = _article_select_row(current_rows, part)
            if not row:
                continue
            label = _clean_article_label(row.get("label"))
            if label in source_labels:
                continue
            previous_row = _article_matching_row(row, previous_lookup)
            current, previous = _article_current_previous_amounts(
                row,
                previous_row,
                force_previous_row=force_previous_row,
            )
            if current is not None:
                current_total += current
                has_current = True
            if previous is not None:
                previous_total += previous
                has_previous = True
            source_labels.append(label)
        if not has_current:
            return None
        current = current_total
        previous = previous_total if has_previous else None
    else:
        row = _article_select_row(current_rows, spec)
        if not row:
            return None
        source_label = _clean_article_label(row.get("label"))
        if source_label in used_labels and not spec.get("allow_duplicate"):
            return None
        previous_row = _article_matching_row(row, previous_lookup)
        current, previous = _article_current_previous_amounts(
            row,
            previous_row,
            force_previous_row=force_previous_row,
        )
        used_labels.add(source_label)

    label = spec.get("label") or _clean_article_label((row or {}).get("label") if not spec.get("aggregate") else "")
    if not spec.get("keep_zero") and _article_is_zero_noise(label, current, previous):
        return None
    entry = {"label": label, "current": current, "previous": previous, "spec": spec}
    if source_label:
        entry["source_label"] = source_label
    if source_labels:
        entry["source_labels"] = source_labels
    return entry


def _normalized_article_entries(
    table_id: str,
    current_rows: list[dict],
    previous_lookup: dict[str, dict],
    *,
    force_previous_row: bool = False,
) -> list[dict]:
    if not current_rows:
        return []
    if table_id.startswith("assets"):
        specs = _asset_article_specs()
    elif table_id.startswith("liabilities"):
        specs = _liability_article_specs()
    elif table_id == "income_statement_horizontal_vertical":
        specs = _income_article_specs()
    else:
        return []

    entries: list[dict] = []
    used_labels: set[str] = set()
    for spec in specs:
        entry = _article_entry_from_spec(
            spec,
            current_rows,
            previous_lookup,
            used_labels,
            force_previous_row=force_previous_row,
        )
        if entry:
            entries.append(entry)
    return entries


def _article_label_keys(label: str) -> set[str]:
    cleaned = _clean_article_label(label)
    if not cleaned or cleaned in {"-", "\u2013", "\u2014"}:
        return set()
    return {
        key
        for key in (
            cleaned.lower(),
            _article_line_code(cleaned),
            _normalize_article_label_key(cleaned),
        )
        if key
    }


def _article_entry_label_keys(entry: dict) -> set[str]:
    keys: set[str] = set()
    for label in (entry.get("label"), entry.get("source_label")):
        keys.update(_article_label_keys(str(label or "")))
    for label in entry.get("source_labels") or []:
        keys.update(_article_label_keys(str(label or "")))
    spec = entry.get("spec") or {}
    for line_code in spec.get("line_codes") or []:
        if line_code:
            keys.add(str(line_code))
    for part in spec.get("aggregate") or []:
        for line_code in part.get("line_codes") or []:
            if line_code:
                keys.add(str(line_code))
    return keys


def _article_supplemental_entries(
    current_rows: list[dict],
    previous_lookup: dict[str, dict],
    used_entries: list[dict],
    limit: int,
    *,
    force_previous_row: bool = False,
) -> list[dict]:
    if limit <= 0:
        return []

    used_keys: set[str] = set()
    for entry in used_entries or []:
        used_keys.update(_article_entry_label_keys(entry))

    entries: list[dict] = []
    for row in current_rows:
        label = _clean_article_label(row.get("label"))
        if _article_supplemental_label_is_noise(label):
            continue
        row_keys = _article_label_keys(label)
        if row_keys and row_keys & used_keys:
            continue
        previous_row = _article_matching_row(row, previous_lookup)
        current, previous = _article_current_previous_amounts(
            row,
            previous_row,
            force_previous_row=force_previous_row,
        )
        if current is None or _article_is_zero_noise(label, current, previous):
            continue
        entry = {"label": label, "current": current, "previous": previous}
        entries.append(entry)
        used_keys.update(row_keys)
        if len(entries) >= limit:
            break
    return entries


def _article_entries_have_current_data(entries: list[dict], *, min_nonzero_rows: int = 2) -> bool:
    nonzero_count = 0
    for entry in entries or []:
        current = _safe_float(entry.get("current"))
        if _article_amount_is_zero(current):
            continue
        nonzero_count += 1
        label = str(entry.get("label") or "")
        if _is_total_report_label(label):
            return True
    return nonzero_count >= min_nonzero_rows


def _article_report_has_current_data(table_id: str, current_rows: list[dict]) -> bool:
    if not current_rows:
        return False
    normalized_entries = _normalized_article_entries(table_id, current_rows, {})
    if normalized_entries:
        return _article_entries_have_current_data(normalized_entries)

    nonzero_count = 0
    for row in current_rows:
        current = _article_current_amount(row)
        if _article_amount_is_zero(current):
            continue
        nonzero_count += 1
        label = str(row.get("label") or "")
        if _is_total_report_label(label):
            return True
    return nonzero_count >= 2
