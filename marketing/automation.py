"""Explicit owner rules select current originals for bounded organic work."""
from datetime import date, datetime, time, timedelta
from typing import Literal, get_args
from urllib.parse import urldefrag

from pydantic import Field, model_validator

from . import calendar_events, digest_events, founder, goals, sources, quarterly_events, store as s
from .errors import MarketingError, require_owner
from .models import Input
from .permissions import TASHKENT, timestamp, release_recipient_matches
from .production_models import ProductionBrief, Target
from .trends import event_groups

COORDINATOR = {"id": "coordinator", "role": "coordinator"}


class Rule(Input):
    title: str = Field(min_length=1, max_length=200)
    strategy_id: str = Field(min_length=1, max_length=200)
    strategy_version: int = Field(ge=1)
    source_ids: list[str] = Field(min_length=1, max_length=30)
    target: Target
    rubric: Literal["market", "news", "dividend", "calendar", "quarterly", "digest", "chart"]
    chart_field: str = Field(default='', max_length=200)
    digest_time: str = Field(default="", pattern=r"^(?:|(?:[01]\d|2[0-3]):[0-5]\d)$")
    calendar_time: str = Field(default="", pattern=r"^(?:|(?:[01]\d|2[0-3]):[0-5]\d)$")
    calendar_day: int = Field(default=6, ge=0, le=6)
    starts_on: date
    ends_on: date
    max_daily: int = Field(default=1, ge=1, le=10)
    max_age_hours: int = Field(default=24, ge=1, le=168)
    mode: Literal["draft", "account"] = "draft"
    priority: Literal["normal", "urgent"] = "normal"
    enabled: bool = False
    founder_fact_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def bounded(self):
        if self.ends_on < self.starts_on or (self.ends_on - self.starts_on).days > 90:
            raise ValueError("Choose an editorial period of at most 91 calendar days")
        if self.priority == "urgent" and (self.rubric != "news" or self.max_age_hours > 24):
            raise ValueError("Urgent selection is restricted to news no more than 24 hours old")
        if self.rubric == "digest" and (not self.digest_time or self.target.format != "post"):
            raise ValueError("Choose a Tashkent digest cutoff and the text post format")
        if self.rubric != "digest" and self.digest_time:
            raise ValueError("A digest cutoff belongs only to the digest rubric")
        if self.calendar_time and (self.rubric != 'calendar' or self.target.format != 'post'):
            raise ValueError('A weekly calendar cutoff requires the calendar rubric and text post format')
        if self.rubric == 'chart' and (not self.chart_field or self.target.format == 'post'):
            raise ValueError('Choose a source series field and a media format for charts')
        if self.rubric != 'chart' and self.chart_field:
            raise ValueError('A series field belongs only to the chart rubric')
        self.source_ids = sorted(set(self.source_ids))
        self.founder_fact_ids = sorted(set(self.founder_fact_ids))
        return self


RUBRICS = get_args(Rule.model_fields["rubric"].annotation)


def _scope(c, rule, now):
    strategy = s.get(c, "strategy", rule["strategy_id"])
    goal = goals.active_goal(c)
    if not goal or strategy["status"] != "approved" or strategy["version"] != rule["strategy_version"] or strategy["goal_version"] != goal["version"]:
        raise MarketingError("EDITORIAL_STRATEGY", "Automatic selection requires this exact approved strategy and current goal.")
    current = goals.current_strategy(c, strategy, now)
    if current["readiness"]["status"] != "ready":
        raise MarketingError("EDITORIAL_STRATEGY", current["readiness"]["reason"])
    account = s.get(c, "account", rule["target"]["account_id"])
    if (account["platform"] not in strategy["channels"] or rule["rubric"] not in strategy["rubrics"]
            or rule["rubric"] not in account["rubrics"] or rule["target"]["format"] not in account["formats"]
            or not set(rule["target"]["languages"]) <= set(account["languages"])
            or rule["target"]["instagram_link"] != "none" and account["platform"] != "instagram"):
        raise MarketingError("EDITORIAL_SCOPE", "The account, rubric, format and languages must fit the approved strategy and account scope.")
    if not goal["starts_on"] <= rule["starts_on"] <= rule["ends_on"] <= goal["deadline"]:
        raise MarketingError("EDITORIAL_PERIOD", "The selection period must fit the approved goal dates.")
    for key in rule["source_ids"]:
        source = s.get(c, "source", key)
        if source["status"] != "connected" or not all(source[field] for field in ("may_store", "may_display", "commercial_use", "terms_checked_on")) or source["rights"] == "unknown":
            raise MarketingError("EDITORIAL_SOURCE", "Every selected source needs current access and permitted commercial use.")
    facts = [s.get(c, "founder_fact", key) for key in rule["founder_fact_ids"]]
    if not all(founder.usable(fact, now) for fact in facts) or account["platform"] == "linkedin" and not facts:
        raise MarketingError("FOUNDER_MAP_REQUIRED", "Choose current owner-confirmed founder facts.")
    return account, {fact["id"]: fact["version"] for fact in facts}


