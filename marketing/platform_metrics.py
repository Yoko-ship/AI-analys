"""Comparable platform windows; cumulative observations are not additive events."""
from collections import defaultdict

from .permissions import timestamp

COUNTS = {"impression", "click", "view", "reach", "reaction", "save", "share"}


def calculate(ctx):
    objects = defaultdict(dict)
    evidence = defaultdict(dict)
    for event in ctx.events:
        object_id = event["publication_id"] or event["object_id"]
        if not object_id or event["kind"] not in COUNTS:
            continue
        if event["observation_mode"] == "snapshot":
            start, end = timestamp(event["observed_starts_at"]), timestamp(event["observed_ends_at"])
            if start < ctx.start or end > ctx.end:
                continue
        elif ctx.contains(event):
            start, end = ctx.start, ctx.end
        else:
            continue
        identity = (event['channel'], object_id, event['promotion'])
        target, records = objects[identity], evidence[identity]
        key = (event["kind"], start, end, event["observation_mode"])
        if event["observation_mode"] == "snapshot":
            target[key] = event["count"]  # The latest observation of exactly this interval.
            records[key] = [event]
        else:
            target[key] = target.get(key, 0) + event["count"]
            records.setdefault(key, []).append(event)
    results = {}
    total_clicks = total_impressions = 0
    ambiguous = False
    aggregate_inputs = []
    for (channel, object_id, promotion), values in objects.items():
        records = evidence[(channel, object_id, promotion)]
        observations, windows = {}, []
        for kind in COUNTS:
            series = sorted((start, end, mode, count) for (name, start, end, mode), count in values.items() if name == kind)
            overlaps = any(series[i][0] < series[i - 1][1] for i in range(1, len(series)))
            observations[kind] = None if not series or overlaps or (kind == "reach" and len(series) > 1) else sum(row[3] for row in series)
            windows.extend({"kind": kind, "starts_at": start.isoformat(), "ends_at": end.isoformat(), "mode": mode, "count": count} for start, end, mode, count in series)
        impressions = sorted((start, end, mode, count) for (kind, start, end, mode), count in values.items() if kind == "impression")
        overlap = any(impressions[i][0] < impressions[i - 1][1] for i in range(1, len(impressions)))
        missing = any(mode == "snapshot" and ("click", start, end, mode) not in values for start, end, mode, _ in impressions)
        clicks = sum(values.get(("click", start, end, mode), 0) for start, end, mode, count in impressions)
        seen = sum(row[3] for row in impressions)
        ambiguous |= overlap or missing
        if not overlap and not missing:
            total_clicks += clicks
            total_impressions += seen
        key = f"{channel}:{object_id}" + (":paid" if promotion == "paid" else "")
        matched_inputs = [row for start, end, mode, _ in impressions for kind in ('click', 'impression')
                          for row in records.get((kind, start, end, mode), [])]
        object_inputs = matched_inputs if impressions else [row for (kind, *_), rows in records.items() if kind == 'click' for row in rows]
        aggregate_inputs.extend(matched_inputs)
        results[key] = {"channel": channel, "object_id": object_id, "promotion": promotion, "observations": observations, "windows": windows,
                        "ctr": ctx.measure("ctr", clicks, seen, inputs=object_inputs, ratio=True, sources=("clicks", "impressions"), status="incomplete" if overlap or missing else "complete")}
    aggregate = ctx.measure("ctr", total_clicks, total_impressions, ratio=True, sources=("clicks", "impressions"), status="incomplete" if ambiguous else "complete",
                            inputs=aggregate_inputs,
                            reason="Клики и показы одного объекта за одинаковые окна. Уникальные охваты не суммируются.")
    return aggregate, results
