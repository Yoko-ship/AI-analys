"""Openinfo pdf operations with explicit dependencies."""
from __future__ import annotations
from typing import Any
import requests

from io import BytesIO
import collectors.openinfo.cells as collectors_openinfo_cells
import collectors.openinfo.settings as collectors_openinfo_settings
import re


def parse_nsbu_pdf_financials(session: requests.Session, pdf_url: str) -> dict[str, Any]:
    """Extract headline financials from an NSBU report PDF.

    Fallback for issuers (microfinance MCHJ, some LLCs) whose Excel export is
    broken on openinfo but whose PDF carries the standard NSBU tables. Matches by
    the stable NSBU line codes first, then by Russian label, and rejects values
    below the plausibility floor (line codes like 180/280 misread as amounts).
    """
    import pdfplumber

    response = session.get(pdf_url, timeout=collectors_openinfo_settings.REQUEST_TIMEOUT)
    response.raise_for_status()

    rows: list[dict[str, Any]] = []
    with pdfplumber.open(BytesIO(response.content)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for raw in table:
                    cells = [str(c).replace("\n", " ").strip() if c else "" for c in raw]
                    label = next((c for c in cells if re.search(r"[А-Яа-я]{4}", c)), "")
                    if not label:
                        continue
                    code = next((c for c in cells if re.fullmatch(r"\d{2,4}", c.strip())), None)
                    nums = [collectors_openinfo_cells._safe_report_number(c) for c in cells]
                    nums = [n for n in nums if n is not None and abs(n) >= 10_000]
                    rows.append({"label": label.lower(), "code": code, "value": nums[-1] if nums else None})

    def by_code(code: str) -> float | None:
        for r in rows:
            if r["code"] == code and r["value"] is not None:
                return r["value"]
        return None

    def by_label(patterns: tuple[str, ...], exclude: tuple[str, ...] = ()) -> float | None:
        hit = None
        for r in rows:  # last match wins (final totals come after subtotals)
            if r["value"] is None:
                continue
            if any(p in r["label"] for p in patterns) and not any(e in r["label"] for e in exclude):
                hit = r["value"]
        return hit

    def by_formula(*formulas: str) -> float | None:
        """A subtotal identified by the line numbers it sums, spacing ignored."""
        for r in rows:
            if r["value"] is None:
                continue
            squashed = re.sub(r"\s+", "", r["label"])
            if "итого" in squashed and any(f in squashed for f in formulas):
                return r["value"]
        return None

    return {
        "net_income": by_code("1200") or by_label(("чистая прибыль (убыток)", "чистая прибыль(убыток)"))
        or by_label(("чистая прибыль", "чистый убыток"), exclude=("до ", "процент", "операц")),
        # Обязательства: сначала свод, который эмитент напечатал сам — «ИТОГО ПО II
        # РАЗДЕЛУ (стр. 490+600)» в форме АО, «Итого по разделу III (стр. 730+930)»
        # в страховой; см. reports_catalog._extract_liabilities_total.
        "total_liabilities": by_code("280") or by_formula("490+600", "730+930")
        or by_label(("итого обязательства",), exclude=("капитал",)),
        "revenue": by_code("180") or by_label(("всего процентных доходов",))
        or by_label(("чистая выручка", "выручка от реализац")),
        # Наличность = расчетный счет (5100), не свод «Денежные средства, всего».
        "cash": by_label(("расчетном счете", "расчетном счёте", "(5100)"))
        or by_code("010") or by_label(("денежные средства",)),
    }


def preview_pdf_url(session: requests.Session, url: str, max_pages: int = 2, max_chars: int = 3000) -> dict[str, Any]:
    import pdfplumber

    response = session.get(url, timeout=collectors_openinfo_settings.REQUEST_TIMEOUT)
    response.raise_for_status()
    chunks: list[str] = []
    with pdfplumber.open(BytesIO(response.content)) as pdf:
        for page in pdf.pages[:max_pages]:
            chunks.append(page.extract_text() or "")
    return {
        "content_type": response.headers.get("content-type"),
        "pages_read": min(len(chunks), max_pages),
        "text": "\n".join(chunks).strip()[:max_chars],
    }
