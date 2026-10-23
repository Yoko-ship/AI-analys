"""Source checks: warnings retain published values, with their evidence."""
from server.terminal.analytics import number, ratio


def insurance_checks(current,previous,opening,annual_close):
    issues=[]
    current_share=ratio(current.get('ceded_premiums'),current.get('insurance_premiums'),100)
    previous_share=ratio(previous.get('ceded_premiums'),previous.get('insurance_premiums'),100)
    c,p=number(current.get('ceded_premiums')),number(previous.get('ceded_premiums'))
    moved=current_share is not None and previous_share is not None and abs(current_share-previous_share)>30
    scaled=c is not None and p is not None and min(c,p)>0 and max(c,p)/min(c,p)>5
    if moved or scaled:
        issues.append({'event':'ins_retention_jump','code':'INS_RETENTION_JUMP','severity':'warning','message':'Проверить строку 012: изменение удержания >30 п.п. или передачи премий >5 раз.',
                       'current_cession':c,'prior_cession':p,'current_share':current_share,'previous_share':previous_share})
    for field in ('net_insurance_reserves','gross_insurance_reserves','total_assets','total_liabilities'):
        annual,quarter=number(annual_close.get(field)),number(opening.get(field))
        if annual is not None and quarter is not None and quarter>0 and abs(annual-quarter)/quarter>.05:
            issues.append({'event':'ins_reserves_missing','code':'INS_RESERVES_MISSING','severity':'warning',
                           'message':'Годовой баланс отличается от начала года квартального отчёта более чем на 5%; проверить резервы.',
                           'field':field,'annual_close':annual,'quarter_opening':quarter})
    return issues


def report_events(report, *, published=False):
    from server.terminal import journal
    context={'ticker':report.get('issuer',{}).get('ticker'),'period':report.get('period'),
             'standard':str(report.get('standard') or '').upper().replace('IFRS','MSFO'),
             'source_url':next((s.get('url') for s in report.get('sources',[]) if s.get('url')),None)}
    key=str(report.get('source_snapshot_hash') or report.get('version'))+':'+str(report.get('calculation_version',''))
    if published:
        journal.emit('ai_published',dedupe_key=key,**context)
    elif report.get('status') not in {'available','stale'}:
        journal.emit('ai_blocked',dedupe_key=key,message=str(report.get('status')),**context)
    high=any(r.get('severity')=='high' for r in report.get('risks',[]))
    if high and report.get('verdict',{}).get('status')!='attention' and report.get('status')=='available':
        journal.emit('verdict_conflict',dedupe_key=key,message='High risk without attention verdict',**context)
    for issue in report.get('data_quality',[]):
        if issue.get('event') in {'ins_retention_jump','ins_reserves_missing'}:
            journal.emit(issue['event'],dedupe_key=key+':'+str(issue.get('field','')),message=issue['message'],details=issue,**context)
