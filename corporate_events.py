"""Evidence-led OpenInfo stories. Public fact codes are not API model/type ids.

No generated summary participates in extraction. Publication, decision and payment
stages stay independent. Missing evidence is reviewable, never guessed.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, parse_qs


def tr(ru, en, uz):
    return dict(ru=ru, en=en, uz=uz)


CATEGORIES = {
    "dividends": tr("Дивиденды и выплаты", "Dividends & payments", "Dividendlar va to‘lovlar"),
    "capital": tr("Акции и капитал", "Shares & capital", "Aksiyalar va kapital"),
    "ownership": tr("Владельцы и контроль", "Ownership & control", "Mulkdorlar va nazorat"),
    "transactions": tr("Сделки и финансы", "Deals & finance", "Bitimlar va moliya"),
    "risks": tr("Риски и лицензии", "Risks & licences", "Xatarlar va litsenziyalar"),
    "governance": tr("Собрания и управление", "Meetings & governance", "Yig‘ilishlar va boshqaruv"),
    "structure": tr("Структура бизнеса", "Business structure", "Biznes tuzilmasi"),
    "reference": tr("Справочные и листинг", "Reference & listing", "Ma’lumotlar va listing"),
}
_GROUPS = {"dividends": [31,32,41,42], "capital": [7,25,26,27,28,29,37,40],
           "ownership": [30,34,35,43,44,45], "transactions": list(range(15,22)),
           "risks": [3,4,5,13,14,22,23,24,33,39], "governance": [6,8,46],
           "structure": [9,10,11,12,36], "reference": [1,2,38]}
# Starting priorities from the supplied specification. Conditional codes stay
# explicitly provisional until their contents have been checked.
_P0 = {4,5,13,14,18,23,24,28,29,33,39}
_P2 = {8,11,12,22,34,35,36,38,46}
_P3 = {1,2,9,10}
_CONDITIONAL = {3,6,7,8,11,12,17,18,19,20,21,22,25,28,29,30,31,32,34,35,36,37,38,39,40,42,43,46}
_TITLES = [
("Компания изменила название", "Company renamed", "Kompaniya nomi o‘zgardi"),
("Изменились контакты компании", "Company contact details changed", "Kompaniya aloqa ma’lumotlari o‘zgardi"),
("Компания проходит реорганизацию", "Company undergoing reorganisation", "Kompaniya qayta tashkil etilmoqda"),
("Компания приостановила работу", "Company suspended operations", "Kompaniya faoliyati to‘xtatildi"),
("Компания прекращает деятельность", "Company ending operations", "Kompaniya faoliyati tugatilmoqda"),
("Акционеры раскрыли принятые решения", "Shareholder decisions disclosed", "Aksiyadorlar qarorlari e’lon qilindi"),
("Изменились права владельцев бумаг", "Security holder rights changed", "Qimmatli qog‘oz egalari huquqlari o‘zgardi"),
("Изменился состав руководящих органов", "Governing bodies changed", "Boshqaruv organlari tarkibi o‘zgardi"),
("Компания обновила сеть филиалов", "Branch network updated", "Filiallar tarmog‘i yangilandi"),
("Изменился список представительств", "Representative offices changed", "Vakolatxonalar ro‘yxati o‘zgardi"),
("Изменился список дочерних компаний", "Subsidiaries changed", "Sho‘ba korxonalar ro‘yxati o‘zgardi"),
("Изменился список зависимых компаний", "Associated companies changed", "Qaram korxonalar ro‘yxati o‘zgardi"),
("Имущество или счета компании арестованы", "Company assets or accounts seized", "Kompaniya mol-mulki yoki hisoblari xatlandi"),
("К компании предъявлен крупный иск", "Significant claim against company", "Kompaniyaga yirik da’vo kiritildi"),
("Компания привлекла значительный кредит", "Significant loan obtained", "Muhim kredit jalb qilindi"),
("Компания привлекла крупный кредит", "Major loan obtained", "Yirik kredit jalb qilindi"),
("Активы выросли более чем на 10%", "Assets increased by over 10%", "Aktivlar 10% dan ortiq o‘sdi"),
("Активы сократились более чем на 10%", "Assets decreased by over 10%", "Aktivlar 10% dan ortiq kamaydi"),
("Заключена крупная по сумме сделка", "High value transaction disclosed", "Katta summali bitim e’lon qilindi"),
("Компания совершила крупную сделку", "Major transaction disclosed", "Yirik bitim e’lon qilindi"),
("Сделка со связанной стороной", "Related party transaction", "Affillangan shaxs bilan bitim"),
("Компания получила лицензию", "Licence obtained", "Litsenziya olindi"),
("Компания утратила лицензию", "Licence lost", "Litsenziya bekor qilindi"),
("Действие лицензии приостановлено", "Licence suspended", "Litsenziya amal qilishi to‘xtatildi"),
("Раскрыт выпуск ценных бумаг", "Securities issue disclosed", "Qimmatli qog‘ozlar chiqarilishi e’lon qilindi"),
("Выпуск ценных бумаг приостановлен", "Securities issue suspended", "Qimmatli qog‘ozlar chiqarilishi to‘xtatildi"),
("Выпуск ценных бумаг возобновлён", "Securities issue resumed", "Qimmatli qog‘ozlar chiqarilishi tiklandi"),
("Выпуск ценных бумаг не состоялся", "Securities issue failed", "Qimmatli qog‘ozlar chiqarilishi amalga oshmadi"),
("Выпуск бумаг признан недействительным", "Securities issue declared invalid", "Qimmatli qog‘ozlar chiqarilishi haqiqiy emas deb topildi"),
("Изменился владелец крупного пакета", "Major shareholder changed", "Yirik aksiyador o‘zgardi"),
("Определены сроки выплат или погашения", "Payment or redemption dates disclosed", "To‘lov yoki so‘ndirish muddatlari belgilandi"),
("Начислен доход по ценным бумагам", "Income accrued on securities", "Qimmatli qog‘ozlar bo‘yicha daromad hisoblandi"),
("Раскрыта процедура банкротства", "Bankruptcy proceedings disclosed", "Bankrotlik jarayoni e’lon qilindi"),
("Изменилась доля акций членов набсовета", "Supervisory board shareholdings changed", "Kuzatuv kengashi aksiyalari ulushi o‘zgardi"),
("Изменилась доля акций руководства", "Management shareholdings changed", "Rahbariyat aksiyalari ulushi o‘zgardi"),
("Изменился список связанных лиц", "Affiliated persons changed", "Affillangan shaxslar ro‘yxati o‘zgardi"),
("Получено право выкупать свои бумаги", "Own securities buyback authorised", "O‘z qimmatli qog‘ozlarini qayta sotib olishga ruxsat berildi"),
("Бумаги допущены к торгам", "Securities admitted to trading", "Qimmatli qog‘ozlar savdoga qo‘yildi"),
("Бумаги исключены из торговых списков", "Securities delisted", "Qimmatli qog‘ozlar listingdan chiqarildi"),
("Изменены параметры выпуска бумаг", "Securities issue terms changed", "Qimmatli qog‘ozlar chiqarilishi shartlari o‘zgardi"),
("Набсовет рекомендовал дивиденды", "Board recommended dividends", "Kuzatuv kengashi dividendlarni tavsiya qildi"),
("Раскрыты данные о фактических выплатах", "Actual payment data disclosed", "Haqiqiy to‘lovlar to‘g‘risida ma’lumot e’lon qilindi"),
("Раскрыт владелец пакета от 35%", "Holder of at least 35% disclosed", "Kamida 35% ulush egasi e’lon qilindi"),
("Инвестор приобрёл крупную долю", "Investor acquired a major stake", "Investor yirik ulushni sotib oldi"),
("Крупный акционер предложил выкуп", "Major shareholder offered a buyout", "Yirik aksiyador sotib olishni taklif qildi"),
("Принято решение о госзакупках", "Public procurement decision disclosed", "Davlat xaridlari bo‘yicha qaror qabul qilindi"),
]
FACTS = {i: {"category": next(k for k,v in _GROUPS.items() if i in v),
             "priority": 0 if i in _P0 else 2 if i in _P2 else 3 if i in _P3 else 1,
             "conditional": i in _CONDITIONAL, "title": tr(*titles)} for i,titles in enumerate(_TITLES,1)}


def day(value):
    raw = str(value or "").strip()
    for fmt, text in [("%Y-%m-%d", raw[:10]), ("%d.%m.%Y", raw[:10])]:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def number(value):
    try:
        n = float(str(value).replace(" ", "").replace(",", "."))
        return n if math.isfinite(n) and n >= 0 else None
    except (ValueError, TypeError):
        return None


def from_fact(raw, *, source_url=None, tickers=None):
    try:
        code = int(raw.get("fact_number"))
    except (TypeError, ValueError):
        code = None
    spec = FACTS.get(code)
    identifier = str(raw.get("fact_identifier") or "")
    m = re.fullmatch(r"f-(\d+)-(\d+)", identifier)
    object_id = raw.get("object_id") or (m[2] if m else raw.get("id"))
    if m and int(m[1]) != code:
        spec = None
    org = raw.get("organization")
    org_id = org.get("id") if isinstance(org, dict) else org
    url = source_url or (f"https://openinfo.uz/ru/facts/{code}/{object_id}" if code and object_id else "")
    ticker_values = tickers or re.split(r"[,;\s]+", str(raw.get("organization_ticket_name") or raw.get("org_ticket_number") or ""))
    stage = {6:"decision_disclosed",31:"scheduled",32:"accrued",41:"proposed",42:"payment_disclosed"}.get(code,"disclosed")
    title = dict(spec["title"]) if spec else tr("Раскрытие проверяется", "Disclosure under review", "Ma’lumot tekshirilmoqda")
    amounts = []
    distribution = None
    proposal = str(raw.get("supervisory_board_proposal") or "").strip().casefold()
    if code == 41:
        if proposal in {"не распределить", "не распределять", "taqsimlamaslik", "not distribute"}:
            distribution = "not_proposed"
            title = tr("Набсовет предложил не выплачивать дивиденды", "Board proposed no dividend distribution", "Kuzatuv kengashi dividend to‘lamaslikni taklif qildi")
        elif proposal in {"распределить", "taqsimlash", "distribute"}:
            distribution = "proposed"
            for security, field in [("ordinary","distrution_share_sums"),("preferred","dividend_share_sums"),("bond","each_security_price")]:
                amount = number(raw.get(field))
                if amount is not None and amount > 0:
                    amounts.append({"security": security, "amount": amount})
    elif code == 32:
        # Public API's sum_aksiya2 does not consistently identify a share class.
        for security, field in [("share","sum_aksiya"),("bond","sum_per")]:
            amount = number(raw.get(field))
            if amount is not None and amount > 0:
                amounts.append({"security": security, "amount": amount})
    payment_start = day(raw.get("date_begin")) if code == 31 else None
    payment_end = day(raw.get("date_end")) if code == 31 else day(raw.get("payment_end_date")) if code == 42 else None
    pub = str(raw.get("pub_date") or raw.get("published_at") or "")
    decision = day(raw.get("decision_date") or raw.get("date_transaction"))
    if decision and day(pub) and decision > day(pub):
        decision = None
    # A portal status of 'approved' means the disclosure passed moderation.
    # It never proves shareholder approval, nor completed dividend payment.
    verified = bool(spec and url and day(pub) and (distribution if code == 41 else decision or payment_start or amounts))
    return {"id": url or identifier or f"unknown:{raw.get('id', '')}", "source_url": url,
            "issuer_id": str(org_id) if org_id else None,
            "organization": raw.get("organization_short_name") or raw.get("organization_short_name_text") or raw.get("organization_name") or "",
            "tickers": list(dict.fromkeys(str(t).strip().upper() for t in ticker_values if str(t).strip())),
            "isins": [], "code": code, "category": spec["category"] if spec else None,
            "priority": spec["priority"] if spec else 2, "priority_provisional": bool(not spec or spec["conditional"]),
            "title": title, "original_title": raw.get("fact_title") or raw.get("title") or "",
            "stage": stage, "confidence": "confirmed" if verified else "review", "distribution": distribution,
            "amounts": amounts, "published_at": pub, "event_date": decision,
            "decision_date": decision, "payment_start": payment_start, "payment_end": payment_end,
            "record_date": None, "ex_dividend_date": None, "period": None,
            "pdf_url": None, "description_changes": str(raw.get("description_changes") or "")[:2000]}


def from_announcement(row, detail=None):
    detail = detail or {}
    title = detail.get("title") or row.get("title") or ""
    text = " ".join(p.get("text", "") for p in detail.get("content", []))
    # An announcement is an agenda, even if its future agenda says 'approve'.
    dividend = bool(re.search(r"дивиденд|dividend", title + " " + text, re.I))
    periods = set(re.findall(r"(20\d{2})[-\s]*(?:yil|год)[^.!?\n]{0,90}(?:дивиденд|dividend)", text, re.I))
    meta = {x["label"].rstrip(":").casefold(): x["value"] for x in detail.get("metadata", [])}
    event_date = day(row.get("meeting_date") or meta.get("дата собрания"))
    pub = row.get("pub_date") or day(meta.get("дата публикации")) or ""
    event = from_fact({}, source_url=detail.get("source_url") or f"https://openinfo.uz/ru/announce/{row['announcement_id']}", tickers=[row["ticker"]] if row.get("ticker") else [])
    event.update(issuer_id=str(row["org_id"]) if row.get("org_id") else None,
                 organization=detail.get("organization") or row.get("organization") or "",
                 original_title=title, published_at=pub, event_date=event_date,
                 category="dividends" if dividend else "governance", priority=1 if dividend else 2,
                 stage="agenda" if dividend else "announced", confidence="confirmed" if detail.get("content") and event_date else "review",
                 period=next(iter(periods)) if len(periods)==1 else None, pdf_url=detail.get("pdf_url"),
                 announcement_id=str(row["announcement_id"]),
                 title=tr("Вопрос дивидендов в повестке собрания", "Dividends on the meeting agenda", "Yig‘ilish kun tartibida dividendlar") if dividend else tr("Объявлено собрание акционеров", "Shareholders meeting announced", "Aksiyadorlar yig‘ilishi e’lon qilindi"))
    return event


def group_stories(documents):
    groups = {}
    for doc in documents:
        # Do not guess a relation from proximity, ticker suffix, amount or year
        # of publication. Only an explicitly extracted dividend period links stages.
        key = (doc.get("issuer_id"), "dividends", doc.get("period")) if doc.get("issuer_id") and doc.get("category")=="dividends" and doc.get("period") else (doc["id"],)
        group = groups.setdefault(key, {})
        group[doc["id"]] = doc
    stories = []
    for key, docs in groups.items():
        ordered = sorted(docs.values(), key=lambda d:(d.get("published_at") or "",d["id"]))
        lead = ordered[-1]
        stories.append({**lead, "story_id": hashlib.sha256(str(key).encode()).hexdigest()[:20],
                        "documents": ordered, "document_count": len(ordered),
                        "priority": min(d["priority"] for d in ordered),
                        "tickers": sorted({t for d in ordered for t in d.get("tickers",[])}),
                        "isins": sorted({s for d in ordered for s in d.get("isins",[])})})
    return sorted(stories, key=lambda s:s.get("published_at") or "", reverse=True)


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS corporate_event_documents (
        source_url TEXT PRIMARY KEY, published_at TEXT NOT NULL,
        document_json TEXT NOT NULL, revisions_json TEXT NOT NULL)""")


