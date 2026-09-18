"""Issuer-independent statement proposals from layout-preserving PDF/OCR text.

No issuer names, report URLs, years or financial amounts are supplied to this
parser. Ambiguity stays explicit; extraction is not evidence review/approval.
"""
from collections import defaultdict
from decimal import Decimal
import re

VERSION = 'statement-columns-v1'


def compact(value):
    return re.sub(r'\s+', '', value.lower().replace('ё', 'е')).strip(' .:;_|')


LABELS = {
    'total_assets': r'(?:totalassets|итогоактив(?:ы|ов)|всегоактив(?:ы|ов))',
    'total_liabilities': r'(?:totalliabilities|итогообязательств(?:а)?|всегообязательств(?:а)?)',
    'total_equity': r'(?:totalequity|totalcapital|итого(?:собственный)?капитал|всего(?:собственный)?капитал)',
    'cash': r'(?:cashandcashequivalents|денежныесредстваиихэквиваленты)',
    'interest_income': r'(?:totalinterestincome|interestincome|итогопроцентныедоходы|процентныедоходы)',
    'interest_expense': r'(?:totalinterestexpenses?|interestexpenses?|итогопроцентныерасходы|процентныерасходы)',
    'operating_income': r'(?:totaloperatingincome|operatingincome|operating\(loss\)/income|итогооперационныедоходы|операционныедоходы)',
    'operating_expenses': r'(?:operatingexpenses|administrativeandotheroperatingexpenses|administrativeexpenses|административныеипрочиеоперационныерасходы|операционныерасходы)',
    'net_income': r'(?:(?:net)?(?:profit|loss|\(loss\)/profit|profit/\(loss\))forthe(?:year|period)|(?:чистая)?(?:прибыль|убыток|прибыль/\(убыток\)|\(убыток\)/прибыль)за(?:год|период)|чистаяприбыль)',
    '_pretax': r'(?:profitbefore(?:income)?tax|(?:прибыль|убыток)доналогообложения)',
    '_staff': r'(?:personnelexpenses|staffcosts|расходынаперсонал)',
    '_associate': r'(?:shareof(?:profit|results?)(?:of|from)associates|доляв(?:прибыли|убытках|результатах)(?:ассоциированных|зависимых)(?:компаний|предприятий|предпиятий))',
}
BALANCE = {'cash', 'total_assets', 'total_liabilities', 'total_equity'}
DATE = re.compile(r'(?P<day>31|30)\s*(?P<month>december|декабря|march|марта|june|июня|september|сентября)\s*(?P<year>20\d{2})', re.I)
MONTHS = {'december':12,'декабря':12,'march':3,'марта':3,'june':6,'июня':6,'september':9,'сентября':9}
START_MONTHS = {**MONTHS, 'january':1, 'января':1, 'february':2, 'февраля':2,
                'april':4, 'апреля':4, 'may':5, 'мая':5, 'july':7, 'июля':7,
                'august':8, 'августа':8, 'october':10, 'октября':10, 'november':11, 'ноября':11}
# A grouped integer must use groups of three. A dash is an explicit printed
# zero, but an absent cell never becomes one. Decimal comma is accepted only
# with one/two fractional digits, avoiding confusion with thousands separators.
NUMBER = re.compile(r'(?<!\d)(?:\(?[−-]?(?:\d{1,3}(?:,\d{3})+|\d{1,4}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d{1,2})?\)?|[—–-])(?!\d)')


def numeric(value):
    value = value.strip().replace('−', '-')
    if value in {'—','–','-'}:
        return '0'
    negative = value.startswith('(') and value.endswith(')')
    value = value.strip('()').replace('\u00a0',' ').replace('\u202f',' ')
    if ',' in value and re.search(r',\d{1,2}$', value):
        value = value.replace(',', '.')
    else:
        value = value.replace(',', '')
    value = value.replace(' ', '')
    amount = Decimal(value)
    return format(-abs(amount) if negative else amount, 'f')


