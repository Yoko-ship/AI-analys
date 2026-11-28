"""Bind research observations to selected, current evidence without URL invention."""
from . import sources
from .permissions import timestamp


def bind_source(c, originals, evidence_id, quote, now, *, required=False):
    if not evidence_id:
        if quote or required:
            raise ValueError('An observed claim needs a selected original')
        return None
    original = originals.get(evidence_id)
    if not original:
        raise ValueError('Research must cite one of the selected originals')
    current = sources.current_evidence(c, original['id'])
    if not current or current['version'] != original['version']:
        raise ValueError('The original changed after the task was prepared')
    available = (current['status'] == 'verified' and current['rights'] != 'unknown'
                 and timestamp(current['retrieved_at']) <= now < timestamp(current['expires_at']))
    quote = quote.strip()
    if required and (not available or not quote):
        raise ValueError('An observed example needs a concrete available excerpt')
    if quote and (not available or quote not in original['excerpt']):
        raise ValueError('The claimed observation is absent from the available excerpt')
    return {**{key: original[key] for key in (
        'id', 'version', 'title', 'url', 'publisher', 'published_at', 'retrieved_at', 'rights')},
        'access': 'excerpt' if available else 'unavailable'}
