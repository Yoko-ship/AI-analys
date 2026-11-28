"""Reconcile refunds before using them in cash or service-margin calculations."""
from collections import defaultdict
from decimal import Decimal

from .permissions import timestamp

CASH_METRICS = {'revenue', 'roi', 'roas'}
SERVICE_METRICS = {'arpu', 'arppu', 'ltv', 'payback'}
MESSAGES = {
    'refund_payment_missing': 'Возврат не связан с подтверждённой исходной оплатой.',
    'refund_identity_mismatch': 'Клиент возврата отличается от клиента исходной оплаты.',
    'refund_entity_mismatch': 'Возврат и исходная оплата относятся к разным формам.',
    'refund_currency_mismatch': 'Валюта возврата отличается от валюты исходной оплаты.',
    'refund_before_payment': 'Дата возврата предшествует исходной оплате.',
    'refund_exceeds_payment': 'Сумма возвратов превышает исходную оплату.',
}


def money_sum(events):
    return sum((Decimal(str(event['amount'])) for event in events), Decimal(0))


def audit(ctx):
    originals = {row['transaction_id']: row for row in ctx.finance if row['kind'] == 'payment'}
    matched, issues = defaultdict(list), []

    def add(code, refunds, original=None):
        rows = [*refunds, *([original] if original else [])]
        if ctx.settings['currency'] not in {row['currency'] for row in rows}:
            return
        cash = any(ctx.contains(row) for row in rows)
        service = any(ctx.contains(row) for row in refunds) or bool(original and original['revenue_kind'] == 'recurring'
            and timestamp(original['service_starts_at']) < min(ctx.end, ctx.cut)
            and timestamp(original['service_ends_at']) > ctx.start)
        metrics = (CASH_METRICS if cash else set()) | (SERVICE_METRICS if service else set())
        if metrics:
            issues.append({'code': code, 'message': MESSAGES[code], 'event_ids': sorted(row['id'] for row in rows),
                           'transaction_id': refunds[0]['related_transaction_id'],
                           'entities': sorted({row['legal_entity'] for row in rows}), 'metrics': sorted(metrics)})

    for refund in (row for row in ctx.finance if row['kind'] == 'refund'):
        original = originals.get(refund['related_transaction_id'])
        if not original:
            add('refund_payment_missing', [refund])
            continue
        mismatches = [code for code, invalid in (
            ('refund_identity_mismatch', refund['subject_id'] != original['subject_id']),
            ('refund_entity_mismatch', refund['legal_entity'] != original['legal_entity']),
            ('refund_currency_mismatch', refund['currency'] != original['currency']),
            ('refund_before_payment', timestamp(refund['at']) < timestamp(original['at'])),
        ) if invalid]
        for code in mismatches:
            add(code, [refund], original)
        if not mismatches:
            matched[original['transaction_id']].append(refund)
    for transaction_id, refunds in matched.items():
        original = originals[transaction_id]
        if money_sum(refunds) > Decimal(str(original['amount'])):
            add('refund_exceeds_payment', refunds, original)
    return issues


def metric_issues(issues, key, entity=None):
    return [issue for issue in issues if key in issue['metrics'] and (entity is None or entity in issue['entities'])]


def expenses(ctx, entity):
    status = ctx.settings['source_status'].get('expenses', 'unavailable')
    selected = [row for row in ctx.expenses if row['legal_entity'] == entity]
    return {'expense_status': status, 'expense_total': float(money_sum(selected)) if status == 'complete' else None,
            'expense_categories': {category: float(money_sum([row for row in selected if row['category'] == category]))
                                  if status == 'complete' else None for category in ('advertising', 'marketing', 'sales', 'other')}}
