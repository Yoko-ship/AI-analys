"""Names that distinguish canonical returns from statutory closing-balance ratios."""

METRIC_NAMES = {'P1': ('Доходность активов на конец периода (P1)',
        'Davr oxiridagi aktivlar daromadliligi (P1)',
        'Return on closing assets (P1)',
        'Чистая прибыль на каждые 100 сум активов на конец периода',
        'Davr oxiridagi har 100 so‘mlik aktivdan sof foyda',
        'Net profit per 100 UZS of closing assets'),
 'P4': ('Доходность капитала до налога (P4)',
        'Kapitalning soliqdan oldingi daromadliligi (P4)',
        'Pre-tax return on closing equity (P4)',
        'Прибыль до налога на каждые 100 сум капитала на конец периода',
        'Davr oxiridagi har 100 so‘mlik kapitaldan soliqdan oldingi foyda',
        'Pre-tax profit per 100 UZS of closing equity'),
 'roa': ('Рентабельность активов (ROA)',
         'Aktivlar rentabelligi (ROA)',
         'Return on assets (ROA)',
         'Чистая прибыль за период на каждые 100 сум активов, в пересчёте на год',
         'Hisobot davridagi sof foyda har 100 so‘mlik aktivga, yillikka aylantirilgan',
         'Net profit for the reporting period per 100 UZS of assets, annualised'),
 'roe': ('Рентабельность капитала (ROE)',
         'Kapital rentabelligi (ROE)',
         'Return on equity (ROE)',
         'Чистая прибыль за период на каждые 100 сум собственного капитала, в пересчёте на год',
         'Hisobot davridagi sof foyda har 100 so‘mlik o‘z kapitaliga, yillikka aylantirilgan',
         'Net profit for the reporting period per 100 UZS of equity, annualised')}


METRIC_NAMES.update({
    "P2": ("Прибыль до налога / оборотные активы", "Soliqdan oldingi foyda / joriy aktivlar", "Pre-tax profit / current assets"),
    "P3": ("Прибыль до налога / задействованный капитал", "Soliqdan oldingi foyda / ishlatilgan kapital", "Pre-tax profit / capital employed"),
    "P5": ("Валовая маржа", "Yalpi marja", "Gross margin"),
    "P6": ("Валовая прибыль / себестоимость", "Yalpi foyda / tannarx", "Gross profit / cost of sales"),
    "P7": ("Прибыль до налога / выручка", "Soliqdan oldingi foyda / tushum", "Pre-tax profit / revenue"),
    "P8": ("Прибыль до налога / долгосрочные активы", "Soliqdan oldingi foyda / uzoq muddatli aktivlar", "Pre-tax profit / non-current assets"),
    "current_ratio": ("Текущая ликвидность", "Joriy likvidlik", "Current ratio"),
    "quick_ratio": ("Быстрая ликвидность", "Tezkor likvidlik", "Quick ratio"),
    "absolute_liquidity": ("Абсолютная ликвидность", "Mutlaq likvidlik", "Cash ratio"),
    "nim": ("Чистая процентная маржа / средние активы", "Sof foiz marjasi / o‘rtacha aktivlar", "Net interest margin / average assets"),
    "cost_of_risk": ("Стоимость риска", "Xatar qiymati", "Cost of risk"),
    "premium_growth": ("Рост начисленных премий", "Hisoblangan mukofotlar o‘sishi", "Written premium growth"),
    "retention": ("Удержание премий", "Mukofotlarni saqlash", "Premium retention"),
    "loss_ratio": ("Убыточность", "Zararlilik", "Loss ratio"),
    "expense_ratio": ("Доля расходов", "Xarajatlar ulushi", "Expense ratio"),
    "combined_ratio": ("Комбинированный коэффициент", "Kombinatsiyalangan koeffitsient", "Combined ratio"),
    "investment_to_premiums": ("Инвестдоход / премии", "Investitsiya daromadi / mukofotlar", "Investment income / premiums"),
    "net_reserves_to_equity": ("Резервы нетто / капитал", "Sof zaxiralar / kapital", "Net reserves / equity"),
})


METRIC_NAMES.update({'equity_to_assets': ('Капитал к активам', 'Kapitalning aktivlarga nisbati', 'Equity to assets', 'Доля собственного капитала в активах', 'O‘z kapitalining aktivlardagi ulushi', 'Share of assets funded by equity'), 'loans_to_deposits': ('Кредиты к средствам клиентов', 'Kreditlarning mijozlar mablag‘lariga nisbati', 'Loans to customer funds', 'Сколько сум кредитов приходится на каждый сум средств клиентов', 'Mijozlar mablag‘larining har bir so‘miga to‘g‘ri keladigan kredit', 'Loans per 1 UZS of customer funds'), 'liquid_to_deposits': ('Ликвидные средства к средствам клиентов', 'Likvid mablag‘larning mijozlar mablag‘lariga nisbati', 'Liquid funds to customer funds', 'Касса, остатки в ЦБ и в других банках на каждые 100 сум средств клиентов', 'Har 100 so‘mlik mijozlar mablag‘iga kassa, Markaziy bank va boshqa banklardagi qoldiqlar', 'Cash and balances with the central bank and other banks per 100 UZS of customer funds'), 'loan_reserve_coverage': ('Резервы к кредитному портфелю', 'Zaxiralarning kredit portfeliga nisbati', 'Reserves to loans', 'Резервы по кредитам на каждые 100 сум кредитного портфеля', 'Har 100 so‘mlik kredit portfeliga kredit zaxiralari', 'Loan-loss reserves per 100 UZS of the loan portfolio'), 'cost_to_income': ('Операционные расходы к доходу', 'Operatsion xarajatlarning daromadga nisbati', 'Cost to income', 'Операционные расходы на каждые 100 сум чистого дохода до операционных расходов', 'Operatsion xarajatlargacha bo‘lgan har 100 so‘mlik sof daromadga operatsion xarajatlar', 'Operating expenses per 100 UZS of net income before operating expenses'), 'provisions_to_net_interest_income': ('Отчисления в резервы к процентному доходу', 'Zaxira ajratmalarining foiz daromadiga nisbati', 'Provisions to net interest income', 'Отчисления в резервы на каждые 100 сум чистого процентного дохода', 'Har 100 so‘mlik sof foiz daromadiga zaxira ajratmalari', 'Credit-loss provisions per 100 UZS of net interest income'), 'reinsurer_share_of_reserves': ('Доля перестраховщиков в резервах', 'Qayta sug‘urtalovchilarning zaxiralardagi ulushi', 'Reinsurers’ share of reserves', 'Часть страховых резервов, приходящаяся на перестраховщиков', 'Sug‘urta zaxiralarining qayta sug‘urtalovchilarga to‘g‘ri keladigan qismi', 'Part of insurance reserves carried by reinsurers'), 'insurance_reserves_to_liabilities': ('Страховые резервы в обязательствах', 'Majburiyatlardagi sug‘urta zaxiralari', 'Insurance reserves to liabilities', 'Чистые страховые резервы на каждые 100 сум обязательств', 'Har 100 so‘mlik majburiyatga sof sug‘urta zaxiralari', 'Net insurance reserves per 100 UZS of liabilities')})

def named(code: str) -> dict[str, str]:
    """The name and meaning fields for one metric code (the code when unknown)."""
    copy = METRIC_NAMES.get(code)
    if not copy:
        return {"name_ru": code, "name_uz": code, "name_en": code}
    keys = ("name_ru", "name_uz", "name_en", "meaning_ru", "meaning_uz", "meaning_en")
    return dict(zip(keys, copy))