def save(actor, rule_id, data, expected_version, *, now):
    require_owner(actor)
    value = Rule.model_validate(data).model_dump(mode="json")
    with s.connection(write=True) as c:
        # Revocation must remain possible even after an old strategy/source expires.
        if value["enabled"]:
            _scope(c, value, now)
        return s.put(c, "editorial_rule", {**value, "id": rule_id}, actor=actor,
                     action="editorial_rule_saved", expected_version=expected_version)


def current(c, rule, now):
    status, reason = "disabled", "Automatic event selection is disabled"
    if rule["enabled"]:
        try:
            _scope(c, rule, now)
            today = now.astimezone(TASHKENT).date().isoformat()
            status = "ready" if rule["starts_on"] <= today <= rule["ends_on"] else "waiting" if today < rule["starts_on"] else "expired"
            reason = "" if status == "ready" else "Outside the approved editorial period"
        except MarketingError as exc:
            status, reason = "blocked", str(exc)
    runtime = s.get(c, "editorial_runtime", rule["id"], required=False)
    return {**rule, "readiness": {"status": status, "reason": reason},
            "runtime": runtime if runtime and runtime["rule_version"] == rule["version"] else None}


def _aliases(group):
    return sorted({alias for item in group for alias in
                   ("event:" + item["canonical_event_id"], "url:" + urldefrag(item["url"])[0])})


def _original_time(item):
    # A later event label or ingestion date never makes an earlier publication new.
    return min(timestamp(item["published_at"]), timestamp(item.get("event_at") or item["published_at"]),
               timestamp(item.get("first_known_at") or item["published_at"]))


def _events(c, rule, now):
    if rule['rubric'] == 'calendar' and rule.get('calendar_time'):
        return calendar_events.select(c, rule, now, _inventory(c, now), _assigned, _aliases)
    if rule["rubric"] == "quarterly":
        return quarterly_events.select(c, rule, now, _inventory(c, now, rubric="quarterly"))
    digest = rule["rubric"] == "digest"
    reference = digest_events.cutoff(rule, now) if digest else now
    if reference is None:
        return []
    wanted = {"news", "dividend"} if digest else {rule["rubric"]}
    result = []
    for group in _inventory(c, now):
        if not any(item["source_id"] in rule["source_ids"] and item.get("suggested_rubric") in wanted for item in group):
            continue
        first = min(group, key=lambda item: (_original_time(item), item["id"]))
        at = _original_time(first)
        if not timedelta(0) <= reference - at < timedelta(hours=rule["max_age_hours"]):
            continue
        originals = [sources.current_evidence(c, item["id"]) for item in group if item["source_id"] in rule["source_ids"]]
        originals = [item for item in originals if item and item["status"] == "verified" and timestamp(item["expires_at"]) > now]
        if not originals or len(originals) > 30 or len({(item["entity"], item.get("period", "")) for item in originals}) != 1:
            continue
        chart = None
        destination = ''
        if rule['rubric'] == 'chart':
            from .chart_series import select
            from .publication_links import valid_destination
            chart = select(originals, rule['chart_field'], now)
            if chart is None:
                continue
            destination = next(row.get('destination_url', '') for row in originals if row['id'] == chart['evidence_id'])
            if not valid_destination(destination):
                continue
        result.append({"id": first["canonical_event_id"], "at": at, "aliases": _aliases(group), "originals": originals,
                       'chart': chart, 'destination_url': destination,
                       "inventory_versions": {item["id"]: item["version"] for item in group}})
    if digest:
        return digest_events.bundle(rule, reference, [event for event in result if not _assigned(c, event, rule["target"]["account_id"])])
    return sorted(result, key=lambda event: (event["at"], event["id"]), reverse=rule["priority"] == "urgent")


def _inventory(c, now, *, rubric=None):
    items = [item for item in s.list_items(c, "evidence") if item.get("canonical_event_id")
             and timestamp(item["retrieved_at"]) <= now and timestamp(item["published_at"]) <= now]
    if rubric == "quarterly":
        groups = {}
        for item in items:
            if item.get("analysis_version"):
                groups.setdefault(item["canonical_event_id"], []).append(item)
        return list(groups.values())
    for item in items:
        # A source can amend dates in place without creating another evidence ID.
        # Immutable history retains the first known original for older imports too.
        item["first_known_at"] = min(_original_time(revision["record"]) for revision in s.history(c, "evidence", item["id"])).isoformat()
    return event_groups(items)


