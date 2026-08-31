"""Comparison is a snapshot of the published market, including its safeguards."""
from datetime import datetime, timezone
import math
import fundamentals

METRICS = (
    ("pe", "P/E", "x"), ("pb", "P/B", "x"), ("ps", "P/S", "x"),
    ("roe", "ROE", "%"), ("roa", "ROA", "%"),
    ("net_margin", "Чистая маржа", "%"), ("equity_assets", "Капитал/Активы", "%"),
)


def build_market_comparison(companies, inputs, multiples, language="ru"):
    """No network, annual-only reanalysis, or inferred scores in this adapter.

    Quotes and capitalisations are in UZS. Metric objects are copied AFTER the
    market's audit blocks, so comparison cannot bypass a withheld value.
    """
    board = {str(r.get("ticker", "")).upper(): r for r in inputs["board"]}
    published = {r["ticker"]: r for r in multiples["items"]}
    labels = {"en": ("Company", "Share class", "Earnings period", "Balance period", "Sector"),
              "uz": ("Kompaniya", "Aksiya turi", "Daromad davri", "Balans davri", "Sektor")}
    names = labels.get(language, ("Компания", "Класс акций", "Период прибыли", "Период баланса", "Сектор"))
    fields = [{"key": k, "label": label} for k, label in zip(
        ("company_name", "share_class", "base_period", "balance_period", "sector"), names)]
    fields += [{"key": "ticker", "label": "Ticker"},
               {"key": "last_price", "label": "Цена / Price", "unit": "UZS"},
               {"key": "last_trade_date", "label": "Дата сделки / Trade date"},
               {"key": "market_cap_class", "label": "Капитализация класса / Class cap", "unit": "UZS"},
               {"key": "market_cap_issuer", "label": "Капитализация эмитента / Issuer cap", "unit": "UZS"}]
    fields += [{"key": k, "label": label, "unit": unit} for k, label, unit in METRICS]
    financial_fields = [{"key": k, "label": label, "unit": "UZS"} for k, label in (
        ("revenue", "Выручка / Процентный доход"), ("noninterest_income", "Непроцентный доход"),
        ("net_income", "Чистая прибыль"), ("total_assets", "Активы"), ("total_equity", "Капитал"))]
    fields += [{"key": "financial_period", "label": "Период финансовых сумм"}] + financial_fields
    rows, seen = [], set()
    for query in companies:
        query = str(query or "").strip()
        ticker = query.upper()
        if ticker not in published:
            matches = [t for t, r in board.items() if t in published and query.casefold() in {
                str(r.get("name") or "").casefold(), str(r.get("company_name") or "").casefold()}]
            if len(matches) != 1:
                raise ValueError(f"Укажите однозначный тикер из таблицы «Рынок»: {query}")
            ticker = matches[0]
        if ticker in seen:
            continue
        seen.add(ticker)
        m, quote = published[ticker], board.get(ticker, {})
        meta = inputs["securities"].get(ticker, {})
        fin = next((inputs.get("financials", {}).get(t) for t in m.get("issuer_classes", [ticker])
                    if inputs.get("financials", {}).get(t)), {})
        balance = fundamentals.balance_snapshot(fin, inputs.get("ratios", {}).get(ticker, {}))
        row = {"input": query, "ticker": ticker,
               "company_name": quote.get("name") or meta.get("name") or ticker,
               "issuer": m.get("issuer"), "share_class": m.get("share_class"),
               "sector": m.get("org_type") or meta.get("sector") or "unknown",
               "base_period": m.get("base_period"), "balance_period": m.get("balance_period"),
               "last_trade_date": quote.get("last_trade_date"),
               "last_price": quote.get("last_price") if quote.get("last_trade_date") else None,
               "market_cap_class": m.get("market_cap_class"),
               "market_cap_issuer": (m.get("market_cap_issuer") or {}).get("value"),
               "metric_details": {k: dict(m.get(k) or {}) for k, _, _ in METRICS}}
        row["org_type"] = m.get("org_type")
        row["sector"] = meta.get("sector") or "unknown"
        row["financial_period"] = fundamentals.period_label(fin)
        row["financial_details"] = {}
        for key in ("revenue", "noninterest_income", "net_income"):
            # These are the filed YTD sums, not a disguised TTM flow.
            row[key] = fin.get(key)
            row["financial_details"][key] = {
                "base_period": (fin.get("field_periods") or {}).get(key) or row["financial_period"],
                "source": "catalog_filing", "note": "Сумма за отчётный период, не TTM"}
        row["total_assets"], row["total_equity"] = balance.get("assets"), balance.get("equity")
        for key in ("total_assets", "total_equity"):
            row["financial_details"][key] = {"base_period": balance.get("period"), "source": balance.get("source")}
        findings = (m.get("validation") or {}).get("findings") or []
        for field in financial_fields:
            key = field["key"]
            detail = row["financial_details"][key]
            reasons = [v["reason"] for v in findings if v.get("field") == key]
            if reasons:
                row[key] = None
                detail.update(status="audit_blocked", note="; ".join(reasons))
            elif not isinstance(row.get(key), (int, float)) or not math.isfinite(row[key]):
                row[key] = None
                detail["status"] = "no_data"
            else:
                detail["status"] = "ok"
            row[key + "_basis"] = " · ".join(str(detail[k]) for k in
                ("base_period", "source", "status", "note") if detail.get(k) is not None)
        for key, _, _ in METRICS:
            value = row["metric_details"][key].get("value")
            row[key] = value if isinstance(value, (int, float)) and math.isfinite(value) else None
            detail = row["metric_details"][key]
            row[key + "_basis"] = " · ".join(str(detail[k]) for k in
                ("base_period", "denominator_period", "status", "note") if detail.get(k) is not None)
        rows.append(row)
    if not 2 <= len(rows) <= 5:
        raise ValueError("Выберите от 2 до 5 разных тикеров")
    warnings = []
    for key, message in (
        ("base_period", "Разные периоды прибыли: прямое ранжирование не выполняется."),
        ("balance_period", "Балансы на разные даты."),
        ("sector", "Разные формы/секторы: показатели могут иметь разный экономический смысл."),
        ("org_type", "Разные формы отчётности: выручка компании и процентный доход банка не равнозначны."),
    ):
        if len({r.get(key) for r in rows}) > 1:
            warnings.append(message)
    if len({r["issuer"] for r in rows}) < len(rows):
        warnings.append("Выбраны классы одного эмитента: его мультипликаторы повторяются, капитализация класса отличается.")
    # All cells retain the period, status and reason; export uses the same snapshot.
    table_rows = []
    for row in rows:
        cells = dict(row)
        for key, _, _ in METRICS:
            detail = row["metric_details"][key]
            cells[key] = {"raw": row[key], **{k: detail.get(k) for k in
                ("status", "base_period", "denominator_period", "note", "estimate", "source")}}
        for field in financial_fields:
            key = field["key"]
            cells[key] = {"raw": row[key], **row["financial_details"][key]}
        table_rows.append(cells)
    summary = "Снимок тех же показателей, что опубликованы в «Рынке». Значения без подтверждённой базы не подменяются нулями."
    return {"ok": True, "language": language, "input_companies": companies,
            "comparison": {"source": "market", "generated_at": datetime.now(timezone.utc).isoformat(),
                "fields": fields,
                "export_fields": fields + [{"key": k + "_basis", "label": label + " — период, статус, причина"} for k, label, _ in METRICS]
                    + [{"key": f["key"] + "_basis", "label": f["label"] + " — период, источник"} for f in financial_fields],
                "rows": rows, "warnings": warnings,
                "tables": {"market": {"columns": fields, "rows": table_rows, "allow_average": False}},
                "charts": [], "leaders": {}, "ranking": [], "normalized_ranking": [],
                "summary": {"short": summary, "methodology": "P/E, P/B, P/S — по капитализации эмитента; ROE/ROA — по базе расчёта «Рынка». Период и статус указаны у каждого показателя. Сводный балл не рассчитывается."},
                "comparative_ai_summary": {"ok": False, "skipped": True}, "errors": []}}
