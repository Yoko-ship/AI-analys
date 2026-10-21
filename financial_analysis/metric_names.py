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


def named(code: str) -> dict[str, str]:
    """The name and meaning fields for one metric code (the code when unknown)."""
    copy = METRIC_NAMES.get(code)
    if not copy:
        return {"name_ru": code, "name_uz": code, "name_en": code}
    keys = ("name_ru", "name_uz", "name_en", "meaning_ru", "meaning_uz", "meaning_en")
    return dict(zip(keys, copy))
