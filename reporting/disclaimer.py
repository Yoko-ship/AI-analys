"""Mandatory report disclaimer shared by HTTP and document exports."""

from __future__ import annotations


_EXCEL_DISCLAIMER = {
    "ru": (
        "Аналитические материалы, прогнозы и оценки, представленные на платформе, носят исключительно "
        "информационный характер и подготовлены на основе публично доступных данных. Они не являются "
        "инвестиционными рекомендациями, офертой или призывом к совершению каких-либо операций с ценными "
        "бумагами. Платформа не несёт ответственности за инвестиционные решения, принятые пользователями."
    ),
    "en": (
        "The analytical materials, forecasts, and assessments provided on the platform are for informational "
        "purposes only and are based on publicly available data. They do not constitute investment advice, an "
        "offer, or a solicitation to conduct any transactions with securities. The platform bears no "
        "responsibility for investment decisions made by users."
    ),
    "uz": (
        "Platformada taqdim etilgan tahliliy materiallar, prognozlar va baholar faqat ma'lumot berish maqsadida "
        "tayyorlangan. Ular investitsiya tavsiyasi, taklif yoki qimmatli qog'ozlar bilan operatsiya qilishga "
        "undov hisoblanmaydi. Platforma foydalanuvchilar qarorlari uchun javobgar emas."
    ),
}


REPORT_DISCLAIMER = _EXCEL_DISCLAIMER


def report_disclaimer(language: str = "ru") -> str:
    """Return the mandatory report disclaimer text for the given language (fallback ru)."""
    lang = (language or "ru").strip().lower()[:2]
    return REPORT_DISCLAIMER.get(lang, REPORT_DISCLAIMER["ru"])
