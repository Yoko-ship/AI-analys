"""Owner goal decisions are independent from CMO strategy proposals."""
from datetime import datetime, timezone

from pydantic import ValidationError

from . import planning, store as s
from .errors import MarketingError, require_owner
from .models import Goal, Strategy


def save_goal(actor, data, expected_version):
    require_owner(actor)
    value = Goal.model_validate(data).model_dump(mode="json")
    with s.connection(write=True) as c:
        return s.put(c, "goal", {**value, "id": "primary", "status": "draft", "timezone": "Asia/Tashkent"},
                     actor=actor, action="goal_drafted", expected_version=expected_version)


def approve_goal(actor, expected_version):
    require_owner(actor)
    with s.connection(write=True) as c:
        goal = s.get(c, "goal", "primary")
        return s.put(c, "goal", {**goal, "status": "approved"}, actor=actor,
                     action="goal_approved", expected_version=expected_version)


def active_goal(c=None):
    if c is None:
        with s.connection() as conn:
            return active_goal(conn)
    return next((r["record"] for r in reversed(s.history(c, "goal", "primary"))
                 if r["action"] == "goal_approved"), None)


def save_strategy(actor, data, strategy_id=None, expected_version=0, *, now=None):
    with s.connection(write=True) as c:
        return propose_in(c, actor, data, strategy_id, expected_version, now=now or datetime.now(timezone.utc))


def propose_in(c, actor, data, strategy_id=None, expected_version=0, *, now, allowed_snapshots=None):
    if actor.get("role") not in {"administrator", "cmo"}:
        raise MarketingError("STRATEGY_ROLE", "Only the owner or CMO can propose a strategy.", 403)
    value = Strategy.model_validate(data).model_dump(mode="json")
    assessment = planning.evaluate(c, value, active_goal(c), now, allowed_snapshots)
    return s.put(c, "strategy", {**value, "id": strategy_id or s.uid("strategy"), "status": "proposed",
                 "assessment": assessment, "assessed_at": now.isoformat()},
                 actor=actor, action="strategy_proposed", expected_version=expected_version)


def approve_strategy(actor, strategy_id, expected_version, *, now=None):
    require_owner(actor)
    with s.connection(write=True) as c:
        strategy = s.get(c, "strategy", strategy_id)
        if strategy["status"] != "proposed":
            raise MarketingError("STRATEGY_PROPOSAL_REQUIRED", "Only a proposed strategy version can be approved.")
        goal = active_goal(c)
        if not goal or strategy["goal_version"] != goal["version"]:
            raise MarketingError("STALE_GOAL", "Review the strategy against the current goal first.")
        try:
            value = Strategy.model_validate({key: strategy[key] for key in Strategy.model_fields if key in strategy}).model_dump(mode="json")
        except ValidationError:
            raise MarketingError("INCOMPLETE_STRATEGY", "Prepare a complete structured strategy before approval.", 422) from None
        assessment = planning.evaluate(c, value, goal, now or datetime.now(timezone.utc))
        if assessment != strategy.get("assessment"):
            raise MarketingError("STALE_STRATEGY", "The strategy's measured basis changed. Prepare a new proposal.")
        return s.put(c, "strategy", {**strategy, "status": "approved"}, actor=actor,
                     action="strategy_approved", expected_version=expected_version)


def current_strategy(c, record, now):
    try:
        value = Strategy.model_validate({key: record[key] for key in Strategy.model_fields if key in record}).model_dump(mode="json")
        assessment = planning.evaluate(c, value, active_goal(c), now)
        if assessment != record.get("assessment"):
            raise MarketingError("STALE_STRATEGY", "The strategy's measured basis changed. Prepare a new proposal.")
        return {**record, "readiness": {"status": "ready", "reason": ""}}
    except ValidationError:
        reason = "Prepare a complete structured strategy before approval."
    except MarketingError as exc:
        reason = str(exc)
    return {**record, "readiness": {"status": "blocked", "reason": reason}}
