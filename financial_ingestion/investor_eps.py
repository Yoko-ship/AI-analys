"""Read self-reconciling annual EPS notes from the exact PDF of a published filing."""
from contextlib import closing
from functools import lru_cache
from datetime import date
import json
import subprocess
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import pypdfium2
from catalogue.storage import get_catalog_conn
import dbx
from . import documents, layout
from .statements import cells


VERSION = 'annual-eps-note-3'
STATEMENT_VERSION = 'annual-reported-eps-1'
NOTE_TITLE = re.compile(r"^\s*(?:\d+[.)]?\s+)?(?:basic )?earnings per (?:ordinary )?share\s*$", re.I | re.M)
PERIOD = re.compile(r'notes to (?:the )?(consolidated|separate|individual) financial statements\s*[-–—,]?\s*(?:as (?:at|of) )?31 December (20\d\d)', re.I)
TABLE = re.compile(r'^(?:in )?(millions|thousands) of (?:Uzbekistan |Uzbek )?(?:soums?|UZS)\s+(20\d\d)\s+(20\d\d)$', re.I)
LABELS = {
    'profit': r'(?:net )?(?:profit|loss|profit or loss) for the year attributable to (?:the )?ordinary shareholders(?: of the (?:bank|group|company|parent))?',
    'weighted': r'weighted average number of ordinary shares (?:in issue|outstanding)\s*\((millions|thousands)\)',
    'eps': r'basic(?: and diluted)? earnings per (?:ordinary )?share\s*\((?:expressed )?in UZS per share\)',
}


def _allocated_table(lines, header_lines):
    """Some notes print the units in the page heading and deduct preferred earnings in the table."""
    scales = [m[1] for line in header_lines if (m := re.fullmatch(
        r'\s*\(In (millions|thousands) of (?:Uzbekistan|Uzbek) Soums, unless otherwise indicated\)\s*', line, re.I))]
    dates = [(i, m) for i, line in enumerate(lines) if (m := re.fullmatch(r'(20\d\d)\s+(20\d\d)', line))]
    if len(scales) != 1 or len(dates) != 1:
        return None
    start, years = dates[0]
    # Rejoin wrapped labels until the row ends with a printed numeric cell.
    data, pending = [], []
    for line in lines[start+1:]:
        pending.append(line)
        if re.search(r'\d\)?$', line):
            data.append(' '.join(pending))
            pending = []
            if len(data) == 5:
                break
    ordinary = r'Profit\s*/\s*\(loss\) for the year attributable to the ordinary shareholders of the (?:Bank|Group|Company)'
    labels = [ordinary, r'Less undistributed profit or loss for the year attributable to preference shareholders based on terms of the shares',
              ordinary, LABELS['weighted'], r'Total basic and diluted earnings per share attributable to the owners of the (?:Bank|Group|Company) \(expressed in UZS per share\)']
    amounts = []
    if len(data) != len(labels):
        return None
    for line, label in zip(data, labels):
        match = re.fullmatch(label + r'\s+([()\d.,\s−-]+)', line, re.I)
        if not match or (label == LABELS['weighted'] and match[1].lower() != scales[0].lower()):
            return None
        values = cells(match.groups()[-1], 2)
        if not values or None in values:
            return None
        amounts.append(values)
    for before, preference, after in zip(*amounts[:3]):
        if Decimal(before) + Decimal(preference) != Decimal(after):
            return None
    fields = {key:(line, values) for key, line, values in zip(('profit','weighted','eps'), data[2:], amounts[2:])}
    return start, *years.groups(), fields


