"""Retain all IFRS source forms; map only exact, dated, unambiguous cells."""
import re
from datetime import date, timedelta

from .ifrs_registry import DEFINITIONS


def key(text):
    return re.sub(r'[^a-zа-я0-9]', '', text.lower().replace('ё', 'е'))


ALIASES = {form: {key(label): metric_id for line in text.splitlines()
                  for metric_id, *labels in [line.split('|')] for label in labels}
           for form, text in DEFINITIONS.items()}


def metric(label, form):
    return ALIASES.get(form, {}).get(key(label))


def accounting_model(pages):
    """Use an explicit applied accounting policy, never the reporting year."""
    evidence = []
    for page, text in pages.items():
        for sentence in re.split(r'(?<=[.!?])\s+', re.sub(r'\s+', ' ', text)):
            standard = re.search(r'(?:IFRS|МСФО)\s*(?:\([^)]+\)\s*)?(17|4)\b', sentence, re.I)
            if (standard and re.search(r'\b(?:applies|adopted|has applied)\b|применяет|применило|применила', sentence, re.I)
                    and not re.search(r'not yet|will |does not|не примен|не вступ|будет', sentence, re.I)):
                evidence.append({'model': 'IFRS17' if standard[1] == '17' else 'legacy', 'page': page, 'text': sentence})
    models = {e['model'] for e in evidence}
    return {'model': next(iter(models)) if len(models) == 1 else None, 'evidence': evidence}


def form_kind(text):
    header = key(text)
    if re.search(r'\bcontents\b|содержание', text, re.I):
        return None
    for form, pattern in (
        ('Notes', r'notestothe.*financialstatements|notestofinancialstatements|примечанияк'),
        ('CF', r'statementofcashflows|отчетодвиженииденежных'),
        ('Equity', r'statementofchangesinequity|отчетобизменениях'),
        ('BS', r'statementoffinancialposition|отчетофинансовомположении'),
        ('PL', r'statementofprofitorloss|statementofincome|statementofcomprehensiveincome|отчето(?:прибыляхиубытках|прибылиилиубытке|совокупномдоходе)'),
    ):
        if re.search(pattern, header):
            return form
    return None


def split_row(line):
    # A date header is column context, not a label followed by an amount.
    if re.search(r'\b(?:31|30|1)\s*(?:December|March|June|September|January|декабря|марта|июня|сентября|января)\s*20\d{2}', line, re.I):
        return None
    for match in re.finditer(r'\s+(?=[({−\-\d—–])', line):
        label, tail = line[:match.start()].strip(), line[match.end():]
        if re.search('[a-zа-я]', label, re.I) and not re.search('[a-zа-я]', tail, re.I):
            return label, tail
    return None


def extract(pages, *, page_count):
    from financial_ingestion import statements as parser
    forms, rows, issues = [], [], []
    previous_form = None
    for number, text in sorted(pages.items()):
        lines = text.splitlines()
        first = next((i for i, line in enumerate(lines) if split_row(line)), len(lines))
        header = '\n'.join(lines[:first])
        form = form_kind(header)
        # Notes can span many pages without repeating the statement heading.
        if form is None and previous_form == 'Notes':
            form = 'Notes'
        if form is None:
            continue
        previous_form = form
        scope = ('consolidated' if re.search(r'consolidated|консолидирован', header, re.I) else
                 'separate' if re.search(r'separate|individual|отдельн|индивидуальн', header, re.I) else 'unknown')
        forms.append({'form': form, 'page': number, 'text': text, 'scope': scope})
        # Dates must appear in the table header. Narrative note dates are not
        # sufficient to attach every number on that page to a reporting period.
        cols = parser.columns(header)
        if not cols and form != 'Notes':
            issues.append(f'TABLE_COLUMNS_UNRESOLVED:{number}')
            continue
        table_started = False
        offset = 0 if form == 'Notes' else first
        if form == 'Notes':
            cols = []
        for row_number, line in enumerate(lines[offset:], offset + 1):
            if form == 'Notes':
                # A running report date is not the date of each Notes table.
                # Only an explicit local date header opens a numeric table;
                # subsequent prose closes it, preventing portfolio crossover.
                dates = parser.columns(line)
                residual = parser.DATE.sub('', line).strip(' \t,;:().')
                if dates and (not residual or re.fullmatch(r'as at|на', residual, re.I)):
                    cols = dates if table_started else list(dict.fromkeys([*cols, *dates]))
                    table_started = False
                    continue
            split = split_row(line)
            if not split:
                if form == 'Notes' and table_started and line.strip():
                    cols = []
                continue
            if form == 'Notes' and not cols:
                issues.append(f'TABLE_COLUMNS_UNRESOLVED:{number}')
                continue
            table_started = True
            label, tail = split
            values = parser.cells(tail, len(cols))
            metric_id = metric(label, form)
            unit, scale = parser.currency(header), parser.units(header)
            per_share = bool(metric_id and metric_id.startswith('eps_'))
            shares = metric_id in {'weighted_average_shares', 'ordinary_shares', 'treasury_share_count'}
            if shares:
                unit, scale = 'shares', '1'
            elif per_share:
                scale = '1' if re.search(r'per.?share|на.?акци', header, re.I) else None
            for column, (year, end) in enumerate(cols):
                value = values[column] if values is not None else None
                reason = ('COLUMN_PARTITION_UNRESOLVED' if values is None else
                          'UNIT_UNRESOLVED' if not unit or not scale else
                          'SCOPE_UNRESOLVED' if scope == 'unknown' else None)
                kind = 'stock' if form == 'BS' or metric_id in {'cash_begin', 'cash_end', 'equity_open'} else 'flow'
                if per_share:
                    kind = 'per_share'
                if form == 'Notes':
                    kind = 'stock'  # notes here map only explicitly defined balance/share disclosures
                start = parser.flow_start(header, year, end, column_index=column, column_count=len(cols))
                when = end
                if kind in {'flow', 'per_share'} and not start:
                    reason = reason or 'PERIOD_START_UNRESOLVED'
                if metric_id in {'cash_begin', 'equity_open'}:
                    if start:
                        when = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
                    else:
                        reason = reason or 'PERIOD_START_UNRESOLVED'
                quality = 'blocked' if reason else 'missing' if value is None else 'valid'
                rows.append({'source_form': form, 'source_code': None, 'metric_id': metric_id,
                             'raw_label': label, 'raw_line': line, 'raw_value': value,
                             'page': number, 'row': row_number, 'column': column,
                             'statement_period_end': end, 'period_end': when,
                             'period_start': start if kind in {'flow', 'per_share'} else when,
                             'scope': scope, 'currency': unit, 'unit_scale': scale,
                             'kind': kind, 'unit': 'shares' if shares else 'UZS_per_share' if per_share else 'UZS_thousand',
                             'quality': quality, 'reason': reason})
    notes = any(f['form'] == 'Notes' for f in forms)
    if not notes:
        issues.append('NOTES_MISSING')
    if len(pages) < page_count:
        issues.append('PAGES_NOT_EXTRACTED')
    if any(not text.strip() for text in pages.values()):
        issues.append('EMPTY_OR_SCANNED_PAGES')
    if not rows:
        issues.append('STATEMENT_ROWS_MISSING')
    present = {f['form'] for f in forms}
    issues.extend('FORM_MISSING:' + form for form in ('BS', 'PL', 'CF', 'Equity') if form not in present)
    return {'forms': forms, 'rows': rows, 'coverage': {
        'complete': not issues, 'notes': 'present' if notes else 'missing',
        'pages_read': sorted(pages), 'page_count': page_count, 'issues': sorted(set(issues))}}
