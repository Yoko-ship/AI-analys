"""Assemble reproducible metric families without inventing missing observations."""
from collections import defaultdict

from . import engagement_metrics, financial_metrics, store as s
from .report_context import ReportContext
from . import count_basis, financial_integrity, publication_attribution


def calculate(events, *, starts_on, ends_on, cutoff, settings, coverage_records=None):
    ctx = ReportContext(events, starts_on=starts_on, ends_on=ends_on, cutoff=cutoff, settings=settings, coverage_records=coverage_records)
    metrics, content_results, activity_inputs = engagement_metrics.calculate(ctx)
    metrics.update(financial_metrics.calculate(ctx, activity_inputs))
    visits, regs = len(ctx.by_kind["visit"]), len(ctx.cohort)
    metrics.update({"visits": ctx.measure("visits", visits, inputs=ctx.by_kind['visit'], sources=("visits",)),
                    "registrations": ctx.measure("registrations", regs, inputs=ctx.cohort.values(), sources=("registrations",)),
                    "visit_to_registration": ctx.measure("visit_to_registration", regs, visits, inputs=[*ctx.by_kind['visit'], *ctx.cohort.values()], ratio=True, sources=("visits", "registrations"))})
    channels = defaultdict(lambda: {"registrations": 0, "first_paying_customers": 0 if ctx.live and ctx.settings["shared_customer_ids"] else None})
    for subject in ctx.cohort:
        channels[ctx.channel(subject)]["registrations"] += 1
    if ctx.live and ctx.settings["shared_customer_ids"]:
        for subject in ctx.paid_period:
            channels[ctx.channel(subject)]["first_paying_customers"] += 1
    entities = {}
    for entity in sorted(set(ctx.settings['legal_entities']) | {e['legal_entity'] for e in ctx.expenses if e['legal_entity'] != 'unknown'}):
        launched = ctx._launched(entity, min(ctx.end, ctx.cut))
        available = launched and ctx.source_basis('first_paying_customers', ['payments'])['payments']['status'] == 'complete'
        revenue_available = launched and ctx.source_basis('revenue', ['payments'])['payments']['status'] == 'complete' and not financial_integrity.metric_issues(ctx.financial_issues, 'revenue', entity)
        entities[entity] = {"first_paying_customers": sum(ctx.contains(e) for (name, _), e in ctx.entity_first.items() if name == entity) if available else None,
                            "revenue": float(financial_integrity.money_sum([e for e in ctx.financial_events('payment') if e['legal_entity'] == entity])
                                       - financial_integrity.money_sum([e for e in ctx.financial_events('refund') if e['legal_entity'] == entity])) if revenue_available else None,
                            **financial_integrity.expenses(ctx, entity)}
    method = {key: value for key, value in ctx.settings.items() if key not in {"source_status", "automatic_weekly"}}
    return {"period": ctx.period, "method": method, "sources": ctx.settings["source_status"], "coverage": ctx.coverage, "metrics": metrics,
            "channels": dict(channels), "content_results": content_results, "entities": entities,
            "count_basis": count_basis.calculate(ctx),
            "publication_attribution": publication_attribution.calculate(ctx),
            "unassigned_expenses": financial_integrity.expenses(ctx, 'unknown'), "financial_issues": ctx.financial_issues,
            "cohorts": {"registrations": regs, "paid_customers": len(ctx.paid_cohort) if ctx.live and ctx.settings["shared_customer_ids"] else None},
            "excluded_events": ctx.excluded, "excluded_financial_events": ctx.excluded_financial,
            "event_count": len(ctx.period_events), "generated_at": s.now()}
