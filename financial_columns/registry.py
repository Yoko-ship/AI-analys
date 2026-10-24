"""Namespaced source codes. A code is never meaningful without its form.

Unmapped lines remain in the original-form view; this registry only selects
the compact semantic projection. Aggregates and their components stay separate.
"""


def mapping(text):
    return dict(item.split(':', 1) for item in text.split())


NSBU = {
    'F1': mapping('''010:ppe_gross 011:ppe_depreciation 012:ppe 020:intangibles_gross
        021:intangibles_amortization 022:intangibles 030:long_term_investments
        040:long_term_securities 050:investments_subsidiaries 060:investments_associates
        070:investments_joint_ventures 080:other_long_term_investments 090:equipment_installation
        100:construction_in_progress 110:long_term_receivables 120:long_term_deferred_expenses
        130:noncurrent_assets 140:inventory 150:materials 160:work_in_progress 170:finished_goods
        180:merchandise 190:prepaid_expenses 200:deferred_expenses 210:receivables
        211:overdue_receivables 220:trade_receivables 230:separate_unit_receivables
        240:subsidiary_receivables 250:employee_advances 260:supplier_advances
        270:tax_advances 280:insurance_advances 290:founder_receivables 300:employee_receivables
        310:other_receivables 320:cash 330:cash_on_hand 340:bank_accounts 350:foreign_currency_accounts
        360:other_cash 370:short_term_investments 380:other_current_assets 390:current_assets
        400:total_assets 410:share_capital 420:share_premium 430:reserve_capital 440:treasury_shares
        450:retained_earnings 460:target_receipts 470:future_expense_reserves 480:total_equity
        490:noncurrent_liabilities 491:long_term_payables 500:long_term_suppliers
        510:long_term_separate_units 520:long_term_subsidiaries 530:deferred_long_term_income
        540:deferred_long_term_taxes 550:other_deferred_long_term_liabilities 560:long_term_customer_advances
        570:bank_borrowings_long 580:other_borrowings_long 590:other_noncurrent_liabilities
        600:current_liabilities 601:current_payables 602:overdue_payables 610:trade_payables
        620:separate_unit_payables 630:subsidiary_payables 640:deferred_income
        650:deferred_taxes 660:other_deferred_liabilities 670:customer_advances 680:tax_payables
        690:insurance_payables 700:state_fund_payables 710:founder_payables 720:salary_payables
        730:bank_borrowings_short 740:other_borrowings_short 750:current_portion_long_term_debt
        760:other_current_payables 770:total_liabilities 780:total_equity_liabilities'''),
    'F2': mapping('''010:revenue 020:cost_of_sales 030:gross_profit 040:operating_expenses
        050:selling_expense 060:admin_expense 070:other_operating_expense 080:excluded_period_expenses
        090:other_operating_income 100:operating_income 110:finance_income 120:dividend_income
        130:interest_income 140:lease_income 150:fx_income 160:other_finance_income
        170:finance_cost 180:interest_expense 190:lease_expense 200:fx_expense
        210:other_finance_cost 220:ordinary_profit 230:extraordinary_profit
        240:profit_before_tax 250:income_tax 260:other_profit_payments 270:net_income'''),
    'BANK_BS': mapping('''1:cash 2:central_bank_balances 3:bank_balances 4:trading_assets
        4а:trading_securities 4б:precious_metals 4в:trading_allowance 4г:trading_assets_net
        5а:investments_gross 5б:investment_allowance 5в:investments_net 6:reverse_repo
        7:loans_and_leases 7а:loans_gross 7б:leases_gross 7в:loan_lease_allowance 7г:loans_leases_net
        8а:bills_gross 8б:bills_allowance 8в:bills_net 9:customer_instrument_obligations
        10:ppe 11:interest_receivables 12:other_property 12а:investment_property 12б:foreclosed_assets
        12в:other_property_allowance 12г:other_property_net
        13:other_assets 14:total_assets 15:demand_deposits 16:savings_deposits 17:term_deposits
        18:central_bank_funding 19:bank_funding 20:repo_liabilities 21:borrowings_and_leases
        22:subordinated_debt 23:interest_payables 24:other_liabilities 25:total_liabilities
        26:share_capital 26а:ordinary_share_capital 26б:preferred_share_capital
        27:share_premium 28:reserve_capital 28а:general_reserves 28б:revaluation_reserves
        28в:other_reserves 29:retained_earnings 30:total_equity 31:total_equity_liabilities'''),
    'BANK_PL': mapping('''1:interest_income 1а:interest_central_bank 1б:interest_banks
        1в:interest_bills 1г:interest_investments 1д:interest_trading_securities
        1е:interest_customer_obligations 1ж:interest_acceptances 1з:interest_loans_leases 1и:interest_reverse_repo
        1к:other_interest_income 1л:interest_income 2:interest_expense 2а:interest_demand_deposits
        2б:interest_savings_deposits 2в:interest_term_deposits 2г:interest_central_bank_funding
        2д:interest_bank_funding 2е:interest_deposits_total 2ж:interest_borrowings 2з:interest_repo
        2и:other_interest_expense 2к:interest_borrowings_total 2л:interest_expense
        3:net_interest_before_ecl 3а:credit_loss_expense 3б:net_interest_after_ecl
        4:noninterest_income 4а:fee_income 4б:fx_income 4в:trading_income 4г:investment_dividend_income
        4д:other_noninterest_income 4е:noninterest_income 5:noninterest_expense 5а:fee_expense
        5б:fx_expense 5в:trading_expense 5г:investment_expense 5д:other_noninterest_expense
        5е:noninterest_expense 6:income_before_opex 7:operating_expenses 7а:staff_expense
        7б:rent_expense 7в:travel_expense 7г:admin_expense 7д:representation_charity_expense
        7е:depreciation_amortization 7ж:insurance_taxes_other_expense 7з:operating_expenses
        8:noncredit_impairment 9:profit_before_tax 9а:income_tax 10:profit_before_adjustments
        10а:profit_adjustment 10б:tax_adjustment 11:net_income'''),
}
NSBU['INSURANCE_BS'] = {k: v for k, v in NSBU['F1'].items() if int(k) <= 130}
NSBU['INSURANCE_BS'].update(mapping('''140:materials 150:work_in_progress 160:finished_goods
    170:prepaid_expenses 180:deferred_expenses 190:receivables 191:overdue_receivables
    200:trade_receivables 220:insurance_receivables 230:policyholder_receivables
    240:agent_receivables 250:reinsured_receivables 260:reinsurer_commission_receivables
    270:reinsurer_receivables 280:life_policy_loans 290:loss_deposits 300:premium_deposits
    410:cash 420:cash_on_hand 430:bank_accounts 440:foreign_currency_accounts 450:other_cash
    460:short_term_investments 470:other_current_assets 480:current_assets 490:total_assets
    500:share_capital 510:share_premium 520:reserve_capital 530:treasury_shares 540:retained_earnings
    550:target_receipts 560:future_expense_reserves 570:total_equity 580:insurance_reserves_gross
    590:unearned_premium_reserve 600:ibnr 610:reported_claims_reserve 620:stabilization_reserve
    630:catastrophe_reserve 640:other_insurance_reserves 650:life_reserves 660:additional_reserves
    670:reinsurer_share_reserves 680:reinsurer_share_upr 690:reinsurer_share_ibnr
    700:reinsurer_share_reported_claims 710:other_reinsurer_reserve_share 720:insurance_reserves_net
    730:noncurrent_liabilities 750:long_term_insurance_payables 930:current_liabilities
    950:insurance_payables 970:policyholder_payables 980:agent_payables 990:reinsured_payables
    1000:reinsurer_payables 1190:nonreserve_liabilities 1200:total_equity_liabilities'''))
