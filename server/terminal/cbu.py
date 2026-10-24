"""CBU monthly observations, separate from issuer financial statements.

Discovery uses official page titles; spreadsheet columns use their headers.
Failed parses never overwrite the last successfully loaded snapshot.
"""
from __future__ import annotations
from datetime import date
from contextvars import ContextVar
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import urljoin
from xml.etree import ElementTree

import dbx
from db import APP_DATA_DIR
from server.terminal import journal
from server.terminal.analytics import number

BASE = "https://cbu.uz"
MONTHS = {name:i+1 for i,name in enumerate(("января","февраля","марта","апреля","мая","июня","июля","августа","сентября","октября","ноября","декабря"))}
MONTHS.update({name:i+1 for i,name in enumerate(("январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"))})
BANK_NAMES = {
    "агробанк":"AGBA", "узпромстройбанк":"SQBN", "банкразвитиябизнеса":"BRBN", "кишлоккурилишбанк":"BRBN",
    "микрокредитбанк":"MCBA", "алокабанк":"ALKB", "туронбанк":"TNBN", "ипотекабанк":"IPTB",
    "хамкорбанк":"HMKB", "ипакйулибанк":"IPKY", "ориентфинансбанк":"ORFI", "даврбанк":"DRBK",
    "инвестфинансбанк":"INFB", "трастбанк":"TRSB", "тенгебанк":"TNGB", "октобанк":"OCBK",
    "равнакбанк":"OCBK", "универсалбанк":"UNVB", "гарантбанк":"GRBK", "савдогарбанк":"GRBK",
    "узсаноаткурилишбанк":"SQBN",
}
SDMX_CATALOGUE = BASE + "/en/statistics/e-gdds/data/"
_probing_format = ContextVar('cbu_probing_format', default=False)


class FormatChanged(ValueError):
    pass


def reject(source, reason):
    if not _probing_format.get():
        journal.emit("load_format_changed", message=f"CBU: {reason}", source_url=source)
    raise FormatChanged(reason)


def norm(value):
    text=str(value or '').lower().translate(str.maketrans({'ё':'е','ў':'у','қ':'к','ғ':'г','ҳ':'х'}))
    key=re.sub(r"[^а-яa-z0-9]", "", text)
    return {'банкноми':'наименованиебанка','жами':'всего','жамикредитлар':'всегокредиты',
            'жамидепозитлар':'всегодепозиты','жисмонийшахслар':'физическиелица',
            'юридикшахслар':'юридическиелица'}.get(key,key)