def _assigned(c, event, account_id):
    aliases = set(event["aliases"])
    if any(row['account_id'] == account_id and row['publication_type'] == 'organic' and 'event:' + row['event_id'] in aliases
           for row in s.list_items(c, 'publication_reservation')):
        return True
    for task in s.list_items(c, "task"):
        scope = task.get("production")
        if scope and any(target["account_id"] == account_id for target in scope["targets"]):
            if "event:" + scope["event_id"] in aliases or aliases.intersection((task.get("editorial") or {}).get("aliases", [])):
                return True
            if scope["rubric"] in {"digest", "calendar"} and aliases.intersection(_aliases(task["evidence"])):
                return True
    for item in s.list_items(c, "candidate"):
        if item["account_id"] != account_id or item.get("publication_type", "organic") != "organic":
            continue
        if "event:" + item["event_id"] in aliases:
            return True
        if item["rubric"] == "digest" or item["rubric"] == "calendar" and item.get('digest_items'):
            versions = (item.get("check") or {}).get("evidence_versions", {})
            originals = [s.revision(c, "evidence", key, versions[key]) if key in versions else
                         s.get(c, "evidence", key, required=False) for key in item["evidence_ids"]]
            if aliases.intersection(_aliases([row for row in originals if row])):
                return True
    return False


def _runtime(c, rule, status, reason, now, task_id=None):
    old = s.get(c, "editorial_runtime", rule["id"], required=False)
    value = {"id": rule["id"], "rule_version": rule["version"], "status": status, "reason": reason,
             "task_id": task_id or (old or {}).get("task_id")}
    if not old or any(old.get(key) != item for key, item in value.items()):
        s.put(c, "editorial_runtime", {**value, "checked_at": now.isoformat()}, actor=COORDINATOR,
              action="editorial_selection", expected_version=old["version"] if old else 0)


def run_one(now):
    with s.connection(write=True) as c:
        if (s.get(c, "settings", "pause", required=False) or {}).get("processing"):
            return False
        rules = sorted(s.list_items(c, "editorial_rule"), key=lambda row: (row["priority"] != "urgent", row["id"]))
        today = now.astimezone(TASHKENT).date().isoformat()
        for rule in rules:
            if not rule["enabled"]:
                continue
            if not rule["starts_on"] <= today <= rule["ends_on"]:
                _runtime(c, rule, "waiting" if today < rule["starts_on"] else "expired", "Outside the approved editorial period", now)
                continue
            try:
                account, founder_versions = _scope(c, rule, now)
            except MarketingError as exc:
                _runtime(c, rule, "blocked", str(exc), now)
                continue
            assigned = [task["editorial"] for task in s.list_items(c, "task") if (task.get("editorial") or {}).get("rule_id") == rule["id"]]
            if sum(timestamp(task["assigned_at"]).astimezone(TASHKENT).date().isoformat() == today for task in assigned) >= rule["max_daily"]:
                _runtime(c, rule, "limited", "Daily assignment limit reached (Asia/Tashkent)", now)
                continue
            try:
                events = [event for event in _events(c, rule, now) if not _assigned(c, event, account["id"])]
            except MarketingError as exc:
                _runtime(c, rule, "blocked", str(exc), now)
                continue
            if not events:
                _runtime(c, rule, "waiting", "No new verified current event within this rule", now)
                continue
            for event in events:
                c.execute("SAVEPOINT editorial_assignment")
                try:
                    task = _assign(c, rule, event, account, founder_versions, now)
                except MarketingError as exc:
                    c.execute("ROLLBACK TO SAVEPOINT editorial_assignment")
                    c.execute("RELEASE SAVEPOINT editorial_assignment")
                    _runtime(c, rule, "blocked", str(exc), now)
                    continue
                c.execute("RELEASE SAVEPOINT editorial_assignment")
                _runtime(c, rule, "assigned", "Verified event assigned within the owner's rule", now, task["id"])
                return True
    return False


