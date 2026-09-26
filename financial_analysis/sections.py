"""Parse tagged analytical sections without provider or persistence dependencies."""
from __future__ import annotations

import re


def parse_bullet(line: str) -> dict:
    result = {}
    line = line.lstrip("•–- ").strip()
    for part in line.split("|"):
        if ":" in part:
            key, _, val = part.partition(":")
            result[key.strip()] = val.strip()
    return result


_SECTION_ALIASES = {
    # 7 основных разделов ipoteka-стиля
    "ОБЩИЕ_СВЕДЕНИЯ": ["ОБЩИЕ_СВЕДЕНИЯ", "ОБЩИЕ СВЕДЕНИЯ", "ОБЩАЯ_ИНФОРМАЦИЯ", "GENERAL_INFO", "ОБ_ЭМИТЕНТЕ", "СВЕДЕНИЯ_ОБ_ЭМИТЕНТЕ"],
    "АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ": ["АНАЛИЗ_ФИНРЕЗУЛЬТАТОВ", "АНАЛИЗ ФИНРЕЗУЛЬТАТОВ", "АНАЛИЗ_ФИН_РЕЗУЛЬТАТОВ", "ОТЧЕТ_О_ФИНРЕЗУЛЬТАТАХ", "ОТЧЁТ_О_ФИНРЕЗУЛЬТАТАХ", "ОТЧЕТ_О_ПРИБЫЛЯХ_И_УБЫТКАХ", "ОТЧЁТ_О_ПРИБЫЛЯХ_И_УБЫТКАХ", "INCOME_STATEMENT", "ПРИБЫЛИ_И_УБЫТКИ"],
    "СВОДНАЯ_ТАБЛИЦА": ["СВОДНАЯ_ТАБЛИЦА", "СВОДНАЯ ТАБЛИЦА", "СВОДКА", "SUMMARY_TABLE", "KEY_METRICS_SUMMARY", "ИТОГОВЫЕ_ПОКАЗАТЕЛИ"],
    "ЗАКЛЮЧЕНИЕ": ["ЗАКЛЮЧЕНИЕ", "CONCLUSION", "ОБЩЕЕ_ЗАКЛЮЧЕНИЕ", "ИТОГОВАЯ_ОЦЕНКА"],
    # Существующие
    "СКОРИНГ": ["СКОРИНГ", "SCORING", "ОЦЕНКА", "SCORE"],
    "ДОСЬЕ": ["ДОСЬЕ", "DOSSIER", "КРАТКОЕ_ДОСЬЕ", "КРАТКОЕ ДОСЬЕ"],
    "ЧТО_С_ДЕНЬГАМИ": ["ЧТО_С_ДЕНЬГАМИ", "ЧТО С ДЕНЬГАМИ", "ФИНАНСЫ", "ДЕНЬГИ", "ФИНАНСОВОЕ_СОСТОЯНИЕ"],
    "ТРЕНД": ["ТРЕНД", "TREND", "ТРЕНДЫ", "НАПРАВЛЕНИЕ"],
    "ЭФФЕКТИВНОСТЬ": ["ЭФФЕКТИВНОСТЬ", "EFFICIENCY", "ОБОРАЧИВАЕМОСТЬ"],
    "ТЕХНИЧЕСКИЙ_АНАЛИЗ": ["ТЕХНИЧЕСКИЙ_АНАЛИЗ", "ТЕХНИЧЕСКИЙ АНАЛИЗ", "TECHNICAL_ANALYSIS", "TECHNICAL ANALYSIS", "RSI", "ТЕХАНАЛИЗ"],
    "ФИБОНАЧЧИ": ["ФИБОНАЧЧИ", "FIBONACCI", "ФИБ", "FIB", "ФИБО"],
    "ОЦЕНКА_ЦЕНЫ": ["ОЦЕНКА_ЦЕНЫ", "ОЦЕНКА ЦЕНЫ", "ОЦЕНКА", "ЦЕНА", "СТОИМОСТЬ", "ДОРОГО_ИЛИ_ДЕШЕВО"],
    "КАТАЛИЗАТОРЫ": ["КАТАЛИЗАТОРЫ", "CATALYSTS", "ДВИЖУЩИЕ_СИЛЫ", "ФАКТОРЫ", "НОВОСТИ"],
    "СИЛЬНЫЕ_СТОРОНЫ": ["СИЛЬНЫЕ_СТОРОНЫ", "СИЛЬНЫЕ СТОРОНЫ", "ПЛЮСЫ", "STRENGTHS"],
    "СЛАБЫЕ_СТОРОНЫ": ["СЛАБЫЕ_СТОРОНЫ", "СЛАБЫЕ СТОРОНЫ", "МИНУСЫ", "WEAKNESSES"],
    "ВОЗМОЖНОСТИ": ["ВОЗМОЖНОСТИ", "OPPORTUNITIES"],
    "УГРОЗЫ": ["УГРОЗЫ", "THREATS", "РИСКИ"],
    "ПРОГНОЗ": ["ПРОГНОЗ", "FORECAST", "ПРОГНОЗЫ"],
    "ВЕРДИКТ": ["ВЕРДИКТ", "VERDICT", "РЕШЕНИЕ", "ИТОГОВЫЙ_ВЕРДИКТ"],
    "СОВЕТЫ": ["СОВЕТЫ", "РЕКОМЕНДАЦИИ", "ADVICE", "РЕКОМЕНДАЦИЯ"],
    "ИТОГ": ["ИТОГ", "ИТОГО", "CONCLUSION", "ВЫВОД", "ЗАКЛЮЧЕНИЕ"],
    "РЫНОЧНЫЕ_ДАННЫЕ": ["РЫНОЧНЫЕ_ДАННЫЕ", "РЫНОЧНЫЕ ДАННЫЕ", "MARKET_DATA", "MARKET DATA"],
    "ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА": ["ОГРАНИЧЕНИЯ_ПУБЛИЧНОГО_КОНТУРА", "ОГРАНИЧЕНИЯ ПУБЛИЧНОГО КОНТУРА", "ОГРАНИЧЕНИЯ", "LIMITATIONS"],
    "ЗЕЛЕНЫЕ_ФЛАГИ": ["ЗЕЛЕНЫЕ_ФЛАГИ", "ЗЕЛЁНЫЕ_ФЛАГИ", "GREEN_FLAGS"],
    "КРАСНЫЕ_ФЛАГИ": ["КРАСНЫЕ_ФЛАГИ", "RED_FLAGS"],
}


