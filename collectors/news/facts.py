"""News facts operations with explicit dependencies."""
from __future__ import annotations

import collectors.news.settings as collectors_news_settings
import collectors.news.sources as collectors_news_sources
import re


_NON_PAYMENT_MAX = 220


def _amount_uz(value):
    """'161662245000.00' → '161 662 245 000 сум'; '612.1253' → '612,1253 сум'.

    Per-share amounts are filed to four decimals and totals to two, so trailing zeros are
    dropped rather than fixed at a width that would misrepresent one of them.
    """
    try:
        num = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        return None
    text = f"{num:,.4f}".replace(",", " ").rstrip("0").rstrip(".")
    return f"{text.replace('.', ',')} сум"


def _pct(value):
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _ru_date(value):
    """'2026-07-24' → '24.07.2026'; anything else is returned as filed."""
    text = str(value or "").strip()[:10]
    if not text:
        return None
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", text)
    return f"{match.group(3)}.{match.group(2)}.{match.group(1)}" if match else text


def _fmt_accrual(facts):
    fact = facts[0]
    """Fact 32 — the amount accrued per security, plus the payment window.

    Shares file ``sum_aksiya`` with the window in ``*_common_shares``; bonds file ``sum_per``
    with the window in ``*_other_securities`` (verified 2026-07-25 across AGAT CREDIT, CONTACT
    FINANCE, UZUM SARMOYA and ToshuyjoyLITI). The ``*2`` variants hold a second class, but the
    API's own naming does not separate ordinary from preferred reliably, so they are left out
    rather than guessed at and mislabelled.
    """
    if _pct(fact.get("sum_aksiya")):
        amount, unit = _amount_uz(fact.get("sum_aksiya")), "на акцию"
        start, end = fact.get("start_date_common_shares"), fact.get("end_date_common_shares")
        nominal = _pct(fact.get("one_procent"))
    elif _pct(fact.get("sum_per")):
        amount, unit = _amount_uz(fact.get("sum_per")), "на облигацию"
        start, end = (fact.get("start_date_other_securities"),
                      fact.get("end_date_other_securities"))
        nominal = _pct(fact.get("percentage_nominal"))
    else:
        return None
    if not amount:
        return None

    text = f"Начислено {amount} {unit}"
    if nominal:
        text += f" ({nominal:.2f}% номинала)"
    window = " — ".join(d for d in (_ru_date(start), _ru_date(end)) if d)
    if window:
        text += f", выплата {window}"
    return text + "."


def _fmt_dividend_payment(facts):
    fact = facts[0]
    """Fact 42 — declared vs actually paid, what is still owed, and why."""
    declared = _amount_uz(fact.get("overall_calculated_sum"))
    paid_pct = _pct(fact.get("overall_paid_percent"))
    parts = []
    if declared:
        parts.append(f"начислено {declared}")
    if paid_pct is not None:
        paid_sum = _amount_uz(fact.get("overall_paid_sum"))
        parts.append(f"выплачено {paid_pct:.2f}%" + (f" ({paid_sum})" if paid_sum else ""))
    end = _ru_date(fact.get("payment_end_date"))
    if end:
        parts.append(f"срок выплаты до {end}")
    if not parts:
        return None

    text = "Дивиденды: " + ", ".join(parts) + "."
    # The unpaid remainder carries the signal, so it gets its own sentence rather than being
    # buried in the list. Reported exactly as filed — several issuers file paid=0 alongside
    # debt=0, and inferring the shortfall would contradict their own numbers.
    debt_pct = _pct(fact.get("overall_debt_percent"))
    if debt_pct:
        debt_sum = _amount_uz(fact.get("overall_debt_sum"))
        text += f" Не выплачено {debt_pct:.2f}%" + (f" ({debt_sum})" if debt_sum else "") + "."
        reason = collectors_news_sources._clean_text(str(fact.get("non_payment_explanation") or "")).strip(" -—")
        if reason:
            text += f" Причина по данным эмитента: {reason[:_NON_PAYMENT_MAX]}"
            if len(reason) > _NON_PAYMENT_MAX:
                text += "…"
    return text