NSBU['INSURANCE_PL'] = mapping('''010:insurance_income 011:direct_premiums 012:ceded_premiums
    013:assumed_premiums 014:change_upr_net 015:change_reported_claims_net 016:change_ibnr_net
    017:change_life_reserves_net 018:change_other_reserves_net 019:other_insurance_income
    020:broker_income 030:claims_recoveries
    040:commission_income 050:surveyor_income 060:net_insurance_revenue 070:insurance_cost 080:gross_profit
    090:operating_expenses 100:selling_expense 110:admin_expense 120:other_operating_expense
    130:excluded_period_expenses 140:other_operating_income 150:operating_income
    160:finance_income 170:dividend_income 180:interest_income 190:lease_income 200:fx_income
    210:other_finance_income 220:finance_cost 230:interest_expense 240:lease_expense
    250:fx_expense 260:other_finance_cost 270:ordinary_profit 280:extraordinary_profit
    290:profit_before_tax 300:income_tax 310:other_profit_payments 320:net_income''')


def metric(form, code):
    return NSBU.get(form, {}).get(code)


# Form revisions sometimes reuse a code. These high-impact totals and sector
# inputs need a matching literal label or the source's defining row formula.
LABEL_RULES = {
    'total_assets': r'актив|asset|aktiv',
    'total_liabilities': r'обязательств|liabil|majburiyat|490\s*\+\s*600',
    'total_equity': r'капитал|собственн|equity|kapital|410.*480|410.*470|500.*560',
    'insurance_reserves_gross': r'страхов.*резерв|insurance.*reserv|sug.*zaxir',
    'reinsurer_share_reserves': r'перестрахов|reinsur|qayta.*sug',
    'credit_loss_expense': r'потер|убыт|loss|zarar',
    'interest_income': r'процент.*доход|доход.*процент|interest.*income|foiz.*daromad',
    'interest_expense': r'процент.*расход|расход.*процент|interest.*expense|foiz.*xarajat',
}
