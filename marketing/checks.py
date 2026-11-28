"""Deterministic financial checks, independent of a language model's verdict."""
from datetime import date
from decimal import Decimal, InvalidOperation
from calendar import monthrange
import re

from .permissions import TASHKENT, timestamp
from .url_policy import public_url
from . import dividend_checks, occasions, rubric_checks


def numbers(text):
    """Normalize displayed numeric tokens, including grouped Russian amounts."""
    text = re.sub(r"https?://\S+", "", str(text))
    return {Decimal(value.replace(" ", "").replace("\u00a0", "").replace("\u202f", "").replace(",", "."))
            for value in re.findall(r"(?<!\w)-?\d+(?:[ \u00a0\u202f]\d{3})*(?:[.,]\d+)?", text)}


def checked_dates(text, evidence):
    dates = set()
    for row in evidence.values():
        values = [row.get(field) for field in ("published_at", "event_at", "period", "period_start")]
        values.extend(row.get("data", {}).values())
        for value in values:
            if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T| )", value):
                continue
            try:
                dates.add(date.fromisoformat(value[:10]))
                if len(value) > 10:
                    dates.add(timestamp(value).astimezone(TASHKENT).date())
            except ValueError:
                continue
    failures = []
    def replace(match):
        value = match[0]
        try:
            parts = [int(part) for part in re.split(r"[-./]", value)]
            found = date(*parts) if "-" in value else date(*reversed(parts))
        except ValueError:
            found = None
        if found not in dates:
            failures.append("Displayed date is not bound to an original: " + value)
        return " "
    # Remove URLs first: dates embedded in a source path are not visible claims.
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}/\d{1,2}/\d{4})(?!\d)", replace, text)
    return text, failures


def check(item, evidence, now, assets):
    from .publication_links import valid_destination
    failures = []
    if timestamp(item["expires_at"]) <= now:
        failures.append("Content is expired")
    if not item["evidence_ids"]:
        failures.append("No evidence supplied")
    for evidence_id in item["evidence_ids"]:
        source = evidence.get(evidence_id)
        if not source:
            failures.append(f"Missing evidence: {evidence_id}")
            continue
        if source["status"] != "verified" or timestamp(source["expires_at"]) <= now:
            failures.append(f"Evidence unavailable or stale: {evidence_id}")
        if timestamp(source["retrieved_at"]) > now:
            failures.append(f"Evidence retrieval is in the future: {evidence_id}")
        if not public_url(source["url"]) or not source["excerpt"]:
            failures.append(f"Missing original extract or URL: {evidence_id}")
        if source["rights"] == "unknown":
            failures.append(f"Usage rights are not established: {evidence_id}")
        if item["entity"] and source["entity"] != item["entity"]:
            failures.append(f"Issuer does not match: {evidence_id}")
    for claim in item["claims"]:
        source = evidence.get(claim["evidence_id"])
        if claim["evidence_id"] not in item["evidence_ids"] or not source or source["data"].get(claim["field"]) != claim["value"]:
            failures.append(f"Unconfirmed fact: {claim['field']} ({claim['evidence_id']})")
        elif source["units"].get(claim["field"], "") != claim["unit"]:
            failures.append(f"Unit does not match: {claim['field']}")
    supported_numbers = set()
    for claim in item["claims"]:
        supported_numbers.update(numbers(claim["value"]))
    if item.get("calculation"):
        supported_numbers.update(numbers(item["calculation"].get("value", "")))
    # Dates may be displayed in either ISO or local order; they still must come
    # from the evidence. URL IDs never count as numerical claims.
    for source in evidence.values():
        for field in ("published_at", "event_at", "period"):
            if source.get(field):
                supported_numbers.update(numbers(source[field][:10].replace("-", " ")))
    displayed, date_failures = checked_dates(item["title"] + " " + item["body"], evidence)
    failures.extend(date_failures)
    if item["rubric"] == "quarterly" and re.fullmatch(r"\d{4}Q[1-4]", item["period"]):
        from .quarter_text import QUARTER, QUARTERS, text
        displayed = QUARTER.sub(lambda match: "" if QUARTERS[next(value for value in match.groups() if value)]
                                == int(item["period"][-1]) else match[0], text(displayed))
    for value in numbers(displayed) - supported_numbers:
        failures.append(f"Displayed number is not bound to a checked claim: {value}")
    if not valid_destination(item["destination_url"]):
        failures.append("A direct UZStock article, chart or analysis link is required")
    failures.extend(rubric_checks.check(item, evidence, now, assets))
    failures.extend(occasions.check(item, evidence, now))
    if item["rubric"] != "digest" and not (item['rubric'] == 'calendar' and item.get('digest_items')):
        failures.extend(dividend_checks.check(item, evidence))
    calculation = item.get("calculation")
    if calculation:
        failures.extend(check_difference(item, calculation, evidence))
    if item["format"] in {"image", "carousel", "video", "story"} or item["assets"]:
        from . import media
        if not item["assets"]:
            failures.append("No finished media file; a script is not a video")
        for reference in item["assets"]:
            asset = assets.get(reference.get("id"))
            if not asset or not media.valid_asset(asset):
                failures.append("Media rendering has not produced a verified file")
            elif asset.get("basis") != media.basis(item) or any(not evidence.get(key) or evidence[key]["version"] != version for key, version in asset.get("source_versions", {}).items()):
                failures.append("Rendered media no longer matches this text and its original versions")
    return failures


def check_difference(item, calc, evidence):
    if calc.get("operation") != "difference":
        return ["Unsupported calculation; supply a reproducible difference"]
    ids = [calc.get("left", ""), calc.get("right", "")]
    missing = [source_id for source_id in ids if source_id not in evidence or source_id not in item["evidence_ids"]]
    if missing:
        return ["Missing comparable original: " + ", ".join(missing)]
    left, right = (evidence[source_id] for source_id in ids)
    if any(not left.get(key) or left[key] != right.get(key) for key in ("entity", "standard", "scope", "currency")):
        return ["Originals differ in issuer, accounting standard, scope or currency"]
    field = calc.get("field")
    if not left["units"].get(field) or left["units"].get(field) != right["units"].get(field):
        return ["Originals use missing or different measurement units"]
    try:
        end, start = date.fromisoformat(left["period"]), date.fromisoformat(right["period"])
        if any(row.get("period_start") != f"{end.year}-01-01" for row in (left, right)):
            return ["Quarter differences require two cumulative originals starting on 1 January"]
        quarter = int(item["period"][-1])
        if (end.year != start.year or end.year != int(item["period"][:4]) or end.month != quarter * 3
                or start.month != (quarter - 1) * 3 or end.day != monthrange(end.year, end.month)[1]
                or start.day != monthrange(start.year, start.month)[1]):
            return ["The original cumulative periods do not define this quarter"]
        field = calc["field"]
        result = Decimal(str(left["data"][field])) - Decimal(str(right["data"][field]))
        if not result.is_finite() or result != Decimal(str(calc["value"])):
            return ["Quarter calculation does not match the originals"]
    except (ValueError, KeyError, TypeError, InvalidOperation):
        return ["Calculation lacks comparable periods or numeric values"]
    return []
