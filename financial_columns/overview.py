"""Compact HTML overview: the first eight named fields of each section.

One template field occupies one row. Distinct source components stay distinct
inside that row; this presentation layer never invents a total or fills a gap.
"""


def compact_rows(groups, rows, columns):
    if not rows:
        return []
    result = []
    for group in groups:
        for field in group['fields'][:8]:
            matches = [r for r in rows if r['display_field'] == field['field_id']]
            if len(matches) == 1:
                result.append(matches[0])
                continue
            form, code, metric = field['selectors'][0]
            cells = {}
            for column in columns:
                parts = [{'source_form': r['source_form'], 'source_code': r.get('source_code'),
                          'metric_id': r.get('metric_id'), 'raw_label': r.get('source_label') or r['label'],
                          **r['cells'][column['key']]} for r in matches]
                cells[column['key']] = {'value': None, 'quality': 'missing', 'reason': 'SOURCE_VALUE_MISSING'}
                if parts:
                    cells[column['key']]['display_parts'] = parts
            result.append({'id': 'reference:' + field['field_id'], 'metric_id': metric,
                           'label': field['label'], 'display_field': field['field_id'],
                           'display_group': group['label'], 'display_ref': field['ref'],
                           'source_form': form, 'source_code': code, 'kind': field['kind'],
                           'unit': matches[0]['unit'] if matches else 'UZS_thousand', 'cells': cells})
    return result
