"""Cohort activity and object-scoped platform observations."""
from datetime import timedelta

from .permissions import timestamp
from . import platform_metrics


def calculate(ctx):
    settings = ctx.settings
    activation_days = settings["activation_days"]
    activation_inputs = [e for subject, registration in ctx.cohort.items() for e in ctx.by_subject[subject] if
        e["kind"] == settings["activation_event"] and e["object_id"] and timestamp(registration["at"]) <= timestamp(e["at"]) <= timestamp(registration["at"]) + timedelta(days=activation_days)
        ]
    activated = {row['subject_id'] for row in activation_inputs}
    prior = {subject for subject, registration in ctx.registrations.items()
             if ctx.start - timedelta(days=settings["retention_days"]) <= timestamp(registration["at"]) < ctx.start}
    activity_inputs = [e for e in ctx.period_events if e["kind"] in settings["activity_events"] and e["subject_id"]]
    active = {e['subject_id'] for e in activity_inputs}
    metrics = {
        "activation": ctx.measure("activation", len(activated), len(ctx.cohort), ratio=True, sources=("activity", "registrations"),
                                  inputs=[*ctx.cohort.values(), *activation_inputs],
                                  status="complete" if ctx.mature(ctx.cohort, activation_days) else "incomplete", reason="Когорта ещё не завершила окно активации." if not ctx.mature(ctx.cohort, activation_days) else ""),
        "retention": ctx.measure("retention", len(prior & active), len(prior), ratio=True, sources=("activity", "registrations"),
                                 inputs=[*(ctx.registrations[subject] for subject in prior), *(row for row in activity_inputs if row['subject_id'] in prior)],
                                 status="complete" if ctx.cut >= ctx.end else "incomplete", reason="База — регистрации за согласованное окно перед началом периода."),
    }
    metrics["ctr"], results = platform_metrics.calculate(ctx)
    return metrics, results, activity_inputs
