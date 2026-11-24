"""Retain all IFRS source forms; map only exact, dated, unambiguous cells."""
import re
from datetime import date, timedelta
from decimal import Decimal

from .ifrs_registry import DEFINITIONS


def key(text):
    return re.sub(r'[^a-zа-я0-9]', '', text.lower().replace('ё', 'е'))


ALIASES = {form: {key(label): metric_id for line in text.splitlines()
                  for metric_id, *labels in [line.split('|')] for label in labels}
           for form, text in DEFINITIONS.items()}


# These source captions explicitly give both earnings measures in whole UZS.
COMBINED_UZS_EPS = {key(caption) for caption in (
    'Базовая и разводненная прибыль на акцию (в сумах на одну акцию)',
    'Basic and diluted earnings per share (UZS per share)',
)}


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
    header = key(text).replace('отчетобществао', 'отчето')
    if re.search(r'\bcontents\b|содержание', text, re.I):
        return None
    for form, pattern in (
        ('Notes', r'notestothe.*financialstatements|notestofinancialstatements|примечанияк'),
        ('CF', r'statementofcashflows|отчетодвиженииденежных'),
        ('Equity', r'statementofchangesinequity|отчетобизменениях'),
        ('BS', r'statementoffinancialposition|отчетофинансовомположении'),
        ('PL', r'statementofprofit(?:or|and)loss|statementofincome|statementofcomprehensiveincome|отчето(?:прибыляхиубытках|прибылиилиубытке|совокупномдоходе)'),
    ):
        if re.search(pattern, header):
            return form
    return None


def split_row(line):
    # A date header is column context, not a label followed by an amount.
    if re.search(r'\b(?:31|30|1)\s*(?:December|March|June|September|January|декабря|марта|июня|сентября|января)\s*20\d{2}', line, re.I):
        return None
    if re.fullmatch(r'\s*(?:за\s+20\d{2}\s*(?:г(?:од[ауы]?)?\.?)?\s*){1,3}', line, re.I):
        return None
    for match in re.finditer(r'\s+(?=[({−\-\d—–])', line):
        label, tail = line[:match.start()].strip(), line[match.end():]
        if re.search('[a-zа-я]', label, re.I) and not re.search('[a-zа-я]', tail, re.I):
            return label, tail
    return None


def statement_scope(header, text, form, columns):
    from financial_ingestion.statements import cells

    if re.search(r'\bunconsolidated\b|\bнеконсолидирован', header, re.I):
        return 'separate'
    if re.search(r'\bconsolidated\b|\bконсолидирован', header, re.I):
        return 'consolidated'
    if re.search(r'\bseparate\b|\bindividual\b|\bотдельн|\bиндивидуальн', header, re.I):
        return 'separate'
    if form not in {'BS', 'PL', 'CF', 'Equity'}:
        return 'unknown'
    if re.search(r'подписан[а-я]*\s+от\s+имени\s+руководства\s+группы\b'
                 r"|signed\s+on\s+behalf\s+of\s+(?:the\s+)?group(?:['’]s)?\s+management\b",
                 text, re.I):
        return 'consolidated'
    if form in {'BS', 'PL'} and columns:
        for line in text.splitlines():
            parts = split_row(line)
            if parts and metric(parts[0], form) in {'nci', 'profit_nci'}:
                amounts = cells(parts[1], len(columns))
                if amounts and any(amount is not None and Decimal(amount) != 0 for amount in amounts):
                    return 'consolidated'
    return 'unknown'


COVER_TITLE = re.compile(
    r"^\s*(?:(consolidated|separate|unconsolidated)\s+financial\s+statements\s+for\s+the\s+year\s+ended"
    r"|(консолидированная|отдельная|неконсолидированная)\s+финансовая\s+отч[её]тность\s+за\s+год,?\s+"
    r"(?:закончившийся|завершившийся))\s+31\s+(?:December|декабря)\s+(20\d{2})\b",
    re.I | re.M,
)


def statement_covers(pages):
    """Carry a signed report's dated cover only through its contiguous statement pages."""
    from financial_ingestion import statements

    result = {}
    cover = None
    previous = None
    for number, text in sorted(pages.items()):
        if previous != number - 1:
            cover = None
        previous = number
        titles = COVER_TITLE.findall(text)
        if titles:
            cover = None
            if len(titles) == 1:
                en, ru, year = titles[0]
                scope = 'consolidated' if (en or ru).lower() in {'консолидированная', 'consolidated'} else 'separate'
                cover = (number, int(year), scope)
            continue
        if not cover:
            continue
        lines = text.splitlines()
        first = next((i for i, line in enumerate(lines) if split_row(line)), len(lines))
        header = '\n'.join(lines[:first])
        form = form_kind(header)
        if form not in {'BS', 'PL', 'CF', 'Equity'}:
            cover = None
            continue
        cols = statements.columns(header)
        declared = statement_scope(header, text, form, cols)
        if declared not in {'unknown', cover[2]} or not cols or max(y for y, _ in cols) != cover[1]:
            cover = None
            continue
        result[number] = cover
    return result


_LEASE_SECTIONS = {
    'currentliabilities': 'lease_liabilities_current',
    'краткосрочныеобязательства': 'lease_liabilities_current',
    'noncurrentliabilities': 'lease_liabilities_noncurrent',
    'долгосрочныеобязательства': 'lease_liabilities_noncurrent',
}


def extract(pages, *, page_count, covers=None):
    from financial_ingestion import statements as parser
    covers = statement_covers(pages) if covers is None else covers
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
        cols = parser.columns(header)
        scope = statement_scope(header, text, form, cols)
        if scope == 'unknown' and number in covers:
            scope = covers[number][2]
        forms.append({'form': form, 'page': number, 'text': text, 'scope': scope})
        # Dates must appear in the table header. Narrative note dates are not
        # sufficient to attach every number on that page to a reporting period.
        if not cols and form != 'Notes':
            issues.append(f'TABLE_COLUMNS_UNRESOLVED:{number}')
            continue
        table_started = False
        offset = 0 if form == 'Notes' else first
        if form == 'Notes':
            cols = []
        lease_section = _LEASE_SECTIONS.get(key(lines[offset - 1])) if form == 'BS' and offset else None
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
                if form == 'BS' and line.strip():
                    lease_section = _LEASE_SECTIONS.get(key(line))
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
            if form == 'BS' and lease_section:
                if metric_id == 'lease_liabilities':
                    metric_id = lease_section
                elif key(label).startswith(('total', 'итого', 'всего')):
                    lease_section = None
            combined_eps = False
            if form == 'PL' and metric_id is None:
                previous = lines[row_number - 2].strip() if row_number > 1 else ''
                if key(previous + ' ' + label) in COMBINED_UZS_EPS:
                    label = previous + ' ' + label
                    line = previous + ' ' + line
                combined_eps = key(label) in COMBINED_UZS_EPS
                if combined_eps:
                    metric_id = 'eps_basic'
            unit, scale = parser.currency(header), parser.units(header)
            per_share = bool(metric_id and metric_id.startswith('eps_'))
            shares = metric_id in {'weighted_average_shares', 'ordinary_shares', 'treasury_share_count'}
            if shares:
                unit, scale = 'shares', '1'
            elif combined_eps:
                unit, scale = 'UZS', '1'
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
                    # A weighted share count belongs to the earnings period,
                    # whereas outstanding shares are a balance at one date.
                    kind = 'flow' if metric_id == 'weighted_average_shares' else 'stock'
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
                if combined_eps:
                    rows.append({**rows[-1], 'metric_id': 'eps_diluted'})
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