def reconciled_eps(text, *, page):
    """Require a dated annual table and independently reproduce each printed EPS."""
    period = PERIOD.search(' '.join(text.splitlines()[:5]))
    titles = list(NOTE_TITLE.finditer(text))
    if not period or len(titles) != 1:
        return []
    lines = [line.strip() for line in text[titles[0].end():].splitlines() if line.strip()]
    headers = [(i, m) for i, line in enumerate(lines) if (m := TABLE.fullmatch(line))]
    if not headers:
        allocated = _allocated_table(lines, text.splitlines()[:5])
        if not allocated:
            return []
        start, latest, prior, fields = allocated
    elif len(headers) == 1:
        start, header = headers[0]
        scale, latest, prior = header.groups()
        fields = {}
        # Cells can wrap to the next physical line. Match whole labels in this table only.
        for index in range(start+1, min(start+12, len(lines))):
            for key, pattern in LABELS.items():
                for line in (lines[index], ' '.join(lines[index:index+2])):
                    match = re.fullmatch(pattern + r'\s+([()\d.,\s−-]+)', line, re.I)
                    if not match:
                        continue
                    if key in fields or (key == 'weighted' and match[1].lower() != scale.lower()):
                        return []
                    values = cells(match.groups()[-1], 2)
                    if not values or any(v is None for v in values):
                        return []
                    fields[key] = (line, values)
                    break
    else:
        return []
    if latest != period[2] or int(prior) != int(latest)-1:
        return []
    if fields.keys() != LABELS.keys():
        return []
    rows = []
    for col, year in enumerate((latest, prior)):
        profit, weighted, eps = (Decimal(fields[k][1][col]) for k in ('profit','weighted','eps'))
        if weighted <= 0 or (profit / weighted).quantize(Decimal(1).scaleb(eps.as_tuple().exponent), rounding=ROUND_HALF_UP) != eps:
            return []
        heading = next((line.strip() for line in text.splitlines() if line.strip()), '')
        rows.append(dict(source_form='Notes', metric_id='eps_basic', source_code=None, raw_label='Basic earnings per ordinary share',
                         issuer_heading=heading,
                         raw_line='\n'.join([lines[start], *(entry[0] for entry in fields.values())]),
                         raw_value=str(eps), scope='consolidated' if period[1].lower()=='consolidated' else 'separate',
                         page=page, column=col, period_start=year+'-01-01', period_end=year+'-12-31',
                         statement_period_end=year+'-12-31', kind='per_share', currency='UZS', unit_scale='1',
                         unit='UZS_per_share', quality='valid', reason=None))
    return rows


def statement_eps(text, *, page, printed_note):
    """A printed basic EPS needs its own unit and unambiguous annual columns."""
    lines = [' '.join(line.split()) for line in text.splitlines() if line.strip()]
    if len(lines) < 4:
        return []
    title = re.fullmatch(r'(Консолидированный|Отдельный|Индивидуальный) отч[её]т о прибылях и убытках'
                         r'(?: и прочем совокупном доходе)?', lines[1], re.I)
    if not title:
        return []
    candidates = [i for i, line in enumerate(lines) if re.match(r'Базовая прибыль на (?:одну )?акцию\b', line, re.I)]
    if len(candidates) != 1:
        return []
    index = candidates[0]
    headers = re.findall(r'\bСтатьи\s+(Примечание\s+)?31 декабря (20\d{2}) года 31 декабря (20\d{2}) года\b',
                         ' '.join(lines[2:min(index, 10)]), re.I)
    if len(headers) != 1:
        return []
    note, year, prior = headers[0]
    if int(prior) + 1 != int(year):
        return []
    # Whitespace can separate columns or thousands in flattened PDF text. Only
    # accept complete, ungrouped decimal cells, with a distinct note number.
    amount = r'(?:-?\d+,\d+|\(\d+,\d+\))'
    label = r'(Базовая прибыль на (?:одну )?акцию \(в (?:узбекских )?сумах\))'
    match = re.fullmatch(label + (r'\s+(?P<note>\d{1,3})' if note else '') + r'\s+(?P<latest>' +
                         amount + r')\s+' + amount, lines[index], re.I)
    if not match:
        return []
    if note and match['note'] != printed_note(match[1]):
        return []
    eps = match['latest'].replace(',', '.').replace('(', '-').rstrip(')')
    return [dict(source_form='Income statement', metric_id='eps_basic', source_code=None,
                 raw_label=match[1], raw_line=lines[index], raw_value=eps, issuer_heading=lines[0],
                 scope='consolidated' if title[1].lower() == 'консолидированный' else 'separate',
                 page=page, column=0, period_start=year+'-01-01', period_end=year+'-12-31',
                 statement_period_end=year+'-12-31', kind='per_share', currency='UZS', unit_scale='1',
                 unit='UZS_per_share', quality='valid', reason=None)]