def save_documents(documents, conn=None):
    from catalogue.storage import get_catalog_conn
    own = conn is None
    conn = conn or get_catalog_conn()
    try:
        _schema(conn)
        for document in documents:
            if not document.get("source_url") or not day(document.get("published_at")):
                continue
            clean = {k:v for k,v in document.items() if k != "revisions"}
            payload = json.dumps(clean, ensure_ascii=False, sort_keys=True)
            row = conn.execute("SELECT document_json, revisions_json FROM corporate_event_documents WHERE source_url = ?", (clean["source_url"],)).fetchone()
            if row and clean.get("confidence") != "confirmed" and json.loads(row["document_json"]).get("confidence") == "confirmed":
                # A failed detail request is not a correction by the issuer.
                continue
            if row and row["document_json"] == payload:
                continue
            revisions = json.loads(row["revisions_json"]) if row else []
            revisions.append({"observed_at": datetime.now(timezone.utc).isoformat(), "document": clean})
            conn.execute("""INSERT INTO corporate_event_documents VALUES (?,?,?,?)
                ON CONFLICT(source_url) DO UPDATE SET published_at=excluded.published_at,
                document_json=excluded.document_json, revisions_json=excluded.revisions_json""",
                (clean["source_url"],clean["published_at"],payload,json.dumps(revisions,ensure_ascii=False)))
        if own:
            conn.commit()
    finally:
        if own:
            conn.close()


