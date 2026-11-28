"""Metric definitions and arithmetic. Unknown denominators never become zero."""
import math

DEFINITIONS = {
    "visits": ("Посещения", "Подтверждённые внешние визиты", "visits"),
    "registrations": ("Регистрации", "Уникальные подтверждённые новые регистрации", "users"),
    "first_paying_customers": ("Новые платящие клиенты", "Уникальные клиенты с первой подтверждённой оплатой по дате события", "users"),
    "advertising_spend": ("Рекламный расход", "Подтверждённые расходы категории advertising", "currency"),
    "revenue": ("Подтверждённая выручка", "Оплаты минус подтверждённые возвраты, без дублей транзакций", "currency"),
    "visit_to_registration": ("Визит → регистрация", "Новые регистрации / визиты × 100%", "percent"),
    "activation": ("Активация", "Активированные в установленное окно / регистрации когорты × 100%", "percent"),
    "registration_to_payment": ("Регистрация → первая оплата", "Первые оплаты в окне / регистрации той же когорты × 100%", "percent"),
    "registration_cost": ("Стоимость регистрации", "Согласованный рекламный расход / отнесённые регистрации", "currency"),
    "advertising_cac": ("Рекламный CAC", "Рекламный расход / отнесённые новые платящие клиенты когорты", "currency"),
    "full_cac": ("Полный CAC", "Все согласованные расходы привлечения / новые платящие клиенты сопоставимой базы", "currency"),
    "ctr": ("CTR", "Подтверждённые клики / измеренные показы × 100%", "percent"),
    "mrr": ("MRR", "Нормализованная месячная регулярная выручка активных подписок", "currency"),
    "arr": ("ARR", "MRR × 12: расчётный годовой темп", "currency"),
    "arpu": ("ARPU", "Регулярная выручка / согласованная активная база пользователей", "currency"),
    "arppu": ("ARPPU", "Регулярная выручка / согласованная активная платящая база", "currency"),
    "retention": ("Удержание", "Активные в окне из исходной когорты / исходная когорта × 100%", "percent"),
    "churn": ("Платный отток", "Ушедшие из платящей базы на начало / платящая база на начало × 100%", "percent"),
    "ltv": ("LTV · оценка", "ARPPU × валовая маржа / стабильный ненулевой месячный отток", "currency"),
    "roi": ("Маркетинговый ROI", "(Отнесённый вклад в прибыль − маркетинговые расходы) / маркетинговые расходы × 100%", "percent"),
    "roas": ("ROAS", "Отнесённая рекламная выручка / фактический рекламный расход", "ratio"),
    "payback": ("Окупаемость CAC", "CAC / месячная маржинальная выручка на клиента", "months"),
}


def metric(key, numerator=None, denominator=None, *, ratio=False, status="complete", reason="", multiplier=1):
    title, formula, unit = DEFINITIONS[key]
    value = None
    if status == "complete":
        if numerator is None or (ratio and (denominator is None or denominator <= 0)):
            status, reason = "no_data", reason or "No comparable nonzero denominator"
        else:
            value = numerator / denominator * multiplier if ratio else numerator
            if not math.isfinite(value):
                value, status, reason = None, "no_data", "Non-finite input"
    return {"title": title, "formula": formula, "unit": unit, "value": value,
            "numerator": numerator, "denominator": denominator, "status": status, "reason": reason}
