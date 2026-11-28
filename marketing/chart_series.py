"""One definition of a measured chart series for rendering and final review."""
from datetime import date
import math

from .permissions import TASHKENT, timestamp


def measured(evidence_id, field, source, now):
    values = source.get('data', {}).get(field) if source else None
    unit = source.get('units', {}).get(field) if source else None
    if not isinstance(values, list) or not 2 <= len(values) <= 2000 or not isinstance(unit, str) or not unit.strip():
        raise ValueError('A chart needs a bounded verified series and its measurement unit')
    dates = []
    for point in values:
        if not isinstance(point, dict) or not isinstance(point.get('date'), str):
            raise ValueError('Chart points require dates and numeric values')
        dates.append(date.fromisoformat(point['date']))
        value = point.get('value')
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError('Chart values must be finite numbers')
    if dates != sorted(set(dates)):
        raise ValueError('Chart dates must be distinct and increasing')
    cutoff = min(now.astimezone(TASHKENT).date(), timestamp(source['retrieved_at']).astimezone(TASHKENT).date())
    if dates[-1] > cutoff:
        raise ValueError('A future observation cannot be displayed as a measured value')
    low = min(0, min(point['value'] for point in values))
    high = max(0, max(point['value'] for point in values))
    return {'series': values, 'unit': unit, 'axis_min': low, 'axis_max': high if high > low else low+1,
            'source_id': evidence_id, 'field': field}


def check(item, evidence, assets, now):
    reason = 'The chart rubric needs a rendered chart with a traceable data series'
    if item['format'] not in {'image', 'carousel', 'video', 'story'}:
        return [reason]
    charts = [asset['chart'] for ref in item['assets'] if (asset := assets.get(ref.get('id'))) and asset.get('chart')]
    if not charts:
        return [reason]
    identities = set()
    for chart in charts:
        try:
            key, field = chart['source_id'], chart['field']
            if key not in item['evidence_ids'] or chart != measured(key, field, evidence.get(key), now):
                return [reason]
            identities.add((key, field))
        except (KeyError, TypeError, ValueError, AttributeError):
            return [reason]
    return [] if len(identities) == 1 else [reason]


def select(originals, field, now):
    """Only a consistent selected field can define an automatic chart event."""
    charts = []
    for original in originals:
        if field not in original.get('data', {}):
            continue
        try:
            charts.append((original, measured(original['id'], field, original, now)))
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
    if not charts or any((chart['series'], chart['unit']) != (charts[0][1]['series'], charts[0][1]['unit']) for _, chart in charts):
        return None
    original, _ = min(charts, key=lambda pair: (timestamp(pair[0]['published_at']), pair[0]['id']))
    return {'evidence_id': original['id'], 'field': field}


def validate_scope(c, scope, originals, now):
    from . import sources
    from .errors import MarketingError
    ref = (scope or {}).get('chart')
    if not ref:
        return
    try:
        if ref['evidence_id'] not in {row['id'] for row in originals}:
            raise ValueError('unselected')
        source = sources.current_evidence(c, ref['evidence_id'])
        if not source or source['status'] != 'verified' or timestamp(source['expires_at']) <= now or timestamp(source['retrieved_at']) > now:
            raise ValueError('unavailable')
        measured(ref['evidence_id'], ref['field'], source, now)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise MarketingError('CHART_SOURCE', 'Выберите актуальный подтверждённый ряд с единицами из оригиналов этого задания.', 422) from None
