"""Preserve physical gaps between PDF/OCR words without a fixed text grid."""
import csv
import io
from statistics import median


def word_lines(words):
    words=[w for w in words if str(w.get('text','')).strip() and w['x1']>w['x0'] and w['bottom']>w['top']]
    if not words:
        return ''
    height=median(w['bottom']-w['top'] for w in words)
    glyph=median((w['x1']-w['x0'])/len(w['text']) for w in words)
    rows=[]
    for word in sorted(words,key=lambda w:((w['top']+w['bottom'])/2,w['x0'])):
        center=(word['top']+word['bottom'])/2
        if rows and abs(center-median((w['top']+w['bottom'])/2 for w in rows[-1]))<=height*.45:
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


def tsv_text(value):
    words=[]
    for row in csv.DictReader(io.StringIO(value),delimiter='\t',quoting=csv.QUOTE_NONE):
        if row.get('level')!='5' or not (row.get('text') or '').strip():
            continue
        x,y,width,height=(float(row[k]) for k in ('left','top','width','height'))
        words.append({'text':row['text'],'x0':x,'x1':x+width,'top':y,'bottom':y+height})
    return word_lines(words)
