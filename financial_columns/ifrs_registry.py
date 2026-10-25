"""Exact bilingual IFRS aliases, isolated by statement rather than row number."""

# Each line is metric_id | English source label | Russian source label.
DEFINITIONS = {
    'BS': '''noncurrent_assets|Non-current assets|Внеоборотные активы
ppe|Property, plant and equipment|Основные средства
intangibles|Intangible assets|Нематериальные активы
rou_assets|Right-of-use assets|Активы в форме права пользования
investment_property|Investment property|Инвестиционная недвижимость
investments_associates|Investments in associates|Инвестиции в ассоциированные компании
financial_assets_fvtpl|Financial assets at fair value through profit or loss|Финансовые активы по справедливой стоимости через прибыль или убыток
financial_assets_fvoci|Financial assets at fair value through other comprehensive income|Финансовые активы по справедливой стоимости через прочий совокупный доход
financial_assets_amortized_cost|Financial assets at amortised cost|Финансовые активы по амортизированной стоимости
inventory|Inventories|Запасы
trade_receivables|Trade receivables|Торговая дебиторская задолженность
contract_assets|Contract assets|Активы по договорам
cash|Cash and cash equivalents|Денежные средства и их эквиваленты
current_assets|Current assets|Оборотные активы
other_assets|Other assets|Прочие активы
total_assets|Total assets|Итого активы
share_capital|Share capital|Уставный капитал
share_premium|Share premium|Эмиссионный доход
retained_earnings|Retained earnings|Нераспределенная прибыль
treasury_shares|Treasury shares|Собственные выкупленные акции
other_reserves|Other reserves|Прочие резервы
equity_owners|Equity attributable to owners of the parent|Капитал, приходящийся на собственников материнской компании
nci|Non-controlling interests|Неконтролирующая доля участия
total_equity|Total equity|Итого капитал
borrowings_short|Short-term borrowings|Краткосрочные заимствования
borrowings_long|Long-term borrowings|Долгосрочные заимствования
lease_liabilities|Lease liabilities|Обязательства по аренде
trade_payables|Trade payables|Торговая кредиторская задолженность
contract_liabilities|Contract liabilities|Обязательства по договорам
provisions|Provisions|Резервы
current_liabilities|Current liabilities|Краткосрочные обязательства
noncurrent_liabilities|Non-current liabilities|Долгосрочные обязательства
deferred_tax_liability|Deferred tax liabilities|Отложенные налоговые обязательства
total_liabilities|Total liabilities|Итого обязательства
total_equity_liabilities|Total liabilities and equity|Итого обязательства и капитал
loans_gross|Gross loans to customers|Кредиты клиентам брутто
loans_net|Loans and advances to customers|Кредиты и авансы клиентам
customer_funds|Customer accounts|Средства клиентов
bank_funding|Due to banks|Средства банков
subordinated_debt|Subordinated debt|Субординированный долг
net_lease_investment|Net investment in finance leases|Чистые инвестиции в финансовую аренду
lease_receivables|Finance lease receivables|Дебиторская задолженность по финансовой аренде
insurance_contract_assets|Insurance contract assets|Активы по договорам страхования
insurance_contract_liabilities|Insurance contract liabilities|Обязательства по договорам страхования
reinsurance_contract_assets|Reinsurance contract assets|Активы по договорам перестрахования
reinsurance_contract_liabilities|Reinsurance contract liabilities|Обязательства по договорам перестрахования
insurance_reserves_gross|Insurance contract reserves|Страховые резервы
reinsurer_share_reserves|Reinsurers share of insurance reserves|Доля перестраховщиков в страховых резервах
deferred_acquisition_costs|Deferred acquisition costs|Отложенные аквизиционные расходы
preferred_share_liability|Preference shares classified as liabilities|Привилегированные акции, классифицированные как обязательства''',
    'PL': '''revenue|Revenue|Выручка
cost_of_sales|Cost of sales|Себестоимость продаж
gross_profit|Gross profit|Валовая прибыль
selling_expense|Selling expenses|Расходы по реализации
admin_expense|Administrative expenses|Административные расходы
other_operating_income|Other operating income|Прочие операционные доходы
other_operating_expense|Other operating expenses|Прочие операционные расходы
depreciation_amortization|Depreciation and amortisation|Износ и амортизация
impairment|Impairment losses|Убытки от обесценения
operating_income|Operating profit|Операционная прибыль
finance_income|Finance income|Финансовые доходы
finance_cost|Finance costs|Финансовые расходы
fx_gain_loss|Net foreign exchange gain|Чистая прибыль от курсовых разниц
share_of_profit_associates|Share of profit of associates|Доля в прибыли ассоциированных компаний
profit_before_tax|Profit before tax|Прибыль до налогообложения
income_tax|Income tax expense|Расходы по налогу на прибыль
profit_continuing|Profit from continuing operations|Прибыль от продолжающейся деятельности
net_income|Profit for the year|Прибыль за год
profit_owners|Profit attributable to owners of the parent|Прибыль, приходящаяся на собственников материнской компании
profit_nci|Profit attributable to non-controlling interests|Прибыль, приходящаяся на неконтролирующие доли участия
oci|Other comprehensive income|Прочий совокупный доход
comprehensive_income|Total comprehensive income|Общий совокупный доход
eps_basic|Basic earnings per share|Базовая прибыль на акцию
eps_diluted|Diluted earnings per share|Разводненная прибыль на акцию
interest_income|Interest income|Процентные доходы
interest_eir|Interest income calculated using the effective interest method|Процентные доходы, рассчитанные по методу эффективной процентной ставки
other_interest_income|Other interest income|Прочие процентные доходы
interest_expense|Interest expense|Процентные расходы
net_interest_before_ecl|Net interest income before credit loss expense|Чистые процентные доходы до кредитных убытков
net_interest_after_ecl|Net interest income after credit loss expense|Чистые процентные доходы после кредитных убытков
credit_loss_expense|Credit loss expense|Расходы по кредитным убыткам
fee_income|Fee and commission income|Комиссионные доходы
fee_expense|Fee and commission expense|Комиссионные расходы
net_fee_income|Net fee and commission income|Чистые комиссионные доходы
trading_income|Net trading income|Чистые торговые доходы
insurance_revenue|Insurance revenue|Страховая выручка
insurance_service_expense|Insurance service expenses|Расходы по страховым услугам
insurance_service_result|Insurance service result|Результат страховых услуг
reinsurance_result|Net result from reinsurance contracts held|Чистый результат по удерживаемым договорам перестрахования
gross_written_premiums|Gross written premiums|Валовые подписанные премии
net_earned_premiums|Net earned premiums|Чистые заработанные премии
net_incurred_claims|Net claims incurred|Чистые понесенные убытки
acquisition_expense|Acquisition costs|Аквизиционные расходы
insurance_expense_nonoverlap|Acquisition and administrative expenses excluding claims|Аквизиционные и административные расходы без страховых убытков
dividend_income|Dividend income|Дивидендный доход
realized_investment_gain|Realised gain on investments|Реализованная прибыль от инвестиций
unrealized_investment_gain|Unrealised gain on investments|Нереализованная прибыль от инвестиций''',
    'CF': '''cfo|Net cash from operating activities|Чистые денежные средства от операционной деятельности
cfi|Net cash used in investing activities|Чистые денежные средства, использованные в инвестиционной деятельности
cff|Net cash from financing activities|Чистые денежные средства от финансовой деятельности
interest_received|Interest received|Проценты полученные
interest_paid|Interest paid|Проценты уплаченные
income_tax_paid|Income tax paid|Налог на прибыль уплаченный
dividends_received|Dividends received|Дивиденды полученные
dividends_paid|Dividends paid|Дивиденды выплаченные
purchase_ppe|Purchase of property, plant and equipment|Приобретение основных средств
purchase_intangibles|Purchase of intangible assets|Приобретение нематериальных активов
proceeds_disposal_assets|Proceeds from sale of property, plant and equipment|Поступления от продажи основных средств
borrowings_proceeds|Proceeds from borrowings|Поступления от заимствований
borrowings_repayments|Repayment of borrowings|Погашение заимствований
lease_principal_paid|Principal payments of lease liabilities|Погашение основной суммы обязательств по аренде
fx_effect_on_cash|Effect of exchange rate changes on cash and cash equivalents|Влияние изменения валютных курсов на денежные средства и их эквиваленты
delta_cash|Net change in cash and cash equivalents|Чистое изменение денежных средств и их эквивалентов
cash_begin|Cash and cash equivalents at beginning of year|Денежные средства и их эквиваленты на начало года
cash_end|Cash and cash equivalents|Денежные средства и их эквиваленты
cash_end|Cash and cash equivalents at end of year|Денежные средства и их эквиваленты на конец года''',
    'Equity': '''share_issuance|Issue of shares|Выпуск акций
buybacks|Repurchase of own shares|Выкуп собственных акций
dividends_declared|Dividends declared|Дивиденды объявленные
changes_ownership|Changes in ownership interests|Изменения долей участия''',
    'Notes': '''stage1_loans|Stage 1 loans|Кредиты стадии 1
stage2_loans|Stage 2 loans|Кредиты стадии 2
stage3_loans|Stage 3 loans|Кредиты стадии 3
ecl_allowance|Expected credit loss allowance|Резерв ожидаемых кредитных убытков
gross_lease_investment|Gross investment in finance leases|Валовые инвестиции в финансовую аренду
unearned_finance_income|Unearned finance income|Незаработанный финансовый доход
earning_assets|Interest-earning assets|Активы, приносящие процентный доход
weighted_average_shares|Weighted average number of ordinary shares|Средневзвешенное количество обыкновенных акций
ordinary_shares|Ordinary shares outstanding|Обыкновенные акции в обращении
treasury_share_count|Number of treasury shares|Количество собственных выкупленных акций
lrc|Liability for remaining coverage|Обязательство по оставшемуся покрытию
lic|Liability for incurred claims|Обязательство по возникшим требованиям
csm|Contractual service margin|Маржа за предусмотренные договором услуги
risk_adjustment|Risk adjustment|Рисковая поправка''',
}

