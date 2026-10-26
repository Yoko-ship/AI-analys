"""Conservative interpretation of the source's typed fields and resolutions.

Voting questions and publication moderation never prove a shareholder decision.
Amounts filed in thousands of UZS remain totals, not per-security income.
"""
import re

DIVIDEND = re.compile(r'dividend|дивиденд', re.I)
APPROVAL = re.compile(r'выплатить|направить.{0,120}дивиденд|дивиденд.{0,120}утверд|дивиденд.{0,100}тўлансин|дивиденд.{0,100}йўналтирилсин|тақсимлансин|taqsimlansin|dividend.{0,100}to[‘\'’`]?lansin|approve.{0,60}dividend|pay.{0,60}dividend', re.I | re.S)
NEGATIVE = re.compile(r'не\s+(?:выплачивать|распределять|утверждать)|тўланмасин|to[‘\'’`]?lanmasin|not\s+(?:pay|distribute|approve)', re.I)


def period_from(text):
    # A reporting year is explicit; publication and legislative-reference years
    # are not reporting periods. Multiple periods require separate review.
    patterns = [r'(20\d{2})\s*[-–]?\s*(?:йил|yil)[^.!?]{0,55}(?:якун|yakun|соф фойда|sof foyda)',
                r'(?:за|for)\s+(20\d{2})\s*(?:год|year)?', r'(20\d{2})\s*год[^.!?]{0,45}(?:прибыл|дивиденд)']
    years = {year for pattern in patterns for year in re.findall(pattern, text, re.I)}
    if len(years) != 1 or re.search(r'квартал|chorak|чорак|полугод|half.year|quarter', text, re.I):
        return None
    return next(iter(years))


def enrich(document, raw):
    from corporate_events import day, number, tr
    d = document
    code = d['code']
    d['evidence'] = []
    d['payment'] = None
    d['capitalization_disclosed'] = False
    d['summary'] = dict(d['title'])
    d['priority_reason'] = 'disclosure_type'
    if code == 6:
        resolutions = [str(row.get('decisions_wording') or '') for row in raw.get('facts_decisions_wording', []) if isinstance(row, dict)]
        dividend_rows = [text for text in resolutions if DIVIDEND.search(text)]
        d['evidence'] = [re.sub(r'\s+', ' ', text.replace('\\r\\n', ' ')).strip()[:3000] for text in (dividend_rows or resolutions)[:3]]
        # Only the adopted resolutions field participates, never agenda questions.
        approved = [text for text in dividend_rows if APPROVAL.search(text) and not NEGATIVE.search(text)]
        if approved and d['decision_date']:
            text = ' '.join(approved)
            d.update(stage='approved', category='dividends', confidence='confirmed', priority=1,
                     priority_provisional=False, priority_reason='dividend_resolution', period=period_from(text))
            d['title'] = tr('Акционеры утвердили распределение дивидендов', 'Shareholders approved dividend distribution', 'Aksiyadorlar dividend taqsimotini tasdiqladi')
            d['capitalization_disclosed'] = bool(re.search(r'капитализац|kapitalizats|capitali[sz]', text, re.I))
            d['summary'] = tr('Решение раскрыто в протоколе. Суммы на одну бумагу и даты выплат показываются только при явном указании.',
                              'The published resolutions confirm distribution. Per-security amounts and payment dates require explicit disclosure.',
                              'Taqsimot qarori e’lon qilingan. Har bir qog‘ozga summa va to‘lov sanalari faqat aniq ko‘rsatilganda beriladi.')
        elif resolutions:
            # Administrative changes do not acquire dividend priority simply
            # because all shareholder decisions share public code 6.
            material = bool(re.search(r'капитал|kapital|эмисси|emissi|credit|кредит|loan|акци|aksiya|share', ' '.join(resolutions), re.I))
            d.update(priority=1 if material else 2, priority_reason='resolution_content')
            d['summary'] = tr('Опубликованы решения акционеров. Формулировки приведены в документах события.',
                              'Shareholder resolutions published. Their original wording is available in the event documents.',
                              'Aksiyadorlar qarorlari e’lon qilindi. Asl matn voqea hujjatlarida mavjud.')
    if code == 32:
        d['decision_date'] = day(raw.get('date_solution')) or d['decision_date']
        if d['decision_date'] and day(d['published_at']) and d['decision_date'] > day(d['published_at']):
            d['decision_date'] = None
        d['event_date'] = d['decision_date']
        kind = 'other_securities' if any(a['security']=='bond' for a in d['amounts']) else 'common_shares'
        if d['amounts']:
            d['payment_start'] = day(raw.get('start_date_'+kind))
            d['payment_end'] = day(raw.get('end_date_'+kind))
        else:
            d['confidence'] = 'review'
    if code == 42:
        d['payment_start'] = day(raw.get('payment_start_date'))
        fields = {'calculated':'overall_calculated_sum', 'paid':'overall_paid_sum', 'paid_percent':'overall_paid_percent', 'debt':'overall_debt_sum', 'debt_percent':'overall_debt_percent'}
        payment = {key:number(raw.get(field)) for key,field in fields.items()}
        d['payment'] = {**payment, 'unit':'thousand_uzs'}
        total, paid, debt, percent = (payment[k] for k in ('calculated','paid','debt','paid_percent'))
        coherent = (all(v is not None for v in (total,paid,debt,percent)) and total > 0 and paid <= total and 0 <= percent <= 100
                    and abs(paid + debt - total) <= .01 and abs(paid / total * 100 - percent) <= .01)
        if coherent and paid == total and debt == 0 and percent == 100:
            d.update(stage='paid', confidence='confirmed', priority_provisional=False, priority_reason='reported_payment_totals')
            d['title'] = tr('Эмитент сообщил о полной выплате дивидендов', 'Issuer reported full dividend payment', 'Emitent dividendlar to‘liq to‘langanini ma’lum qildi')
        elif coherent and 0 < paid < total:
            d.update(stage='paying', confidence='confirmed', priority_reason='reported_payment_totals')
            d['title'] = tr('Дивиденды выплачены частично', 'Dividends partially paid', 'Dividendlar qisman to‘landi')
        else:
            d['confidence'] = 'review'
        d['evidence'] = [str(raw['non_payment_explanation'])[:2000]] if raw.get('non_payment_explanation') else []
        d['summary'] = tr('Начислено и выплачено — общие суммы в тысячах сум, по раскрытию эмитента.',
                          'Accrued and paid figures are issuer-reported totals in thousands of UZS.',
                          'Hisoblangan va to‘langan qiymatlar — emitent ko‘rsatgan jami summalar, ming so‘mda.')
    if code == 41:
        d['priority_provisional'] = d['confidence'] != 'confirmed'
    # Keep the public field names intact. Never infer entitlement or an ex-date.
    for field in ('dividend_record_date', 'dividend_entitlement_date'):
        if raw.get(field):
            d['record_date'] = day(raw[field])
    d['period'] = d.get('period') or period_from(str(raw.get('dividend_period') or raw.get('reporting_period') or ''))
    if d['payment_start'] and d['payment_end'] and d['payment_start'] > d['payment_end']:
        d.update(payment_start=None, payment_end=None, confidence='review')
    return d
