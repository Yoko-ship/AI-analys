"""Validate classification, units, source context and financial identities before publication."""
from __future__ import annotations
from datetime import date
from decimal import Decimal
from financial_analysis.sector_models import ValidatedFiling
import financial_analysis.sector_calculations as financial_analysis_sector_calculations
import financial_analysis.sector_inputs as financial_analysis_sector_inputs
import financial_analysis.sector_language as financial_analysis_sector_language
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_templates as financial_analysis_sector_templates
import re


def validate_filing(snapshot, issuer, lang, today, workbook=None, period_label=None):
    today = today or date.today()
    values, previous, opening, lines = financial_analysis_sector_inputs.prepare_inputs(snapshot, workbook)
    resolution = snapshot.get("template_resolution") or financial_analysis_sector_templates.resolve_template(issuer, snapshot.get("organization_type"), today)
    template = resolution["selected_template"]
    org = snapshot.get("organization_type")
    standard, period = snapshot.get("standard", "nsbu"), snapshot.get("period")
    period_text = period_label or period or "—"
    source = snapshot.get("source") or {}
    source_url = source.get("url")
    data_quality = [dict(item) for item in (snapshot.get("quality") or {}).get("data_quality") or []
                    if item.get("code") not in {"BALANCE_COMPONENTS_MISSING", "BALANCE_IDENTITY_FAILED", "SECTOR_TEMPLATE_MISSING"}]
    codes = financial_analysis_sector_templates.block_codes(template)
    # A bank's generic catalog "operating income" is often pre-tax income.
    # It cannot enter a bank verdict without a dedicated source mapping.
    if template in {"bank", "microfinance_bank", "microfinance"}:
        values.pop("operating_income", None)
        previous.pop("operating_income", None)
    balance = financial_analysis_sector_calculations.balance_gate(values, snapshot.get("rounding_unit", 1))
    if balance["status"] != "passed" and values:
        data_quality.append({**balance, "message": financial_analysis_sector_language.tr(lang, "Баланс не прошёл сверку: проверьте компоненты и единицы.", "Balans tekshiruvdan o‘tmadi: tarkib va birliklarni tekshiring.", "Balance validation failed: check components and units.")})
    if resolution["resolution_status"] == "classification_conflict":
        data_quality.append({"code": "CLASSIFICATION_CONFLICT", "severity": "blocking", "message": financial_analysis_sector_language.tr(lang, "Источники классификации противоречат друг другу.", "Tasnif manbalari bir-biriga zid.", "Classification sources conflict.")})
    if (template in financial_analysis_sector_templates.FINANCIAL_TYPES or org in financial_analysis_sector_templates.FINANCIAL_TYPES) and template != org:
        data_quality.append({"code": "TEMPLATE_FORM_MISMATCH", "severity": "blocking",
                             "message": financial_analysis_sector_language.tr(lang, "Отраслевой шаблон не соответствует типу исходной формы.", "Tarmoq shabloni asl shakl turiga mos emas.", "The sector template does not match the source form type.")})
    if snapshot.get("scope") == "consolidated" and not snapshot.get("scope_verified"):
        data_quality.append({"code": "SCOPE_NOT_VERIFIED", "severity": "blocking", "message": financial_analysis_sector_language.tr(lang, "Консолидированный периметр не подтверждён источником.", "Konsolidatsiya doirasi manbada tasdiqlanmagan.", "Consolidated scope is not verified by the source.")})
    for key, row in lines.items():
        if row.get("conflict"):
            data_quality.append({"code": "DUPLICATE_SOURCE_LINE", "severity": "blocking", "message": key})
        for field, expected in (("period", period), ("accounting_standard", standard.upper()), ("issuer_id", issuer["id"])):
            if row.get(field) is not None and str(row[field]).upper() != str(expected).upper():
                data_quality.append({"code": "FACT_CONTEXT_MISMATCH", "severity": "blocking", "message": f"{key}: {field}"})
    # A thousandfold form discrepancy cannot be silently repaired by scaling.
    scale = financial_analysis_sector_numbers.ratio(abs(financial_analysis_sector_numbers.decimal(values.get("net_income")) or 0), values.get("total_assets"))
    declared_units = snapshot.get("form_units") or {}
    if (scale is not None and scale > 100) or len(set(declared_units.values())) > 1:
        data_quality.append({"code": "blocked_unit_mismatch", "severity": "blocking", "message": financial_analysis_sector_language.tr(lang, "Масштаб Форм №1 и №2 не сопоставим; коэффициенты скрыты.", "1- va 2-shakl masshtablari mos emas; koeffitsiyentlar yashirilgan.", "Form 1 and Form 2 scales are incompatible; ratios are withheld.")})
    if template == "investment_fund_ifrs_annual" and (standard != "ifrs" or not snapshot.get("audited")):
        data_quality.append({"code": "AUDITED_IFRS_REQUIRED", "severity": "blocking", "message": financial_analysis_sector_language.tr(lang, "Нужна аудированная годовая МСФО фонда.", "Fondning auditdan o‘tgan yillik MHXS hisoboti kerak.", "The fund requires audited annual IFRS statements.")})
    if template == "spv":
        data_quality.append({"code": "SPV_ASSET_LINK_REQUIRED", "severity": "blocking", "message": financial_analysis_sector_language.tr(lang, "Не подтверждены обеспечивающие активы и денежные потоки SPV.", "SPV ta’minot aktivlari va pul oqimlari tasdiqlanmagan.", "SPV backing assets and cash flows have not been verified.")})
    if not source_url and values:
        data_quality.append({"code": "SOURCE_NOT_VERIFIED", "severity": "blocking", "message": financial_analysis_sector_language.tr(lang, "Нет ссылки на исходный документ.", "Asl hujjat havolasi yo‘q.", "The source document link is missing.")})
    capital = financial_analysis_sector_calculations.capital_analysis(values, opening)
    quality = financial_analysis_sector_calculations.profit_quality(values, previous)
    computed_ratios = financial_analysis_sector_calculations.enterprise_ratios(lines, org, standard, period, methods=snapshot.get("formula_methods"))
    for item in computed_ratios:
        disclosed = financial_analysis_sector_numbers.decimal((snapshot.get("reported_ratios") or {}).get(item["metric"]))
        if item["unit"] == "percent" and disclosed is not None and item["raw_result"] is not None and abs(disclosed - financial_analysis_sector_numbers.decimal(item["raw_result"])) > Decimal("0.1"):
            data_quality.append({"code": "PERCENTAGE_RECONCILIATION_FAILED", "severity": "blocking", "message": item["metric"]})
    if capital["reconciliation_status"] == "failed":
        data_quality.append({"code": "CAPITAL_COMPONENTS_MISMATCH", "severity": "blocking", "message": financial_analysis_sector_language.tr(lang, "Изменение капитала не сходится с его компонентами.", "Kapital o‘zgarishi uning tarkibiga mos emas.", "Equity movement does not reconcile to its components.")})
    if not period or not values:
        status = "no_source"
    elif any(q.get("severity") == "blocking" for q in data_quality):
        status = "mapping_failed" if any(q.get("code") == "SOURCE_MAPPING_FAILED" for q in data_quality) else "quality_blocked"
    else:
        status = "available"
    year = int(str(period)[:4]) if period and str(period)[:4].isdigit() else today.year
    quarter = int(str(period)[-1]) if period and re.fullmatch(r"\d{4}Q[1-4]", period) else 4
    end = date(year, quarter * 3, (31, 30, 30, 31)[quarter - 1])
    if status == "available" and (today - end).days > snapshot.get("max_age_days", 550 if standard == "ifrs" else 210):
        status = "stale"
    # An issuer that has stopped filing is still analyzable from its last
    # traceable statement.  Keep the distinct ``stale`` status and date so it
    # can never be mistaken for current information, but do not turn a valid
    # historical report into an empty screen.
    publishable = status in {"available", "stale"}
    ratios = computed_ratios if publishable else []
    if template == "commodity_exchange" and any(values.get(k) is None for k in ("own_cash", "client_cash", "settlement_liabilities")):
        ratios = [r for r in ratios if r["metric"].startswith("P")]
    return ValidatedFiling(snapshot=snapshot, issuer=issuer, lang=lang, today=today, values=values, previous=previous, opening=opening, lines=lines, resolution=resolution, template=template, org=org, standard=standard, period=period, period_text=period_text, source=source, source_url=source_url, data_quality=data_quality, codes=codes, balance=balance, capital=capital, quality=quality, status=status, year=year, end=end, publishable=publishable, ratios=ratios)
