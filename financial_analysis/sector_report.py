"""Compose validated facts, assessments and language into the public report contract."""
from __future__ import annotations
from financial_analysis.sector_validation import validate_filing
from financial_analysis.sector_evidence import collect_evidence
from financial_analysis.sector_assessment import assess_filing
from financial_analysis.sector_narrative import render_narrative
from datetime import date
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_templates as financial_analysis_sector_templates


def make_report(snapshot, issuer, lang="ru", today=None, workbook=None, period_label=None):
    today = today or date.today()
    filing = validate_filing(snapshot, issuer, lang, today, workbook, period_label)
    evidence = collect_evidence(filing)
    assessment = assess_filing(filing, evidence)
    narrative = render_narrative(filing, evidence, assessment)
    refs = [{**f, "raw": financial_analysis_sector_numbers.number(f["raw"])} for f in evidence.verified]
    report = {"ok": True, "issuer": {"id": issuer["id"], "ticker": issuer["ticker"], "name": issuer.get("name"), "organization_type": filing.org, "sector": filing.template},
              "report": {"standard": filing.standard.upper(), "template_basis": snapshot.get("template_basis"), "period": filing.period, "period_end": filing.end.isoformat(), "status": filing.status},
              "standard": filing.standard, "scope": snapshot.get("scope"), "period": filing.period, "period_label": filing.period_text,
              "display_divisor": financial_analysis_sector_numbers.number(narrative.display_divisor),
              "period_basis": snapshot.get("period_basis"), "language": lang, "status": filing.status,
              "content_status": "complete" if narrative.complete_content else "shortened",
              "shortened_reason": None if narrative.complete_content else "insufficient_traceable_metrics",
              "sector_template_code": filing.template, "template_resolution": filing.resolution,
              "industry_analysis_basis": {"oked_code": filing.resolution.get("input_oked"), "profile": filing.template,
                                            "matched": filing.template in financial_analysis_sector_templates.SECTOR_PROFILES},
              "template_version": financial_analysis_sector_templates.VERSION,
              "calculation_version": financial_analysis_sector_templates.CALCULATION_VERSION, "mapping_version": financial_analysis_sector_templates.MAPPING_VERSION,
              "headline": narrative.headline, "short_summary": narrative.card_text, "card_text": narrative.card_text,
              "card_word_count": len(narrative.card_text.split()) if narrative.card_text else 0,
              "headline_tone": {"positive": "positive", "mixed": "warning", "negative": "danger", "no_signal": "neutral"}[assessment.verdict_status],
              "narrative_structure": "ielts-task-1-v1", "task1_sections": narrative.task1_sections,
              "key_changes": narrative.key_changes,
              "paragraphs": narrative.paragraphs, "text": narrative.text, "paragraph_count": len(narrative.paragraphs), "word_count": len(narrative.text.split()),
              "abstract": narrative.headline if filing.publishable else None,
              "sections": narrative.report_sections,
              "verified_facts": refs, "number_references": refs, "calculation_inputs": evidence.calculation_inputs,
              "ratios": filing.ratios, "public_ratios": [item for item in filing.ratios if item.get("metric_code") not in {"current_ratio", "quick_ratio"}],
              "replacement_blocks": evidence.blocks,
              "capital_analysis": filing.capital if filing.publishable else {}, "profit_quality": filing.quality if filing.publishable else {},
              "analytical_signals": assessment.signals, "analytical_issues": assessment.issues, "risks": assessment.risks,
              "monitoring_points": assessment.monitoring_points if filing.publishable else [], "trend": assessment.trend,
              "verification_summary": assessment.verification_summary,
              "verdict": {"status": assessment.verdict_status, "headline": narrative.headline if filing.publishable else None, "evidence_signal_ids": [s["id"] for s in assessment.signals] if assessment.verdict_status != "no_signal" else [], "period_end": filing.end.isoformat()},
              "data_quality": filing.data_quality, "balance_check": filing.balance, "financial_as_of": filing.end.isoformat() if filing.period else None,
              "market_as_of": None, "sources": [filing.source] if filing.source_url else [],
              "availability": {"reason_code": filing.status, "last_source_period": filing.period, "last_successful_period": filing.period if filing.publishable else None,
                               "next_action": financial_analysis_sector_language.tr(lang, "Мы проверим данные снова после обновления источника.", "Manba yangilangach ma’lumotlarni yana tekshiramiz.", "We will check the data again after the source is updated.") if filing.status == "stale" or not filing.publishable else None},
              "source_snapshot_hash": financial_analysis_sector_numbers.digest([issuer["id"], filing.standard, filing.period, filing.values, filing.previous, filing.opening, filing.lines, filing.source]),
              "generated_at": snapshot.get("generated_at")}
    report["control_rule_versions"] = snapshot.get("control_rule_versions", [])
    for result in report["ratios"]:
        if result["metric_code"] in snapshot.get("formula_rule_versions", {}):
            result["method_id"] = snapshot["formula_rule_versions"][result["metric_code"]]
    if report["control_rule_versions"]:
        report["calculation_version"] += ":" + financial_analysis_sector_numbers.digest(report["control_rule_versions"])[:16]
    report["version"] = financial_analysis_sector_numbers.digest([report["source_snapshot_hash"], filing.resolution, financial_analysis_sector_templates.VERSION, financial_analysis_sector_templates.MAPPING_VERSION, financial_analysis_sector_templates.CALCULATION_VERSION, lang, filing.status, today.isoformat(), report["control_rule_versions"]])
    return report
