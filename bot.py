"""
Телеграм бот — Анализатор акций.

Установка:
  pip install python-telegram-bot anthropic pandas python-dotenv selenium seleniumwire

.env файл:
  TELEGRAM_TOKEN=your_bot_token
  ANTHROPIC_API_KEY=your_api_key

Запуск:
  python bot.py
"""

import asyncio
import io
import logging
import traceback
from datetime import datetime
from functools import partial

from dotenv import load_dotenv
import os

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from analyzer import (
    df_to_annual,
    df_to_quarterly,
    research_company_online,
    build_company_profile,
    run_analysis,
    build_html,
)
from main import get_data
from cache import cache as analysis_cache
from company_catalog import COMPANY_CATALOG
from users import (
    user_db,
    TIER_ADMIN,
    FREE_DAILY_LIMIT,
)

load_dotenv()

# ─────────────────────────────────────────────────────────
# КОНФИГ
# ─────────────────────────────────────────────────────────

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не найден в .env")

# Username администратора для фидбека (можно изменить в .env)
FEEDBACK_USERNAME = os.getenv("FEEDBACK_USERNAME", "@your_username")

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_COMPANY = 1

STAGES = [
    ("🌐", "Собираю финансовые данные..."),
    ("🔍", "Ищу информацию в интернете..."),
    ("📋", "Составляю профиль компании..."),
    ("📊", "Провожу инвестиционный анализ..."),
    ("📄", "Формирую отчёт..."),
]


# ─────────────────────────────────────────────────────────
# ПАРСЕР СЕКЦИЙ
# ─────────────────────────────────────────────────────────

# Alias map для бота (та же что в analyzer.py)
_BOT_ALIAS_MAP = {
    "СКОРИНГ":"СКОРИНГ","SCORING":"СКОРИНГ",
    "ДОСЬЕ":"ДОСЬЕ","DOSSIER":"ДОСЬЕ","КРАТКОЕ_ДОСЬЕ":"ДОСЬЕ",
    "ЧТО_С_ДЕНЬГАМИ":"ЧТО_С_ДЕНЬГАМИ","ЧТО С ДЕНЬГАМИ":"ЧТО_С_ДЕНЬГАМИ","ФИНАНСЫ":"ЧТО_С_ДЕНЬГАМИ",
    "ТРЕНД":"ТРЕНД","TREND":"ТРЕНД","ТРЕНДЫ":"ТРЕНД",
    "ФИБОНАЧЧИ":"ФИБОНАЧЧИ","FIBONACCI":"ФИБОНАЧЧИ","ФИБ":"ФИБОНАЧЧИ",
    "ОЦЕНКА_ЦЕНЫ":"ОЦЕНКА_ЦЕНЫ","ОЦЕНКА ЦЕНЫ":"ОЦЕНКА_ЦЕНЫ","ОЦЕНКА":"ОЦЕНКА_ЦЕНЫ","СТОИМОСТЬ":"ОЦЕНКА_ЦЕНЫ",
    "КАТАЛИЗАТОРЫ":"КАТАЛИЗАТОРЫ","ФАКТОРЫ":"КАТАЛИЗАТОРЫ","НОВОСТИ":"КАТАЛИЗАТОРЫ",
    "СИЛЬНЫЕ_СТОРОНЫ":"СИЛЬНЫЕ_СТОРОНЫ","СИЛЬНЫЕ СТОРОНЫ":"СИЛЬНЫЕ_СТОРОНЫ","ПЛЮСЫ":"СИЛЬНЫЕ_СТОРОНЫ",
    "СЛАБЫЕ_СТОРОНЫ":"СЛАБЫЕ_СТОРОНЫ","СЛАБЫЕ СТОРОНЫ":"СЛАБЫЕ_СТОРОНЫ","МИНУСЫ":"СЛАБЫЕ_СТОРОНЫ",
    "ПРОГНОЗ":"ПРОГНОЗ","FORECAST":"ПРОГНОЗ",
    "ВЕРДИКТ":"ВЕРДИКТ","VERDICT":"ВЕРДИКТ","РЕШЕНИЕ":"ВЕРДИКТ",
    "СОВЕТЫ":"СОВЕТЫ","РЕКОМЕНДАЦИИ":"СОВЕТЫ",
    "ИТОГ":"ИТОГ","ВЫВОД":"ИТОГ","ЗАКЛЮЧЕНИЕ":"ИТОГ","CONCLUSION":"ИТОГ",
    "ЗЕЛЕНЫЕ_ФЛАГИ":"ЗЕЛЕНЫЕ_ФЛАГИ","ЗЕЛЁНЫЕ_ФЛАГИ":"ЗЕЛЕНЫЕ_ФЛАГИ",
    "КРАСНЫЕ_ФЛАГИ":"КРАСНЫЕ_ФЛАГИ",
}

def parse_sections(text: str) -> dict:
    import re
    sections, current_key, current_lines = {}, None, []
    for line in text.splitlines():
        stripped = line.strip()
        m = re.match(r"^\[([A-ZА-ЯЁa-zа-яё_\s]+)\]", stripped)
        if m:
            raw = m.group(1).strip().upper().replace(" ", "_")
            canonical = _BOT_ALIAS_MAP.get(raw, raw)
            if current_key:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = canonical
            rest = stripped[m.end():].strip()
            current_lines = [rest] if rest else []
        else:
            current_lines.append(line)
    if current_key:
        sections[current_key] = "\n".join(current_lines).strip()
    return sections


def get_verdict(sections: dict) -> tuple[str, str, str, str]:
    """Возвращает (emoji, label, css_class, reason). Поддерживает 5 уровней."""
    emoji, label, css, reason = "🟡", "НАБЛЮДАТЬ", "yellow", ""
    for line in sections.get("ВЕРДИКТ", "").splitlines():
        ls = line.strip()
        if ls.lower().startswith("метка:"):
            raw = ls.partition(":")[2].strip()
            up  = raw.upper()
            if "ПОКУПАТЬ" in up:
                emoji, label, css = "🟢", "ПОКУПАТЬ", "green"
            elif "ДЕРЖАТЬ" in up:
                emoji, label, css = "🟢", "ДЕРЖАТЬ", "green"
            elif "НАБЛЮДАТЬ" in up:
                emoji, label, css = "🟡", "НАБЛЮДАТЬ", "yellow"
            elif "ОСТОРОЖНО" in up:
                emoji, label, css = "🟠", "ОСТОРОЖНО", "orange"
            elif "ВОЗДЕРЖАТЬСЯ" in up:
                emoji, label, css = "🔴", "ВОЗДЕРЖАТЬСЯ", "red"
            elif "🟢" in raw:
                emoji, label, css = "🟢", raw.replace("🟢","").strip(), "green"
            elif "🔴" in raw:
                emoji, label, css = "🔴", raw.replace("🔴","").strip(), "red"
        elif ls.lower().startswith("обоснование:"):
            reason = ls.partition(":")[2].strip()
    return emoji, label, css, reason


def get_forecast_lines(sections: dict) -> list[str]:
    lines = []
    icons = {
        "рост прибыли":      "📈",
        "долговая нагрузка": "🏦",
        "ликвидность":       "💧",
    }
    trend_icons = {
        "высокая": "↑", "высок": "↑", "улучшение": "↑",
        "низкая":  "↓", "низк":  "↓", "ухудшение": "↓",
    }
    for raw_line in sections.get("ПРОГНОЗ", "").splitlines():
        low = raw_line.strip().lower()
        for key, icon in icons.items():
            if low.startswith(key):
                val = raw_line.partition(":")[2].strip().split("—")[0].strip()
                arrow = next((v for k, v in trend_icons.items() if k in val.lower()), "→")
                lines.append(f"{icon} {val} {arrow}")
                break
    return lines


def format_liquidity_brief(liquidity: dict | None) -> str:
    if not liquidity:
        return ""

    label_map = {
        "high": "высокая",
        "medium": "средняя",
        "low": "низкая",
    }
    label = label_map.get(str(liquidity.get("liquidity_label", "")).lower(), "нет данных")
    trade_days = liquidity.get("trade_days")
    avg_trade_value = liquidity.get("avg_trade_value")

    parts = [f"Ликвидность: {label}"]
    if trade_days is not None:
        parts.append(f"дней с торгами: {trade_days}/30")
    if avg_trade_value is not None:
        try:
            parts.append(f"средняя сделка: {float(avg_trade_value):,.0f} UZS")
        except (TypeError, ValueError):
            pass
    return "💧 " + " · ".join(parts)


def get_bullets(text: str, key_fact: str, key_num: str, limit: int) -> list[str]:
    result = []
    for line in text.splitlines():
        if not line.strip().startswith("•"):
            continue
        parts = {}
        for p in line.lstrip("• ").split("|"):
            if ":" in p:
                k, _, v = p.partition(":")
                parts[k.strip().lower()] = v.strip()
        fact = parts.get(key_fact, "")
        num  = parts.get(key_num, "")
        if fact:
            result.append(f"{fact}" + (f" — {num}" if num else ""))
        if len(result) >= limit:
            break
    return result


# ─────────────────────────────────────────────────────────
# ФОРМАТТЕРЫ (3 режима)
# ─────────────────────────────────────────────────────────

def fmt_short(sections: dict, company: str, cost: float, liquidity: dict | None = None) -> str:
    """
    Кратко — только самое важное.
    Вердикт + 2 плюса + 2 минуса + итог. ~10 секунд чтения.
    """
    emoji, label, _, reason = get_verdict(sections)
    pros  = get_bullets(sections.get("СИЛЬНЫЕ_СТОРОНЫ", ""), "факт", "цифра", 2)
    cons  = get_bullets(sections.get("СЛАБЫЕ_СТОРОНЫ",  ""), "факт", "цифра", 2)
    itog  = sections.get("ИТОГ", "").strip()
    forecast = get_forecast_lines(sections)

    lines = [
        f"{emoji} *{label}*",
        f"_{reason}_" if reason else "",
        "",
    ]

    if pros:
        lines.append("✅ " + "\n✅ ".join(pros))
    if cons:
        lines.append("⚠️ " + "\n⚠️ ".join(cons))

    if forecast:
        lines.append("")
        lines.append("  ".join(forecast))

    liquidity_line = format_liquidity_brief(liquidity)
    if liquidity_line:
        lines += ["", liquidity_line]

    if itog:
        lines += ["", f"💬 _{itog}_"]

    lines += [
        "",
        f"━━━━━━━━━━━━━━━",
        "⚠️ _Не является рекомендацией_",
    ]
    return "\n".join(l for l in lines if l is not None)


def fmt_detailed(sections: dict, company: str,
                 annual_period: str, quarterly_period: str, cost: float,
                 liquidity: dict | None = None) -> str:
    """
    Подробно — полный разбор с цифрами и флагами.
    """
    emoji, label, _, reason = get_verdict(sections)

    def swot_block(raw: str, key_fact: str, key_num: str,
                   key_sig: str, limit: int) -> list[str]:
        out = []
        for line in raw.splitlines():
            if not line.strip().startswith("•"):
                continue
            parts = {}
            for p in line.lstrip("• ").split("|"):
                if ":" in p:
                    k, _, v = p.partition(":")
                    parts[k.strip().lower()] = v.strip()
            fact = parts.get(key_fact, "")
            num  = parts.get(key_num, "")
            sig  = parts.get(key_sig, "")
            if fact:
                row = f"*{fact}*"
                if num: row += f"\n  `{num}`"
                if sig: row += f"\n  _{sig}_"
                out.append(row)
            if len(out) >= limit:
                break
        return out

    pros  = swot_block(sections.get("СИЛЬНЫЕ_СТОРОНЫ", ""), "факт","цифра","значимость", 3)
    cons  = swot_block(sections.get("СЛАБЫЕ_СТОРОНЫ",  ""), "факт","цифра","значимость", 3)
    opps  = swot_block(sections.get("ВОЗМОЖНОСТИ",     ""), "факт","цифра","значимость", 2)
    risks = swot_block(sections.get("УГРОЗЫ",          ""), "факт","цифра","значимость", 2)

    def flag_block(raw: str, icon: str, limit: int) -> list[str]:
        out = []
        for line in raw.splitlines():
            if not line.strip().startswith("•"):
                continue
            parts = {}
            for p in line.lstrip("• ").split("|"):
                if ":" in p:
                    k, _, v = p.partition(":")
                    parts[k.strip().lower()] = v.strip()
            sig = parts.get("сигнал", "")
            exp = parts.get("объяснение", "")
            if sig:
                out.append(f"{icon} *{sig}*" + (f"\n  _{exp}_" if exp else ""))
            if len(out) >= limit:
                break
        return out

    green_flags = flag_block(sections.get("ЗЕЛЕНЫЕ_ФЛАГИ", ""), "✅", 3)
    red_flags   = flag_block(sections.get("КРАСНЫЕ_ФЛАГИ", ""), "🚩", 3)
    forecast    = get_forecast_lines(sections)

    # Советы
    tips = sections.get("СОВЕТЫ", "")
    share, horizon = "", ""
    for line in tips.splitlines():
        ls = line.strip()
        if ls.lower().startswith("доля"):    share   = ls.partition(":")[2].strip()
        elif ls.lower().startswith("горизонт"): horizon = ls.partition(":")[2].strip()

    itog = sections.get("ИТОГ", "").strip()

    out = [
        f"{emoji} *{label}* — {company}",
        f"_{reason}_" if reason else "",
        "📅 " + annual_period + (
            f" | {quarterly_period}" if "недоступны" not in quarterly_period else ""
        ),
        "",
    ]

    if pros:
        out += ["*💪 Сильные стороны:*"] + [f"• {p}" for p in pros] + [""]
    if cons:
        out += ["*⚠️ Слабые стороны:*"] + [f"• {p}" for p in cons] + [""]
    if opps:
        out += ["*🚀 Возможности:*"] + [f"• {p}" for p in opps] + [""]
    if risks:
        out += ["*🔥 Угрозы:*"] + [f"• {p}" for p in risks] + [""]
    if green_flags:
        out += ["*Зелёные флаги:*"] + green_flags + [""]
    if red_flags:
        out += ["*Красные флаги:*"] + red_flags + [""]
    if forecast:
        out += ["*📊 Прогноз:*", "  ".join(forecast), ""]
    liquidity_line = format_liquidity_brief(liquidity)
    if liquidity_line:
        out += [f"*💧 Ликвидность акции:* {liquidity_line.replace('💧 ', '')}", ""]
    if share or horizon:
        tips_parts = []
        if share:   tips_parts.append(f"Доля: {share}")
        if horizon: tips_parts.append(f"Горизонт: {horizon}")
        out += ["*💼 Если покупать:* " + " · ".join(tips_parts), ""]
    if itog:
        out += [f"💬 _{itog}_", ""]

    out += [
        "━━━━━━━━━━━━━━━",
        "⚠️ _Не является рекомендацией_",
    ]
    return "\n".join(l for l in out if l is not None)


# ─────────────────────────────────────────────────────────
# КНОПКИ
# ─────────────────────────────────────────────────────────

def view_keyboard(active: str = "", cached: bool = False, company_key: str = "",
                  allow_refresh: bool = False) -> InlineKeyboardMarkup:
    """Кнопки выбора режима просмотра."""
    def btn(label: str, mode: str) -> InlineKeyboardButton:
        text = f"· {label} ·" if mode == active else label
        return InlineKeyboardButton(text, callback_data=f"view:{mode}")

    rows = [
        [
            btn("📋 Кратко",    "short"),
            btn("📊 Подробно",  "detailed"),
            btn("📄 HTML файл", "html"),
        ],
    ]
    # Если результат из кэша — добавляем кнопку обновления
    if cached and company_key and allow_refresh:
        rows.append([
            InlineKeyboardButton(
                "🔄 Обновить анализ",
                callback_data=f"cache:refresh:{company_key}"
            )
        ])
    rows.append([InlineKeyboardButton("🔍 Новый анализ", callback_data="new_analysis")])
    return InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ
# ─────────────────────────────────────────────────────────

def build_progress_text(stage: int, company: str, done=False, error=False) -> str:
    lines = [f"🏢 *Анализирую: {company}*\n"]
    for i, (icon, text) in enumerate(STAGES):
        if error and i == stage:
            lines.append(f"❌ {text}")
        elif i < stage or (done and i == stage):
            lines.append(f"✅ {text}")
        elif i == stage:
            lines.append(f"{icon} *{text}*")
        else:
            lines.append(f"⬜ {text}")
    if not done and not error:
        lines.append("\n_⏳ Подождите — это занимает 1–3 минуты_")
    elif done:
        lines.append("\n✨ *Готово! Выбери формат:*")
    elif error:
        lines.append("\n❌ *Произошла ошибка*")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────
# ОСНОВНОЙ АНАЛИЗ
# ─────────────────────────────────────────────────────────

async def run_full_analysis(company_name: str, progress_callback) -> dict:
    loop = asyncio.get_event_loop()

    # Этап 0 — финансовые данные
    await progress_callback(0)

    annual_df, quarter_df, liquidity_df, fetched_name = await loop.run_in_executor(
        None, partial(get_data, company_name)
    )
    if annual_df is None or quarter_df is None:
        raise ValueError(f"Данные не найдены для «{company_name}»")

    annual_data    = await loop.run_in_executor(None, df_to_annual,    annual_df)
    quarterly_data = await loop.run_in_executor(None, df_to_quarterly, quarter_df)
    liquidity_data = (
        liquidity_df.iloc[0].to_dict()
        if liquidity_df is not None and not liquidity_df.empty
        else None
    )
    name = fetched_name or company_name

    # Этап 1 — веб-исследование
    await progress_callback(1)
    web = await loop.run_in_executor(None, research_company_online, name)

    # Этап 2 — профиль
    await progress_callback(2)
    profile = await loop.run_in_executor(
        None, partial(build_company_profile, name, annual_data, quarterly_data, web, liquidity_data)
    )

    # Этап 3 — анализ
    await progress_callback(3)
    raw, annual_period, quarterly_period, cost, metrics = await loop.run_in_executor(
        None, partial(run_analysis, name, profile, web, annual_data, quarterly_data, liquidity_data)
    )

    # Этап 4 — HTML
    await progress_callback(4)
    html = await loop.run_in_executor(
        None, partial(build_html, name, profile, web, raw, annual_period, quarterly_period, cost, metrics)
    )

    return {
        "company_name":     name,
        "html_report":      html,
        "raw_analysis":     raw,
        "sections":         parse_sections(raw),
        "annual_period":    annual_period,
        "quarterly_period": quarterly_period,
        "cost":             cost,
        "metrics":          metrics,
        "liquidity":        liquidity_data,
    }


# ─────────────────────────────────────────────────────────
# ОБРАБОТЧИКИ
# ─────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    db_user = user_db.upsert(user)  # регистрируем / обновляем
    await update.message.reply_text(
        f"👋 Привет, {user.first_name}!\n\n"
        f"Я анализирую акции узбекских компаний с биржи.\n\n"
        f"🔍 Что делаю:\n"
        f"  • Собираю финансовые данные\n"
        f"  • Ищу новости о компании\n"
        f"  • Провожу ИИ-анализ\n"
        f"  • Даю вердикт: инвестировать или нет\n\n"
        f"⏱ Время анализа: 1–3 минуты\n"
        f"📦 Статус: {db_user.sub_status}\n\n"
        f"Напиши /analyze чтобы начать 👇",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Начать анализ", callback_data="new_analysis")],
            [InlineKeyboardButton("❓ Помощь",        callback_data="help")],
        ]),
    )
    return WAITING_COMPANY


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = (
        "📖 *Как пользоваться:*\n\n"
        "1️⃣ Напиши тикер или название компании\n"
        "   Например: `ALKB`, `HMKB`, `QATT`\n\n"
        "2️⃣ Посмотри список компаний: `/companies`\n\n"
        "3️⃣ Подожди 1–3 минуты\n\n"
        "4️⃣ Выбери формат результата:\n"
        "   📋 *Кратко* — вердикт + главное за 10 сек\n"
        "   📊 *Подробно* — полный разбор с цифрами\n"
        "   📄 *HTML файл* — красивый отчёт для браузера\n\n"
        "🎁 *Бесплатный тариф:*\n"
        "   • 3 новых анализа в день\n"
        "   • ♾️ Безлимитно из кэша — повторные запросы бесплатны\n\n"
        "*Команды:*\n"
        "/analyze  — новый анализ\n"
        "/companies — список компаний\n"
        "/me       — мой профиль и лимиты\n"
        "/feedback — написать отзыв\n"
        "/cancel   — отменить\n"
        "/help     — эта справка\n\n"
        "⚠️ _Не является инвестиционной рекомендацией_"
    )
    if update.message:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    else:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    return WAITING_COMPANY


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🏢 *Введи название компании или тикер:*\n\n"
        "Или выбери из примеров:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("ALKB", callback_data="company:ALKB"),
                InlineKeyboardButton("QATT",  callback_data="company:QATT"),
                InlineKeyboardButton("HMKB", callback_data="company:HMKB"),
            ],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
        ]),
    )
    return WAITING_COMPANY


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ Отменено.\n\nНапиши /analyze чтобы начать новый анализ."
    )
    return ConversationHandler.END


async def receive_company(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    company = update.message.text.strip()
    if not company:
        await update.message.reply_text("⚠️ Введи название компании.")
        return WAITING_COMPANY
    return await _start_analysis(update, context, company, is_callback=False)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data  = query.data
    chat_id = update.effective_chat.id

    # ── Переключение режима просмотра ────────────────────
    if data.startswith("view:"):
        mode = data.split(":")[1]
        result = context.chat_data.get("last_result")

        if not result:
            await query.edit_message_text(
                "⚠️ Результат устарел. Запусти новый анализ через /analyze"
            )
            return ConversationHandler.END

        sections = result["sections"]
        name     = result["company_name"]
        cost     = result["cost"]

        if mode == "short":
            text = fmt_short(sections, name, cost, result.get("liquidity"))
            await query.edit_message_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=view_keyboard("short"),
            )

        elif mode == "detailed":
            text = fmt_detailed(
                sections, name,
                result["annual_period"], result["quarterly_period"], cost,
                result.get("liquidity")
            )
            # Telegram лимит — 4096 символов. Если длиннее — режем и шлём новым сообщением
            if len(text) <= 4096:
                await query.edit_message_text(
                    text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=view_keyboard("detailed"),
                )
            else:
                # Редактируем текущее на заглушку, потом шлём длинный текст новым сообщением
                await query.edit_message_text(
                    f"📊 *Подробный анализ: {name}*\n\n_Смотри следующее сообщение_ 👇",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=view_keyboard("detailed"),
                )
                # Режем по 4096 и шлём частями
                for i in range(0, len(text), 4000):
                    chunk = text[i:i+4000]
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode=ParseMode.MARKDOWN,
                    )

        elif mode == "html":
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            html_bytes = result["html_report"].encode("utf-8")
            buf = io.BytesIO(html_bytes)
            buf.name = f"report_{name.replace(' ','_')}_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
            await context.bot.send_document(
                chat_id=chat_id,
                document=buf,
                caption=(
                    f"📄 *{name}* — полный отчёт\n"
                    f"Открой файл в браузере для интерактивного просмотра."
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
        return ConversationHandler.END

    # ── Навигация ────────────────────────────────────────
    if data == "new_analysis":
        await query.edit_message_text(
            "🏢 *Введи название компании или тикер:*\n\nИли выбери из примеров:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("ALKB", callback_data="company:ALKB"),
                    InlineKeyboardButton("QATT",  callback_data="company:QATT"),
                    InlineKeyboardButton("HMKB", callback_data="company:HMKB"),
                ],
                [InlineKeyboardButton("❌ Отмена", callback_data="cancel")],
            ]),
        )
        return WAITING_COMPANY

    if data == "help":
        return await cmd_help(update, context)

    if data == "cancel":
        await query.edit_message_text("❌ Отменено. /analyze — новый анализ.")
        return ConversationHandler.END

    if data.startswith("cache:refresh:"):
        user = user_db.get(update.effective_user.id)
        if not user or not user.is_admin:
            await query.answer("⛔ Только администратор может обновлять анализ.", show_alert=True)
            return ConversationHandler.END
        company = data.split(":", 2)[2]
        analysis_cache.invalidate(company)
        await query.answer("🔄 Кэш сброшен, запускаю свежий анализ...")
        return await _start_analysis(
            update, context, company,
            is_callback=True, force_refresh=True
        )

    if data.startswith("company:"):
        company = data.split(":", 1)[1]
        return await _start_analysis(update, context, company, is_callback=True)

    return WAITING_COMPANY


# ─────────────────────────────────────────────────────────
# ЯДРО: ЗАПУСК АНАЛИЗА
# ─────────────────────────────────────────────────────────

async def _start_analysis(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           company: str, is_callback: bool = False,
                           force_refresh: bool = False) -> int:
    chat_id   = update.effective_chat.id
    tg_user   = update.effective_user

    # Регистрируем / обновляем пользователя
    db_user = user_db.upsert(tg_user)

    # Кэш всегда доступен даже при исчерпанном лимите
    if force_refresh or not analysis_cache.get(company):
        ok, reason = user_db.can_analyze(tg_user.id)
        if not ok:
            await context.bot.send_message(
                chat_id=chat_id, text=reason,
                parse_mode=ParseMode.MARKDOWN,
            )
            return ConversationHandler.END

    # ── Проверяем кэш (если не принудительное обновление) ────────────
    if not force_refresh:
        cached = analysis_cache.get(company)
        if cached:
            context.chat_data["last_result"] = cached

            # Записываем в историю (из кэша — бесплатно)
            user_db.record_analysis(tg_user.id, cached["company_name"],
                                    cost=0.0, from_cache=True)

            emoji, label, _, reason = get_verdict(cached["sections"])
            forecast     = get_forecast_lines(cached["sections"])
            forecast_str = "  ".join(forecast) if forecast else ""

            verdict_text = (
                f"{emoji} *{label}*\n"
                f"_{reason}_\n"
            )
            if forecast_str:
                verdict_text += f"\n{forecast_str}\n"
            liquidity_str = format_liquidity_brief(cached.get("liquidity"))
            if liquidity_str:
                verdict_text += f"\n{liquidity_str}\n"
            verdict_text += (
                f"\n🏢 *{cached['company_name']}*\n"
                f"📅 {cached['annual_period']}" + (
                    f" | {cached['quarterly_period']}"
                    if "недоступны" not in cached["quarterly_period"] else ""
                ) + "\n\n"
                f"📦 _Из кэша — анализ сделан {cached['age_str']}_\n"
                f"_Актуален ещё {cached['expires_in_days']} дн._\n\n"
                f"👇 *Выбери что показать:*"
            )

            send_fn = (
                update.callback_query.edit_message_text
                if is_callback else
                update.message.reply_text
            )
            await send_fn(
                verdict_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=view_keyboard(
                    cached=True,
                    company_key=company,
                    allow_refresh=db_user.is_admin,
                ),
            )
            return ConversationHandler.END

    # ── Кэша нет или force_refresh — запускаем полный анализ ──────────
    if is_callback:
        progress_msg = await update.callback_query.edit_message_text(
            build_progress_text(0, company),
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        progress_msg = await update.message.reply_text(
            build_progress_text(0, company),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def update_progress(stage: int):
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            await progress_msg.edit_text(
                build_progress_text(stage, company),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    try:
        result = await run_full_analysis(company, update_progress)

        # Сохраняем в кэш, историю пользователя и в chat_data
        analysis_cache.set(company, result)
        user_db.record_analysis(tg_user.id, result["company_name"],
                                cost=result["cost"], from_cache=False)
        context.chat_data["last_result"] = result

        await progress_msg.edit_text(
            build_progress_text(len(STAGES), company, done=True),
            parse_mode=ParseMode.MARKDOWN,
        )

        emoji, label, _, reason = get_verdict(result["sections"])
        forecast     = get_forecast_lines(result["sections"])
        forecast_str = "  ".join(forecast) if forecast else ""

        verdict_text = (
            f"{emoji} *{label}*\n"
            f"_{reason}_\n"
        )
        if forecast_str:
            verdict_text += f"\n{forecast_str}\n"
        liquidity_str = format_liquidity_brief(result.get("liquidity"))
        if liquidity_str:
            verdict_text += f"\n{liquidity_str}\n"
        verdict_text += (
            f"\n🏢 *{result['company_name']}*\n"
            f"📅 {result['annual_period']}" + (
                f" | {result['quarterly_period']}"
                if "недоступны" not in result["quarterly_period"] else ""
            ) + "\n\n"
            f"👇 *Выбери что показать:*"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=verdict_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=view_keyboard(),
        )

    except ValueError as e:
        await progress_msg.edit_text(
            build_progress_text(0, company, error=True),
            parse_mode=ParseMode.MARKDOWN,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"❌ *Данные не найдены*\n\n"
                f"Компания: `{company}`\n"
                f"_{str(e)}_\n\n"
                f"Попробуй другой тикер или название."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="new_analysis")]
            ]),
        )

    except Exception as e:
        logger.error(f"Ошибка анализа:\n{traceback.format_exc()}")
        await progress_msg.edit_text(
            build_progress_text(0, company, error=True),
            parse_mode=ParseMode.MARKDOWN,
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                f"⚠️ *Произошла ошибка*\n\n"
                f"`{str(e)[:300]}`\n\n"
                f"Попробуй позже."
            ),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Попробовать снова", callback_data="new_analysis")]
            ]),
        )

    return ConversationHandler.END


async def cmd_cache(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /cache — статистика и список кэшированных компаний."""
    stats   = analysis_cache.stats()
    entries = analysis_cache.list_all()

    lines = [
        "🗄 Кэш анализов\n",
        f"📊 Всего записей: {stats['total']}",
        f"✅ Актуальных:    {stats['fresh']}",
        f"⏰ Устаревших:    {stats['expired']}",
        f"🔁 Всего хитов:  {stats['total_hits']}",
        f"💰 Потрачено:    ~${stats['total_cost']:.2f}",
        f"💚 Сэкономлено:  ~${stats['saved_cost']:.2f}",
    ]

    if entries:
        lines += ["", "📋 Компании в кэше:"]
        for e in entries:
            status = "✅" if e["is_fresh"] else "⏰"
            lines.append(
                f"{status} {e['company_name']} — {e['age_str']}"
                + (f", ещё {e['expires_in_days']} дн." if e["is_fresh"] else " (устарел)")
                + f" (открыт {e['hit_count']} раз)"
            )
    else:
        lines.append("\nКэш пуст — анализов ещё не было")

    ttl_days = analysis_cache.ttl_secs // 86400
    lines += ["", f"TTL кэша: {ttl_days} дней (CACHE_TTL_DAYS в .env)"]

    await update.message.reply_text("\n".join(lines))


async def cmd_companies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/companies — список доступных компаний и тикеров."""
    lines = [
        "🏢 *Доступные компании*",
        "",
        "Можешь отправить боту тикер или название компании.",
        "Например: `HMKB`, `ALKB`, `UzAuto Motors`",
        "",
    ]

    for company_name, ticker in COMPANY_CATALOG.items():
        lines.append(f"`{ticker}` — {company_name}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/me — профиль пользователя и история запросов."""
    tg_user = update.effective_user
    user    = user_db.upsert(tg_user)
    history = user_db.user_history(tg_user.id, limit=5)

    free_used_today = user.analyses_today if not user.is_pro else 0
    free_left = (
        max(0, FREE_DAILY_LIMIT - free_used_today)
        if FREE_DAILY_LIMIT > 0 and not user.is_pro
        else "∞"
    )

    lines = [
        f"👤 Мой профиль\n",
        f"Имя: {user.full_name}",
        f"ID: {user.user_id}",
        f"Статус: {user.sub_status}",
        f"В боте с: {user.joined_at.strftime('%d.%m.%Y')}",
        f"Анализов сделано: {user.total_analyses}",
        f"Из кэша: безлимит всегда",
    ]

    if not user.is_pro:
        lines.insert(-1, f"Новых сегодня использовано: {free_used_today}/{FREE_DAILY_LIMIT}")
        lines.insert(-1, f"Осталось новых сегодня: {free_left}")
    else:
        lines.insert(-1, "Новых анализов: безлимит")

    if history:
        lines += ["", "📋 Последние запросы:"]
        for h in history:
            icon = "📦" if h["from_cache"] else "🔍"
            lines.append(
                f"{icon} {h['company']} — {h['date'].strftime('%d.%m %H:%M')}"
            )

    await update.message.reply_text("\n".join(lines))


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/admin — статистика бота (только для администраторов)."""
    tg_user = update.effective_user
    user    = user_db.get(tg_user.id)

    if not user or not user.is_admin:
        await update.message.reply_text("⛔ Нет доступа.")
        return

    s = user_db.stats()

    lines = [
        "📊 Статистика бота\n",
        f"👥 Пользователей: {s['total_users']}",
        f"  • Новых сегодня: {s['new_today']}",
        f"  • Активных за неделю: {s['active_week']}",
        f"  • PRO: {s['pro_users']}",
        f"  • Заблокировано: {s['banned_users']}",
        "",
        f"🔍 Анализов сегодня: {s['analyses_today']}",
        f"🔍 Анализов всего: {s['analyses_total']}",
        f"💰 Потрачено: ~${s['cost_total']:.2f}",
        f"💚 Сэкономлено кэшом: ~${s['cost_saved']:.2f}",
    ]

    if s["top_companies"]:
        lines += ["", "🏆 Топ компаний:"]
        for i, (name, cnt) in enumerate(s["top_companies"], 1):
            lines.append(f"  {i}. {name} — {cnt} запросов")

    await update.message.reply_text("\n".join(lines))


async def cmd_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/feedback — показывает контакт для отзывов."""
    await update.message.reply_text(
        f"💬 *Обратная связь*\n\n"
        f"Нашёл баг? Есть идея? Хочешь PRO-доступ?\n\n"
        f"Пиши напрямую: {FEEDBACK_USERNAME}\n\n"
        f"_Отвечаем в течение 24 часов_",
        parse_mode=ParseMode.MARKDOWN,
    )


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Напиши /analyze чтобы начать анализ\nили /help для справки.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Начать анализ", callback_data="new_analysis")],
        ]),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Глобальная ошибка: {context.error}", exc_info=context.error)


# ─────────────────────────────────────────────────────────
# ЗАПУСК
# ─────────────────────────────────────────────────────────

def main():
    # ── DECOMMISSIONED — ТЗ compliance (product decision 2026-07-09) ──────────
    # This Telegram bot emitted buy/sell/hold recommendations, stop-loss levels and
    # valuation verdicts that the ТЗ forbids ("Купить/Продать/Держать" запрещено даже
    # в закрытом контуре). It is retired: it no longer starts or serves analysis.
    # No code is deleted (analyzer.py compute helpers are still used by the web path);
    # set BOT_ENABLED=1 only to run the legacy bot locally for debugging.
    if os.getenv("BOT_ENABLED", "0") != "1":
        print("⛔ Telegram bot decommissioned for ТЗ compliance — not starting. "
              "Set BOT_ENABLED=1 to override (legacy/debug only).")
        return

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    async def post_init(application):
        await application.bot.set_my_commands([
            BotCommand("start",    "Начало работы"),
            BotCommand("analyze",  "Анализировать компанию"),
            BotCommand("companies", "Список компаний"),
            BotCommand("me",       "Мой профиль и лимиты"),
            BotCommand("feedback", "Написать отзыв / связаться"),
            BotCommand("help",     "Справка"),
            BotCommand("cancel",   "Отменить анализ"),
        ])
        removed = analysis_cache.cleanup_expired()
        if removed:
            logger.info(f"При старте удалено {removed} устаревших записей кэша")

    app.post_init = post_init

    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start",   cmd_start),
            CommandHandler("analyze", cmd_analyze),
            CallbackQueryHandler(button_callback,
                pattern=r"^(new_analysis|help|cancel|company:.+)$"),
        ],
        states={
            WAITING_COMPANY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_company),
                CallbackQueryHandler(button_callback),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cmd_cancel),
            CommandHandler("start",  cmd_start),
        ],
        allow_reentry=True,
    )

    # view: колбэки живут ВНЕ ConversationHandler — всегда доступны
    app.add_handler(CallbackQueryHandler(button_callback, pattern=r"^view:.+$"))
    app.add_handler(CallbackQueryHandler(button_callback, pattern=r"^cache:.+$"))
    app.add_handler(conv)
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("cache", cmd_cache))
    app.add_handler(CommandHandler("companies", cmd_companies))
    app.add_handler(CommandHandler("me",       cmd_me))
    app.add_handler(CommandHandler("admin",    cmd_admin))
    app.add_handler(CommandHandler("feedback", cmd_feedback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_message))
    app.add_error_handler(error_handler)

    print("🤖 Бот запущен. Ctrl+C для остановки.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
