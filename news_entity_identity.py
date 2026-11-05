"""Reject ticker links contradicted by explicitly named source entities.

The registry separates confusable entities, including non-issuers. This is a
contradiction check, not a fuzzy-name guess: unknown or short source text is left
alone, both entities may be mentioned, and generated summaries are not evidence.
"""
import json
from pathlib import Path
import re
import unicodedata


def _normalize(text):
    value = unicodedata.normalize('NFKC', str(text or '')).casefold().replace('ё', 'е')
    value = re.sub("['‘’ʻʼ`ʹ]", '', value)
    return ' '.join(re.findall(r'[^\W_]+', value))


GROUPS = json.loads(Path(__file__).with_name('news_entity_identities.json').read_text())['groups']
_MATCHERS = [
    [(set(entity['tickers']), re.compile(r'(?<!\w)(?:' + '|'.join(
        re.escape(_normalize(alias)) for alias in entity['aliases']) + r')(?!\w)'))
     for entity in group['entities']]
    for group in GROUPS
]
IDENTITY_TICKERS = frozenset(ticker for group in _MATCHERS for tickers, _ in group for ticker in tickers)


def consistent_tickers(item, tickers):
    # Match fields independently, never an invented name across a field boundary.
    source = [_normalize(item.get(field)) for field in ('title', 'snippet')]
    rejected = set()
    for group in _MATCHERS:
        mentioned = [symbols for symbols, pattern in group if any(pattern.search(text) for text in source)]
        if mentioned:
            supported = set().union(*mentioned)
            known = set().union(*(symbols for symbols, _ in group))
            rejected.update(known - supported)
    return [ticker for ticker in tickers if ticker not in rejected]


def classifier_identity_context():
    lines = ['ENTITY IDENTITIES: These organizations are distinct. A venue mention does not identify a listed issuer.']
    for group in GROUPS:
        for entity in group['entities']:
            symbols = ', '.join(entity['tickers']) or 'no issuer ticker in this registry'
            lines.append(f"{entity['name']} ({', '.join(entity['aliases'][:3])}): {symbols}.")
    return '\n'.join(lines)
