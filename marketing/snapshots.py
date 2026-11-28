"""Named immutable reporting cuts; owner corrections never overwrite originals."""
from copy import deepcopy
from datetime import date, datetime

from . import store as s
from .errors import MarketingError, require_owner
from .permissions import TASHKENT, timestamp


def freeze(actor, name, report):
    require_owner(actor)
    if not name.strip() or len(name) > 150:
        raise MarketingError("INVALID_NAME", "Give the snapshot a name of at most 150 characters.", 422)
    with s.connection(write=True) as c:
        return s.put(c, "snapshot", {"id": s.uid("snapshot"), "name": name.strip(), "report": deepcopy(report), "status": "frozen"},
                     actor=actor, action="snapshot_frozen", expected_version=0)


def correct(actor, snapshot_id, corrections, reason, expected_version):
    require_owner(actor)
    if not reason.strip():
        raise MarketingError("REASON_REQUIRED", "Explain the correction.", 422)
    with s.connection(write=True) as c:
        original = s.get(c, "snapshot", snapshot_id)
        for key, value in corrections.items():
            if key not in original["report"]["metrics"] or not isinstance(value, (int, float)) or value < 0:
                raise MarketingError("INVALID_CORRECTION", "Use a nonnegative value for an existing metric.", 422)
        return s.put(c, "snapshot_correction", {"id": snapshot_id, "original_id": snapshot_id,
                     "corrections": corrections, "reason": reason, "status": "owner_corrected"},
                     actor=actor, action="snapshot_corrected", expected_version=expected_version)


def compare(first, second):
    a, b = first["report"], second["report"]
    comparable = a["method"] == b["method"] and a["sources"] == b["sources"] and a.get("source_basis") == b.get("source_basis")
    duration = lambda r: date.fromisoformat(r["period"]["ends_on"]) - date.fromisoformat(r["period"]["starts_on"])
    comparable = comparable and duration(a) == duration(b)
    if a["period"]["starts_on"] != b["period"]["starts_on"]:
        closed = lambda r: timestamp(r["period"]["cutoff"]) >= datetime.combine(date.fromisoformat(r["period"]["ends_on"]), datetime.min.time(), TASHKENT)
        comparable = comparable and closed(a) and closed(b)
    metrics = {}
    for key, current in b["metrics"].items():
        previous = a["metrics"].get(key, {})
        old, new = previous.get("value"), current["value"]
        valid = comparable and old is not None and new is not None and previous["unit"] == current["unit"]
        metrics[key] = {"baseline": old, "current": new, "difference": new - old if valid else None,
                        "relative_percent": (new - old) / old * 100 if valid and old != 0 else None}
    return {"comparable": comparable, "warning": None if comparable else "Different periods, sources or metric definitions; do not compare these values.", "metrics": metrics}
