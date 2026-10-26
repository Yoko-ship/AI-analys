"""Source-field contracts for all 46 public disclosure forms.

The priority policy is editorial attention, not a credit rating or price forecast.
Unknown enumerations and monetary units remain as filed. Publication moderation,
contact fields and signatures never supply evidence of the underlying event.
"""
from decimal import Decimal, InvalidOperation
import re
import math

VERSION = 3


def words(ru, en, uz):
    return dict(ru=ru, en=en, uz=uz)


# A field's unit is explicit. Source amounts with an undocumented unit are not
# combined with another amount or silently treated as UZS per security.
FIELDS = {}
def field(key, kind, ru, en, uz):
    FIELDS[key] = (kind, words(ru, en, uz))

for key,kind,ru,en,uz in [
 ('full_name_before_change','text','Прежнее название','Previous name','Oldingi nom'),
 ('location_before_change','text','Прежний адрес','Previous address','Oldingi manzil'),
 ('reorganization_method','text','Способ реорганизации (код источника)','Reorganisation method (source code)','Qayta tashkil etish usuli (manba kodi)'),
 ('order_request','text','Порядок обращений','Request procedure','Murojaat tartibi'),
 ('description_changes','text','Содержание изменений','Changes disclosed','O‘zgarishlar mazmuni'),
 ('suspension_date','date','Дата приостановления','Suspension date','To‘xtatish sanasi'),
 ('date_termination','date','Дата прекращения деятельности','Termination date','Faoliyat tugash sanasi'),
 ('doc_emintet','reference','Документ-основание','Source document','Asos hujjati'),
 ('name_of_property','text','Имущество (как раскрыто)','Property (as disclosed)','Mol-mulk (manbadagidek)'),
 ('carrying_value','source_units','Балансовая стоимость','Book value','Balans qiymati'),
 ('subject_matter','text','Предмет','Subject','Predmet'),
 ('claim_amount','source_units','Сумма иска','Claim amount','Da’vo summasi'),
 ('purpose_loan','text','Цель кредита','Loan purpose','Kredit maqsadi'),
 ('loan_amount','source_units','Сумма кредита','Loan amount','Kredit summasi'),
 ('loan_capital','percent','Отношение кредита к базе раскрытия','Loan / disclosure basis','Kredit / oshkor etish bazasi'),
 ('maturity_loan','text','Срок кредита','Loan term','Kredit muddati'),
 ('value_of_assets','source_units','Стоимость активов','Asset value','Aktivlar qiymati'),
 ('transaction_amount','source_units','Сумма сделки','Transaction amount','Bitim summasi'),
 ('type_transaction','text','Вид сделки','Transaction type','Bitim turi'),
 ('assets_issuer','percent','Сделка к активам','Transaction / assets','Bitim / aktivlar'),
 ('share_affiliated_entity','percent','Доля связанного лица','Affiliate share','Affillangan shaxs ulushi'),
 ('type_activity','text','Лицензируемая деятельность','Licensed activity','Litsenziyalanadigan faoliyat'),
 ('number_licensing','text','Номер лицензии','Licence number','Litsenziya raqami'),
 ('revocation_reason','text','Основание прекращения / приостановления','Cancellation / suspension grounds','Bekor qilish / to‘xtatish asosi'),
 ('for_period','text','Указанный срок приостановления','Disclosed suspension term','Ko‘rsatilgan to‘xtatish muddati'),
 ('paper_type','text','Вид бумаги (код источника)','Security type (source code)','Qog‘oz turi (manba kodi)'),
 ('paper_num','count','Количество бумаг','Security count','Qog‘ozlar soni'),
 ('nominal_paper_cost','source_units','Номинальная стоимость','Nominal value','Nominal qiymat'),
 ('total_amount','source_units','Объём выпуска','Issue amount','Emissiya hajmi'),
 ('num_registration','text','Регистрация выпуска','Issue registration','Emissiya ro‘yxati'),
 ('placement_method','text','Способ размещения','Placement method','Joylashtirish usuli'),
 ('suspension_reason','text','Основание по выпуску','Issue decision grounds','Emissiya qarori asosi'),
 ('procedure_repayment','text','Порядок возврата средств','Refund procedure','Mablag‘ qaytarish tartibi'),
 ('description_issuers_obligations','text','Обязательства эмитента','Issuer obligations','Emitent majburiyatlari'),
 ('procedure','text','Процедура (код источника)','Procedure (source code)','Tartib (manba kodi)'),
 ('stock_type','text','Вид акции','Share class','Aksiya turi'),
 ('stock_kind','text','Вид бумаги','Security type','Qog‘oz turi'),
 ('buyout_reason','text','Основание выкупа','Buyback grounds','Qayta sotib olish asosi'),
 ('buyout_price','source_units','Цена выкупа','Buyback price','Qayta sotib olish narxi'),
 ('foreign_cap_markets','text','Торговая площадка / решение','Trading venue / decision','Savdo maydoni / qaror'),
 ('securities_type','text','Вид бумаги','Security type','Qog‘oz turi'),
 ('securities_count_before','count','Количество до изменения','Security count before','Oldingi qog‘ozlar soni'),
 ('securities_count_after','count','Количество после изменения','Security count after','Keyingi qog‘ozlar soni'),
 ('total_issue_amount_before','source_units','Объём до изменения','Issue amount before','Oldingi emissiya hajmi'),
 ('total_issue_amount_after','source_units','Объём после изменения','Issue amount after','Keyingi emissiya hajmi'),
 ('securities_amount','count','Количество в пакете','Holding size','Paketdagi qog‘ozlar soni'),
 ('securities_percent','percent','Раскрытая доля','Disclosed ownership','Oshkor etilgan ulush'),
 ('reasons_for_buy','text','Основание предложения','Offer grounds','Taklif asosi'),
 ('redemption_price','source_units','Предложенная цена выкупа','Offered buyout price','Taklif etilgan narx'),
 ('supervisory_board_proposal','text','Предложение наблюдательного совета','Supervisory board proposal','Kuzatuv kengashi taklifi'),
 ('sum_aksiya','uzs_per_security','Начислено на акцию (класс не указан)','Accrued per share (class unspecified)','Har bir aksiyaga (turi ko‘rsatilmagan)'),
 ('sum_per','uzs_per_security','Начислено на облигацию','Accrued per bond','Har bir obligatsiyaga'),
 ('overall_calculated_sum','thousand_uzs','Начислено всего','Total accrued','Jami hisoblangan'),
 ('overall_paid_sum','thousand_uzs','Выплачено всего','Total paid','Jami to‘langan'),
 ('overall_paid_percent','percent','Доля выплаченного','Paid proportion','To‘langan ulush'),
 ('overall_debt_sum','thousand_uzs','Остаток задолженности','Outstanding balance','Qolgan qarzdorlik'),
]: field(key,kind,ru,en,uz)