# Combined investor rows have their own exact source identities. A narrower
# disclosure (for example trade receivables alone) cannot fill a combined total.
INVESTOR_DEFINITIONS = {
    'BS': '''intangibles_goodwill|Intangible assets and goodwill|Нематериальные активы и гудвил
long_term_financial_other_assets|Long-term financial and other assets|Долгосрочные финансовые и прочие активы
trade_other_receivables|Trade and other receivables|Торговая и прочая дебиторская задолженность
other_current_assets|Other current assets|Прочие оборотные активы
central_bank_and_bank_placements|Balances with central bank and other banks|Средства в Центральном банке и других банках
debt_equity_investments|Investments in debt and equity instruments|Инвестиции в долговые и долевые инструменты
interest_bearing_debt|Interest-bearing debt|Процентный долг
other_liabilities|Other liabilities|Прочие обязательства
insurance_financial_investments|Financial investments of the insurer|Финансовые инвестиции страховщика
investment_portfolio|Investment portfolio|Инвестиционный портфель''',
    'PL': '''research_expense|Research and development expenses|Расходы на исследования и разработки
staff_costs|Staff costs|Расходы на персонал
operating_income_before_ecl|Operating income before expenses|Операционный доход до расходов
operating_profit_before_ecl|Operating profit before credit losses|Операционная прибыль до кредитных убытков
insurance_finance_expense|Insurance finance expenses|Финансовые расходы по страхованию
investment_income|Investment income|Инвестиционные доходы
fair_value_gain_loss|Net fair value gain or loss|Чистая прибыль или убыток от переоценки по справедливой стоимости
fund_expenses|Fund expenses|Расходы фонда''',
    'CF': '''other_investing_cash_flows|Other investing cash flows|Прочие инвестиционные потоки''',
    'Equity': '''equity_open|Equity at beginning of period|Капитал на начало периода
other_equity_changes|Other changes in equity|Прочие движения капитала''',
    'Notes': '''unrestricted_cash|Unrestricted cash and cash equivalents|Неограниченные денежные средства и их эквиваленты''',
}
for _form, _definitions in INVESTOR_DEFINITIONS.items():
    DEFINITIONS[_form] += '\n' + _definitions