def read_documents(lo, hi):
    from catalogue.storage import get_catalog_conn
    conn = get_catalog_conn()
    try:
        _schema(conn)
        conn.commit()
        rows = conn.execute("SELECT document_json, revisions_json FROM corporate_event_documents WHERE published_at >= ? AND published_at < ?",(lo,hi)).fetchall()
        return [{**json.loads(r["document_json"]),"revisions":json.loads(r["revisions_json"])} for r in rows]
    finally:
        conn.close()


def feed(start=None, end=None):
    import calendar_events
    import meetings
    import news_store
    from catalogue.storage import get_catalog_conn
    today = calendar_events._today()
    first,last = calendar_events.parse_range(start or (today-timedelta(days=90)).isoformat(),end or today.isoformat())
    lo,hi = first.isoformat(),(last+timedelta(days=1)).isoformat()
    documents = read_documents(lo,hi)
    known = {d["source_url"] for d in documents}
    status = {}
    conn = get_catalog_conn()
    try:
        sources = sorted(news_store.disclosure_source_ids())
        rows = conn.execute("SELECT n.*, (SELECT GROUP_CONCAT(e.ticker) FROM news_entities e WHERE e.news_id=n.id) AS tickers_csv FROM news n WHERE n.published_at >= ? AND n.published_at < ? " + f"AND n.source_id IN ({','.join('?' for _ in sources)})", (lo,hi,*sources)).fetchall() if sources else []
        for row in rows:
            r=dict(row)
            if r["url"] in known:
                continue
            # Older collector rows retain the public code in their source snippet.
            match=re.search(r"Существенный факт №\s*(\d+)",r.get("snippet") or "")
            title=r.get("title") or ""
            org,sep,original=title.partition(": ")
            parts=urlsplit(r["url"])
            orgmatch=re.search(r"/organizations/(\d+)",parts.path)
            ev=from_fact({"fact_number":match[1] if match else None,"organization":orgmatch[1] if orgmatch else None,
                          "organization_short_name":org if sep else "","fact_title":original if sep else title,
                          "pub_date":r.get("published_at")},source_url=r["url"],tickers=(r.get("tickers_csv") or "").split(","))
            ev["news_id"]=r["id"]
            # The same global fact ID can have both an organization and direct URL.
            fact_id=(parse_qs(parts.query).get("fact") or [None])[0]
            if any(d.get("global_fact_id") == fact_id and fact_id for d in documents):
                continue
            documents.append(ev)
        status["facts"]={"ok":True}
    finally:
        conn.close()
    try:
        meetings.ensure_snapshot()
        for row in meetings.read_published(lo,hi):
            ev=from_announcement(row)
            if ev["source_url"] not in known:
                documents.append(ev)
        status["announcements"]={"ok":True}
    except Exception:
        status["announcements"]={"ok":False}
    # Exact security identifiers come from the registry, never suffix guessing.
    try:
        from catalogue.market_store import get_all_listings
        listings=get_all_listings()
        for d in documents:
            d["isins"]=sorted({listings[t]["isin"] for t in d.get("tickers",[]) if listings.get(t,{}).get("isin")})
    except Exception:
        pass
    return {"ok":True,"start":lo,"end":last.isoformat(),"items":group_stories(documents),
            "categories":CATEGORIES,"facts":FACTS,"sources":status}


