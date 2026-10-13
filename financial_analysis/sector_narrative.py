"""Assemble the published analysis from the six written blocks.

A filing that cannot be published still gets a line: a snapshot on the date
from the figures its failed check does not touch, and the one reason.
"""
from __future__ import annotations

from decimal import Decimal

from financial_analysis.sector_models import ReportEvidence
from financial_analysis.sector_models import ReportNarrative
from financial_analysis.sector_models import SectorAssessment
from financial_analysis.sector_models import ValidatedFiling
import financial_analysis.sector_numbers as financial_analysis_sector_numbers
import financial_analysis.sector_vocabulary as vocab
import financial_analysis.sector_writer as financial_analysis_sector_writer

# Why a filing is blocked, in one line, and which figures that reason leaves
# standing.  «flows» are the results of the period, «assets» the asset total.
BLOCK_REASONS = {
    "BALANCE_IDENTITY_FAILED": (("баланс в отчёте не сходится на {difference}", "hisobotdagi balans {difference}ga mos kelmaydi", "the balance sheet is out by {difference}"), ("flows",)),
    "BALANCE_COMPONENTS_MISSING": (("в балансе нет итога активов, капитала или обязательств", "balansda aktivlar, kapital yoki majburiyatlar jami yo‘q", "the balance sheet lacks a total for assets, equity or liabilities"), ("flows",)),
    "CAPITAL_COMPONENTS_MISMATCH": (("изменение капитала не сходится с его составляющими", "kapital o‘zgarishi uning tarkibiy qismlariga mos kelmaydi", "the change in equity does not match its components"), ("flows", "assets")),
    "SOURCE_NOT_VERIFIED": (("нет ссылки на исходный документ", "asl hujjatga havola yo‘q", "there is no link to the source document"), ()),
    "SOURCE_MAPPING_FAILED": (("строки отчёта пока не распознаны", "hisobot satrlari hali aniqlanmagan", "the filing's lines are not recognised yet"), ()),
    "blocked_unit_mismatch": (("единицы измерения форм №1 и №2 не совпадают", "1- va 2-shakl o‘lchov birliklari mos emas", "Forms 1 and 2 use different units"), ()),
    "COMPARATIVE_VALUES_UNIT_MISMATCH": (("сравнительные данные отчёта расходятся по единицам измерения", "hisobotning taqqoslama ma’lumotlari o‘lchov birligi bo‘yicha farq qiladi", "the filing's comparative figures disagree on units"), ()),
    "INSURANCE_RESERVES_OMITTED": (("в отчёте не найдены страховые резервы", "hisobotda sug‘urta zaxiralari topilmadi", "the insurance reserves were not found in the filing"), ("flows",)),
    "SCOPE_NOT_VERIFIED": (("периметр консолидации не подтверждён", "konsolidatsiya doirasi tasdiqlanmagan", "the consolidation scope is not confirmed"), ()),
    "CLASSIFICATION_CONFLICT": (("источники расходятся в отраслевой классификации", "manbalar tarmoq tasnifida farq qiladi", "the sources disagree on the industry classification"), ()),
    "TEMPLATE_FORM_MISMATCH": (("форма отчёта не соответствует типу организации", "hisobot shakli tashkilot turiga mos emas", "the filing form does not match the organisation type"), ()),
    "DUPLICATE_SOURCE_LINE": (("одна строка отчёта указана с разными суммами", "hisobotning bir satri turli summalar bilan berilgan", "one line of the filing carries two different amounts"), ()),
    "FACT_CONTEXT_MISMATCH": (("строки отчёта относятся к другому периоду или эмитенту", "hisobot satrlari boshqa davr yoki emitentga tegishli", "lines of the filing belong to another period or issuer"), ()),
    "PERCENTAGE_RECONCILIATION_FAILED": (("раскрытые коэффициенты не сходятся с расчётом", "oshkor qilingan koeffitsiyentlar hisob-kitobga mos emas", "the disclosed ratios do not match the calculation"), ("flows", "assets")),
    "AUDITED_IFRS_REQUIRED": (("нужна аудированная годовая отчётность МСФО", "auditdan o‘tgan yillik MHXS hisoboti kerak", "audited annual IFRS statements are required"), ()),
    "SPV_ASSET_LINK_REQUIRED": (("не подтверждены обеспечивающие активы", "ta’minot aktivlari tasdiqlanmagan", "the backing assets are not confirmed"), ()),
    "REGRESSION_GATE_FAILED": (("текст анализа не прошёл автоматическую проверку", "tahlil matni avtomatik tekshiruvdan o‘tmadi", "the analysis text failed its automatic checks"), ("flows", "assets")),
    "TEXT_CHECK_FAILED": (("текст анализа не прошёл автоматическую проверку", "tahlil matni avtomatik tekshiruvdan o‘tmadi", "the analysis text failed its automatic checks"), ("flows", "assets")),
}
NO_SOURCE = ("подходящая отчётность НСБУ не найдена", "mos BHMS hisoboti topilmadi", "no suitable NSBU filing was found")


