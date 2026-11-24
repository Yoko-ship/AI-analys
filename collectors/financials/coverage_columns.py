"""Summarize the financial tables returned by the public company endpoint."""

from collections import defaultdict

from financial_columns.presentation import FIELDS, RATIOS

from .coverage import cell


def _evidence(item):
    """Keep only traceable input references and conflicts, including a calculated cell's inputs."""
    refs = set()
    missing = set()
    stack = [item]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("metric_id") and (
            node.get("quality") in {"missing", "blocked"}
            or node.get("value") is None
            and node.get("reason")
        ):
            missing.add(node["metric_id"])
        if node.get("source_version") or node.get("source_url"):
            refs.add(
                tuple(
                    str(node.get(k) or "")
                    for k in ("source_version", "source_url", "page", "sheet", "row")
                )
            )
        for key in ("components", "sources"):
            stack.extend(node.get(key) or [])
    return sorted(map(list, refs)), missing


def statement_cells(data):
    template, form = data["display_template"], data["standard"]
    groups = FIELDS[template]["nsbu" if form == "NSBU" else "ifrs"]
    names = {
        field["field_id"]: field["kind"]
        for group in groups
        for field in group["fields"]
    }
    ratios = {f"ratio:{code}": "ratio" for code in RATIOS[template][form].split()}
    rows = {r["id"]: r for r in data["ratios"]}
    for r in data["rows"]:
        # A reference field may have multiple independently reported components.
        names.pop(r["display_field"], None)
        rows[r["id"]] = r
    specs = {**names, **ratios, **{k: v.get("kind") for k, v in rows.items()}}
    bases = defaultdict(list)
    for col in data["columns"]:
        bases[col["basis"]].append(col)
    if not bases:
        bases[
            {"quarter": "quarter", "interim": "ytd"}.get(data.get("freq"), "annual")
        ] = []
    result = {}
    for basis, columns in bases.items():
        columns.sort(key=lambda c: c["end"], reverse=True)
        for k, kind in specs.items():
            row = rows.get(k, {})
            cells = row.get("cells", {})
            selected = columns[0]["end"] if columns else None
            current = cells.get(columns[0]["key"], {}) if columns else {}
            reason = "SOURCE_VALUE_MISSING"
            if (basis == "as_of" and kind == "flow") or (
                basis == "ttm" and kind == "stock"
            ):
                reason = "NOT_APPLICABLE"
            item = dict(current)
            prior = {}
            if (
                item.get("value") is None
                and item.get("quality") != "not_applicable"
                and reason != "NOT_APPLICABLE"
            ):
                for col in columns[1:]:
                    older = cells.get(col["key"], {})
                    if older.get("value") is not None and older.get("quality") not in {
                        "blocked",
                        "missing",
                    }:
                        prior = older
                        item["last_verified"] = {**older, "period_end": col["end"]}
                        break
            metric = cell(item, selected, reason=reason)
            refs, missing = _evidence(item)
            if prior:
                more, _ = _evidence(prior)
                refs = sorted(map(list, {tuple(ref) for ref in [*refs, *more]}))
            if metric["status"] in {"gap", "earlier"}:
                metric["missing_inputs"] = sorted(
                    set(metric["missing_inputs"]) | missing
                )
                if not current and k in names:
                    metric["missing_inputs"] = [k]
            if current.get("formula"):
                metric["formula"] = current["formula"]
            if refs:
                metric["sources"] = refs
            if row.get("unit"):
                metric["unit"] = row["unit"]
            result[f"{basis}/{k}"] = metric
    for row in data.get("published_ratios", []):
        k = "published/" + row["field"]
        if k not in result or str(row["period"]) > str(result[k]["period"]):
            result[k] = cell(row, row["period"])
    if data.get("issues"):
        from financial_ingestion.store import encoded

        result["source_conflicts"] = {
            "status": "gap",
            "reason": "SOURCE_RECONCILIATION",
            "issues": sorted(data["issues"], key=encoded),
        }
    return result