def refresh_document(source):
    """Enrich only a document already present in the local disclosure ledger.

    Users cannot make the server fetch arbitrary URLs. All upstream calls use
    existing paced OpenInfo adapters. The old record survives upstream failure.
    """
    from catalogue.storage import get_catalog_conn
    import meetings
    parts = urlsplit(source)
    if parts.scheme != "https" or parts.netloc != "openinfo.uz":
        raise ValueError("Unknown disclosure source")
    conn = get_catalog_conn()
    try:
        _schema(conn)
        conn.commit()
        row = conn.execute("SELECT document_json FROM corporate_event_documents WHERE source_url=?",(source,)).fetchone()
        existing = json.loads(row["document_json"]) if row else None
        ann = re.fullmatch(r"/ru/announce/(\d+)/?",parts.path)
        if ann:
            raw = conn.execute("SELECT * FROM catalog_meetings WHERE announcement_id=?",(ann[1],)).fetchone()
            if not raw and not existing:
                raise ValueError("Unknown announcement")
            raw = dict(raw) if raw else {"announcement_id":ann[1],"org_id":existing.get("issuer_id"),
                  "ticker": next(iter(existing.get("tickers",[])),None),"pub_date":existing.get("published_at"),
                  "meeting_date":existing.get("event_date")}
        else:
            legacy = conn.execute("SELECT * FROM news WHERE url=?",(source,)).fetchone()
            if not existing and not legacy:
                raise ValueError("Unknown disclosure")
            raw = dict(legacy) if legacy else {}
            if legacy:
                import news_store
                if raw.get("source_id") not in news_store.disclosure_source_ids():
                    raise ValueError("Not an issuer disclosure")
                tickers = [r["ticker"] for r in conn.execute("SELECT ticker FROM news_entities WHERE news_id=?",(raw["id"],)).fetchall()]
            else:
                tickers = existing.get("tickers",[])
    finally:
        conn.close()
    if ann:
        document=from_announcement(raw,meetings.announcement_detail(ann[1],"ru"))
    else:
        from collectors.news.facts import _fact_detail
        fact_id=(existing or {}).get("global_fact_id") or (parse_qs(parts.query).get("fact") or [None])[0]
        if not fact_id or not str(fact_id).isdigit():
            raise ValueError("No stored source identifier")
        detail=_fact_detail(fact_id)
        if not detail:
            raise RuntimeError("Source unavailable")
        document=from_fact(detail,source_url=source,tickers=tickers)
        document["global_fact_id"]=str(fact_id)
        if not day(document.get("published_at")):
            document["published_at"]=(existing or raw).get("published_at")
    save_documents([document])
    lo=day(document["published_at"])
    hi=(datetime.strptime(lo,"%Y-%m-%d").date()+timedelta(days=1)).isoformat()
    return next(d for d in read_documents(lo,hi) if d["source_url"]==source)
