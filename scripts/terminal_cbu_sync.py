"""Monthly CBU sync/backfill. Run from the repository root with python -m.

Example: .venv/bin/python -m scripts.terminal_cbu_sync --from-month 2020-01
Re-running upserts dated observations; failed sources preserve prior data.
"""
import argparse
from datetime import date
import json
from server.terminal import cbu, journal


def months(start,end):
    year,month=map(int,start.split('-'));last_year,last_month=map(int,end.split('-'))
    date(year,month,1);date(last_year,last_month,1)
    if (year,month)>(last_year,last_month):raise ValueError('Start must precede end')
    while (year,month)<=(last_year,last_month):
        yield year,month
        year,month=(year+1,1) if month==12 else (year,month+1)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-month',default=date.today().strftime('%Y-%m'))
    parser.add_argument('--through-month',default=date.today().strftime('%Y-%m'))
    parser.add_argument('--fx-from-year',type=int,default=2020,help='Cache year-end USD rates from this year')
    args=parser.parse_args();failed=False
    if not 2000<=args.fx_from_year<=date.today().year:parser.error('Invalid FX starting year')
    pending=list(months(args.from_month,args.through_month))
    for i,(year,month) in enumerate(pending):
        try:result=cbu.sync_month(year,month,with_sdmx=i==len(pending)-1)
        except Exception as exc:result={'loaded':[],'errors':[type(exc).__name__]}
        failed=failed or bool(result['errors'])
        print(json.dumps({'month':f'{year}-{month:02d}',**result},ensure_ascii=False),flush=True)
    from server.currency.history import rates
    for year in range(args.fx_from_year,date.today().year):
        try:rates(f'{year}-12-31')
        except Exception as exc:
            failed=True
            print(json.dumps({'fx_year':year,'error':type(exc).__name__}),flush=True)
    journal.flush()
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
