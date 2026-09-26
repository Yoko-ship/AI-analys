"""Sector language. Pure deterministic rules."""
from __future__ import annotations




LABELS = {
    "revenue": ("Выручка / раскрытые доходы", "Tushum / daromad", "Revenue / disclosed income"),
    "net_income": ("Чистая прибыль (убыток)", "Sof foyda (zarar)", "Net income (loss)"),
    "operating_income": ("Прибыль основной деятельности", "Asosiy faoliyat foydasi", "Operating result"),
    "total_assets": ("Активы", "Aktivlar", "Assets"), "total_equity": ("Капитал", "Kapital", "Equity"),
    "total_liabilities": ("Обязательства", "Majburiyatlar", "Liabilities"), "cash": ("Деньги", "Pul mablag‘lari", "Cash"),
    "cost_of_sales": ("Себестоимость", "Tannarx", "Cost of sales"), "gross_profit": ("Валовая прибыль", "Yalpi foyda", "Gross profit"),
    "period_expenses": ("Расходы периода", "Davr xarajatlari", "Period expenses"), "profit_before_tax": ("Прибыль до налога", "Soliqdan oldingi foyda", "Profit before tax"),
    "financial_income": ("Финансовые доходы", "Moliyaviy daromadlar", "Finance income"),
    "financial_expenses": ("Финансовые расходы", "Moliyaviy xarajatlar", "Finance expenses"),
    "receivables": ("Дебиторская задолженность", "Debitorlik qarzi", "Receivables"), "inventories": ("Запасы", "Zaxiralar", "Inventories"),
    "current_liabilities": ("Текущие обязательства", "Joriy majburiyatlar", "Current liabilities"),
    "fixed_assets": ("Основные средства", "Asosiy vositalar", "Fixed assets"), "construction_in_progress": ("Незавершённые вложения", "Tugallanmagan investitsiyalar", "Construction in progress"),
    "long_term_investments": ("Долгосрочные инвестиции", "Uzoq muddatli investitsiyalar", "Long-term investments"),
    "interest_income": ("Процентные доходы", "Foizli daromad", "Interest income"), "interest_expenses": ("Процентные расходы", "Foizli xarajat", "Interest expenses"),
    "noninterest_income": ("Непроцентные доходы", "Foizsiz daromad", "Noninterest income"), "noninterest_expenses": ("Непроцентные расходы", "Foizsiz xarajat", "Noninterest expenses"),
    "operating_expenses": ("Операционные расходы", "Operatsion xarajatlar", "Operating expenses"), "expenses": ("Расходы", "Xarajatlar", "Expenses"),
    "net_revenue_before_operating_expenses": ("Чистый доход до операционных расходов", "Operatsion xarajatlargacha sof daromad", "Net revenue before operating expenses"),
    "central_bank_balances": ("Средства в ЦБ", "Markaziy bankdagi mablag‘lar", "Central bank balances"),
    "loan_portfolio": ("Кредитный портфель", "Kredit portfeli", "Loan portfolio"), "customer_funds": ("Средства клиентов", "Mijozlar mablag‘lari", "Customer funds"),
    "borrowings": ("Заимствования", "Qarz mablag‘lari", "Borrowings"), "loan_reserves": ("Резервы по кредитам", "Kredit zaxiralari", "Loan reserves"),
    "insurance_premiums": ("Страховые премии", "Sug‘urta mukofotlari", "Insurance premiums"), "insurance_claims": ("Страховые выплаты", "Sug‘urta to‘lovlari", "Insurance claims"),
    "gross_insurance_reserves": ("Валовые страховые резервы", "Yalpi sug‘urta zaxiralari", "Gross insurance reserves"),
    "reinsurer_share_in_reserves": ("Доля перестраховщиков", "Qayta sug‘urtalovchilar ulushi", "Reinsurer share"),
    "net_insurance_reserves": ("Чистые страховые резервы", "Sof sug‘urta zaxiralari", "Net insurance reserves"),
    "other_liabilities": ("Прочие обязательства", "Boshqa majburiyatlar", "Other liabilities"),
    "own_cash": ("Собственные деньги", "O‘z pul mablag‘lari", "Own cash"), "client_cash": ("Деньги клиентов", "Mijozlar puli", "Client cash"),
    "settlement_liabilities": ("Расчётные обязательства", "Hisob-kitob majburiyatlari", "Settlement liabilities"),
    "unrealized_fair_value_gain": ("Нереализованная переоценка", "Realizatsiya qilinmagan qayta baholash", "Unrealized revaluation"),
    "dividend_income": ("Дивидендный доход", "Dividend daromadi", "Dividend income"), "management_expenses": ("Расходы управляющего", "Boshqaruvchi xarajatlari", "Management expenses"),
    "due_from_banks": ("Средства в других банках", "Boshqa banklardagi mablag‘lar", "Due from other banks"),
    "demand_deposits": ("Депозиты до востребования", "Talab qilinguncha depozitlar", "Demand deposits"),
    "savings_deposits": ("Сберегательные депозиты", "Jamg‘arma depozitlari", "Savings deposits"),
    "term_deposits": ("Срочные депозиты", "Muddatli depozitlar", "Term deposits"),
    "net_interest_income_before_provisions": ("Чистый процентный доход до оценки кредитных потерь", "Kredit yo‘qotishlarini baholashgacha sof foizli daromad", "Net interest income before the credit-loss estimate"),
    "credit_loss_provisions": ("Расходы на оценку кредитных потерь", "Kredit yo‘qotishlarini baholash xarajatlari", "Credit-loss estimate"),
    "net_interest_income_after_provisions": ("Чистый процентный доход после оценки кредитных потерь", "Kredit yo‘qotishlarini baholashdan keyingi sof foizli daromad", "Net interest income after the credit-loss estimate"),
    "fee_income": ("Комиссионные доходы", "Komission daromadlar", "Fee and commission income"),
    "fee_expenses": ("Комиссионные расходы", "Komission xarajatlar", "Fee and commission expense"),
    "fx_income": ("Доходы по валютным операциям", "Valyuta operatsiyalari daromadi", "Foreign-exchange gains"),
    "fx_expenses": ("Расходы по валютным операциям", "Valyuta operatsiyalari xarajati", "Foreign-exchange losses"),
    "ceded_premiums": ("Премии, переданные в перестрахование", "Qayta sug‘urtaga berilgan mukofotlar", "Premiums ceded to reinsurers"),
    "insurance_service_cost": ("Себестоимость страховых услуг", "Sug‘urta xizmatlari tannarxi", "Cost of insurance services"),
    "insurance_service_result": ("Результат от страховых услуг", "Sug‘urta xizmatlari natijasi", "Insurance-service result"),
    "tax": ("Налог", "Soliq", "Tax"), "portfolio_fair_value": ("Стоимость портфеля", "Portfel qiymati", "Portfolio fair value"),
    "dividends_receivable": ("Дивиденды к получению", "Olinadigan dividendlar", "Dividends receivable"), "accounts_payable": ("Кредиторская задолженность", "Kreditorlik qarzi", "Accounts payable"),
    "level3_investments": ("Инвестиции Level 3", "Level 3 investitsiyalari", "Level 3 investments"), "largest_holding": ("Крупнейшая позиция", "Eng yirik pozitsiya", "Largest holding"), "top5_holdings": ("Пять крупнейших позиций", "Eng yirik beshta pozitsiya", "Top five holdings"),
}


def tr(lang, ru, uz, en):
    return (ru, uz, en)[{"ru": 0, "uz": 1, "en": 2}.get(lang, 0)]


def label(code, lang):
    return tr(lang, *LABELS.get(code, (code, code, code)))


def format_number(value):
    return "—" if value is None else f"{float(value):,.2f}".replace(",", " ")
