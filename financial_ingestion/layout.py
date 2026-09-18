"""Preserve physical gaps between PDF/OCR words without a fixed text grid."""
import csv
import io
from statistics import median


def word_lines(words):
    words=[w for w in words if str(w.get('text','')).strip() and w['x1']>w['x0'] and w['bottom']>w['top']]
    if not words:
        return ''
    glyph=median((w['x1']-w['x0'])/len(w['text']) for w in words)
    rows=[]
    for word in sorted(words,key=lambda w:((w['top']+w['bottom'])/2,w['x0'])):
        # OCR boxes follow glyph shapes: descenders, capitals and bold totals
        # on the same baseline can have different vertical centres. Their
        # vertical overlap is a more reliable row signal than centre distance.
        previous = rows[-1] if rows else []
        top = median(w['top'] for w in previous) if previous else 0
        bottom = median(w['bottom'] for w in previous) if previous else 0
        overlap = min(word['bottom'], bottom) - max(word['top'], top)
        if rows and overlap >= .35 * min(word['bottom']-word['top'], bottom-top):
            rows[-1].append(word)
        else:
            rows.append([word])
    lines=[]
    for row in rows:
        row.sort(key=lambda w:w['x0'])
        line=row[0]['text']
        for previous,current in zip(row,row[1:]):
            # A word's printed width matters. A fixed character grid expands
            # spaces inside one number or collapses gaps between year columns.
            gap=current['x0']-previous['x1']
            line+=('  ' if gap>glyph*1.4 else ' ')+current['text']
        lines.append(line)
    return '\n'.join(lines)


def tsv_words(value, *, top_offset=0, core=None):
    """Restore page coordinates; an overlap belongs to exactly one tile core."""
    words=[]
    for row in csv.DictReader(io.StringIO(value),delimiter='\t',quoting=csv.QUOTE_NONE):
        if row.get('level')!='5' or not (row.get('text') or '').strip():
            continue
        x,y,width,height=(float(row[k]) for k in ('left','top','width','height'))
        y += top_offset
        if core is not None and not core[0] <= y + height / 2 < core[1]:
            continue
        words.append({'text':row['text'],'x0':x,'x1':x+width,'top':y,'bottom':y+height})
    return words


def tsv_text(value):
    return word_lines(tsv_words(value))
