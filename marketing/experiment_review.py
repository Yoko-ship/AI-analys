"""Bounded, point-in-time experiment evidence for the report and its CMO task."""
from datetime import date, timedelta


def context(c, dataset, start, end, cut):
    from .report_activity import latest
    designs = {row['id']: row for row in latest(c, 'editorial_experiment', cut)}
    evaluations = {}
    for row in latest(c, 'experiment_evaluation', cut):
        design = row['design']
        if (design['dataset'] != dataset or design['starts_on'] >= end.date().isoformat()
                or date.fromisoformat(design['ends_on'])+timedelta(days=design['followup_days']) <= start.date()):
            continue
        old = evaluations.get(row['experiment_id'])
        if old is None or (row['result']['cutoff'], row['updated_at'], row['id']) > (old['result']['cutoff'], old['updated_at'], old['id']):
            evaluations[row['experiment_id']] = row
    ordered = sorted(evaluations.values(), key=lambda row: (row['result']['cutoff'], row['id']), reverse=True)
    items = []
    for row in ordered[:10]:
        item = designs.get(row['experiment_id'])
        if not item:
            continue
        decision = item.get('decision')
        items.append({'experiment_id': item['id'], 'title': item['title'], 'evaluation_id': row['id'],
                      'design': {key: value for key, value in row['design'].items() if key not in {'goal', 'creatives'}},
                      'result': row['result'], 'owner_decision': decision,
                      'decision_uses_this_evaluation': bool(decision and decision['evaluation_id'] == row['id'])})
    return {'items': items, 'total': len(ordered), 'truncated': len(ordered) > 10}
