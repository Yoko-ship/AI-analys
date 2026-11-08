"""People in form 8, preserving source groups without inferring succession.

OpenInfo calls the person's name `question_name` in change tables, and `name`
in the resulting roster. Those keys have different meanings in other forms.
"""
from urllib.parse import urlsplit
import re

from corporate_event_fields import content, words

SUPERVISORY = r'наблюдательн.{0,25}совет|совет.{0,15}банк|член.{0,15}совет|совет.{0,15}директор|kuzatuv.{0,25}kengash|кузатув.{0,25}кенгаш|supervisory|board of directors'
AUDIT = r'ревизионн|taftish|тафтиш|revision commission'
EXECUTIVE = r'правлен|boshqaruv|бошқарув|бошкарув|директор|direktor|director|ijro|ижро|исполнительн|executive|\bceo\b'


def person_key(person):
    return ' '.join(str(person.get('name') or '').casefold().split())


def named_person(person):
    return person_key(person) not in {'', 'вакансия', 'вакантно', 'vacant', 'vacancy', 'vakant', "bo'sh", 'bo‘sh'}


def _employer_tokens(value):
    # Use the catalog's existing transliteration and legal-form normalization.
    # Exact token containment only: an ambiguous employer is not fuzzy-matched.
    from main import _normalize_company_key, _meaningful_tokens, _transliterate_to_latin
    tokens = _meaningful_tokens(_normalize_company_key(value))
    return _meaningful_tokens(_normalize_company_key(' '.join(_transliterate_to_latin(t) for t in tokens)))


def _issuer_executives(rows, issuer_names):
    candidates = [row for row in rows if re.search(EXECUTIVE, str(row.get('position') or '').casefold())]
    if not candidates:
        return False
    roles = [str(row.get('position') or '').casefold() for row in rows if named_person(row)]
    employers = {_normalize for row in rows if named_person(row) and (_normalize := frozenset(_employer_tokens(row.get('work_place') or '')))}
    chair = r'председател.{0,4}\s+правлен|boshqaruv.{0,4}\s+raisi|бош[қк]арув.{0,4}\s+раиси'
    deputy = r'заместител|o.rinbosar|ўринбосар'
    # A joint chairman/deputy roster at one employer identifies a management
    # board even when its issuer uses a new name, abbreviation or another script.
    if (len(employers) == 1 and any(re.search(chair, role) and not re.search(deputy, role) for role in roles)
            and any(re.search(chair, role) and re.search(deputy, role) for role in roles)):
        return True
    if not issuer_names:
        # Legacy reviewed rosters have no issuer context. Only explicit board-of-
        # management roles qualify; a bare director title is insufficient.
        return all(re.search(r'правлен|boshqaruv|бошқарув|бошкарув|ijro|ижро|исполнительн|executive', str(row.get('position') or '').casefold()) for row in candidates)
    names = [tokens for name in issuer_names if (tokens := _employer_tokens(name))]
    for row in candidates:
        employer = _employer_tokens(row.get('work_place') or '')
        if employer and not any(tokens <= employer or employer <= tokens for tokens in names):
            return False
    return True


def body_for(groups):
    """The form's roster field is reused for several bodies by Openinfo.

    The deciding body is NOT the affected body: a supervisory board appoints
    executives too. Explicit council/commission roles in a roster take priority
    over members' day jobs (e.g. another bank's CEO in HMKB filing 15173).
    """
    title = str(groups.get('source_title') or '').casefold()
    titled = [body for body, pattern in [('supervisory', SUPERVISORY), ('audit', AUDIT), ('executive', EXECUTIVE)] if re.search(pattern, title)]
    if len(titled) == 1:
        return titled[0]
    rows = groups.get('roster') or groups.get('appointed') or groups.get('departed') or []
    roles = ' | '.join(str(row.get('position') or '').casefold() for row in rows)
    if re.search(SUPERVISORY, roles):
        return 'supervisory'
    if re.search(AUDIT, roles):
        return 'audit'
    if _issuer_executives(rows, groups.get('issuer_names')):
        return 'executive'
    return 'unspecified'


def people(raw, table, name_field):
    rows = raw.get(table)
    if not isinstance(rows, list):
        return []
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        person = {key: content(row.get(source)) if isinstance(row.get(source), str) else None
                  for key, source in [('name', name_field), ('position', 'position'), ('work_place', 'work_place')]}
        if person['name'] or person['position']:
            result.append({'source_field': f'{table}.{index}', **person})
    return result


def enrich_governance(document, raw):
    groups = {
        'appointed': people(raw, 'factscaseelection', 'question_name'),
        'departed': people(raw, 'factsterminationpowers', 'question_name'),
        'roster': people(raw, 'factsmembershipexecutive', 'name'),
        'source_title': content(raw.get('fact_title')),
        'issuer_names': [value for key in ('organization_name', 'organization_short_name', 'organization_short_name_text') if isinstance(value := raw.get(key), str) and value],
    }
    groups['body'] = body_for(groups)
    document['governance'] = groups
    labels = {
        'appointed': words('Назначены', 'Appointed', 'Tayinlanganlar'),
        'departed': words('Полномочия прекращены', 'Terms ended', 'Vakolatlari tugatilganlar'),
    }
    summaries = {lang: [] for lang in ('ru', 'en', 'uz')}
    for group, label in labels.items():
        rows = groups[group]
        if not rows:
            continue
        for lang in summaries:
            names = [r['name'] for r in rows if r['name']]
            # Include both kinds of change; bound long lists without implying
            # that unnamed people were absent or matching rows by their order.
            value = ', '.join(names[:3])
            if len(names) != len(rows) or len(names) > 3:
                value += ('; ' if value else '') + words(
                    f'всего записей: {len(rows)}', f'{len(rows)} records in total',
                    f'jami {len(rows)} yozuv')[lang]
            summaries[lang].append(f'{label[lang]}: {value}.')
    if any(summaries.values()):
        document['summary'] = {lang: ' '.join(parts) for lang, parts in summaries.items()}
    link = raw.get('fact_own_link')
    if isinstance(link, str):
        try:
            parts = urlsplit(link)
            if parts.scheme in {'http', 'https'} and parts.netloc and parts.path.lower().endswith('.pdf'):
                document['pdf_url'] = link
        except ValueError:
            pass
