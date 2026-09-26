"""Compatibility imports for sector_analysis; implementations have explicit owners."""

from financial_analysis.sector_calculations import (
    METHODS,
    balance_gate,
    capital_analysis,
    enterprise_ratios,
    profit_quality,
    trend_state,
)

from financial_analysis.sector_inputs import (
    EXPENSE_LINES,
    FORM1,
    FORM2,
    prepare_inputs,
    source_line_pairs,
    statement_rows,
)

from financial_analysis.sector_issues import (
    make_issues,
)

from financial_analysis.sector_language import (
    LABELS,
    format_number,
    label,
    tr,
)

from financial_analysis.sector_numbers import (
    change,
    decimal,
    difference,
    digest,
    number,
    ratio,
    total,
)

from financial_analysis.sector_report import (
    make_report,
)

from financial_analysis.sector_templates import (
    BALANCE,
    BANK_RESULT,
    CALCULATION_VERSION,
    CATALOG_SECTOR_TEMPLATES,
    CORE_RESULT,
    FINANCE_BALANCE,
    FINANCIAL_TYPES,
    FUND_BALANCE,
    FUND_RESULT,
    INSURANCE_BALANCE,
    INSURANCE_RESULT,
    MAPPING_VERSION,
    OKED_MAP,
    SECTOR_PHRASE_BALANCE_LINES,
    SECTOR_PHRASE_FLOW_LINES,
    SECTOR_PROFILES,
    SPECIAL_TYPES,
    VERSION,
    block_codes,
    resolve_template,
)