def blocked_text(filing):
    """«Срез на 30.06.2026: … Анализ не публикуется: баланс не сходится на X.»"""
    lang = filing.lang if filing.lang in vocab.LANGS else "ru"
    blocking = [item for item in filing.data_quality if item.get("severity") == "blocking"]
    if filing.status == "no_source" or not blocking:
        reason, standing = vocab.pick(lang, *NO_SOURCE), ()
    else:
        entry = next((BLOCK_REASONS[item["code"]] for item in blocking if item.get("code") in BLOCK_REASONS), None)
        first = next((item for item in blocking if item.get("code") in BLOCK_REASONS), blocking[0])
        if entry is None:
            reason, standing = vocab.pick(lang, "данные не прошли автоматическую сверку", "ma’lumotlar avtomatik tekshiruvdan o‘tmadi", "the data failed automated validation"), ()
        else:
            reason = vocab.pick(lang, *entry[0])
            # Every reason that fired limits what may still be shown.
            standing = set(entry[1])
            for item in blocking:
                standing &= set((BLOCK_REASONS.get(item.get("code")) or ((), ()))[1])
            if "{difference}" in reason:
                difference = financial_analysis_sector_numbers.decimal(first.get("difference"))
                assets = financial_analysis_sector_numbers.decimal(filing.values.get("total_assets"))
                if difference and assets and assets > 0:
                    reason = reason.format(difference=vocab.money(abs(difference), lang))
                else:
                    reason = vocab.pick(lang, "в балансе нет положительной суммы активов", "balansda aktivlarning musbat summasi yo‘q", "the balance sheet shows no positive total assets")
    figures = []
    for group, code, ru, uz, en in (("flows", "revenue", "выручка за период", "davr tushumi", "revenue for the period"),
                                    ("flows", "net_income", "чистая прибыль", "sof foyda", "net profit"),
                                    ("assets", "total_assets", "активы", "aktivlar", "total assets")):
        value = financial_analysis_sector_numbers.decimal(filing.values.get(code))
        if group in standing and value is not None:
            figures.append(f"{vocab.pick(lang, ru, uz, en)} — {vocab.money(value, lang)}")
    date = filing.end.strftime("%d.%m.%Y") if filing.period else None
    tail = vocab.pick(lang, f"Анализ не публикуется: {reason}.", f"Tahlil e’lon qilinmaydi: {reason}.", f"The analysis is not published: {reason}.")
    if figures and date:
        lead = vocab.pick(lang, f"Срез на {date}: ", f"{date} holatiga: ", f"Snapshot at {date}: ") + ", ".join(figures) + "."
        return lead + " " + tail, lead, reason
    return tail, None, reason


def render_narrative(filing: ValidatedFiling, evidence: ReportEvidence, assessment: SectorAssessment):
    display_divisor = financial_analysis_sector_numbers.decimal(filing.snapshot.get("display_divisor")) or Decimal(1)
    complete_content = filing.publishable and len(evidence.verified) >= 7
    if not filing.publishable:
        headline, snapshot_line, reason = blocked_text(filing)
        return ReportNarrative(key_changes=[], task1_sections=[], narrative_blocks={}, display_divisor=display_divisor,
                               headline=headline, complete_content=False, paragraphs=[headline], text=headline,
                               report_sections=[], card_text=None, verdict_line=None, footnote=None,
                               sentences=[], blocked={"snapshot": snapshot_line, "reason": reason})
    written = financial_analysis_sector_writer.write(filing, evidence, assessment)
    sections = [{key: value for key, value in section.items() if key != "sentences"} for section in written["sections"]]
    sentences = [(section["id"], sentence) for section in written["sections"] for sentence in section["sentences"]]
    paragraphs = [section["text"] for section in sections]
    key_changes = []
    for sentence in written["key_points"]:
        facts = [evidence.by_code.get(code) for code in sentence.metrics]
        if not facts or any(not fact or not fact.get("source_url") for fact in facts):
            continue
        key_changes.append({
            "id": financial_analysis_sector_numbers.digest([filing.issuer["id"], filing.period, "key-change", sentence.metrics])[:24],
            "code": sentence.metrics[0], "category": "change", "text": sentence.text,
            "metric_codes": list(sentence.metrics), "evidence_fact_ids": [fact["id"] for fact in facts],
            "verification_status": "verified",
        })
    footnote = next((section["text"] for section in sections if section["id"] == "footnote"), None)
    return ReportNarrative(key_changes=key_changes, task1_sections=sections, narrative_blocks={}, display_divisor=display_divisor,
                           headline=written["headline"], complete_content=complete_content, paragraphs=paragraphs,
                           text="\n\n".join(paragraphs), report_sections=sections, card_text=written["card_text"],
                           verdict_line=written["verdict_line"], footnote=footnote, sentences=sentences, blocked=None)