def _ocr(page, scratch, *, scale):
    width, height = page.get_size()
    if width * height * scale**2 > 20_000_000:
        raise ValueError('EPS scan exceeds page size limit')
    bitmap = page.render(scale=scale)
    try:
        bitmap.to_pil().convert('L').save(scratch)
    finally:
        bitmap.close()
    result = subprocess.run(['tesseract', str(scratch), 'stdout', '-l', 'eng', '--psm', '6', 'tsv'],
                            capture_output=True, check=True, timeout=30)
    return layout.tsv_text(result.stdout.decode('utf-8'))


def _note_cell(native, label):
    """Read the intersection of the EPS row and the physically separate note column."""
    locations = []
    for phrase in ('Примечание', label):
        search = native.search(phrase, match_whole_word=False)
        try:
            hit = search.get_next()
            if not hit:
                return ''
            start, count = hit
            locations.append((native.get_charbox(start), native.get_charbox(start+count-1)))
        finally:
            search.close()
    (left, right), (first, last) = locations
    if left[1] <= first[3] or last[2] >= left[0]:
        return ''
    return native.get_text_bounded(left[0], min(first[1], last[1]), right[2], max(first[3],last[3])).strip()


def scan_pdf(content, *, ocr, statements=False):
    rows = []
    with pypdfium2.PdfDocument(content) as pdf, TemporaryDirectory(prefix='uzstock-eps-') as folder:
        if len(pdf) > 500:
            raise ValueError('EPS scan exceeds document page limit')
        for index in range(len(pdf)):
            page = pdf[index]
            try:
                native = page.get_textpage()
                try:
                    text = native.get_text_bounded()
                    found = (statement_eps(text, page=index+1, printed_note=lambda label: _note_cell(native, label))
                             if statements else reconciled_eps(text, page=index+1))
                finally:
                    native.close()
                if not found and ocr:
                    # A broken text layer can contain thousands of unreadable glyphs.
                    # Survey only when native text cannot identify a readable report page.
                    is_note = bool(NOTE_TITLE.search(text))
                    if not is_note and not re.search(r'financial statements|financial position|финансов\w+ отчетност', text, re.I):
                        survey = _ocr(page, Path(folder)/'page.png', scale=1.5)
                        is_note = bool(re.search(r'earnings per (?:ordinary )?share', survey, re.I))
                    if is_note:
                        found = reconciled_eps(_ocr(page, Path(folder)/'page.png', scale=3), page=index+1)
                rows.extend(found)
            finally:
                page.close()
    return rows


def archived_rows(sha, *, ocr):
    """Cache successful scans (including empty ones), separately by OCR capability."""
    return _cached_scan(sha, VERSION, ocr)


def archived_statements(sha):
    return _cached_scan(sha, STATEMENT_VERSION, False)


def _cached_scan(sha, parser, ocr):
    with closing(get_catalog_conn()) as conn:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS investor_eps_scans (sha TEXT, parser TEXT, ocr INTEGER, '
                         'rows_json TEXT NOT NULL, PRIMARY KEY (sha,parser,ocr))')
        row = conn.execute('SELECT rows_json FROM investor_eps_scans WHERE sha=? AND parser=? AND ocr>=? '
                           'ORDER BY ocr DESC LIMIT 1', (sha, parser, int(ocr))).fetchone()
        if row:
            return json.loads(row['rows_json'])
    content = documents.read_artifact(sha)
    rows = scan_pdf(content, ocr=False, statements=True) if parser == STATEMENT_VERSION else scan_pdf(content, ocr=ocr)
    with closing(get_catalog_conn()) as conn:
        with conn:
            conn.execute('INSERT INTO investor_eps_scans VALUES (?,?,?,?) ON CONFLICT DO NOTHING',
                         (sha, parser, int(ocr), json.dumps(rows, ensure_ascii=False)))
        return rows


def published_rows(snapshot):
    sha = (snapshot['payload'].get('source') or {}).get('file_hash')
    if not sha:
        return []
    with closing(get_catalog_conn()) as conn:
        if 'investor_eps_scans' not in dbx.tables(conn):
            return []
        item = conn.execute('SELECT rows_json FROM investor_eps_scans WHERE sha=? AND parser=? ORDER BY ocr DESC LIMIT 1',
                            (sha, VERSION)).fetchone()
    return [r for r in json.loads(item['rows_json']) if r['scope']==snapshot['scope'] and r['period_end']==snapshot['period_end']
            and r['period_start']==snapshot['payload']['classification']['period_start']] if item else []


def _name(value):
    words = re.findall(r'[^\W_]+', str(value or '').casefold())
    legal = {'jscb','jsc','aj','atb','akb','акб','ао','пао','оао','атб'}
    while words and words[0] in legal:
        words.pop(0)
    while words and words[-1] in legal:
        words.pop()
    return ' '.join(words)


def official_filing(meta, *, url, org, row, end, cutoff):
    """A separately attributed disclosure, independent of whole-report publication."""
    path = urlsplit(url)
    if (path.scheme != 'https' or path.netloc != 'openinfo.uz' or not path.path.startswith('/media/msfo/')
            or not path.path.lower().endswith('.pdf') or meta.get('pdf_url') != url
            or str(meta.get('organization_id')) != org or meta.get('status') != 'approved'
            or meta.get('report_form') != 'MSFO' or meta.get('period_type') != 'annual' or row['column'] != 0):
        return None
    printed = _name(row.get('issuer_heading'))
    registered = _name(meta.get('organization_name'))
    if row.get('scope') == 'consolidated' and row.get('source_form') == 'Notes':
        # An English bank group heading can include its legal form and the consolidation perimeter.
        bank = re.fullmatch(r'joint stock commercial (.+) and its subsidiaries', printed)
        if bank and registered.startswith('at '):
            printed, registered = bank[1], registered.removeprefix('at ')
    if row.get('source_form') == 'Income statement':
        # The Russian and Uzbek legal forms must retain the same activity and
        # the full distinctive name. Never match a substring of an issuer.
        printed = re.sub(r' и е[её] дочерн(?:ее предприятие|ие предприятия)$', '', printed)
        printed = printed.removeprefix('акционерное общество ')
        insurance = re.fullmatch(r'(?:ск|страховая компания) (.+)', printed)
        if insurance:
            printed = insurance[1] + ' sug urta kompaniyasi'
    if not printed or printed != registered:
        return None
    try:
        published = date.fromisoformat(str(meta.get('published_at') or '')[:10]).isoformat()
    except ValueError:
        return None
    stamp = row['period_end']
    if not stamp <= published <= cutoff or stamp > end:
        return None
    return {'standard':'ifrs', 'scope':row['scope'], 'period':stamp[:4], 'value':float(row['raw_value']),
            'unit':row['unit'], 'source_url':url, 'page':row['page']}


@lru_cache(maxsize=1)
def _reviewed_notes():
    path = Path(__file__).resolve().parents[1] / 'config' / 'reviewed_eps_notes.json'
    return json.loads(path.read_text(encoding='utf-8'))


def _reviewed_eps_unit(note, eps):
    """Return the unit only after validating the statement row or its components."""
    components = {'ordinary_profit', 'uzs_per_currency_unit', 'weighted_ordinary_shares', 'shares_per_unit'}
    if components.intersection(note):
        if not components.issubset(note) or note.get('unit', 'UZS_per_ordinary_share') != 'UZS_per_ordinary_share':
            return None
        profit = Decimal(note['ordinary_profit']) * note['uzs_per_currency_unit']
        shares = Decimal(note['weighted_ordinary_shares']) * note['shares_per_unit']
        precision = Decimal(1).scaleb(eps.as_tuple().exponent)
        if shares > 0 and (profit / shares).quantize(precision, rounding=ROUND_HALF_UP) == eps:
            return 'UZS_per_share'
        return None
    # Scanned income statements can print basic EPS directly, with its own unit.
    if (note.get('source_form') == 'income_statement' and note.get('row_label') and note['page'] > 0
            and note['period_end'] == f"{note.get('column_year')}-12-31"):
        return {'UZS_per_ordinary_share': 'UZS_per_share',
                'USD_per_ordinary_share': 'USD_per_share'}.get(note.get('unit'))


def _reviewed_eps(conn, org, end, cutoff):
    for note in _reviewed_notes().get(str(org), []):
        url, stamp = note['source_url'], note['period_end']
        if stamp > end:
            continue
        record = conn.execute(
            'SELECT s.metadata_json FROM ingest_sources s JOIN ingest_versions v ON v.id=s.latest_version '
            'WHERE s.org_id=? AND s.category=? AND s.url=? AND v.sha=?',
            (str(org), 'MSFO', url, note['sha256'])).fetchone()
        if not record:
            continue
        meta = json.loads(record['metadata_json'])
        if (meta.get('id') != note['report_id'] or str(meta.get('organization_id')) != str(org)
                or meta.get('pdf_url') != url or meta.get('status') != 'approved'
                or meta.get('report_form') != 'MSFO' or meta.get('period_type') != 'annual'
                or not stamp <= str(meta.get('published_at') or '')[:10] <= cutoff):
            continue
        eps = Decimal(note['reported_eps'])
        unit = _reviewed_eps_unit(note, eps)
        if unit:
            yield {'standard': 'ifrs', 'scope': note['scope'], 'period': stamp[:4], 'value': float(eps),
                   'unit': unit, 'source_url': url, 'page': note['page']}


def official_eps(org, end, cutoff, preferred_scope):
    with closing(get_catalog_conn()) as conn:
        tables = set(dbx.tables(conn))
        if not {'ingest_sources','ingest_versions'} <= tables:
            return None
        reviewed = list(_reviewed_eps(conn, org, end, cutoff))
        checks = 'ingest_version_filing_checks' in tables
        observation = 'COALESCE(f.metadata_json,v.metadata_json)' if checks else 'v.metadata_json'
        join = 'LEFT JOIN ingest_version_filing_checks f ON f.version_id=v.id ' if checks else ''
        records = conn.execute(
            f'SELECT s.url,s.metadata_json,{observation} AS archived_metadata,x.rows_json '
            'FROM ingest_sources s JOIN ingest_versions v ON v.id=s.latest_version '
            f'{join}'
            'JOIN investor_eps_scans x ON x.sha=v.sha WHERE s.org_id=? AND s.category=? AND x.parser IN (?,?)',
            (str(org), 'MSFO', VERSION, STATEMENT_VERSION)).fetchall() if 'investor_eps_scans' in tables else []
    by_period = {}
    for fact in reviewed:
        by_period.setdefault((fact['period'], fact['scope']), []).append(fact)
    for record in records:
        meta = json.loads(record['metadata_json'])
        archived = json.loads(record['archived_metadata'])
        for row in json.loads(record['rows_json']):
            fact = official_filing(meta, url=record['url'], org=str(org), row=row, end=end, cutoff=cutoff)
            if fact and official_filing(archived, url=record['url'], org=str(org), row=row, end=end, cutoff=cutoff):
                by_period.setdefault((fact['period'], fact['scope']), []).append(fact)
    for key in sorted(by_period, key=lambda k:(k[0], k[1]==preferred_scope), reverse=True):
        choices = by_period[key]
        if len({(item['value'], item['unit']) for item in choices}) == 1:
            return choices[0]
