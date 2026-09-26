"""Render completed analysis and comparison results to PDF and Excel.

No collection, calculation requests, or persistence happens here."""

from __future__ import annotations
import json
from numeric_parse import parse_decimal
from reporting.comparison_metrics import COMPARISON_FIELDS
from reporting.disclaimer import _EXCEL_DISCLAIMER, report_disclaimer
from reporting.localization import _normalize_language, _risk_tr
from reporting.numbers import _safe_float
from reporting.settings import OPENAI_MODEL


def _excel_number(value):
    """Return a float if value is numeric-like, else None (so numbers export as numbers).

    Multiplier cells are rendered with a times sign ("8.4x"); drop it, then hand
    the token to the shared parser so a comma-grouped sum exports as a number
    instead of falling through to text.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("×", "").replace("x", "")
    return parse_decimal(text, group_sep=",", strip_non_numeric=False)


_PDF_FONT_CACHE: dict = {}


def _pdf_font():
    """Register a Cyrillic-capable TTF once; return (regular, bold) family names.
    DejaVu on Linux (the Docker image installs fonts-dejavu-core), Arial on
    Windows dev, Helvetica as a last resort (Latin only)."""
    if _PDF_FONT_CACHE.get("name"):
        return _PDF_FONT_CACHE["name"], _PDF_FONT_CACHE["bold"]
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ]
    for regular, bold in candidates:
        if os.path.exists(regular):
            try:
                pdfmetrics.registerFont(TTFont("AppSans", regular))
                bold_name = "AppSans"
                if os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont("AppSans-Bold", bold))
                    pdfmetrics.registerFontFamily("AppSans", normal="AppSans", bold="AppSans-Bold")
                    bold_name = "AppSans-Bold"
                _PDF_FONT_CACHE.update(name="AppSans", bold=bold_name)
                return "AppSans", bold_name
            except Exception:
                continue
    _PDF_FONT_CACHE.update(name="Helvetica", bold="Helvetica-Bold")
    return "Helvetica", "Helvetica-Bold"


def build_analysis_pdf(result: dict, language: str = "ru", generated_at=None) -> bytes:
    """Render a completed analysis result to a PDF (ТЗ §3.13 / C5). Mirrors the
    Excel export: header, key metrics, risk profile, statistical observations,
    narrative sections, and the mandatory disclaimer."""
    from io import BytesIO
    from datetime import datetime
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    generated_at = generated_at or datetime.now()
    font, bold = _pdf_font()
    lang = _normalize_language(language)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=font, fontSize=9.5, leading=13)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontName=bold, fontSize=18, leading=22, spaceAfter=2, alignment=0)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=bold, fontSize=12, leading=15, spaceBefore=11, spaceAfter=4)
    muted = ParagraphStyle("muted", parent=body, textColor=colors.HexColor("#64748b"), fontSize=8.5)
    disc = ParagraphStyle("disc", parent=body, textColor=colors.HexColor("#64748b"), fontSize=7.5, leading=10)

    def esc(s):
        s = "" if s is None else str(s)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def fnum(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return "—"
        for unit, div in ((("млрд" if lang == "ru" else "B"), 1e9), (("млн" if lang == "ru" else "M"), 1e6), (("тыс" if lang == "ru" else "K"), 1e3)):
            if abs(v) >= div:
                return f"{v / div:.2f} {unit}"
        return f"{v:.0f}"

    def pct(v):
        try:
            return f"{float(v):.1f}%"
        except (TypeError, ValueError):
            return "—"

    snap = result.get("ifrs_snapshot") or {}
    inc = snap.get("income_statement") or {}
    bs = snap.get("balance_sheet") or {}
    q = snap.get("quality") or {}
    company = result.get("company_name") or result.get("input") or "—"
    ticker = result.get("ticker") or ""
    summary = result.get("summary") or {}

    story = [Paragraph(esc(company) + (f" · {esc(ticker)}" if ticker else ""), h1)]
    meta_bits = []
    if summary.get("score") is not None:
        meta_bits.append(f"{_risk_tr(lang, 'Скоринг', 'Score', 'Skoring')}: {esc(summary.get('score'))}" + (f" ({esc(summary.get('grade'))})" if summary.get("grade") else ""))
    meta_bits.append(generated_at.strftime("%Y-%m-%d %H:%M"))
    story.append(Paragraph(" · ".join(meta_bits), muted))
    story.append(Spacer(1, 8))

    metric_rows = [
        [_risk_tr(lang, "Выручка", "Revenue", "Tushum"), fnum(inc.get("revenue"))],
        ["EBIT", fnum(inc.get("ebit"))],
        ["EBITDA", fnum(inc.get("ebitda"))],
        [_risk_tr(lang, "Чистая прибыль", "Net income", "Sof foyda"), fnum(inc.get("net_income"))],
        [_risk_tr(lang, "Чистая маржа", "Net margin", "Sof marja"), pct(inc.get("net_margin_pct"))],
        ["ROE", pct(q.get("roe_pct"))],
        ["ROA", pct(q.get("roa_pct"))],
        [_risk_tr(lang, "Долг/капитал", "Debt/equity", "Qarz/kapital"), (f"{float(bs.get('debt_to_equity')):.2f}" if bs.get("debt_to_equity") is not None else "—")],
    ]
    story.append(Paragraph(_risk_tr(lang, "Ключевые показатели", "Key metrics", "Asosiy ko'rsatkichlar"), h2))
    tbl = Table([[Paragraph(esc(r[0]), body), Paragraph(esc(r[1]), body)] for r in metric_rows], colWidths=[100 * mm, 74 * mm])
    tbl.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
    ]))
    story.append(tbl)

    rp = result.get("risk_profile") or {}
    if rp.get("axes"):
        story.append(Paragraph(_risk_tr(lang, "Профиль риска", "Risk profile", "Risk profili"), h2))
        for ax in rp["axes"]:
            drivers = "; ".join(ax.get("drivers") or [])
            story.append(Paragraph(f"<b>{esc(ax.get('label'))}:</b> {esc(ax.get('level_label'))}" + (f" — {esc(drivers)}" if drivers else ""), body))

    obs = result.get("observations") or []
    if obs:
        story.append(Paragraph(_risk_tr(lang, "Статистические наблюдения", "Statistical observations", "Statistik kuzatuvlar"), h2))
        for o in obs:
            story.append(Paragraph("• " + esc(o.get("text")), body))

    sections = result.get("sections") or {}
    if isinstance(sections, dict) and sections:
        story.append(Paragraph(_risk_tr(lang, "Разделы отчёта", "Report sections", "Hisobot bo'limlari"), h2))
        for name, text in sections.items():
            if not text:
                continue
            story.append(Paragraph(f"<b>{esc(name)}</b>", body))
            story.append(Paragraph(esc(str(text)[:3500]).replace("\n", "<br/>"), body))
            story.append(Spacer(1, 4))

    story.append(Spacer(1, 10))
    story.append(Paragraph(esc(report_disclaimer(lang)), disc))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=14 * mm, title=f"{company} — analysis")
    doc.build(story)
    return buf.getvalue()


def build_analysis_excel(result: dict, language: str = "ru", generated_at=None) -> bytes:
    """Export an analysis result to .xlsx (ТЗ §3.13): sheet 1 = disclaimer + meta,
    following sheets = data. Numbers are written as numbers, dates as Excel dates."""
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment

    lang = (language or "ru").lower()
    if lang not in ("ru", "en", "uz"):
        lang = "ru"
    L = {
        "ru": {"info": "Информация", "metrics": "Показатели", "sections": "Разделы",
               "title": "Аналитический отчёт", "company": "Компания", "generated": "Дата формирования",
               "annual": "Годовой период", "quarter": "Квартальный период", "model": "Модель",
               "disclaimer": "Дисклеймер", "metric": "Показатель", "value": "Значение", "section": "Раздел", "text": "Текст"},
        "en": {"info": "Info", "metrics": "Metrics", "sections": "Sections",
               "title": "Analytical report", "company": "Company", "generated": "Generated at",
               "annual": "Annual period", "quarter": "Quarterly period", "model": "Model",
               "disclaimer": "Disclaimer", "metric": "Metric", "value": "Value", "section": "Section", "text": "Text"},
        "uz": {"info": "Ma'lumot", "metrics": "Ko'rsatkichlar", "sections": "Bo'limlar",
               "title": "Tahliliy hisobot", "company": "Kompaniya", "generated": "Shakllantirilgan sana",
               "annual": "Yillik davr", "quarter": "Choraklik davr", "model": "Model",
               "disclaimer": "Ogohlantirish", "metric": "Ko'rsatkich", "value": "Qiymat", "section": "Bo'lim", "text": "Matn"},
    }[lang]
    bold = Font(bold=True)

    wb = Workbook()
    # ── Sheet 1: Info + disclaimer ──
    ws = wb.active
    ws.title = L["info"]
    ws["A1"] = L["title"]
    ws["A1"].font = Font(bold=True, size=14)
    meta = [
        (L["company"], result.get("company_name") or result.get("input") or "—"),
        (L["generated"], generated_at),
        (L["annual"], result.get("annual_period") or "—"),
        (L["quarter"], result.get("quarterly_period") or "—"),
        (L["model"], result.get("model") or OPENAI_MODEL),
    ]
    row = 3
    for label, val in meta:
        ws.cell(row=row, column=1, value=label).font = bold
        cell = ws.cell(row=row, column=2, value=val)
        if label == L["generated"] and generated_at is not None:
            cell.number_format = "yyyy-mm-dd hh:mm"
        row += 1
    row += 1
    ws.cell(row=row, column=1, value=L["disclaimer"]).font = bold
    dcell = ws.cell(row=row + 1, column=1, value=_EXCEL_DISCLAIMER[lang])
    dcell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 6, end_column=6)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 46

    # ── Sheet 2: Metrics (numbers as numbers) ──
    ws2 = wb.create_sheet(L["metrics"])
    ws2.cell(row=1, column=1, value=L["metric"]).font = bold
    ws2.cell(row=1, column=2, value=L["value"]).font = bold
    metrics = result.get("metrics") or {}
    r = 2

    def put(label, raw):
        nonlocal r
        if raw is None or raw == "":
            return
        num = _excel_number(raw)
        ws2.cell(row=r, column=1, value=str(label))
        ws2.cell(row=r, column=2, value=num if num is not None else str(raw))
        r += 1

    if isinstance(metrics, dict):
        score = metrics.get("total_score") or {}
        if isinstance(score, dict):
            put("Score / Итоговый скор", score.get("score"))
            put("Grade / Класс", score.get("grade"))
        for key in ("piotroski_f_score", "altman_z_score", "graham_number", "dcf"):
            val = metrics.get(key)
            if isinstance(val, dict):
                put(key, val.get("score") if val.get("score") is not None else val.get("value") or val.get("intrinsic_value_bn"))
            elif val is not None:
                put(key, val)
        liq = metrics.get("market_liquidity") or {}
        if isinstance(liq, dict):
            put("Liquidity / Ликвидность", liq.get("liquidity_label"))
            put("Trade days / Дней с торгами", liq.get("trade_days"))
            put("Avg trade value / Средний оборот", liq.get("avg_trade_value"))
        ind = metrics.get("industry") or {}
        if isinstance(ind, dict):
            put("Sector / Отрасль", ind.get("sector_name"))
            put("Good indicators / Хороших", ind.get("good_count"))
            put("Weak indicators / Слабых", ind.get("weak_count"))
            de = ind.get("debt_equity") or {}
            if isinstance(de, dict):
                put("D/E", de.get("value"))
                burden = de.get("burden") or {}
                if isinstance(burden, dict):
                    put("Debt load / Долговая нагрузка", burden.get(lang) or burden.get("ru"))
    ws2.column_dimensions["A"].width = 40
    ws2.column_dimensions["B"].width = 24

    # ── Sheet 3: Text sections ──
    sections = result.get("sections") or {}
    if isinstance(sections, dict) and sections:
        ws3 = wb.create_sheet(L["sections"])
        ws3.cell(row=1, column=1, value=L["section"]).font = bold
        ws3.cell(row=1, column=2, value=L["text"]).font = bold
        rr = 2
        for key, val in sections.items():
            text = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
            if not text:
                continue
            ws3.cell(row=rr, column=1, value=str(key)).font = bold
            c = ws3.cell(row=rr, column=2, value=text[:4000])
            c.alignment = Alignment(wrap_text=True, vertical="top")
            rr += 1
        ws3.column_dimensions["A"].width = 30
        ws3.column_dimensions["B"].width = 90

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _comparison_matrix(result: dict):
    """Flatten a /api/compare result into (fields, companies, cell-getter) for
    export. Accepts either the full response or the inner `comparison` block."""
    comp = result.get("comparison") if isinstance(result.get("comparison"), dict) else result
    fields = comp.get("fields") or COMPARISON_FIELDS
    rows = comp.get("rows") or []
    companies = [
        {"name": r.get("company_name") or r.get("input") or "—", "ticker": r.get("ticker") or "", "row": r}
        for r in rows
    ]
    return fields, companies, comp


def build_comparison_excel(result: dict, language: str = "ru", generated_at=None) -> bytes:
    """Export a company comparison to .xlsx (ТЗ §3.6 / §3.13): sheet 1 = disclaimer
    + meta, sheet 2 = metric × issuer matrix. Numbers stay numeric."""
    from io import BytesIO
    from datetime import datetime
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment

    generated_at = generated_at or datetime.now()
    lang = _normalize_language(language)
    fields, companies, _comp = _comparison_matrix(result)
    bold = Font(bold=True)

    wb = Workbook()
    ws0 = wb.active
    ws0.title = _risk_tr(lang, "О документе", "About", "Hujjat haqida")
    ws0.cell(row=1, column=1, value=_risk_tr(lang, "Сравнение эмитентов", "Issuer comparison", "Emitentlar taqqoslovi")).font = Font(bold=True, size=14)
    ws0.cell(row=2, column=1, value=_risk_tr(lang, "Эмитенты", "Issuers", "Emitentlar") + ": " + ", ".join(c["name"] for c in companies))
    ws0.cell(row=3, column=1, value=generated_at.strftime("%Y-%m-%d %H:%M"))
    dcell = ws0.cell(row=5, column=1, value=report_disclaimer(lang))
    dcell.alignment = Alignment(wrap_text=True, vertical="top")
    ws0.column_dimensions["A"].width = 100

    ws = wb.create_sheet(_risk_tr(lang, "Показатели", "Metrics", "Ko'rsatkichlar"))
    ws.cell(row=1, column=1, value=_risk_tr(lang, "Показатель", "Metric", "Ko'rsatkich")).font = bold
    for ci, comp_c in enumerate(companies, start=2):
        header = comp_c["name"] + (f" ({comp_c['ticker']})" if comp_c["ticker"] else "")
        ws.cell(row=1, column=ci, value=header).font = bold
    for ri, field in enumerate(fields, start=2):
        label = field.get("label") or field.get("key")
        unit = field.get("unit")
        ws.cell(row=ri, column=1, value=f"{label} ({unit})" if unit else label)
        for ci, comp_c in enumerate(companies, start=2):
            raw = comp_c["row"].get(field["key"])
            num = _safe_float(raw)
            ws.cell(row=ri, column=ci, value=num if num is not None else (raw if raw not in (None, "") else "—"))
    ws.column_dimensions["A"].width = 34
    for ci in range(2, len(companies) + 2):
        ws.column_dimensions[chr(64 + ci) if ci <= 26 else "A"].width = 20

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_comparison_pdf(result: dict, language: str = "ru", generated_at=None) -> bytes:
    """Render a company comparison to PDF (ТЗ §3.6 / §3.13): metric × issuer table,
    comparative AI summary (if present), and the mandatory disclaimer."""
    from io import BytesIO
    from datetime import datetime
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    generated_at = generated_at or datetime.now()
    font, bold = _pdf_font()
    lang = _normalize_language(language)
    fields, companies, comp = _comparison_matrix(result)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["Normal"], fontName=font, fontSize=8.5, leading=11)
    cellb = ParagraphStyle("cellb", parent=body, fontName=bold)
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontName=bold, fontSize=16, leading=20, alignment=0)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontName=bold, fontSize=11, leading=14, spaceBefore=10, spaceAfter=4)
    muted = ParagraphStyle("muted", parent=body, textColor=colors.HexColor("#64748b"), fontSize=8)
    disc = ParagraphStyle("disc", parent=body, textColor=colors.HexColor("#64748b"), fontSize=7.5, leading=10)

    def esc(s):
        s = "" if s is None else str(s)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def fmt(raw):
        num = _safe_float(raw)
        if num is None:
            return esc(raw) if raw not in (None, "") else "—"
        if abs(num) >= 1e9:
            return f"{num / 1e9:.2f}B"
        if abs(num) >= 1e6:
            return f"{num / 1e6:.2f}M"
        return f"{num:.2f}".rstrip("0").rstrip(".")

    story = [Paragraph(_risk_tr(lang, "Сравнение эмитентов", "Issuer comparison", "Emitentlar taqqoslovi"), h1)]
    story.append(Paragraph(", ".join(esc(c["name"]) for c in companies) + " · " + generated_at.strftime("%Y-%m-%d %H:%M"), muted))
    story.append(Spacer(1, 8))

    head = [Paragraph(_risk_tr(lang, "Показатель", "Metric", "Ko'rsatkich"), cellb)]
    head += [Paragraph(esc(c["name"]) + (f"<br/>{esc(c['ticker'])}" if c["ticker"] else ""), cellb) for c in companies]
    data = [head]
    for field in fields:
        label = field.get("label") or field.get("key")
        unit = field.get("unit")
        line = [Paragraph(esc(f"{label} ({unit})" if unit else label), body)]
        line += [Paragraph(fmt(c["row"].get(field["key"])), body) for c in companies]
        data.append(line)
    col1 = 52 * mm
    rest = (250 * mm - col1) / max(1, len(companies))
    tbl = Table(data, colWidths=[col1] + [rest] * len(companies), repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)

    ai = (comp.get("comparative_ai_summary") or {}) if isinstance(comp, dict) else {}
    if ai.get("text"):
        story.append(Paragraph(_risk_tr(lang, "Comparative AI summary", "Comparative AI summary", "Comparative AI summary"), h2))
        story.append(Paragraph(esc(str(ai["text"])[:3500]).replace("\n", "<br/>"), body))

    story.append(Spacer(1, 10))
    story.append(Paragraph(esc(report_disclaimer(lang)), disc))

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=12 * mm, title="comparison")
    doc.build(story)
    return buf.getvalue()