def parse_bank_rows(rows, kind, source_url, *, percent_points=False):
    title=" ".join(str(c) for row in rows[:12] for c in row if c is not None)
    match=re.search(r"(?:на|состоянию на)\s+(\d{1,2})\s+([а-я]+)\s+(20\d{2})",title.lower())
    uzbek=re.search(r'(20\d{2})\s+йил\s+(\d{1,2})\s+([а-я]+)',title.lower())
    if match and match[2] in MONTHS:
        day=date(int(match[3]),MONTHS[match[2]],int(match[1])).isoformat()
    elif uzbek and uzbek[3] in MONTHS:
        day=date(int(uzbek[1]),MONTHS[uzbek[3]],int(uzbek[2])).isoformat()
    else:reject(source_url,"Missing observation date")
    if "млрд" not in title.lower():reject(source_url,"Unrecognised monetary unit")
    header_at=next((i for i,row in enumerate(rows[:20]) if any("наименованиебанка" in norm(c) for c in row)),None)
    if header_at is None:reject(source_url,"Missing bank-name header")
    header=rows[header_at]
    def col(prefix):
        # Published older templates contain these spelling variants. Keep
        # matching explicit so an unrelated new column still fails closed.
        prefixes={"кредитныйпортфель":("кредитныйпортфель","кредитыйпортфель"),
                  "всегодепозиты":("всегодепозиты","всегодерозиты")}.get(prefix,(prefix,))
        found=next((i for i,c in enumerate(header) if norm(c).startswith(prefixes)),None)
        if found is None:reject(source_url,"Missing column: "+prefix)
        return found
    name_col=col("наименованиебанка")
    if kind=="npl":
        columns={"loans_bn":col("кредитныйпортфель"),"npl_bn":col("изнихпроблемныекредиты"),"npl_pct":col("доля")}
    elif kind=="main":
        columns={f"{field}_bn":col(prefix) for field,prefix in (("assets","актив"),("loans","кредит"),("equity","капитал"),("deposits","депозит"))}
        for field in ("assets","loans","equity","deposits"):
            idx=columns[field+"_bn"]+1
            if header_at+1>=len(rows) or idx>=len(rows[header_at+1]) or "доля" not in str(rows[header_at+1][idx]).lower():reject(source_url,"Missing market-share subheader")
            columns[field+"_share_pct"]=idx
    elif kind=="structure":
        columns={"loans_bn":col("всегокредиты"),"deposits_bn":col("всегодепозиты")}
        sub=rows[header_at+1]
        for field in ("loans","deposits"):
            start=columns[field+"_bn"]
            for offset,part,prefix in ((1,"household","физическ"),(2,"company","юридическ")):
                if start+offset>=len(sub) or not norm(sub[start+offset]).startswith(prefix):reject(source_url,"Missing household/corporate subheader")
                columns[f"{part}_{field}_bn"]=start+offset
    else:raise ValueError("Unknown CBU bank table")
    output=[];totals={}
    for row in rows[header_at+1:]:
        if len(row)<=max(columns.values()):continue
        name=row[name_col]
        total=any(norm(c)=="всего" for c in row[:name_col+1])
        if not name and not total:continue
        if not total and not isinstance(row[0],(int,float)):continue
        item={"name":str(name or "Сектор"),"ticker":BANK_NAMES.get(norm(name)),"date":day,"source_url":source_url}
        for field,idx in columns.items():
            raw=row[idx];v=number(str(raw).replace("\xa0","").replace(" ","").replace(",",".").replace("%",""))
            if v is None:
                if total or str(raw or '').strip() not in {'','-','—','–'}:
                    reject(source_url,"Missing or invalid bank value: "+str(name))
                item[field]=None
                continue
            if v<0 and not (kind=='main' and field.startswith('equity_')):
                if kind=='structure' and field.startswith(('household_','company_')) and not total:
                    # Some published residuals are negative (including tiny
                    # rounding residues). Retain evidence and withhold only
                    # this invalid component, not every other bank's figures.
                    item[field]=None
                    item.setdefault('quality_issues',[]).append({'field':field,'original_value':v,'code':'NEGATIVE_COMPONENT'})
                    continue
                reject(source_url,"Negative bank value: "+str(name))
            item[field]=v if not field.endswith("pct") or percent_points or isinstance(raw,str) and "%" in raw else v*100
        if kind=="npl":
            if (item['npl_bn'] is not None and item['loans_bn'] is not None and item["npl_bn"]>item["loans_bn"]
                    or item['npl_pct'] is not None and item["npl_pct"]>100):reject(source_url,"Invalid NPL units")
            item["npl_flag"]=item["npl_pct"]>5 if item['npl_pct'] is not None else None
        if total:totals=item
        else:output.append(item)
    if len(output)<10 or not totals:reject(source_url,"Incomplete bank table")
    if len({norm(r["name"]) for r in output})!=len(output):reject(source_url,"Duplicate bank name")
    return {"kind":kind,"date":day,"unit":"billion UZS","source_url":source_url,"rows":output,"sector":totals}