def _assign(c, rule, event, account, founder_versions, now):
    from . import agents
    end = datetime.combine(date.fromisoformat(rule["ends_on"]) + timedelta(days=1), time(), TASHKENT)
    originals = event["originals"]
    scope = ProductionBrief.model_validate({"event_id": event["id"], "rubric": rule["rubric"], "entity": event.get("entity", originals[0]["entity"]),
            "period": event.get("period", originals[0].get("period", "")), "destination_url": event.get("destination_url", ""),
            'chart': event.get('chart'),
            "targets": [rule["target"]], "mode": rule["mode"],
            "expires_at": min(end, event.get('expires_at', event["at"] + timedelta(hours=rule["max_age_hours"])), *(timestamp(item["expires_at"]) for item in originals)),
            "founder_fact_ids": rule["founder_fact_ids"]}).model_dump(mode="json")
    binding = {"rule_id": rule["id"], "rule_version": rule["version"], "aliases": event["aliases"],
               "inventory_versions": event["inventory_versions"],
               "event_at": event["at"].isoformat(), "assigned_at": now.isoformat(), "priority": rule["priority"],
               "account_version": account["version"], "founder_versions": founder_versions}
    if event.get("analysis_version"):
        binding["analysis_version"] = event["analysis_version"]
    if event.get("digest_cutoff"):
        binding["digest_cutoff"] = event["digest_cutoff"]
    if event.get('calendar_cutoff'):
        binding['calendar_cutoff'] = event['calendar_cutoff']
    return agents._start_in(c, COORDINATOR, kind="content", message=rule["title"] + ": " + originals[0]["title"],
                            evidence_ids=[item["id"] for item in originals], production=scope, editorial=binding)


def guard(c, task, now, *, released_candidate=None):
    binding = task.get("editorial")
    if not binding:
        return
    rule = s.get(c, "editorial_rule", binding["rule_id"], required=False)
    if not rule or not rule["enabled"] or rule["version"] != binding["rule_version"]:
        raise MarketingError("EDITORIAL_RULE_CHANGED", "The automatic editorial rule changed or was disabled; this assignment is stopped.")
    account, founder_versions = _scope(c, rule, now)
    # An explicit owner release reviews the current account after draft production
    # (including login). It does not waive rule, strategy, source or founder checks.
    reviewed = released_candidate is not None and release_recipient_matches(account, released_candidate)
    if (not reviewed and account["version"] != binding["account_version"]) or founder_versions != binding["founder_versions"]:
        raise MarketingError("EDITORIAL_INPUTS_CHANGED", "The selected account or founder facts changed; this assignment is stopped.")
    if timestamp(task["production"]["expires_at"]) <= now:
        raise MarketingError("EDITORIAL_EXPIRED", "The selected event's editorial validity expired.")
    quarterly_events.guard(task, now)
    related = [item for group in _inventory(c, now, rubric=rule["rubric"]) if set(binding["aliases"]).intersection(_aliases(group)) for item in group]
    if {item["id"]: item["version"] for item in related} != binding["inventory_versions"]:
        raise MarketingError("EDITORIAL_EVIDENCE_CHANGED", "The event's original inventory changed; its facts need a new review.")
    for key, version in task["evidence_versions"].items():
        original = sources.current_evidence(c, key)
        if not original or original["version"] != version or original["status"] != "verified" or timestamp(original["expires_at"]) <= now:
            raise MarketingError("EDITORIAL_EVIDENCE_CHANGED", "Selected editorial evidence changed, expired or became unavailable.")


def candidate_failures(c, item, now):
    task = s.get(c, "task", item["origin_task"], required=False) if item.get("origin_task") else None
    if task:
        try:
            guard(c, task, now, released_candidate=item)
        except MarketingError as exc:
            return [str(exc)]
        if any((task.get("editorial") or {}).get(key) for key in ('digest_cutoff', 'calendar_cutoff')):
            included = {key for entry in item.get("digest_items", []) for key in entry["evidence_ids"]}
            if any(not included.intersection(row["id"] for row in group) for group in event_groups(task["evidence"])):
                return ["Every selected event must appear in the automatic " + task['production']['rubric']]
    return []


def _urgent(task):
    # This context is assigned by the coordinator from an owner rule. Every
    # claim still runs guard(); untrusted model output cannot supply it.
    return (task.get("editorial") or {}).get("priority") == "urgent"


def order_tasks(tasks):
    """Prioritize production slots while retaining the other owner's work."""
    production = iter(sorted((task for task in tasks if task.get("production")), key=lambda task: not _urgent(task)))
    return [next(production) if task.get("production") else task for task in tasks]


def order_deliveries(c, jobs):
    """Urgent news moves before ordinary posts to the same account."""
    def priority(job):
        item = s.get(c, "candidate", job["candidate_id"])
        task = s.get(c, "task", item["origin_task"], required=False) if item.get("origin_task") else None
        return not (task and _urgent(task))
    queues = {account: iter(sorted((job for job in jobs if job["account_id"] == account), key=priority))
              for account in {job["account_id"] for job in jobs}}
    return [next(queues[job["account_id"]]) for job in jobs]
