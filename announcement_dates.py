"""Meeting timing from explicit scheduling paragraphs, never registry dates.

Portal meeting metadata can contain the upload time. Keep a quoted paragraph
with every body-derived date, and refuse conflicting dates instead of guessing.
"""
import re
from datetime import date

MONTHS = {
    'январ': 1, 'yanvar': 1, 'january': 1, 'феврал': 2, 'fevral': 2, 'february': 2,
    'март': 3, 'mart': 3, 'march': 3, 'апрел': 4, 'aprel': 4, 'april': 4,
    'мая': 5, 'may': 5, 'июн': 6, 'iyun': 6, 'june': 6,
    'июл': 7, 'iyul': 7, 'july': 7, 'август': 8, 'avgust': 8, 'august': 8,
    'сентябр': 9, 'sentabr': 9, 'sentyabr': 9, 'september': 9,
    'октябр': 10, 'oktabr': 10, 'oktyabr': 10, 'october': 10,
    'ноябр': 11, 'noyabr': 11, 'november': 11, 'декабр': 12, 'dekabr': 12, 'december': 12,
}
MEETING = re.compile(r"собрани|yig'il|йиғил|meeting", re.I)
SCHEDULE = re.compile(r"состоится|o'tkazil(?:adi|ishi)|bo'lib\s+o't|ўтказил(?:ади|иши)|бўлиб\s+ўт|will\s+be\s+held|to\s+be\s+held", re.I)
EXCLUDE = re.compile(r"наблюдательн|кузатув|kuzatuv|supervisory|чоп этилган|previously announced|ранее опубликован|ўтказилган|o'tkazilgan|реестр|reyestr|reestr|ro'yxat|р[ўу]й[хҳ]ат|регистрац|registration|register|уведомлени[яй]\s+акционер", re.I)


def _dates(text):
    found = set()
    def add(y, m, d):
        try:
            found.add(date(int(y), int(m), int(d)).isoformat())
        except (ValueError, TypeError):
            pass
    for y, m, d in re.findall(r'\b(20\d{2})-(\d{2})-(\d{2})\b', text):
        add(y, m, d)
    for d, m, y in re.findall(r'\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b', text):
        add(y, m, d)
    for stem, month in MONTHS.items():
        for d, y in re.findall(rf'\b(\d{{1,2}})\s*[- ]\s*{stem}\w*\s+(20\d{{2}})\b', text):
            add(y, month, d)
        for d, y in re.findall(rf'\b{stem}\w*\s+(\d{{1,2}}),?\s+(20\d{{2}})\b', text):
            add(y, month, d)
        for y, d in re.findall(rf'\b(20\d{{2}})\s*[- ]?\s*(?:yil|йил)\w*\s+(\d{{1,2}})\s*[- ]\s*{stem}\w*\b', text):
            add(y, month, d)
    return found


def meeting_schedule(detail):
    candidates = {}
    for paragraph in detail.get('content', []):
        original = re.sub(r'\s+', ' ', paragraph.get('text', '')).strip()
        text = re.sub(r"[‘’ʻʼ`ъ]", "'", original.casefold()).replace('«', '').replace('»', '')
        if not MEETING.search(text) or not SCHEDULE.search(text) or EXCLUDE.search(text):
            continue
        for day in _dates(text):
            candidates.setdefault(day, []).append(original)
    if len(candidates) != 1:
        return {'date': None, 'time': None, 'evidence': None, 'ambiguous': len(candidates) > 1}
    day, paragraphs = next(iter(candidates.items()))
    times = set()
    for paragraph in paragraphs:
        for h, m, suffix in re.findall(r'(?:soat|соат|\bв|\bat)\s*(\d{1,2})\s*[:. -]\s*(\d{2})\s*([ap]\.?m\.?)?', paragraph, re.I):
            hour = int(h)
            if suffix:
                if not 1 <= hour <= 12:
                    continue
                hour = hour % 12 + (12 if suffix.lower().startswith('p') else 0)
            if hour < 24 and int(m) < 60:
                times.add(f'{hour:02d}:{m}')
    return {'date': day, 'time': next(iter(times)) if len(times) == 1 else None,
            'evidence': paragraphs[0][:1800], 'ambiguous': False}