TABLES = {
 'facts_decisions_wording':words('Принятые решения','Adopted resolutions','Qabul qilingan qarorlar'),
 'factscaseelection':words('Избрания в органы управления','Appointments','Boshqaruvga saylovlar'),
 'factsterminationpowers':words('Прекращения полномочий','Terminations of office','Vakolatlarning tugatilishi'),
 'factsinformationchanges':words('Изменения в подразделениях','Branch / office changes','Bo‘linmalardagi o‘zgarishlar'),
 'factsinformationabout':words('Изменения в дочерних обществах','Subsidiary changes','Sho‘ba jamiyatlardagi o‘zgarishlar'),
 'factsinformationofabout':words('Изменения в зависимых обществах','Associate changes','Qaram jamiyatlardagi o‘zgarishlar'),
 'factsinformationlist':words('Изменения стоимости активов','Asset value changes','Aktivlar qiymati o‘zgarishi'),
 'factslistoflegal':words('Участие в юридических лицах','Investee holdings','Yuridik shaxslardagi ulushlar'),
 'factsshareinauthorized':words('Изменения долей руководства','Insider holding changes','Rahbariyat ulushlari o‘zgarishi'),
 'factscorresponding':words('Изменения связанных лиц','Affiliate changes','Affillangan shaxslar o‘zgarishi'),
}
for key,label in TABLES.items(): FIELDS[key]=('table',label)

# Public number -> relevant content fields, not the API model's internal type.
SCHEMAS = {
 1:('full_name_before_change',),2:('location_before_change',),
 3:('reorganization_method','order_request'),4:('suspension_date','order_request'),5:('date_termination','order_request'),
 6:('facts_decisions_wording',),7:('description_changes',),
 8:('factscaseelection','factsterminationpowers'),9:('factsinformationchanges',),10:('factsinformationchanges',),
 11:('factsinformationabout',),12:('factsinformationofabout',),13:('name_of_property','carrying_value'),
 14:('subject_matter','claim_amount'),15:('purpose_loan','loan_amount','loan_capital','maturity_loan'),
 16:('purpose_loan','loan_amount','loan_capital','maturity_loan'),17:('value_of_assets','factsinformationlist'),18:('value_of_assets','factsinformationlist'),
 19:('type_transaction','subject_matter','transaction_amount'),20:('type_transaction','subject_matter','transaction_amount','assets_issuer'),
 21:('type_transaction','subject_matter','transaction_amount','share_affiliated_entity'),
 22:('type_activity','number_licensing'),23:('type_activity','revocation_reason'),24:('type_activity','revocation_reason','for_period'),
 25:('paper_type','paper_num','nominal_paper_cost','total_amount','placement_method'),
 26:('paper_type','paper_num','suspension_reason'),27:('paper_type','paper_num','nominal_paper_cost','total_amount','placement_method'),
 28:('paper_type','paper_num','suspension_reason','procedure_repayment'),29:('paper_type','paper_num','num_registration'),
 30:('factslistoflegal',),31:('description_issuers_obligations',),32:('sum_aksiya','sum_per'),33:('procedure',),
 34:('factsshareinauthorized','doc_emintet'),35:('factsshareinauthorized','doc_emintet'),36:('factscorresponding',),
 37:('stock_type','stock_kind','buyout_reason','buyout_price'),38:('foreign_cap_markets',),39:('foreign_cap_markets',),
 40:('securities_type','securities_count_before','securities_count_after','total_issue_amount_before','total_issue_amount_after','description_changes'),
 41:('supervisory_board_proposal',),42:('overall_calculated_sum','overall_paid_sum','overall_paid_percent','overall_debt_sum'),
 43:('securities_amount','securities_percent'),44:('securities_amount','securities_percent'),45:('securities_type','reasons_for_buy','redemption_price'),
 46:('facts_decisions_wording','subject_matter','transaction_amount'),
}
EVENT_DATES = {1:'date_of_changes_registration',2:'date_of_changes_registration',3:'date_of_reorganization',4:'suspension_date',5:'date_termination',
 6:'date_transaction',7:'date_registration',8:'date_apply',9:'date_effective',10:'date_effective',11:'date_apply',12:'date_apply',13:'date_seizure',
 14:'date_of_filing',15:'date_receipt',16:'date_receipt',19:'date_transaction',20:'date_transaction',21:'date_transaction',22:'date_licensing',
 23:'date_decision_cancellation',24:'date_decision_cancellation',25:'date_registration',26:'suspension_date',27:'date_registration',
 28:'date_recognition_of_fail',29:'date_recognition',30:'date_apply',31:'date_begin',33:'date_begin',36:'date_vnesn',
 37:'buyout_start_date',38:'date_registration',39:'date_registration',40:'date_registration',43:'transaction_date',45:'redemption_start_date'}
DECISION_DATES = {6:'date_transaction',8:'date_apply',9:'date_apply',10:'date_apply',11:'date_apply',12:'date_apply',19:'date_decision',20:'date_decision',21:'date_decision',22:'date_decision',23:'date_decision_cancellation',24:'date_decision_cancellation',25:'date_decision',26:'date_solutions',27:'date_decision',28:'date_solutions',30:'date_apply',31:'date_solution',32:'date_solution',33:'date_solution',45:'sollution_approval_date'}


def numeric(value):
    if value is None or isinstance(value,bool):return None
    text=re.sub(r'[\s\u00a0\u202f%]', '',str(value))
    if ',' in text and '.' in text:
        # Last separator is decimal; preceding groups must have three digits.
        decimal=',' if text.rfind(',')>text.rfind('.') else '.'
        grouping='.' if decimal==',' else ','
        whole,fraction=text.rsplit(decimal,1)
        if grouping in whole and not re.fullmatch(r'\d{1,3}(?:'+re.escape(grouping)+r'\d{3})+',whole):return None
        text=whole.replace(grouping,'')+'.'+fraction
    elif text.count(',')>1:
        if not re.fullmatch(r'\d{1,3}(?:,\d{3})+',text):return None
        text=text.replace(',','')
    else:text=text.replace(',','.')
    try:
        n=Decimal(text)
        value=float(n) if n.is_finite() and n>=0 else None
        return value if value is not None and math.isfinite(value) else None
    except (InvalidOperation,ValueError,OverflowError):return None


def content(value):
    if value is None:return None
    text=re.sub(r'\s+',' ',str(value)).strip()
    return text[:1800] if text.casefold() not in {'','-','—','none','null','нет данных'} else None


