"""Cash, service-period revenue, subscriptions and explicitly conditional estimates."""
from datetime import timedelta

from .permissions import timestamp
from .financial_integrity import money_sum
from . import ltv_review


def _subscription_state(ctx, at):
    latest = {}
    for event in ctx.financial_events("subscription", period=False):
        if timestamp(event["at"]) <= at:
            latest[(event["legal_entity"], event["subscription_id"])] = event
    return list(latest.values())


def _active_subscriptions(states, at):
    return [event for event in states if event["subscription_state"] == "active" and event['amount'] > 0
            and timestamp(event["service_starts_at"]) <= at < timestamp(event["service_ends_at"])]


def _service_income(ctx, subjects=None):
    """Allocate confirmed recurring receipts over their documented service days."""
    revenue = margin = 0
    customers = set()
    unknown = False
    payments = [event for event in ctx.financial_events("payment", period=False)
                if event['amount'] > 0 and (subjects is None or event["subject_id"] in subjects)]
    by_transaction = {event["transaction_id"]: event for event in payments}
    refunds = [event for event in ctx.financial_events("refund", period=False) if event['amount'] > 0]
    margin_known = True
    inputs = []
    for payment in payments:
        if payment["payment_type"] == "one_off" or payment["revenue_kind"] == "one_off":
            continue
        if payment["revenue_kind"] != "recurring":
            unknown |= ctx.contains(payment)
            if ctx.contains(payment):
                inputs.append(payment)
            continue
        start, end = timestamp(payment["service_starts_at"]), timestamp(payment["service_ends_at"])
        overlap = max(0, (min(end, ctx.end, ctx.cut) - max(start, ctx.start)).total_seconds())
        if not overlap:
            continue
        fraction = overlap / (end - start).total_seconds()
        related = [event for event in refunds if event["related_transaction_id"] == payment["transaction_id"]]
        inputs.extend([payment, *related])
        refunded = money_sum(related)
        net = float(money_sum([payment]) - refunded)
        revenue += net * fraction
        customers.add(payment["subject_id"])
        if payment["gross_profit"] is None:
            margin_known = False
        elif payment["amount"] > 0:
            margin += payment["gross_profit"] * net / payment["amount"] * fraction
    unmatched = [event for event in refunds if ctx.contains(event) and (subjects is None or event['subject_id'] in subjects)
                 and event['related_transaction_id'] not in by_transaction]
    inputs.extend(unmatched)
    return revenue, margin if margin_known else None, customers, unknown or bool(unmatched), inputs


