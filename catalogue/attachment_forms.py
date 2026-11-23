"""Recognize national statements submitted as paired Openinfo audit attachments."""
from collections import defaultdict
from datetime import date
import re

from catalogue import history, settings, sources

_PERIOD = re.compile(r'\bза\s+(?:(1\s+полугодие|[1-3]\s+квартал|9\s+месяцев)\s+)?(20\d{2})\s*г(?:од|\.|\b)', re.I)
_FORMS = {'income': ('отчет о финансовых результатах', '0710002'),
          'balance': ('бухгалтерский баланс', '0710001')}


def _text(value):
    return ' '.join(str(value or '').lower().replace('ё', 'е').split())


def _period(text):
    matches = set(_PERIOD.findall(text))
    if len(matches) != 1:
        return None
    term, year = matches.pop()
    quarter = 2 if term == '1 полугодие' else 3 if term == '9 месяцев' else int(term[0]) if term else 0
    return int(year), quarter


def _verified(session, url, form, period, inn):
    parsed = history._parse_workbook_uncached(session, url)
    if not parsed.get('ok') or parsed.get('warnings') or len(parsed.get('sheets', [])) != 1:
        return False
    # Match the registration and tax fields on the original cover, including
    # the form identifier. The year in the ministerial template is not a date.
    rows = [[_text(v) for v in r['cells']] for r in parsed['sheets'][0].get('source_rows', [])[:40]]
    header = ' '.join(cell for row in rows for cell in row if cell)
    label, okud = _FORMS[form]
    return (label in header and _period(header) == period and 'консолидирован' not in header
            and any(okud in row and any('окуд' in v for v in row) for row in rows)
            and any(inn in row and any('инн' in v or 'стир' in v for v in row) for row in rows))


def discover(conn, session, attachments):
    groups = defaultdict(lambda: defaultdict(dict))
    for ticker, record in attachments:
        file = record.get('pdf_file') or ''
        if record.get('status') != 'approved' or not re.fullmatch(r'audition/[\w.-]+\.xlsx', file, re.I):
            continue
        title = _text(record.get('title'))
        period = _period(title)
        forms = [key for key, (label, _) in _FORMS.items() if label in title]
        if len(forms) != 1 or not period or 'консолидирован' in title:
            continue
        published = str(record.get('pub_date') or '')
        try:
            day = date.fromisoformat(published[:10])
        except ValueError:
            continue
        year, quarter = period
        if (day.year, day.month, day.day) < (year, (quarter or 4) * 3, 30 if quarter in (2, 3) else 31):
            continue
        key = (ticker, str(record['organization']), year, quarter)
        groups[key][forms[0]][f'{sources.OPENINFO_WEB_BASE}/media/{file}'] = published

    added = 0
    for (ticker, org, year, quarter), forms in groups.items():
        if forms.keys() != _FORMS.keys() or any(len(candidates) != 1 for candidates in forms.values()):
            continue
        income, balance = (next(iter(forms[f])) for f in ('income', 'balance'))
        published = [forms['income'][income], forms['balance'][balance]]
        if published[0][:10] != published[1][:10]:
            continue
        if conn.execute("SELECT 1 FROM catalog_reports r JOIN catalog_companies c ON c.ticker=r.ticker "
                        "WHERE c.org_id=? AND r.report_form='NSBU' AND r.year=? AND r.quarter=? "
                        "AND COALESCE(r.excel_url,r.excel_url_form1,r.pdf_url) IS NOT NULL LIMIT 1",
                        (org, year, quarter)).fetchone():
            continue
        try:
            identity = sources._json_get(session, f'/home/organizations/{org}/')
            inn = str(identity.get('inn') or '')
            if (str(identity.get('id')) != org or not re.fullmatch(r'\d{9}', inn)
                    or not all(_verified(session, url, form, (year, quarter), inn)
                               for form, url in [('income', income), ('balance', balance)])):
                continue
        except Exception:
            settings.logger.exception('Could not verify statutory attachments for %s %s Q%s', ticker, year, quarter)
            continue
        period_type = 'quarter' if quarter else 'annual'
        with conn:
            result = conn.execute(
                "INSERT INTO catalog_reports(ticker,report_form,period_type,year,quarter,title,published_at,excel_url,excel_url_form1) "
                "VALUES (?,'NSBU',?,?,?,?,?,?,?) ON CONFLICT(ticker,report_form,period_type,year,quarter) DO UPDATE SET "
                "excel_url=excluded.excel_url,excel_url_form1=excluded.excel_url_form1,published_at=excluded.published_at "
                "WHERE COALESCE(catalog_reports.excel_url,catalog_reports.excel_url_form1,catalog_reports.pdf_url) IS NULL",
                (ticker, period_type, year, quarter, f'НСБУ, {year}' + (f' Q{quarter}' if quarter else ''),
                 max(published), income, balance))
            added += result.rowcount
    return added
