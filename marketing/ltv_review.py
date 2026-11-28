"""An owner's stability assessment applies only to its measured monthly basis."""
from .permissions import timestamp


def eligibility(ctx, opening, lost):
    review = ctx.settings['ltv_stability']
    if not ctx.monthly():
        return False, 'Для LTV нужен завершённый календарный месяц.'
    if not review['confirmed']:
        return False, 'Стабильность оттока не подтверждена владельцем.'
    if (review['period'] != ctx.start.strftime('%Y-%m') or review['currency'] != ctx.settings['currency']
            or review['dataset'] != ctx.settings['dataset'] or set(review['legal_entities']) != set(ctx.settings['legal_entities'])):
        return False, 'Решение о стабильности относится к другому месяцу, валюте, среде или составу форм.'
    if not review['reviewed_at'] or not ctx.end <= timestamp(review['reviewed_at']) <= ctx.cut:
        return False, 'Нет датированного подтверждения стабильности после закрытия месяца и до отсечения данных.'
    if not lost or review['opening_customers'] != len(opening) or review['lost_customers'] != len(lost):
        return False, 'Платящая база или отток изменились после решения о стабильности; требуется новая сверка.'
    month_index = ctx.start.year * 12 + ctx.start.month - 1
    previous = {f'{(month_index-i)//12:04d}-{(month_index-i)%12+1:02d}' for i in (1, 2, 3)}
    if not previous <= {row['period'] for row in review['monthly_rates']}:
        return False, 'Нужны измеренные значения за три последовательных месяца непосредственно перед выбранным.'
    # Stability is an explicit owner assessment, not an invented universal
    # statistical threshold. Changed current counts invalidate that assessment.
    return True, review['note']