def parse_bank_page(html, kind, source_url):
    """Read the official HTML table when its workbook is absent or unusable.

    Keep merged-cell positions, explicit observation dates and stated units.
    A publication timestamp never supplies the observation date.
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    tables = [t for t in soup.select('table') if 'наименованиебанка' in norm(t.get_text(' ', strip=True))]
    if len(tables) != 1:
        reject(source_url, 'Expected one bank observation table')
    table = tables[0]
    heading = soup.find('h1')
    container = table.find_parent(class_='detail-text') or table.parent
    units = ' '.join(str(t) for t in container.find_all(string=True)
                     if not t.find_parent('table') and 'млрд' in str(t).lower())
    grid = {}
    for row_index, tr in enumerate(table.select('tr')):
        column = 0
        for cell in tr.find_all(['td', 'th'], recursive=False):
            while (row_index, column) in grid:
                column += 1
            value = cell.get_text(' ', strip=True)
            if column == 0 and re.fullmatch(r'\d+', value):
                value = int(value)
            try:
                rowspan, colspan = int(cell.get('rowspan', 1)), int(cell.get('colspan', 1))
            except (TypeError, ValueError):
                reject(source_url, 'Invalid table span')
            if not 1 <= rowspan <= 100 or not 1 <= colspan <= 100:
                reject(source_url, 'Invalid table span')
            for dr in range(rowspan):
                for dc in range(colspan):
                    grid[row_index + dr, column + dc] = value if dr == dc == 0 else None
            column += colspan
    if not grid:
        reject(source_url, 'Empty HTML table')
    height = max(r for r, _ in grid) + 1
    width = max(c for _, c in grid) + 1
    rows = [[heading.get_text(' ', strip=True) if heading else '', units]]
    rows += [[grid.get((r, c)) for c in range(width)] for r in range(height)]
    title = ' '.join(str(c) for row in rows[:12] for c in row if c is not None).lower()
    dates = {(int(y), MONTHS.get(m), int(d)) for d, m, y in
             re.findall(r'(?:на|состоянию на)\s+(\d{1,2})\s+([а-я]+)\s+(20\d{2})', title)}
    if len(dates) > 1:
        reject(source_url, 'Conflicting observation dates')
    return {**parse_bank_rows(rows, kind, source_url, percent_points=True), 'source_format': 'html'}


def _read_month_table(html, kind, page, expected_month):
    import requests
    import openpyxl
    from bs4 import BeautifulSoup

    def check(payload):
        if expected_month and payload['date'][:7] != expected_month:
            raise FormatChanged('Observation date differs from requested month')
        return payload

    errors = []
    token = _probing_format.set(True)
    try:
        sheet = next((a.get('href') for a in BeautifulSoup(html, 'html.parser').select('a[href]')
                      if '.xlsx' in a.get('href', '').lower()), None)
        if sheet:
            source = urljoin(BASE, sheet)
            try:
                if not source.startswith(BASE + '/'):
                    raise FormatChanged('Unexpected attachment host')
                response = requests.get(source, timeout=30)
                response.raise_for_status()
                workbook = openpyxl.load_workbook(io.BytesIO(response.content), data_only=True, read_only=True)
                try:
                    parser = parse_bank_rows if kind in {'npl', 'main', 'structure'} else parse_sector_rows
                    return check(parser(list(workbook.active.values), kind, source))
                finally:
                    workbook.close()
            except Exception as exc:
                errors.append(f'XLSX: {type(exc).__name__}: {exc}')
        else:
            errors.append('No XLSX attachment')
        if kind in {'npl', 'main', 'structure'}:
            try:
                payload = check(parse_bank_page(html, kind, page))
                payload['attachment_issues'] = errors
                return payload
            except FormatChanged as exc:
                errors.append(f'HTML: {exc}')
    finally:
        _probing_format.reset(token)
    reject(page, '; '.join(errors))


def parse_sdmx(content, source_url):
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():reject(source_url,"Unexpected XML declaration")
    try:root=ElementTree.fromstring(content)
    except ElementTree.ParseError:reject(source_url,"Invalid SDMX XML")
    local=lambda node:node.tag.split("}")[-1]
    if local(root) not in {"StructureSpecificData","GenericData"}:reject(source_url,"Not an SDMX dataset")
    out=[]
    for series in root.iter():
        if local(series)!="Series":continue
        dimensions=dict(series.attrib)
        for key in series:
            if local(key)=="SeriesKey":
                dimensions.update({value.attrib.get("id"):value.attrib.get("value") for value in key})
        indicator=dimensions.get("INDICATOR")
        if not indicator:reject(source_url,"SDMX indicator dimension missing")
        for obs in series:
            if local(obs)!="Obs":continue
            period=obs.attrib.get("TIME_PERIOD");value=obs.attrib.get("OBS_VALUE")
            for child in obs:
                if local(child)=="ObsDimension":period=child.attrib.get("value")
                elif local(child)=="ObsValue":value=child.attrib.get("value")
            parsed=number(value)
            if not period or parsed is None:continue
            out.append({"indicator":indicator,"period":period,"value":parsed,"dimensions":dimensions,"source_url":source_url})
    if not out:reject(source_url,"Empty SDMX dataset")
    return out


def schema(c):
    c.execute("CREATE TABLE IF NOT EXISTS terminal_cbu (kind TEXT NOT NULL, period TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(kind,period))")
    c.commit()


def connect():
    path=Path(os.getenv("CBU_DATA_DB") or APP_DATA_DIR/"cbu_terminal.sqlite3")
    path.parent.mkdir(parents=True,exist_ok=True)
    c=dbx.connect(str(path));dbx.ensure_schema(c,"terminal-cbu-v1",schema);return c


def save(kind,period,payload):
    c=connect()
    try:
        c.execute("INSERT INTO terminal_cbu(kind,period,payload) VALUES (?,?,?) ON CONFLICT(kind,period) DO UPDATE SET payload=excluded.payload",(kind,period,json.dumps(payload)))
        c.commit()
    finally:c.close()


def latest(kind):
    c=connect()
    try:
        row=c.execute("SELECT payload FROM terminal_cbu WHERE kind=? ORDER BY period DESC LIMIT 1",(kind,)).fetchone()
        return json.loads(row["payload"]) if row else None
    finally:c.close()


def ranked_banks(dataset):
    """Rank within the complete dated CBU table, including unlisted banks."""
    rows=dataset.get('rows',[])
    amounts=[value for row in rows if (value:=number(row.get('assets_bn'))) is not None and value>=0]
    return [{**row,'assets_rank':1+sum(other>value for other in amounts) if (value:=number(row.get('assets_bn'))) is not None and value>=0 else None,
             'rank_population':len(amounts)} for row in rows]


def monthly_bank_history(ticker):
    """Only published observations; no interpolation for absent months."""
    c=connect()
    try:
        datasets=[json.loads(row['payload']) for row in c.execute(
            "SELECT payload FROM terminal_cbu WHERE kind='main' AND period>='2020-01-01' ORDER BY period")]
    finally:c.close()
    return [row for dataset in datasets for row in ranked_banks(dataset) if row.get('ticker')==ticker]


def context():
    rates=latest("rates") or []
    # IMF ECOFIN: FITD_NC_WA_PA = term deposits, national currency,
    # weighted average, percent per annum. Other series keep their dimensions.
    deposits=[r for r in rates if r["indicator"]=="FITD_NC_WA_PA" and r["dimensions"].get("FREQ")=="M"]
    deposit=max(deposits,key=lambda r:r["period"],default=None)
    banks={}
    sector={}
    for kind in ("npl","main","structure"):
        dataset=latest(kind)
        if not dataset:continue
        sector[kind]=dataset.get("sector")
        for row in ranked_banks(dataset) if kind=='main' else dataset['rows']:
            if row["ticker"]:banks.setdefault(row["ticker"],{})[kind]=row
    return {"banks":banks,"sector":sector,"deposit":deposit,"fsi":latest("fsi") or [], "inflation":annual_inflation(latest("inflation") or []),
            "sector_series":{kind:latest(kind) for kind in ("capital","liquidity","profitability","industry") if latest(kind)}}


def discover_sdmx(html):
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    soup = BeautifulSoup(html, 'html.parser')
    result = {}
    for row in soup.select('tr'):
        title = row.get_text(' ', strip=True).lower()
        kind = 'fsi' if 'financial soundness indicators' in title else 'rates' if 'interest rates' in title else None
        if not kind:
            continue
        links = [urljoin(BASE, a['href']) for a in row.select('a[href]')
                 if urlparse(a['href']).path.lower().endswith('.xml')]
        if len(links) != 1 or urlparse(links[0]).hostname != 'cbu.uz' or not links[0].startswith('https://'):
            reject(SDMX_CATALOGUE, 'Missing or untrusted SDMX link for ' + kind)
        result[kind] = links[0]
    if set(result) != {'rates', 'fsi'}:
        reject(SDMX_CATALOGUE, 'Expected SDMX datasets absent')
    return result


def sync_month(year=None,month=None,*,with_sdmx=True,kinds=None):
    import requests
    from bs4 import BeautifulSoup
    url=BASE+"/ru/statistics/bankstats/"
    if year and month:url+=f"?year={int(year)}&month={int(month):02d}&set_filter=Y"
    response=requests.get(url,timeout=20);response.raise_for_status()
    soup=BeautifulSoup(response.text,"html.parser")
    titles={"npl":"проблемных кредитах коммерческих банков","main":"основных показателях коммерческих банков","structure":"кредитах и депозитах коммерческих банков"}
    titles.update({"capital":"достаточность собственного капитала банковского сектора", "liquidity":"динамика ликвидности банковского сектора", "profitability":"показатели доходности банковского сектора", "industry":"кредитах коммерческих банков в разрезе отраслей"})
    if kinds is not None:
        if not set(kinds)<=titles.keys():raise ValueError('Unknown CBU source kind')
        titles={k:v for k,v in titles.items() if k in kinds}
    result={"loaded":[],"errors":[]}
    for kind,title in titles.items():
        links=[a for a in soup.select('a[href]') if title in a.get_text(' ',strip=True).lower()]
        def matching_observation(anchor):
            text=anchor.get_text(' ',strip=True).lower()
            match=re.search(r'(?:по состоянию на\s+)?\b(\d{1,2})\s+([а-я]+)\s+(20\d{2})',text)
            return bool(match and int(match[3])==year and MONTHS.get(match[2])==month)
        if year and month:links.sort(key=matching_observation,reverse=True)
        link=links[0].get('href') if links else None
        if not link:
            result["errors"].append(f"{kind}: no published table");continue
        page=urljoin(BASE,link)
        try:
            detail=requests.get(page,timeout=20);detail.raise_for_status()
            expected = f'{int(year):04d}-{int(month):02d}' if year and month else None
            payload = _read_month_table(detail.text, kind, page, expected)
            save(kind,payload["date"],payload);result["loaded"].append(kind)
        except Exception as exc:result["errors"].append(f"{kind}: {type(exc).__name__}: {exc}")
    if with_sdmx:
        try:
            catalogue = requests.get(SDMX_CATALOGUE, timeout=20)
            catalogue.raise_for_status()
            links = discover_sdmx(catalogue.text)
        except Exception as exc:
            links = {}
            result['errors'].append(f'SDMX catalogue: {type(exc).__name__}')
        for kind,source in links.items():
            try:
                response=requests.get(source,timeout=30)
                if response.status_code!=200:reject(source,f"SDMX HTTP {response.status_code}")
                records=parse_sdmx(response.content,source)
                save(kind,max(r["period"] for r in records),records);result["loaded"].append(kind)
            except Exception as exc:result["errors"].append(f"{kind}: {type(exc).__name__}: {exc}")
    if with_sdmx:
        try:sync_inflation();result["loaded"].append("inflation")
        except Exception as exc:result["errors"].append(f"inflation: {type(exc).__name__}")
    return result


INFLATION_URL=BASE+'/en/monetary-policy/annual-inflation/indicators/'


def parse_inflation(rows,source_url):
    from datetime import datetime
    header_at=next((i for i,row in enumerate(rows) if any('Headline inflation compared to the same month' in str(c) for c in row)),None)
    if header_at is None:reject(source_url,'Inflation headline header missing')
    header=rows[header_at]
    col=next(i for i,c in enumerate(header) if 'Headline inflation compared to the same month' in str(c))
    records=[]
    for row in rows[header_at+1:]:
        if len(row)<=col or not re.fullmatch(r'\d{2}\.\d{2}\.\d{4}',row[0]):continue
        observed=datetime.strptime(row[0],'%d.%m.%Y').date()
        value=number(row[col].replace(',','.'))
        if value is None or value<=-100:reject(source_url,'Invalid inflation observation')
        records.append({'period':observed.strftime('%Y-%m'),'value':value,'source_url':source_url})
    if not records:reject(source_url,'No inflation observations')
    return records


def annual_inflation(records):
    return {r['period'][:4]:r['value'] for r in review_inflation(records) if r['period'].endswith('-12')}


def review_inflation(records):
    reviews=json.loads(Path(__file__).with_name('inflation_reviews.json').read_text())['reviews']
    result=[]
    for row in records:
        review=next((r for r in reviews if r['period']==row['period'] and r['superseded_value']==row['value']
                     and row.get('source_url','').split('?')[0]==INFLATION_URL),None)
        result.append({**row,**review,'original_value':row['value'],'original_source_url':row['source_url']} if review else row)
    return result


def sync_inflation():
    import requests
    from bs4 import BeautifulSoup
    # CBU's navigation truncates older pages. Advance the documented page
    # parameter until no older observations appear; repeated last pages stop.
    records = {}
    for page in range(1, 21):
        url = INFLATION_URL + (f'?lists_list_elements_983=page-{page}&mobile=Y' if page > 1 else '')
        response = requests.get(url, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        table = next((t for t in soup.select('table') if 'Headline inflation compared to the same month' in t.get_text()), None)
        if table is None:
            reject(url, 'Inflation table missing')
        rows = [[c.get_text(' ', strip=True) for c in row.select('th,td')] for row in table.select('tr')]
        if not any(row and re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', row[0]) for row in rows):
            break
        observed = parse_inflation(rows, url)
        new = [r for r in observed if r['period'] not in records]
        if not new:
            break
        records.update({r['period']: r for r in new})
        if min(records) <= '2020-01':
            break
    if not records:
        reject(INFLATION_URL, 'No inflation observations')
    merged = {r['period']: r for r in latest('inflation') or []}
    merged.update(records)
    payload = review_inflation(sorted(merged.values(), key=lambda r:r['period']))
    save('inflation', max(merged), payload)
    return payload


def parse_sector_rows(rows,kind,source_url):
    """Published spreadsheet units differ: capital/liquidity ratios are fractions,
    profitability ratios are already percentage points. Never infer from size.
    """
    from datetime import datetime
    columns={};header_at=None
    for i,row in enumerate(rows[:8]):
        for j,cell in enumerate(row):
            match=re.search(r'\b(\d{2}\.\d{2}\.\d{4})\b',str(cell or ''))
            if match:columns[j]=datetime.strptime(match[1],'%d.%m.%Y').date().isoformat();header_at=i
        if columns:break
    if not columns and kind=='industry':
        # The earliest table has one date in its title, followed by amount
        # and percentage headers rather than two comparison-date columns.
        title=' '.join(str(c) for r in rows[:3] for c in r if c is not None)
        match=re.search(r'по состоянию на (\d{1,2}) ([а-я]+) (20\d{2})',title.lower())
        header_at=next((i for i,r in enumerate(rows[:8]) if any('сумма' in str(c).lower() and 'млрд' in str(c).lower() for c in r)),None)
        if match and match[2] in MONTHS and header_at is not None:
            index=next(j for j,c in enumerate(rows[header_at]) if 'млрд' in str(c).lower())
            columns[index]=date(int(match[3]),MONTHS[match[2]],int(match[1])).isoformat()
    if not columns:reject(source_url,'Sector observation headers missing')
    if kind not in {'capital','liquidity','profitability','industry'}:raise ValueError('Unknown sector table')
    records=[];metrics={};day=max(columns.values())
    known={'коэффициентдостаточностикапитала':'capital_adequacy',
           'отношениечистойприбыликсовокупномукапиталупобалансуroe':'roe',
           'чистаяпроцентнаямаржаксовокупнымактивам':'nim'}
    for row in rows[header_at+1:]:
        name=str(row[0] or '').strip()
        if not name or not any(number(row[j]) is not None for j in columns if j<len(row)):continue
        percent=(kind=='liquidity' and 'млрд' not in name) or (kind=='capital' and 'коэффициент' in name.lower()) or (kind=='profitability' and (name.startswith('Отношение') or name.startswith('Чистая процентная маржа')))
        factor=100 if percent and kind in {'capital','liquidity'} else 1
        observations={period:(number(row[j])*factor if j<len(row) and number(row[j]) is not None else None) for j,period in columns.items()}
        record={'name':name,'unit':'%' if percent else 'billion UZS','observations':observations}
        if kind=='industry':
            record['share_pct']={period:number(row[j+1])*100 if j+1<len(row) and number(row[j+1]) is not None else None for j,period in columns.items()}
        records.append(record)
        if norm(name) in known:metrics[known[norm(name)]]={'value':observations[day],'date':day,'name':name,'unit':record['unit'],'source_url':source_url}
    if not records:reject(source_url,'No sector observations')
    return {'kind':kind,'date':day,'source_url':source_url,'rows':records,'metrics':metrics}
