"""One bounded digest edition per owner rule and closed Tashkent daily window."""
from datetime import datetime, time

from .permissions import TASHKENT
from .publication_links import valid_destination
from . import store as s


def cutoff(rule, now):
    local = now.astimezone(TASHKENT)
    at = datetime.combine(local.date(), time.fromisoformat(rule["digest_time"]), TASHKENT)
    return at if now >= at else None


def bundle(rule, at, events):
    selected, originals = [], []
    for event in sorted(events, key=lambda value: (value["at"], value["id"])):
        if not any(valid_destination(row.get("destination_url", "")) for row in event["originals"]):
            continue
        if len(originals) + len(event["originals"]) > 30:
            continue
        selected.append(event)
        originals.extend(event["originals"])
        if len(selected) == 8:
            break
    if len(selected) < 2:
        return []
    identity = "digest:" + s.digest([rule["id"], at.isoformat()])
    return [{"id": identity, "at": at, "entity": "", "period": at.date().isoformat(), "originals": originals,
             "destination_url": next(row["destination_url"] for row in originals if valid_destination(row.get("destination_url", ""))),
             "aliases": sorted({"event:" + identity, *(alias for event in selected for alias in event["aliases"])}),
             "inventory_versions": {key: version for event in selected for key, version in event["inventory_versions"].items()},
             "digest_cutoff": at.isoformat()}]