def calculate(ctx, activity_inputs):
    cfg = ctx.settings
    active_users = {row['subject_id'] for row in activity_inputs}
    ad_expenses = [event for event in ctx.expenses if event['category'] == 'advertising']
    scoped_ad_expenses = [event for event in ad_expenses if event['channel'] in ctx.scope]
    ads = sum(event['amount'] for event in ad_expenses)
    scope_ads = sum(event['amount'] for event in scoped_ad_expenses)
    categories = set(cfg["cost_categories"])
    acquisition = [event for event in ctx.expenses if event["category"] in categories and event["channel"] in ctx.scope]
    cost_inputs = [*acquisition, *(row for row in ctx.expenses if row['category'] in categories and row['channel'] in {'unknown', ''})]
    ad_inputs = [*scoped_ad_expenses, *(row for row in ad_expenses if row['channel'] in {'unknown', ''})]
    cohort_inputs = [*ctx.cohort.values(), *ctx.paid_cohort.values()]
    total_cost = sum(event["amount"] for event in acquisition)
    scope_regs = sum(ctx.channel(subject) in ctx.scope for subject in ctx.cohort)
    scope_paid = sum(ctx.channel(subject) in ctx.scope for subject in ctx.paid_cohort)
    payments, refunds = ctx.financial_events("payment"), ctx.financial_events("refund")
    revenue = float(money_sum(payments) - money_sum(refunds))
    attributed = [event for event in payments if event['amount'] > 0 and ctx.channel(event["subject_id"]) in ctx.scope]
    attributed_refunds = [event for event in refunds if event['amount'] > 0 and ctx.channel(event["subject_id"]) in ctx.scope]
    attributed_revenue = float(money_sum(attributed) - money_sum(attributed_refunds))
    contribution = sum(event["gross_profit"] or 0 for event in attributed)
    profit_known = all(event["gross_profit"] is not None for event in attributed)
    originals = {event["transaction_id"]: event for event in ctx.financial_events("payment", period=False)}
    cash_inputs = [*payments, *refunds, *(originals[row['related_transaction_id']] for row in refunds if row['related_transaction_id'] in originals)]
    for refund in attributed_refunds:
        original = originals.get(refund["related_transaction_id"])
        if not original or original["gross_profit"] is None or original["amount"] <= 0:
            profit_known = False
        else:
            contribution -= original["gross_profit"] * refund["amount"] / original["amount"]
    comparable_costs = bool(categories and ctx.scope) and not any(event["category"] in categories and event["channel"] in {"unknown", ""} for event in ctx.expenses)
    cost_status = "complete" if comparable_costs else "unavailable"
    ad_status = "unavailable" if any(e["category"] == "advertising" and e["channel"] in {"unknown", ""} for e in ctx.expenses) else "complete"
    cohort_status = "complete" if ctx.mature(ctx.cohort, cfg["conversion_days"]) else "incomplete"
    metrics = {
        "first_paying_customers": ctx.measure("first_paying_customers", len(ctx.paid_period), inputs=ctx.paid_period.values(), sources=("payments",), monetized=True, unique_customers=True),
        "advertising_spend": ctx.measure("advertising_spend", ads, inputs=ad_expenses, sources=("expenses",)),
        "revenue": ctx.measure("revenue", revenue, inputs=cash_inputs, sources=("payments",), monetized=True),
        "registration_to_payment": ctx.measure("registration_to_payment", len(ctx.paid_cohort), len(ctx.cohort), inputs=cohort_inputs, ratio=True, sources=("payments", "registrations"), monetized=True, unique_customers=True, status=cohort_status),
        "registration_cost": ctx.measure("registration_cost", scope_ads, scope_regs, inputs=ad_inputs, ratio=True, sources=("expenses", "registrations", "visits"), status=ad_status, reason="Расход и регистрации одного канала; нераспределённый рекламный расход блокирует расчёт."),
        "advertising_cac": ctx.measure("advertising_cac", scope_ads, scope_paid, inputs=[*ad_inputs, *cohort_inputs], ratio=True, sources=("expenses", "payments", "registrations", "visits"), monetized=True, unique_customers=True, status=ad_status if ad_status != "complete" else cohort_status),
        "full_cac": ctx.measure("full_cac", total_cost, scope_paid, inputs=[*cost_inputs, *cohort_inputs], ratio=True, sources=("expenses", "payments", "registrations", "visits"), monetized=True, unique_customers=True, status=cost_status if cost_status != "complete" else cohort_status),
        "roas": ctx.measure("roas", attributed_revenue, scope_ads, inputs=ad_inputs, ratio=True, sources=("payments", "expenses", "visits", "registrations"), monetized=True, unique_customers=True, status=ad_status),
        "roi": ctx.measure("roi", contribution - total_cost, total_cost, ratio=True, sources=("payments", "margin", "expenses", "visits", "registrations"), monetized=True, unique_customers=True,
                           inputs=cost_inputs,
                           status=cost_status if profit_known else "unavailable", reason="Отнесённый вклад до маркетинговых расходов; выручка не подменяет прибыль."),
    }
    closing_at, opening_at = min(ctx.end, ctx.cut) - timedelta(microseconds=1), ctx.start - timedelta(microseconds=1)
    closing_state, opening_state = _subscription_state(ctx, closing_at), _subscription_state(ctx, opening_at)
    closing = _active_subscriptions(closing_state, closing_at)
    opening = {event['subject_id'] for event in _active_subscriptions(opening_state, opening_at)}
    churn_inputs = [*opening_state, *(row for row in closing_state if row['subject_id'] in opening)]
    closing_customers = {event["subject_id"] for event in closing}
    lost = opening - closing_customers
    mrr = sum(event["amount"] / event["billing_months"] for event in closing)
    recurring, margin, served, unknown_service, service_inputs = _service_income(ctx)
    service_status = "incomplete" if unknown_service else "complete"
    metrics.update({
        "mrr": ctx.measure("mrr", mrr, inputs=closing_state, sources=("subscriptions",), monetized=True),
        "arr": ctx.measure("arr", mrr * 12, inputs=closing_state, sources=("subscriptions",), monetized=True, reason="Расчётный годовой темп на дату среза, не годовая фактическая выручка."),
        "arpu": ctx.measure("arpu", recurring, len(active_users), inputs=[*service_inputs, *activity_inputs], ratio=True, sources=("payments", "activity"), monetized=True, unique_customers=True, status=service_status),
        "arppu": ctx.measure("arppu", recurring, len(served), ratio=True, sources=("payments",), monetized=True, unique_customers=True, status=service_status,
                             inputs=service_inputs,
                             reason="Знаменатель — клиенты с подтверждённым регулярным обслуживанием в периоде; доход распределён по дням обслуживания."),
        "churn": ctx.measure("churn", len(lost), len(opening), ratio=True, sources=("subscriptions",), monetized=True, unique_customers=True,
                             inputs=churn_inputs,
                             status="complete" if ctx.cut >= ctx.end else "incomplete", reason="Ушедшие к концу периода из платящей базы на его начало; новые за период исключены."),
    })
    stable, stability_reason = ltv_review.eligibility(ctx, opening, lost)
    margin_per_customer = margin / len(served) if margin is not None and served else None
    churn = metrics["churn"]["value"]
    metrics["ltv"] = ctx.measure("ltv", margin_per_customer, churn / 100 if churn else None, ratio=True,
        inputs=[*service_inputs, *churn_inputs],
        reference_sources=[row['source'] for row in cfg['ltv_stability']['monthly_rates']] if stable else (),
        sources=("payments", "margin", "subscriptions"), monetized=True, unique_customers=True,
        status="complete" if stable and metrics["arppu"]["value"] is not None else "unavailable", estimate=True,
        reason="Приближение по месячному ARPPU, подтверждённой марже и месячному оттоку. " + stability_reason)
    paid_scope = {subject for subject in ctx.paid_cohort if ctx.channel(subject) in ctx.scope}
    _, cohort_margin, served_cohort, cohort_unknown, cohort_service_inputs = _service_income(ctx, paid_scope)
    monthly_contribution = cohort_margin / len(served_cohort) if cohort_margin is not None and served_cohort else None
    metrics["payback"] = ctx.measure("payback", metrics["full_cac"]["value"], monthly_contribution, ratio=True,
        inputs=[*cost_inputs, *cohort_inputs, *cohort_service_inputs],
        sources=("expenses", "payments", "margin", "visits", "registrations"), monetized=True, unique_customers=True,
        status="complete" if ctx.monthly() and not cohort_unknown else "unavailable", estimate=True,
        reason="Оценка по полному CAC и месячному маржинальному доходу на обслуженного клиента той же привлечённой когорты.")
    return metrics
