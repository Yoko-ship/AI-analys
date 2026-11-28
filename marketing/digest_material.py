"""One source-bound paragraph per digest event; dates and links are rendered facts."""
from .permissions import TASHKENT, timestamp
from .trends import event_groups


def _selected(entry, evidence):
    return [evidence[key] for key in entry["evidence_ids"] if evidence.get(key)]


def _destination(rows):
    return next((row["destination_url"] for row in rows if row.get("destination_url")), "")


def render(item, evidence):
    blocks = []
    calendar = item['rubric'] == 'calendar'
    labels = {"ru": ("Опубликовано", "Событие", "Первоисточники"),
              "uz": ("E’lon qilingan", "Voqea", "Birlamchi manbalar"),
              "en": ("Published", "Event", "Original sources")}[item["language"]]
    entries = item.get('digest_items', [])
    if calendar:
        if any(not _selected(entry, evidence) or any(not row.get('event_at') for row in _selected(entry, evidence)) for entry in entries):
            return None
        entries = sorted(entries, key=lambda entry: min(timestamp(row['event_at']) for row in _selected(entry, evidence)))
    event_names = {
        'ru': {'meeting': 'Собрание', 'report': 'Отчёт', 'placement': 'Размещение', 'payment': 'Плановая выплата'},
        'uz': {'meeting': 'Yig‘ilish', 'report': 'Hisobot', 'placement': 'Joylashtirish', 'payment': 'Rejalashtirilgan to‘lov'},
        'en': {'meeting': 'Meeting', 'report': 'Report', 'placement': 'Placement', 'payment': 'Scheduled payment'},
    }[item['language']]
    for entry in entries:
        rows = _selected(entry, evidence)
        if not rows or len(rows) != len(entry["evidence_ids"]):
            return None
        published = min(timestamp(row["published_at"]) for row in rows).astimezone(TASHKENT).date()
        dates = [labels[0] + " " + published.strftime("%d.%m.%Y")]
        events = [timestamp(row["event_at"]).astimezone(TASHKENT).date() for row in rows if row.get("event_at")]
        if events and min(events) != published:
            dates.append(labels[1] + " " + min(events).strftime("%d.%m.%Y"))
        entities = sorted({row["entity"] for row in rows if row.get("entity")})
        header = " · ".join(entities + dates)
        if calendar:
            header = ' · '.join([min(events).strftime('%d.%m.%Y'), *entities,
                                 event_names.get(rows[0]['data'].get('event_type'), labels[1]), dates[0]])
        originals = list(dict.fromkeys(row["url"] for row in rows))
        parts = [header, entry["text"], _destination(rows), labels[2] + ":\n" + "\n".join(originals)]
        blocks.append("\n".join(part for part in parts if part))
    return "\n\n".join(blocks)


def prepare(c, item):
    if item["rubric"] not in {"digest", "calendar"} or not item.get("digest_items"):
        return item
    from . import sources
    evidence = {key: sources.current_evidence(c, key) for key in item["evidence_ids"]}
    body = render(item, evidence)
    if body is not None and len(body) > 20000:
        from .errors import MarketingError
        raise MarketingError("DIGEST_LENGTH", "Use shorter digest items; assembled text exceeds 20000 characters.", 422)
    return {**item, "body": body} if body is not None else item


def check(item, evidence, now):
    from . import checks, dividend_checks
    calendar = item['rubric'] == 'calendar'
    name = 'Calendar' if calendar else 'Digest'
    entries = item.get("digest_items") or []
    if not (1 if calendar else 2) <= len(entries) <= 8:
        return ['A weekly calendar requires one to eight source-bound items' if calendar else "A digest requires two to eight source-bound items"]
    if item["format"] != "post":
        return ["Structured calendars currently require the text post format" if calendar else "Structured digests currently require the text post format"]
    headline = dividend_checks._text(item["title"])
    states, _ = dividend_checks._states(headline)
    if states or dividend_checks.AMOUNT.search(headline):
        return ["Keep the digest headline neutral; financial states and amounts belong to their source-bound items"]
    rows = list(evidence.values())
    groups = event_groups([row for row in rows if row.get("canonical_event_id")])
    group_for = {row["id"]: index for index, group in enumerate(groups) for row in group}
    seen, used = set(), set()
    for index, entry in enumerate(entries, 1):
        ids = entry["evidence_ids"]
        grouping = {group_for.get(key) for key in ids}
        if len(grouping) != 1 or None in grouping or grouping & seen or len(set(ids)) != len(ids):
            return ["Each digest item must identify one distinct confirmed event; reprints count once"]
        seen.update(grouping)
        used.update(ids)
        originals = _selected(entry, evidence)
        claims = [claim for claim in item["claims"] if claim["evidence_id"] in ids]
        virtual = {**item, "rubric": "news", "digest_items": [], "title": "", "body": entry["text"],
                   "entity": originals[0]["entity"], "evidence_ids": ids, "claims": claims,
                   "destination_url": _destination(originals), "calculation": None, "assets": [], "format": "post"}
        failures = checks.check(virtual, {row["id"]: row for row in originals}, now, {})
        if failures:
            return [f"{name} item {index}: {failure}" for failure in failures]
    if used != set(item["evidence_ids"]):
        return ["Every selected digest original must belong to its visible item"]
    if render(item, evidence) != item["body"]:
        return ["Digest copy differs from its source-bound items, dates or links"]
    return []
