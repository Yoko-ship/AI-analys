"""Results passed between independent report stages."""
from __future__ import annotations
from dataclasses import dataclass


from typing import Any


@dataclass(frozen=True)
class ValidatedFiling:
    snapshot: Any
    issuer: Any
    lang: Any
    today: Any
    values: Any
    previous: Any
    opening: Any
    lines: Any
    resolution: Any
    template: Any
    org: Any
    standard: Any
    period: Any
    period_text: Any
    source: Any
    source_url: Any
    data_quality: Any
    codes: Any
    balance: Any
    capital: Any
    quality: Any
    status: Any
    year: Any
    end: Any
    publishable: Any
    ratios: Any


@dataclass(frozen=True)
class ReportEvidence:
    verified: Any
    by_code: Any
    calculation_inputs: Any
    blocks: Any


@dataclass(frozen=True)
class SectorAssessment:
    signals: Any
    negatives: Any
    positives: Any
    verdict_status: Any
    verdict_label: Any
    issues: Any
    risks: Any
    monitoring_points: Any
    trend: Any
    verification_summary: Any


@dataclass(frozen=True)
class ReportNarrative:
    key_changes: Any
    task1_sections: Any
    narrative_blocks: Any
    display_divisor: Any
    headline: Any
    complete_content: Any
    paragraphs: Any
    text: Any
    report_sections: Any
    card_text: Any