NESTED_FIELDS = {
 'decisions_wording':('text',words('Принятое решение','Adopted resolution','Qabul qilingan qaror')),
 'position':('text',words('Должность / организация (как раскрыто)','Position / entity (as disclosed)','Lavozim / tashkilot (manbadagidek)')),
 'type_change':('text',words('Изменение (код источника)','Change (source code)','O‘zgarish (manba kodi)')),
 'akt_name':('text',words('Актив','Asset','Aktiv')),
 'sum':('source_units',words('Стоимость по строке','Row amount','Qator qiymati')),
 'ownership':('text',words('Участие (как раскрыто)','Holding (as disclosed)','Ulush (manbadagidek)')),
 'to_change_num':('count',words('Количество до изменения','Quantity before','Oldingi son')),
 'after_change_num':('count',words('Количество после изменения','Quantity after','Keyingi son')),
}


def table_percent(value, table, field_name, code):
    n=numeric(value)
    # Growth is a change relative to an earlier asset base. It can exceed
    # 100%; ownership is a fraction of a whole and cannot.
    growth=code==17 and table=='factsinformationlist' and field_name=='prosent'
    return n if n is not None and (n<=100 or growth) else None


def table_row_has_content(row, table, code):
    if table=='facts_decisions_wording':return bool(content(row.get('decisions_wording')))
    return (any((content(row.get(name)) if unit=='text' else numeric(row.get(name))) is not None
                for name,(unit,_) in NESTED_FIELDS.items())
            or any(table_percent(row.get(name),table,name,code) is not None
                   for name in ('prosent','to_change_pro','after_change_pro')))


def extract(raw, code):
    out=[]
    keys=SCHEMAS.get(code,())
    if code in SCHEMAS and code not in {6,46} and raw.get('facts_decisions_wording'):
        keys=(*keys,'facts_decisions_wording')
    for key in keys:
        kind,label=FIELDS[key];value=raw.get(key)
        if kind=='table':
            rows=[(index,r) for index,r in enumerate(value) if isinstance(r,dict) and table_row_has_content(r,key,code)] if isinstance(value,list) else []
            if rows:out.append(dict(source_field=key,label=label,value=len(rows),unit='records'))
            # Only typed values from known source tables; no officer contacts.
            for index,row in rows[:8]:
                for name,(unit,labels) in NESTED_FIELDS.items():
                    value=content(row.get(name)) if unit=='text' else numeric(row.get(name))
                    if value is not None:
                        out.append(dict(source_field=f'{key}.{index}.{name}',label=labels,value=value,unit=unit))
                for name in ('prosent','to_change_pro','after_change_pro'):
                    n=table_percent(row.get(name),key,name,code)
                    if n is not None:
                        suffix=words('До изменения','Before change','O‘zgarishdan oldin') if name=='to_change_pro' else words('После изменения','After change','O‘zgarishdan keyin') if name=='after_change_pro' else words('Доля изменения','Change proportion','O‘zgarish ulushi')
                        out.append(dict(source_field=f'{key}.{index}.{name}',label=suffix,value=n,unit='percent'))
        else:
            from corporate_events import day
            value=day(value) if kind=='date' else content(value) if kind in {'text','reference'} else numeric(value)
            if value is None or (kind=='percent' and value>100 and key not in {'loan_capital','assets_issuer'}):continue
            out.append(dict(source_field=key,label=label,value=value,unit=kind))
    return out


def summary_value(f, lang):
    units = {
        'percent': words('%','%','%'),
        'source_units': words(' (единицы источника)',' (source units)',' (manba birliklari)'),
        'thousand_uzs': words(' тыс. сум',' thousand UZS',' ming so‘m'),
        'uzs_per_security': words(' сум на бумагу',' UZS per security',' so‘m / qog‘oz'),
        'records': words(' записей',' records',' yozuv'),
    }
    return str(f['value'])[:200]+units.get(f['unit'],{}).get(lang,'')