def _org_short(name):
    """'Общество с ограниченной ответственностью «Бухарский НПЗ»' → 'Бухарский НПЗ'.

    Counterparties are filed with their full legal form, which is most of the string and none
    of the information. The quoted trade name is what identifies the party.
    """
    text = collectors_news_sources._clean_text(str(name or "")).strip()
    if not text:
        return None
    quoted = re.search(r"[«\"]([^»\"]{2,})[»\"]", text)
    if quoted:
        return quoted.group(1).strip()
    return text if len(text) <= 60 else text[:59].rstrip() + "…"


def _plural_ru(n, forms):
    """(1, 2-4, 5+) — 'сделка' / 'сделки' / 'сделок'. Machine-generated text still has to
    read like Russian, or the card looks broken."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return forms[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return forms[1]
    return forms[2]


def _join_few(values, limit=3):
    """'A, B, C и др.' — enough to see who is involved, not a wall of names."""
    seen = []
    for v in values:
        if v and v not in seen:
            seen.append(v)
    if not seen:
        return None
    head = ", ".join(seen[:limit])
    return head + (" и др." if len(seen) > limit else "")


def _fmt_transaction(facts):
    """Facts 20 / 21 — a major or related-party deal: with whom, for what, how much.

    A grouped day is aggregated rather than reported once: O'zbekneftgaz files eight
    related-party notices in an hour, and "eight deals totalling N" is the story — the count
    alone (which is all the card said before) is not.

    Fact 20 also files ``assets_issuer``, the deal's size as a share of the issuer's assets;
    that is the number that separates routine trading from a balance-sheet event, so it is
    kept whenever it is filed.
    """
    total, priced = 0.0, 0
    parties, subjects, assets_pct, when = [], [], None, None
    for f in facts:
        amount = _pct(str(f.get("transaction_amount") or "").replace(" ", ""))
        if amount:
            total += amount
            priced += 1
        parties.append(_org_short(f.get("name_counterparty")))
        subject = collectors_news_sources._clean_text(str(f.get("subject_matter") or "")).strip()
        if subject:
            subjects.append(subject if len(subject) <= 70 else subject[:69].rstrip() + "…")
        assets_pct = assets_pct or _pct(f.get("assets_issuer"))
        when = when or _ru_date(f.get("date_transaction"))

    who, what = _join_few(parties), _join_few(subjects, 2)
    if len(facts) == 1:
        parts = [p for p in (who and f"контрагент — {who}", what and f"предмет — {what}") if p]
        if priced:
            money = _amount_uz(round(total) if total >= 1000 else total)
            parts.append(f"сумма {money}" + (f" ({assets_pct:.2f}% активов)" if assets_pct else ""))
        if when:
            parts.append(f"дата {when}")
        return ("Сделка: " + ", ".join(parts) + ".") if parts else None

    parts = [f"{len(facts)} {_plural_ru(len(facts), ('сделка', 'сделки', 'сделок'))} за день"]
    if priced:
        rounded = round(total) if total >= 1000 else total
        parts.append(f"на {_amount_uz(rounded)}"
                     + (f" по {priced} из них" if priced < len(facts) else ""))
    text = ", ".join(parts) + "."
    if who:
        text += f" Контрагенты: {who.rstrip('.')}."
    if what:
        text += f" Предмет: {what.rstrip('.')}."
    return text


def _fmt_obligation(facts):
    """Fact 31 — the window in which the issuer must redeem or pay out on a security."""
    fact = facts[0]
    window = " — ".join(d for d in (_ru_date(fact.get("date_begin")),
                                    _ru_date(fact.get("date_end"))) if d)
    if not window:
        return None
    text = f"Срок исполнения обязательств: {window}."
    detail = collectors_news_sources._clean_text(str(fact.get("description_issuers_obligations") or "")).strip()
    if detail:
        text += f" {detail[:120]}" + ("…" if len(detail) > 120 else "")
    return text


def _fmt_meeting(facts):
    """Fact 6 — a shareholders'/board meeting: when it sat and how much of the register voted.

    The resolutions themselves are filed as arrays that are empty on most records, so only the
    facts that are consistently present are reported. Quorum is the one number here that says
    something on its own: on a register this concentrated, who turned up is a governance
    datapoint.
    """
    fact = facts[0]
    parts = []
    when = _ru_date(fact.get("date_transaction"))
    if when:
        parts.append(f"собрание {when}")
    quorum = _pct(fact.get("quorum_general"))
    if quorum:
        parts.append(f"кворум {quorum:.2f}%")
    minutes = _ru_date(fact.get("date_minutes"))
    if minutes:
        parts.append(f"протокол от {minutes}")
    return (", ".join(parts).capitalize() + ".") if parts else None


def _fmt_license(facts):
    """Fact 22 — which licence, from whom, and how long it runs."""
    fact = facts[0]
    activity = collectors_news_sources._clean_text(str(fact.get("type_activity") or "")).strip()
    number = collectors_news_sources._clean_text(str(fact.get("number_licensing") or "")).strip()
    parts = []
    if activity:
        parts.append(f"вид деятельности — {activity[:90]}")
    if number:
        parts.append(f"№ {number}")
    valid = _ru_date(fact.get("validity_license"))
    if valid:
        parts.append(f"действует до {valid}")
    return ("Лицензия: " + ", ".join(parts) + ".") if parts else None


_FIGURE_FORMATTERS = {
    6: _fmt_meeting, 20: _fmt_transaction, 21: _fmt_transaction, 22: _fmt_license,
    31: _fmt_obligation, 32: _fmt_accrual, 42: _fmt_dividend_payment,
}


_FIGURE_MAX_FETCH = 8


def _fact_detail(fact_id):
    """One filing's own fields from ``/disclosure/facts/{id}/``, or None on any failure."""
    try:
        import openinfo_http
        from collectors.openinfo.settings import OPENINFO_API_BASE

        resp = openinfo_http.get(f"{OPENINFO_API_BASE}/disclosure/facts/{fact_id}/", timeout=40)
        resp.raise_for_status()
        payload = (resp.json() or {}).get("fact") or []
    except Exception as exc:  # noqa: BLE001 — enrichment is never worth failing a run over
        collectors_news_settings.logger.debug("fact detail failed for %s: %s", fact_id, exc)
        return None
    fact = payload[0] if isinstance(payload, list) and payload else payload
    return fact if isinstance(fact, dict) else None


def _fact_figures(fact_number, fact_ids):
    """What the filings in one item actually say, as a sentence — or None.

    One paced call per filing (capped at ``_FIGURE_MAX_FETCH``) using ids the item already
    carries; no model is involved, so this costs the requests and nothing else. Any failure
    returns None and the item keeps its plain snippet: a filing that cannot be enriched must
    still be published.
    """
    formatter = _FIGURE_FORMATTERS.get(fact_number)
    if formatter is None or not fact_ids:
        return None
    facts = [f for f in (_fact_detail(i) for i in fact_ids[:_FIGURE_MAX_FETCH]) if f]
    if not facts:
        return None
    try:
        return formatter(facts)
    except Exception:  # noqa: BLE001 — one malformed filing must not break the run
        collectors_news_settings.logger.debug("fact #%s did not format (%d filing(s))", fact_number, len(facts))
        return None


def _filing_snippet(group, detail, figures):
    """The card text for one filing item: what was filed, then what it says.

    Sentences are joined rather than concatenated, because the pieces come from different
    places and half of them arrive without a full stop — which is how "…по ценным бумагам
    Начислено 2 301,37 сум" happened. The bare filing count is dropped once ``figures`` is
    present, since the figures sentence already opens with it.
    """
    chunks = [f"Существенный факт №{group['fact_number']} на openinfo.uz"]
    if detail:
        chunks.append(detail)
    count = group["count"]
    if count > 1 and not figures:
        word = _plural_ru(count, ("сообщение", "сообщения", "сообщений"))
        chunks.append(f"Подано {count} {word} за день")
    text = ". ".join(c.strip().rstrip(".") for c in chunks if c and c.strip()) + "."
    if figures:
        text += " " + figures.strip()
    return text[:1000]