_ALIAS_MAP = {}


for canonical, aliases in _SECTION_ALIASES.items():
    for alias in aliases:
        _ALIAS_MAP[alias.upper().replace(" ","_")] = canonical


def parse_response(text: str) -> dict:
    """
    Парсит ответ Claude в словарь секций.
    Устойчив к: mixed case, пробелам в метках, markdown заголовкам,
    альтернативным названиям секций.
    """
    sections = {}
    current_key = None
    current_lines = []

    for line in text.splitlines():
        stripped = line.strip()

        # Вариант 1: стандартная метка [СЕКЦИЯ] или [СЕКЦИЯ С ПРОБЕЛОМ]
        m = re.match(r"^\[([A-ZА-ЯЁa-zа-яё_\s]+)\]\s*$", stripped)
        if not m:
            # Вариант 2: метка с текстом после [СЕКЦИЯ] текст
            m = re.match(r"^\[([A-ZА-ЯЁa-zа-яё_\s]+)\]", stripped)

        if m:
            raw_key = m.group(1).strip().upper().replace(" ", "_")
            # Нормализуем через alias map
            canonical = _ALIAS_MAP.get(raw_key, raw_key)

            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = canonical
            # Если после метки есть текст — добавляем как первую строку
            rest = stripped[m.end():].strip()
            current_lines = [rest] if rest else []
            continue

        current_lines.append(line)

    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections
