"""Derive risk axes and observations from supplied report metrics."""

from __future__ import annotations
from reporting.localization import _normalize_language, _risk_tr


_RISK_LEVELS = {
    "ru": {"low": "Низкий", "medium": "Средний", "high": "Высокий", "na": "Недостаточно данных"},
    "en": {"low": "Low", "medium": "Medium", "high": "High", "na": "Insufficient data"},
    "uz": {"low": "Past", "medium": "O'rta", "high": "Yuqori", "na": "Ma'lumot yetarli emas"},
}


def _risk_level(points):
    if points >= 4:
        return "high"
    if points >= 2:
        return "medium"
    return "low"


def _compute_risk_profile(ifrs_snapshot, metrics, liquidity, language):
    """Structured 3-axis risk profile (ТЗ §3.4). Financial and market axes are
    computed from existing metrics; the informational axis is pending the news
    module. Purely factual Low/Medium/High + concrete drivers, so it carries no
    recommendation and passes the compliance sanitizer.
    """
    lang = _normalize_language(language)
    levels = _RISK_LEVELS.get(lang, _RISK_LEVELS["ru"])
    snap = ifrs_snapshot or {}
    quality = snap.get("quality") or {}
    bs = snap.get("balance_sheet") or {}
    liq = liquidity or snap.get("liquidity") or {}
    mliq = (metrics or {}).get("market_liquidity") or {}

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # ---- financial axis ----
    fin_pts = 0.0
    fin = []
    zone = str((quality.get("altman") or {}).get("zone") or "").lower()
    if any(k in zone for k in ("distress", "бедств", "опас", "red")):
        fin_pts += 2; fin.append(_risk_tr(lang, "Altman в зоне риска банкротства", "Altman in the distress zone", "Altman xavf zonasida"))
    elif any(k in zone for k in ("grey", "gray", "сер")):
        fin_pts += 1; fin.append(_risk_tr(lang, "Altman в серой зоне", "Altman in the grey zone", "Altman kulrang zonada"))
    de = num(bs.get("debt_to_equity"))
    if de is not None and de > 2:
        fin_pts += 2; fin.append(_risk_tr(lang, f"Высокий долг/капитал ({de:.1f})", f"High debt/equity ({de:.1f})", f"Yuqori qarz/kapital ({de:.1f})"))
    elif de is not None and de > 1:
        fin_pts += 1; fin.append(_risk_tr(lang, f"Повышенный долг/капитал ({de:.1f})", f"Elevated debt/equity ({de:.1f})", f"Oshgan qarz/kapital ({de:.1f})"))
    icr = num(quality.get("interest_coverage"))
    if icr is not None and icr < 1.5:
        fin_pts += 2; fin.append(_risk_tr(lang, f"Слабое покрытие процентов ({icr:.1f}×)", f"Weak interest coverage ({icr:.1f}×)", f"Zaif foiz qoplami ({icr:.1f}×)"))
    elif icr is not None and icr < 3:
        fin_pts += 1; fin.append(_risk_tr(lang, f"Умеренное покрытие процентов ({icr:.1f}×)", f"Moderate interest coverage ({icr:.1f}×)", f"O'rtacha foiz qoplami ({icr:.1f}×)"))
    cr = num(bs.get("current_ratio"))
    if cr is not None and cr < 1:
        fin_pts += 2; fin.append(_risk_tr(lang, f"Текущая ликвидность ниже 1 ({cr:.2f})", f"Current ratio below 1 ({cr:.2f})", f"Joriy likvidlik 1 dan past ({cr:.2f})"))
    elif cr is not None and cr < 1.3:
        fin_pts += 1; fin.append(_risk_tr(lang, f"Невысокая текущая ликвидность ({cr:.2f})", f"Modest current ratio ({cr:.2f})", f"Past joriy likvidlik ({cr:.2f})"))
    pio = num((quality.get("piotroski") or {}).get("score"))
    if pio is not None and pio < 3:
        fin_pts += 1; fin.append(_risk_tr(lang, f"Низкий Piotroski ({int(pio)}/9)", f"Low Piotroski ({int(pio)}/9)", f"Past Piotroski ({int(pio)}/9)"))
    if not fin:
        fin.append(_risk_tr(lang, "Явных финансовых рисков не выявлено", "No notable financial risks flagged", "Muhim moliyaviy risk aniqlanmadi"))

    # ---- market axis ----
    mkt_pts = 0.0
    mkt = []
    trade_days = num(mliq.get("trade_days") if mliq.get("trade_days") is not None else liq.get("trade_days"))
    llabel = str(mliq.get("liquidity_label") or liq.get("liquidity_label") or "").lower()
    if trade_days is not None and trade_days < 30:
        mkt_pts += 2; mkt.append(_risk_tr(lang, f"Редкие торги ({int(trade_days)} дн.)", f"Sparse trading ({int(trade_days)} days)", f"Kam savdo ({int(trade_days)} kun)"))
    elif trade_days is not None and trade_days < 90:
        mkt_pts += 1; mkt.append(_risk_tr(lang, f"Невысокая частота торгов ({int(trade_days)} дн.)", f"Modest trading frequency ({int(trade_days)} days)", f"O'rtacha savdo ({int(trade_days)} kun)"))
    elif any(k in llabel for k in ("low", "низк", "past")):
        mkt_pts += 2; mkt.append(_risk_tr(lang, "Низкая ликвидность", "Low liquidity", "Past likvidlik"))
    vol = num(liq.get("volatility_pct") or liq.get("volatility") or mliq.get("volatility_pct"))
    if vol is not None and vol > 40:
        mkt_pts += 2; mkt.append(_risk_tr(lang, f"Высокая волатильность (~{vol:.0f}%)", f"High volatility (~{vol:.0f}%)", f"Yuqori volatillik (~{vol:.0f}%)"))
    elif vol is not None and vol > 20:
        mkt_pts += 1; mkt.append(_risk_tr(lang, f"Повышенная волатильность (~{vol:.0f}%)", f"Elevated volatility (~{vol:.0f}%)", f"Oshgan volatillik (~{vol:.0f}%)"))
    if not mkt:
        mkt.append(_risk_tr(lang, "Показатели ликвидности в норме", "Liquidity within the normal range", "Likvidlik me'yorida"))

    # ---- debt-load indicator (ТЗ §3.3): 4 tiers Low/Moderate/High/Critical ----
    inc = snap.get("income_statement") or {}
    de_val = num(bs.get("debt_to_equity"))
    dte_val = num(inc.get("debt_to_ebitda"))
    debt_load = None
    if de_val is not None or dte_val is not None:
        # Take the worse of the two available signals. D/E thresholds 1/2/3.5;
        # Debt/EBITDA thresholds 2/4/6 (the >4x "high leverage" convention).
        tiers = []
        if de_val is not None:
            tiers.append(3 if de_val > 3.5 else 2 if de_val > 2 else 1 if de_val > 1 else 0)
        if dte_val is not None and dte_val > 0:
            tiers.append(3 if dte_val > 6 else 2 if dte_val > 4 else 1 if dte_val > 2 else 0)
        tier = max(tiers) if tiers else 0
        _DEBT_TIERS = {
            "ru": ["Низкая", "Умеренная", "Высокая", "Критическая"],
            "en": ["Low", "Moderate", "High", "Critical"],
            "uz": ["Past", "O'rtacha", "Yuqori", "Kritik"],
        }
        _DEBT_TONE = ["good", "warning", "danger", "critical"]
        labels = _DEBT_TIERS.get(lang, _DEBT_TIERS["ru"])
        debt_load = {
            "tier": tier,
            "level": ["low", "moderate", "high", "critical"][tier],
            "label": labels[tier],
            "tone": _DEBT_TONE[tier],
            "debt_to_equity": round(de_val, 2) if de_val is not None else None,
            "debt_to_ebitda": round(dte_val, 2) if dte_val is not None else None,
        }

    fin_lvl = _risk_level(fin_pts)
    mkt_lvl = _risk_level(mkt_pts)
    return {
        "version": 1,
        "debt_load": debt_load,
        "axes": [
            {"key": "financial", "label": _risk_tr(lang, "Финансовый риск", "Financial risk", "Moliyaviy risk"),
             "level": fin_lvl, "level_label": levels[fin_lvl], "drivers": fin[:4]},
            {"key": "market", "label": _risk_tr(lang, "Рыночный риск", "Market risk", "Bozor riski"),
             "level": mkt_lvl, "level_label": levels[mkt_lvl], "drivers": mkt[:4]},
            {"key": "informational", "label": _risk_tr(lang, "Информационный риск", "Information risk", "Axborot riski"),
             "level": "na", "level_label": levels["na"],
             "drivers": [_risk_tr(lang, "Требуется модуль анализа новостей (§3.11)", "Requires the news-analysis module (§3.11)", "Yangiliklar tahlili moduli kerak (§3.11)")]},
        ],
    }


def _compute_observations(ifrs_snapshot, metrics, language):
    """ТЗ §3.5 statistical detectors. Purely factual observations — an anomaly
    vs the issuer's own history (>2σ), a simultaneous multi-metric shift, and
    deviation from the sector norm. Stated as facts, never as a diagnosis or a
    recommendation, so they pass the compliance sanitizer.
    """
    lang = _normalize_language(language)
    snap = ifrs_snapshot or {}
    annual = [r for r in ((snap.get("series") or {}).get("annual") or []) if isinstance(r, dict)]
    out = []

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    # ---- detector 1: >2σ anomaly vs the issuer's own history ----
    metric_defs = [
        ("revenue", _risk_tr(lang, "Выручка", "Revenue", "Tushum")),
        ("net_income", _risk_tr(lang, "Чистая прибыль", "Net income", "Sof foyda")),
        ("net_profit_margin", _risk_tr(lang, "Чистая маржа", "Net margin", "Sof marja")),
    ]
    if len(annual) >= 4:
        for key, label in metric_defs:
            vals = [num(r.get(key)) for r in annual]
            vals = [v for v in vals if v is not None]
            if len(vals) < 4:
                continue
            latest = vals[-1]
            hist = vals[:-1]
            n = len(hist)
            mean = sum(hist) / n
            std = (sum((x - mean) ** 2 for x in hist) / n) ** 0.5
            if std <= 0:
                continue
            z = (latest - mean) / std
            if abs(z) >= 2:
                above = z > 0
                direction = _risk_tr(lang, "выше", "above", "yuqori") if above else _risk_tr(lang, "ниже", "below", "past")
                out.append({
                    "type": "anomaly",
                    "tone": "warning" if above else "danger",
                    "text": _risk_tr(
                        lang,
                        f"{label} на {abs(z):.1f}σ {direction} исторической нормы за {n} лет",
                        f"{label} is {abs(z):.1f}σ {direction} the {n}-year historical norm",
                        f"{label} {n} yillik me'yordan {abs(z):.1f}σ {direction}",
                    ),
                })

    # ---- detector 2: simultaneous multi-metric YoY shift ----
    if len(annual) >= 2:
        prev, cur = annual[-2], annual[-1]
        checks = [
            ("revenue", 1, _risk_tr(lang, "выручка", "revenue", "tushum")),
            ("net_income", 1, _risk_tr(lang, "прибыль", "net income", "foyda")),
            ("net_profit_margin", 1, _risk_tr(lang, "маржа", "margin", "marja")),
            ("debt_to_equity_ratio", -1, _risk_tr(lang, "долг/капитал", "debt/equity", "qarz/kapital")),
        ]
        worse, better = [], []
        for key, good_dir, label in checks:
            pv, cv = num(prev.get(key)), num(cur.get(key))
            if pv is None or cv is None or pv == cv:
                continue
            (better if ((cv - pv) * good_dir) > 0 else worse).append(label)
        if len(worse) >= 3:
            out.append({"type": "joint", "tone": "danger", "text": _risk_tr(
                lang,
                f"Одновременное ухудшение показателей: {', '.join(worse)}",
                f"Simultaneous deterioration across: {', '.join(worse)}",
                f"Bir vaqtda yomonlashuv: {', '.join(worse)}")})
        elif len(better) >= 3:
            out.append({"type": "joint", "tone": "good", "text": _risk_tr(
                lang,
                f"Одновременное улучшение показателей: {', '.join(better)}",
                f"Simultaneous improvement across: {', '.join(better)}",
                f"Bir vaqtda yaxshilanish: {', '.join(better)}")})

    # ---- detector 3: deviation from the sector norm ----
    industry = (metrics or {}).get("industry") or snap.get("industry") or {}
    ratings = industry.get("ratings") or {}
    sector_name = industry.get("sector_name") or industry.get("name_ru") or industry.get("sector")
    rating_labels = {
        "net_margin": _risk_tr(lang, "чистая маржа", "net margin", "sof marja"),
        "roe": "ROE", "roa": "ROA",
        "debt_equity": _risk_tr(lang, "долговая нагрузка", "leverage", "qarz yuki"),
        "revenue_growth": _risk_tr(lang, "рост выручки", "revenue growth", "tushum o'sishi"),
    }
    weak = [rating_labels.get(k, k) for k, v in ratings.items() if str(v).lower() in ("weak", "слаб", "плох", "low")]
    if weak and sector_name:
        out.append({"type": "sector", "tone": "warning", "text": _risk_tr(
            lang,
            f"Ниже типичного для сектора «{sector_name}»: {', '.join(weak[:3])}",
            f"Below the «{sector_name}» sector norm: {', '.join(weak[:3])}",
            f"«{sector_name}» sektori me'yoridan past: {', '.join(weak[:3])}")})

    return out