def cells(tail, count):
    """Return only a unique column partition, discarding an optional note cell.

    Layout whitespace separates cells first. If a text layer collapses it,
    grouped-number parsing is accepted only when it produces exactly the
    declared number of columns (or those columns and a short note number).
    """
    tail = tail.strip()
    note = re.match(r'\d{1,2}(?:,\s*\d{1,2})+\s{2,}', tail)
    if note:
        without_note = cells(tail[note.end():], count)
        if without_note is not None:
            return without_note
    pieces = re.split(r'\s{2,}', tail)
    if len(pieces) in {count, count + 1} and all(NUMBER.fullmatch(p.strip()) for p in pieces):
        if len(pieces) == count and re.fullmatch(r'\d{1,2}', pieces[0]) and any(re.search(r'\d \d', p) for p in pieces[1:]):
            # The first cell can be a note number while the remaining cell
            # contains two collapsed space-grouped amounts. Do not guess.
            return None
        chosen = pieces[-count:]
    else:
        matches = list(NUMBER.finditer(tail))
        if re.sub(NUMBER, '', tail).strip():
            return None
        if len(matches) == count:
            chosen = [m.group() for m in matches]
        elif len(matches) == count + 1 and re.fullmatch(r'\d{1,2}', matches[0].group()):
            chosen = [m.group() for m in matches[1:]]
        else:
            return None
    try:
        return [numeric(p) for p in chosen]
    except ArithmeticError:
        return None


def row_label(line):
    # Financial labels can contain digits (IFRS 9); a numeric tail begins only
    # after whitespace and must contain exclusively amounts/note references.
    for match in re.finditer(r'\s+(?=[(−\-\d—–])', line):
        label, tail = line[:match.start()].strip(), line[match.end():]
        keys = [compact(label).strip('_/\\')]
        label_parts = re.split(r'\s{2,}', label)
        while len(label_parts) > 1 and len(label_parts[0].strip()) <= 5:
            label_parts.pop(0)
            keys.append(compact(' '.join(label_parts)).strip('_/\\'))
        for key in keys:
            field = next((f for f, pattern in LABELS.items() if re.fullmatch(pattern, key)), None)
            if field:
                return field, label, tail
            # Split interest categories are components, never mistaken for a total.
            if re.match(r'(?:otherinterestincome|прочиепроцентныедоходы|прочаяпроцентнаявыручка|.*income.*effectiveinterest|.*доходы.*эффективн)', key):
                return '_interest_income_part', label, tail
            if re.match(r'(?:otherinterestexpenses?|прочиепроцентныерасходы|.*expenses?.*effectiveinterest|.*расходы.*эффективн)', key):
                return '_interest_expense_part', label, tail
    return None


def statement_lines(text):
    lines = text.splitlines()
    result = []
    for index, line in enumerate(lines):
        # A wrapped row may place its amounts on the next baseline. Only
        # join a label to a numbers-only continuation, never to another row.
        if index + 1 < len(lines) and line.strip() and not row_label(line):
            following = lines[index + 1]
            interest_label = re.match(r'(?:interestincome|interestexpense|процентныедоходы|процентныерасходы)', compact(line)) or re.search(r'(?:income|expense|доходы|расходы).*(?:effective|эффективн)', compact(line))
            if following.strip() and (not re.sub(NUMBER, '', following).strip() or interest_label):
                combined = line.rstrip() + '  ' + following.strip()
                if row_label(combined):
                    result.append(combined)
                    continue
        if (index and line.lstrip()[:1].islower() and len(lines[index-1].strip()) > 40
                and not row_label(lines[index-1]) and not re.search(r'\d',lines[index-1])):
            # A continuation such as “interest income” beneath “Loss on
            # initial recognition of assets earning” is not an income total.
            result.append(lines[index-1].strip() + ' ' + line.strip())
            continue
        result.append(line)
    return result


def section_kind(text):
    key = compact(text)
    # Notes, cash flows and equity movements may repeat all the same labels.
    # Only the heading preceding the first financial row selects a statement.
    if re.search(r'(?:notesto(?:the)?(?:consolidated)?financial|примечанияк|statementofcashflows|отчетодвиженииденежных|statementofchangesinequity|отчетобизменениях)',key):
        return None
    if re.search(r'(?:statementoffinancialposition|отчетофинансовомположении)',key):
        return 'balance'
    if re.search(r'(?:statementof(?:profitorloss|income|comprehensiveincome)|отчето(?:прибыляхиубытках|совокупномдоходе))',key):
        return 'income'
    return None


def units(text):
    key = compact(text)
    scale = None
    if re.search(r'(?:million|миллион)',key) and re.search(r'(?:soum|sums|sum|uzs|сум|узс)',key):
        scale = '1000000'
    elif re.search(r'(?:thousand|тысяч|тыс\.)',key) and re.search(r'(?:soum|sums|sum|uzs|сум|узс)',key):
        scale = '1000'
    return scale


def columns(header):
    """Use statement column headers, never the largest year on a cover/opinion."""
    lines = header.splitlines()
    options = []
    for i,line in enumerate(lines):
        # A “from DATE to DATE” duration repeats a year in one column. Only
        # its end belongs to the year-column list; retain the full header as
        # period-start evidence for flow_start().
        column_line = re.sub(r'(?:\bfrom\b|\bс\b)\s*\d{1,2}\s*(?:' + '|'.join(START_MONTHS)
                             + r')\s*20\d{2}\s*(?:to|по)', '', line, flags=re.I)
        years = re.findall(r'20\d{2}', column_line)
        if 1 <= len(years) <= 3 and len(set(years)) == len(years):
            options.append((len(years),i,[int(y) for y in years]))
    if not options:
        return []
    _,index,years = max(options)
    window = '\n'.join(lines[max(0,index-4):index+3])
    dates = list(DATE.finditer(window))
    by_year = {int(m['year']):f"{m['year']}-{MONTHS[m['month'].lower()]:02d}-{int(m['day']):02d}" for m in dates}
    months = re.findall(r'(?:31|30)\s*(december|декабря|march|марта|june|июня|september|сентября)',window,re.I)
    if not months:
        # Some statements use only year labels over the columns and state the
        # full year-ended date in the title. That evidence must be explicit.
        dates = list(DATE.finditer(header))
        if dates:
            months = [dates[-1]['month']]
    if not months:
        return []
    month_numbers = [MONTHS[m.lower()] for m in months]
    result=[]
    for index,year in enumerate(years):
        end=by_year.get(year)
        if not end:
            if len(set(month_numbers)) != 1:
                return []
            month=month_numbers[0]
            end=f'{year}-{month:02d}-{31 if month in {3,12} else 30}'
        result.append((year,end))
    return result


def flow_start(text, year, end):
    """Retain non-calendar and standalone-quarter evidence instead of relabeling it."""
    start = re.search(r'(?:\bfrom\b|\bс\b)\s*(\d{1,2})\s*(' + '|'.join(START_MONTHS) + r')\s*(20\d{2})', text, re.I)
    if start:
        # A single explicit inaugural start date cannot establish the start
        # of a comparative column from another year.
        return f'{year}-{START_MONTHS[start[2].lower()]:02d}-{int(start[1]):02d}' if int(start[3]) == year else None
    key = compact(text)
    months = next((n for pattern,n in [(r'threemonths|тр[её]хмесяч|тримесяца',3),
                                       (r'sixmonths|шестимесяч|шестьмесяцев|полугод',6),
                                       (r'ninemonths|девятимесяч|девятьмесяцев',9)] if re.search(pattern,key)), None)
    if months is None and re.search(r'yearended|fortheyear|загод|год,закончивш',key):
        months=12
    if months is None:
        return None
    start_month=int(end[5:7])-months+1
    return f'{year if start_month>0 else year-1}-{(start_month-1)%12+1:02d}-01'


def _calculated(parts, label, field):
    # A transparent derivation stores each literal source line and coefficient.
    total = sum(Decimal(p['raw_value']) * p.get('coefficient',1) for p in parts)
    return {'raw_value':format(total,'f'),'raw_label':label,'page':parts[0]['page'],
            'column_year':parts[0]['column_year'],'calculation':'signed_sum',
            'components':parts,'field':field}


def proposals(pages, evidence):
    """Extract all supported columns and keep incompatible scopes separate."""
    joined='\n'.join(pages.values())
    standard='MSFO' if re.search(r'IFRS|МСФО|International Financial Reporting',joined,re.I) else None
    groups={}
    issues=[]
    for number,text in pages.items():
        lines=statement_lines(text)
        matched=[i for i,line in enumerate(lines) if row_label(line)]
        if not matched:
            continue
        first=matched[0]
        header='\n'.join(lines[:first])
        kind=section_kind(header)
        if not kind:
            # OCR can damage the heading while leaving the table intact.
            # Require a financial-statement heading plus multiple accounting
            # anchors; never infer a statement from an isolated note total.
            normalized = compact(header)
            if re.search(r'notesto|примечанияк|cashflows|движенииденежных|changesinequity|изменениях', normalized):
                continue
            fields = {row_label(line)[0] for line in lines if row_label(line)}
            if not re.search(r'financialstatements|финансоваяотчетность', normalized):
                continue
            if {'total_assets','total_liabilities','total_equity'} <= fields:
                kind='balance'
            elif {'operating_expenses','net_income'} <= fields and any('interest_' in f for f in fields):
                kind='income'
            else:
                continue
        cols=columns(header)
        if not cols:
            issues.append(f'COLUMN_DATES_UNRESOLVED:{number}')
            continue
        scale=units(header)
        # Unqualified financial statements describe the reporting entity;
        # consolidation must be stated in the heading, not a subsidiary note.
        scope='consolidated' if re.search(r'consolidated|консолидирован',header,re.I) else 'separate'
        document_year=max(year for year,end in cols)
        restated=bool(re.search(r'restated|пересчитан|пересмотрен',header,re.I))
        for year,end in cols:
            key=(scope,end,scale)
            if key not in groups:
                groups[key]={'classification':{'standard':standard,'scope':scope,'currency':'UZS' if scale else None,
                    'unit_scale':scale,'period_start':f'{year}-01-01','period_end':end,'document_year':document_year,
                    'role':'PRIMARY' if year==document_year else 'RESTATEMENT' if restated else 'COMPARATIVE',
                    'period_evidence':[], 'unit_evidence':[], 'issuer_evidence':None},
                    'figures':{},'parts':defaultdict(list),'conflicts':set(),'statement_pages':[]}
            g=groups[key]
            if kind == 'income':
                g['classification']['period_start'] = flow_start(text, year, end)
            g['classification']['document_year']=max(g['classification']['document_year'],document_year)
            g['classification']['period_evidence'].append(f'PDF page {number}: {header.strip()}')
            g['classification']['unit_evidence'].append(f'PDF page {number}: {header.strip()}')
            g['statement_pages'].append(number)
        for line in lines[first:]:
            row=row_label(line)
            if not row:
                continue
            field,label,tail=row
            if (kind=='balance') != (field in BALANCE):
                continue
            values=cells(tail,len(cols))
            if values is None:
                issues.append(f'AMBIGUOUS_CELLS:{number}:{label}')
                continue
            for (year,end),value in zip(cols,values):
                g=groups[(scope,end,scale)]
                figure={'raw_value':value,'raw_label':label,'page':number,'column_year':year}
                if field.startswith('_'):
                    if not any(old['raw_value']==value and old['page']==number
                               and compact(old['raw_label'])==compact(label) for old in g['parts'][field]):
                        g['parts'][field].append(figure)
                elif field in g['figures'] and g['figures'][field]['raw_value']!=value:
                    g['conflicts'].add(field)
                else:
                    g['figures'][field]=figure
    result=[]
    for g in groups.values():
        figures=g['figures'];parts=g.pop('parts')
        for field in ['interest_income','interest_expense']:
            components=parts.get('_'+field+'_part',[])
            if field not in figures and len(components)==2 and len({compact(p['raw_label']) for p in components})==2:
                figures[field]=_calculated(components,'Sum of reported interest categories',field)
        # Derive the pre-expense operating result only where no separate staff
        # expense line would be silently omitted. Otherwise leave it for review.
        if 'operating_income' not in figures and 'operating_expenses' in figures and len(parts.get('_pretax',[]))==1 and not parts.get('_staff'):
            components=[{**parts['_pretax'][0],'coefficient':1},{**figures['operating_expenses'],'coefficient':-1}]
            if len(parts.get('_associate',[]))==1:
                components.append({**parts['_associate'][0],'coefficient':-1})
            elif len(parts.get('_associate',[]))>1:
                components=[]
            if components:
                figures['operating_income']=_calculated(components,'Profit before tax less signed operating expenses and associate result','operating_income')
        for field in g.pop('conflicts'):
            figures.pop(field,None)
            issues.append('CONFLICTING_VALUES:'+field)
        meta=g['classification']
        for field in ['period_evidence','unit_evidence']:
            meta[field]='\n'.join(meta[field])
        # Issuer attribution is deliberately not inferred from a download URL.
        # A reviewer verifies the document heading against the catalog entity.
        meta['issuer_evidence']='\n'.join(next(iter(pages.values()),'').splitlines()).strip()[:2000] or None
        g['page_evidence']={str(n):pages[n][:20000] for n in set(g['statement_pages'])}
        g['extraction']={**evidence,'parser':VERSION,'issues':sorted(set(issues)),
                         'requires_review':True,'issuer_identity_verified':False}
        result.append(g)
    return result