def apply(document, raw):
    from corporate_events import day
    d=document;code=d['code'];facts=extract(raw,code)
    d.update(extraction_version=VERSION,facts=facts)
    decision=day(raw.get(DECISION_DATES.get(code,'decision_date')))
    if decision and (not day(d['published_at']) or decision<=day(d['published_at'])):d['decision_date']=decision
    event=day(raw.get(EVENT_DATES.get(code,'')))
    if event:d['event_date']=event
    # Materiality is assessed only from actual disclosed content. A document
    # whose body is missing retains its provisional starting priority.
    reason='missing_content';explanation=words('Недостаточно содержательных полей; требуется проверка.','Insufficient source content; review required.','Mazmunli maydonlar yetarli emas; tekshirish kerak.')
    meaningful=[f for f in facts if f['unit']!='reference' and f['source_field'].split('.')[0] in SCHEMAS.get(code,())]
    if meaningful:
        reason='source_content'
        explanation=words('Оценка внимания по содержанию раскрытия.','Attention level based on disclosed content.','E’tibor darajasi oshkor etilgan mazmunga asoslangan.')
        d['confidence']='confirmed' if day(d['published_at']) else 'review'
        d['priority_provisional']=d['confidence']!='confirmed'
        if code in {1,2,9,10}:d['priority']=3
        elif code in {8,11,12,30,34,35,36,38,46}:d['priority']=2
        elif code in {4,5,13,14,24,33}:d['priority']=0
        elif code in {3,7,15,16,17,18,19,20,21,22,23,25,26,27,28,29,31,32,37,39,40,41,42,43,44,45}:d['priority']=1
        if code in {6,32,41,42}:
            # The specialised stage interpreter owns the evidence requirements.
            d['confidence']=document['_stage_confidence']
            d['priority_provisional']=d['confidence']!='confirmed'
        if code==6:
            reason=document.get('priority_reason','source_content')
            explanation=words('Оценка по принятым решениям, не по вопросам повестки.','Based on adopted resolutions, not agenda questions.','Kun tartibi emas, qabul qilingan qarorlarga asoslangan.')
        if code==23:d['priority']=0
        if code==22:d['priority']=2
        if code==23 and re.search(r'доброволь|voluntar|ixtiyor',str(raw.get('revocation_reason','')),re.I):
            d['priority']=1;reason='voluntary_license_return'
            explanation=words('Эмитент указал добровольный возврат лицензии; принудительная остановка не подтверждена.','The issuer reports voluntary licence return; enforced suspension is not established.','Emitent litsenziyani ixtiyoriy qaytargan; majburiy to‘xtatish tasdiqlanmagan.')
        if code==24:
            explanation=words('Раскрыто приостановление лицензируемой деятельности.','Suspension of licensed activity is disclosed.','Litsenziyalangan faoliyat to‘xtatilishi oshkor etilgan.')
        if code in {17,18}:
            reason='asset_movement'
            explanation=words('Изменение стоимости активов; само по себе не означает неплатёжеспособность.','An asset value change does not by itself establish insolvency.','Aktiv qiymati o‘zgarishi o‘z-o‘zidan to‘lovga qobiliyatsizlikni bildirmaydi.')
        if code in {28,29,39}:
            reason='security_event'
            explanation=words('Оценка относится к выпуску или допуску бумаги, не к остановке всей компании.','This concerns the security issue or trading admission, not a company-wide shutdown.','Bu qog‘oz emissiyasi yoki savdoga ruxsatga tegishli, butun kompaniya yopilishiga emas.')
        if code==40:
            pairs=[(numeric(raw.get(a)),numeric(raw.get(b))) for a,b in [('securities_count_before','securities_count_after'),('total_issue_amount_before','total_issue_amount_after')]]
            if all(a is not None and b is not None for a,b in pairs):
                changed=any(a!=b for a,b in pairs)
                d['priority']=1 if changed else 2;reason='changed_issue_size' if changed else 'unchanged_issue_size'
                explanation=words('Количество или объём выпуска изменились.' if changed else 'Количество и объём выпуска не изменились.', 'Issue quantity or amount changed.' if changed else 'Issue quantity and amount are unchanged.', 'Emissiya soni yoki hajmi o‘zgardi.' if changed else 'Emissiya soni va hajmi o‘zgarmagan.')
        if code in {15,16,19,20,21,43,44,45}:
            reason='financial_terms'
            explanation=words('Приоритет по раскрытым финансовым условиям и долям; без прогноза цены.','Priority reflects disclosed financial terms and ownership, without predicting price.','Ustuvorlik oshkor etilgan moliyaviy shartlar va ulushlarga asoslangan; narx bashorati yo‘q.')
        if code in {34,35}:
            changes=[f['value'] for f in facts if f['unit']=='percent']
            if any(v>=50 for v in changes):d['priority']=1
    else:
        d['confidence']='review';d['priority_provisional']=True
    d['priority_reason']=reason;d['priority_explanation']=explanation
    # Show concise content, with source wording preserved separately. Never
    # pretend an untranslated issuer text is an official translation.
    if facts and code not in {6,32,41,42}:
        d['summary']={lang: ' '.join(f"{f['label'][lang]}: {summary_value(f,lang)}." for f in facts[:3]) for lang in ('ru','en','uz')}
    elif facts and d['summary']==d['title']:
        d['summary']={lang: ' '.join(f"{f['label'][lang]}: {summary_value(f,lang)}." for f in facts[:2]) for lang in ('ru','en','uz')}
    d.pop('_stage_confidence',None)
    return d
