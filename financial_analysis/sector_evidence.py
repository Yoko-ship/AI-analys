"""Build traceable facts and ratio inputs from a validated filing."""
from __future__ import annotations
from financial_analysis.sector_models import ReportEvidence
from financial_analysis.sector_models import ValidatedFiling
import financial_analysis.sector_inputs as financial_analysis_sector_inputs
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_templates as financial_analysis_sector_templates


def _period_end(period):
    text = str(period or "")
    if not text[:4].isdigit():
        return None
    year, quarter = int(text[:4]), int(text[-1]) if "Q" in text else 4
    return f"{year}-{quarter * 3:02d}-{(31, 30, 30, 31)[quarter - 1]}"


def comparison_date(filing, basis):
    """The date the comparison figure stands at, as the filing's sources say.

    A balance line is compared with the date its comparison column was
    reconciled to (``opening_date``), 1 January by default — the enterprise
    form's own column head.  A result is compared with the same period a year
    earlier and stands at that period's end.
    """
    sources = filing.snapshot.get("comparison_sources") or {}
    if basis == "opening":
        return sources.get("opening_date") or f"{filing.year - 1}-12-31"
    return _period_end(filing.snapshot.get("previous_comparable_period"))


def collect_evidence(filing: ValidatedFiling):
    facts, by_code = [], {}
    mapping = {key: f"form1:{code}" for code, key in financial_analysis_sector_inputs.FORM1.items()}
    mapping.update({key: f"form2:{code}" for code, key in financial_analysis_sector_inputs.FORM2.items()})
    allowed = set(sum(filing.codes.values(), [])) | {"fx_income", "fx_expenses", "financial_income", "financial_expenses", "short_term_investments", "retained_earnings", "share_capital", "additional_capital"} | financial_analysis_sector_templates.SECTOR_PHRASE_BALANCE_LINES | financial_analysis_sector_templates.SECTOR_PHRASE_FLOW_LINES
    def metric_label(key):
        if filing.template == "insurance" and key == "revenue":
            return financial_analysis_sector_language.tr(filing.lang, "Чистая выручка от страховых услуг", "Sug‘urta xizmatlaridan sof tushum", "Net insurance-service revenue")
        return financial_analysis_sector_language.label(key, filing.lang)

    for key in sorted(allowed):
        value = financial_analysis_sector_numbers.number(filing.values.get(key))
        if value is None:
            continue
        line = (filing.snapshot.get("field_sources", {}).get(key) or {}).get("source_line_id") or (mapping.get(key) if mapping.get(key) in filing.lines else f"catalog:{key}")
        line_row = filing.lines.get(line) or {}
        raw = line_row.get("raw_current", str(filing.values[key]))
        fact_url = line_row.get("source_url") or filing.source_url
        fact_doc_id = "filing:" + financial_analysis_sector_numbers.digest([filing.issuer["id"], filing.standard, filing.period, fact_url])[:24] if fact_url else filing.source.get("document_id")
        base = filing.opening if financial_analysis_sector_templates.balance_line(key, filing.template) else filing.previous
        fact = {"id": financial_analysis_sector_numbers.digest([filing.issuer["id"], filing.standard, filing.period, key, raw, fact_doc_id])[:24],
                "issuer_id": filing.issuer["id"], "metric": key, "metric_code": key, "label": metric_label(key),
                "raw": raw, "value_raw": raw, "value": value, "value_normalized": str(financial_analysis_sector_numbers.decimal(raw)),
                "unit": "thousand UZS", "unit_raw": line_row.get("unit") or filing.source.get("unit") or "thousand UZS",
                "unit_normalized": "thousand UZS", "currency": line_row.get("currency") or filing.source.get("currency") or filing.snapshot.get("currency") or "UZS",
                "multiplier": financial_analysis_sector_numbers.number(line_row.get("multiplier") or filing.source.get("multiplier") or filing.snapshot.get("multiplier") or 1),
                "period": filing.period, "period_start": filing.snapshot.get("period_start") or f"{filing.year}-01-01", "period_end": filing.end.isoformat(),
                "period_kind": filing.snapshot.get("period_basis"), "accounting_standard": filing.standard.upper(),
                "consolidation_scope": filing.snapshot.get("scope"), "source": {**filing.source, "url": fact_url, "document_id": fact_doc_id}, "source_url": fact_url,
                "source_document_id": fact_doc_id, "source_line_id": line,
                "source_document_hash": filing.source.get("document_hash") or filing.source.get("sha256") or filing.source.get("hash"),
                "source_published_at": filing.source.get("published_at") or filing.source.get("publication_date"),
                "source_received_at": filing.source.get("received_at") or filing.source.get("retrieved_at"),
                "source_location": {k: v for k, v in {
                    "page": line_row.get("page") or filing.source.get("page"), "sheet": line_row.get("sheet"),
                    "row": line_row.get("row"), "cell": line_row.get("cell") or line_row.get("cell_ref")
                }.items() if v is not None},
                "source_original_line": line_row.get("label") or line_row.get("original_line"),
                "mapping_rule_version": financial_analysis_sector_templates.MAPPING_VERSION, "parser_version": filing.snapshot.get("parser_version", "catalog"),
                "verification_status": "verified" if filing.publishable else "blocked", "confidence": "high" if filing.source_url else "low",
                "comparison_basis": "opening" if base is filing.opening else "previous",
                **financial_analysis_sector_numbers.change(value, base.get(key))}
        fact["previous_date"] = comparison_date(filing, fact["comparison_basis"]) if fact.get("previous") is not None else None
        facts.append(fact)
        by_code[key] = fact
    verified = facts if filing.publishable else []
    calculation_inputs = []
    narrative_lines = {fact["source_line_id"] for fact in verified}
    for line in sorted({line for result in filing.ratios for line in result["component_facts"]} - narrative_lines):
        row = filing.lines.get(line) or {}
        raw = row.get("raw_current")
        if raw is None:
            continue
        fact_url = row.get("source_url") or filing.source_url
        calculation_inputs.append({"id": financial_analysis_sector_numbers.digest([filing.issuer["id"], filing.standard, filing.period, line, raw, fact_url])[:24],
                "metric_code": line, "label": row.get("label") or line, "value_raw": raw, "value": financial_analysis_sector_numbers.number(raw),
                "unit": "thousand UZS", "period": filing.period, "period_end": filing.end.isoformat(), "source_url": fact_url,
                "source_document_id": "filing:" + financial_analysis_sector_numbers.digest([filing.issuer["id"], filing.standard, filing.period, fact_url])[:24], "source_line_id": line,
                "source_location": {k: row[k] for k in ("sheet", "row") if row.get(k) is not None},
                "parser_version": filing.snapshot.get("parser_version", "catalog"), "mapping_rule_version": row.get("mapping_rule", financial_analysis_sector_templates.MAPPING_VERSION),
                "verification_status": "verified" if filing.publishable else "blocked"})
    blocks = {key: [{"metric_code": code, "label": financial_analysis_sector_language.label(code, filing.lang), **(by_code.get(code) or {"value": None, "previous": None, "change_value": None, "change_pct": None})} for code in columns] if filing.publishable else [] for key, columns in filing.codes.items()}
    return ReportEvidence(verified=verified, by_code=by_code, calculation_inputs=calculation_inputs, blocks=blocks)
