"""People in form 8, preserving source groups without inferring succession.

OpenInfo calls the person's name `question_name` in change tables, and `name`
in the resulting roster. Those keys have different meanings in other forms.
"""
from urllib.parse import urlsplit

from corporate_event_fields import content, words


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
    }
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
