"""UZStock V3 financial-data ledger.

The older catalogue remains the operational cache used by the public product.
This module is the stricter V3 source-of-truth layer: facts and source files are
append-only, conflicts are explicit, and a publication always names its exact
inputs and formula version.  It deliberately uses decimal strings rather than
SQLite REAL values for every financial amount.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import sqlite3
from typing import Any, Iterable
from uuid import uuid4


QUALITY = {"READY", "CONFLICT", "NEEDS_REVIEW", "FAILED"}
ROLES = {"PRIMARY", "COMPARATIVE", "RESTATEMENT"}
FORMULA_STATES = {"DRAFT", "ACTIVE", "ARCHIVED"}
PUBLICATION_STATES = {"PUBLISHED", "SUPERSEDED", "ROLLED_BACK"}
REQUIRED = {"revenue", "net_income", "total_assets", "equity"}
ERROR_CODES = {
    "PERIOD_MISMATCH", "VALUE_CONFLICT", "SIGN_CHANGE", "SCALE_SUSPECTED",
    "MISSING_REQUIRED_ROW", "DUPLICATE_DOCUMENT", "DUPLICATE_ISSUER",
    "SECURITY_CLASS_INCOMPLETE", "FORMULA_INPUT_CONFLICT", "SOURCE_DOWNLOAD_FAILED",
}


class V3Error(ValueError):
    """A request cannot safely advance through the financial pipeline."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _decimal(value: Any, *, field: str = "value") -> Decimal:
    if isinstance(value, bool) or value is None:
        raise V3Error(f"{field} must be a decimal value")
    try:
        result = Decimal(str(value).strip().replace(" ", "").replace(",", "."))
    except (InvalidOperation, AttributeError) as exc:
        raise V3Error(f"{field} must be a decimal value") from exc
    if not result.is_finite():
        raise V3Error(f"{field} must be finite")
    return result


def decimal_text(value: Any, *, field: str = "value") -> str:
    result = _decimal(value, field=field)
    rendered = format(result.normalize(), "f")
    return "0" if rendered in {"-0", ""} else rendered


def _date(value: str | date, *, field: str) -> str:
    try:
        return value.isoformat() if isinstance(value, date) else date.fromisoformat(str(value)[:10]).isoformat()
    except (TypeError, ValueError) as exc:
        raise V3Error(f"{field} must be an ISO date") from exc


def resolve_period(*, explicit: tuple[str, str] | None = None,
                   form_header: tuple[str, str] | None = None,
                   publication_metadata: tuple[str, str] | None = None) -> dict[str, str | None]:
    """Resolve a filing period without using the collection date as a proxy.

    A period stated in the file wins over a form heading, which wins over source
    metadata.  If no candidate is usable the caller must create a review item;
    it may never silently label the document with its publication date.
    """
    for source, value in (("EXPLICIT_FILE", explicit), ("FORM_HEADER", form_header),
                          ("PUBLICATION_METADATA", publication_metadata)):
        if not value:
            continue
        start, end = _date(value[0], field="period_start"), _date(value[1], field="period_end")
        if start <= end:
            return {"period_start": start, "period_end": end, "period_resolution": source}
    return {"period_start": None, "period_end": None, "period_resolution": "NEEDS_REVIEW"}


def _connection() -> sqlite3.Connection:
    from reports_catalog import get_catalog_conn
    conn = get_catalog_conn()
    conn.row_factory = sqlite3.Row
    return conn


def init(conn: sqlite3.Connection | None = None) -> None:
    own = conn is None
    conn = conn or _connection()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS v3_issuers (
          issuer_id TEXT PRIMARY KEY, inn TEXT UNIQUE, name TEXT NOT NULL,
          openinfo_id TEXT UNIQUE, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v3_security_classes (
          issuer_id TEXT NOT NULL REFERENCES v3_issuers(issuer_id),
          class_id TEXT NOT NULL, ticker TEXT, isin TEXT, share_type TEXT NOT NULL,
          price TEXT, shares_outstanding TEXT, priced_at TEXT, status TEXT NOT NULL DEFAULT 'ACTIVE',
          updated_at TEXT NOT NULL, PRIMARY KEY (issuer_id, class_id)
        );
        CREATE TABLE IF NOT EXISTS v3_documents (
          id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL REFERENCES v3_issuers(issuer_id),
          source_url TEXT, source_hash TEXT NOT NULL UNIQUE, published_at TEXT,
          standard TEXT NOT NULL, period_start TEXT, period_end TEXT,
          period_resolution TEXT NOT NULL, role TEXT NOT NULL, parser_version TEXT,
          title TEXT, original BLOB, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v3_document_assessments (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES v3_documents(id),
          quality TEXT NOT NULL, reasons_json TEXT NOT NULL, assessed_at TEXT NOT NULL,
          UNIQUE(document_id, quality, reasons_json)
        );
        CREATE INDEX IF NOT EXISTS v3_document_assessments_current
          ON v3_document_assessments(document_id, assessed_at DESC);
        CREATE TABLE IF NOT EXISTS v3_facts (
          id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES v3_documents(id),
          issuer_id TEXT NOT NULL, standard TEXT NOT NULL, statement TEXT NOT NULL,
          line_code TEXT NOT NULL, normalized_key TEXT NOT NULL,
          period_start TEXT NOT NULL, period_end TEXT NOT NULL, role TEXT NOT NULL,
          raw_value TEXT NOT NULL, normalized_value TEXT NOT NULL, unit TEXT NOT NULL,
          unit_scale TEXT NOT NULL, sign INTEGER NOT NULL, page INTEGER, sheet TEXT, cell TEXT,
          raw_label TEXT, parser_version TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS v3_facts_match
          ON v3_facts(issuer_id, standard, statement, line_code, period_end, unit);
        CREATE INDEX IF NOT EXISTS v3_facts_metric
          ON v3_facts(issuer_id, normalized_key, period_end);
        CREATE TABLE IF NOT EXISTS v3_incidents (
          id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, period_end TEXT, form_name TEXT,
          code TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN', evidence_json TEXT NOT NULL,
          created_at TEXT NOT NULL, resolved_at TEXT, resolution_json TEXT,
          UNIQUE(issuer_id, period_end, form_name, code)
        );
        CREATE TABLE IF NOT EXISTS v3_incident_items (
          incident_id TEXT NOT NULL REFERENCES v3_incidents(id), fact_id TEXT NOT NULL REFERENCES v3_facts(id),
          PRIMARY KEY(incident_id, fact_id)
        );
        CREATE TABLE IF NOT EXISTS v3_formula_versions (
          id TEXT PRIMARY KEY, metric TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL,
          expression TEXT NOT NULL, required_inputs_json TEXT NOT NULL, created_at TEXT NOT NULL,
          activated_at TEXT, archived_at TEXT, UNIQUE(metric, version)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS v3_one_active_formula
          ON v3_formula_versions(metric) WHERE state='ACTIVE';
        CREATE TABLE IF NOT EXISTS v3_calculations (
          id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, period_end TEXT NOT NULL,
          metric TEXT NOT NULL, value TEXT, status TEXT NOT NULL, null_reason TEXT,
          formula_id TEXT NOT NULL REFERENCES v3_formula_versions(id), inputs_json TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(issuer_id, period_end, metric, formula_id, inputs_json)
        );
        CREATE TABLE IF NOT EXISTS v3_publications (
          id TEXT PRIMARY KEY, issuer_id TEXT NOT NULL, period_end TEXT NOT NULL,
          calculation_ids_json TEXT NOT NULL, payload_json TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, superseded_at TEXT
        );
        CREATE TABLE IF NOT EXISTS v3_publication_pointers (
          issuer_id TEXT PRIMARY KEY, publication_id TEXT NOT NULL REFERENCES v3_publications(id), updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS v3_audit (
          id TEXT PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS v3_documents_immutable_update BEFORE UPDATE ON v3_documents
          BEGIN SELECT RAISE(ABORT, 'v3 documents are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS v3_documents_immutable_delete BEFORE DELETE ON v3_documents
          BEGIN SELECT RAISE(ABORT, 'v3 documents are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS v3_facts_immutable_update BEFORE UPDATE ON v3_facts
          BEGIN SELECT RAISE(ABORT, 'v3 facts are immutable'); END;
        CREATE TRIGGER IF NOT EXISTS v3_facts_immutable_delete BEFORE DELETE ON v3_facts
          BEGIN SELECT RAISE(ABORT, 'v3 facts are immutable'); END;
        """)
        _seed_formulas(conn)
        conn.commit()
    finally:
        if own:
            conn.close()


def _audit(conn: sqlite3.Connection, actor: str, action: str, entity_type: str, entity_id: str, payload: Any) -> None:
    conn.execute("INSERT INTO v3_audit VALUES (?,?,?,?,?,?,?)", (_uid("audit"), actor, action, entity_type, entity_id, _json(payload), _now()))


_FORMULAS = {
    "market_cap": ("sum(close_price * shares_outstanding)", ("security_classes",)),
    "pe": ("market_cap / net_income_ltm", ("market_cap", "net_income_ltm")),
    "ps": ("market_cap / revenue_ltm", ("market_cap", "revenue_ltm")),
    "pb": ("market_cap / equity", ("market_cap", "equity")),
    "roe": ("net_income_ltm / average_equity", ("net_income_ltm", "average_equity")),
    "roa": ("net_income_ltm / average_assets", ("net_income_ltm", "average_assets")),
    "net_margin": ("net_income_ltm / revenue_ltm", ("net_income_ltm", "revenue_ltm")),
}


def _seed_formulas(conn: sqlite3.Connection) -> None:
    for metric, (expression, inputs) in _FORMULAS.items():
        if conn.execute("SELECT 1 FROM v3_formula_versions WHERE metric=?", (metric,)).fetchone():
            continue
        conn.execute("INSERT INTO v3_formula_versions VALUES (?,?,?,?,?,?,?,?,?)", (
            _uid("formula"), metric, 1, "ACTIVE", expression, _json(inputs), _now(), _now(), None))


def upsert_issuer(*, issuer_id: str, name: str, inn: str | None = None, openinfo_id: str | None = None, actor: str = "pipeline") -> dict[str, Any]:
    if not issuer_id.strip() or not name.strip():
        raise V3Error("issuer_id and name are required")
    conn = _connection()
    try:
        init(conn)
        existing = conn.execute("SELECT * FROM v3_issuers WHERE issuer_id=?", (issuer_id,)).fetchone()
        if existing and (existing["inn"] not in {None, inn} or existing["openinfo_id"] not in {None, openinfo_id}):
            raise V3Error("DUPLICATE_ISSUER")
        if not existing:
            conn.execute("INSERT INTO v3_issuers VALUES (?,?,?,?,?)", (issuer_id, inn, name, openinfo_id, _now()))
        _audit(conn, actor, "issuer.upserted", "issuer", issuer_id, {"inn": inn, "openinfo_id": openinfo_id})
        conn.commit()
        return dict(conn.execute("SELECT * FROM v3_issuers WHERE issuer_id=?", (issuer_id,)).fetchone())
    finally:
        conn.close()


def add_document(*, issuer_id: str, source_url: str | None, original: bytes | None, standard: str,
                 period_start: str | None, period_end: str | None, period_resolution: str,
                 role: str = "PRIMARY", published_at: str | None = None, parser_version: str | None = None,
                 title: str | None = None, source_hash: str | None = None, actor: str = "pipeline") -> dict[str, Any]:
    if role not in ROLES or period_resolution not in {"EXPLICIT_FILE", "FORM_HEADER", "PUBLICATION_METADATA", "NEEDS_REVIEW"}:
        raise V3Error("invalid document role or period resolution")
    if not original and not source_hash:
        raise V3Error("an original file or its SHA-256 hash is required")
    if source_hash and len(source_hash) != 64:
        raise V3Error("source_hash must be SHA-256")
    source_hash = source_hash or hashlib.sha256(original or b"").hexdigest()
    start = _date(period_start, field="period_start") if period_start else None
    end = _date(period_end, field="period_end") if period_end else None
    if start and end and start > end:
        raise V3Error("PERIOD_MISMATCH")
    conn = _connection()
    try:
        init(conn)
        if not conn.execute("SELECT 1 FROM v3_issuers WHERE issuer_id=?", (issuer_id,)).fetchone():
            raise V3Error("issuer is unknown")
        prior = conn.execute("SELECT * FROM v3_documents WHERE source_hash=?", (source_hash,)).fetchone()
        if prior:
            return {**dict(prior), "duplicate": True}
        document = {"id": _uid("doc"), "issuer_id": issuer_id, "source_url": source_url, "source_hash": source_hash,
                    "published_at": published_at, "standard": standard.upper(), "period_start": start, "period_end": end,
                    "period_resolution": period_resolution, "role": role, "parser_version": parser_version, "title": title,
                    "original": original, "created_at": _now()}
        conn.execute("""INSERT INTO v3_documents VALUES (:id,:issuer_id,:source_url,:source_hash,:published_at,:standard,
                     :period_start,:period_end,:period_resolution,:role,:parser_version,:title,:original,:created_at)""", document)
        quality = "NEEDS_REVIEW" if period_resolution == "NEEDS_REVIEW" else "READY"
        _assessment(conn, document["id"], quality, ["period requires review"] if quality != "READY" else [])
        _audit(conn, actor, "document.created", "document", document["id"], {k: v for k, v in document.items() if k != "original"})
        conn.commit()
        return {**document, "duplicate": False}
    finally:
        conn.close()


def _assessment(conn: sqlite3.Connection, document_id: str, quality: str, reasons: list[str]) -> None:
    if quality not in QUALITY:
        raise V3Error("invalid quality")
    conn.execute("INSERT OR IGNORE INTO v3_document_assessments VALUES (?,?,?,?,?)", (_uid("assessment"), document_id, quality, _json(reasons), _now()))


def record_facts(document_id: str, rows: Iterable[dict[str, Any]], *, actor: str = "pipeline") -> list[dict[str, Any]]:
    conn = _connection()
    try:
        init(conn)
        doc = conn.execute("SELECT * FROM v3_documents WHERE id=?", (document_id,)).fetchone()
        if not doc:
            raise V3Error("document is unknown")
        facts: list[dict[str, Any]] = []
        for row in rows:
            role = str(row.get("role") or doc["role"]).upper()
            if role not in ROLES:
                raise V3Error("invalid fact role")
            unit_scale = decimal_text(row.get("unit_scale", 1), field="unit_scale")
            raw = decimal_text(row.get("raw_value", row.get("value")), field="raw_value")
            normalized = decimal_text(_decimal(raw) * _decimal(unit_scale), field="normalized_value")
            start = _date(row.get("period_start") or doc["period_start"], field="period_start")
            end = _date(row.get("period_end") or doc["period_end"], field="period_end")
            if start > end:
                raise V3Error("PERIOD_MISMATCH")
            line = str(row.get("line_code") or row.get("normalized_key") or "").strip()
            key = str(row.get("normalized_key") or line).strip().lower()
            statement = str(row.get("statement") or "unknown").lower()
            if not line or not key:
                raise V3Error("line_code and normalized_key are required")
            fact = {"id": _uid("fact"), "document_id": document_id, "issuer_id": doc["issuer_id"], "standard": doc["standard"],
                    "statement": statement, "line_code": line, "normalized_key": key, "period_start": start, "period_end": end,
                    "role": role, "raw_value": raw, "normalized_value": normalized, "unit": str(row.get("unit") or "UZS"),
                    "unit_scale": unit_scale, "sign": -1 if _decimal(normalized) < 0 else 1, "page": row.get("page"),
                    "sheet": row.get("sheet"), "cell": row.get("cell"), "raw_label": row.get("raw_label"),
                    "parser_version": row.get("parser_version") or doc["parser_version"], "created_at": _now()}
            conn.execute("""INSERT INTO v3_facts VALUES (:id,:document_id,:issuer_id,:standard,:statement,:line_code,:normalized_key,
                         :period_start,:period_end,:role,:raw_value,:normalized_value,:unit,:unit_scale,:sign,:page,:sheet,:cell,
                         :raw_label,:parser_version,:created_at)""", fact)
            facts.append(fact)
        if not facts:
            raise V3Error("no facts supplied")
        _audit(conn, actor, "facts.recorded", "document", document_id, {"count": len(facts)})
        conn.commit()
        return facts
    finally:
        conn.close()


def _incident(conn: sqlite3.Connection, *, issuer_id: str, period_end: str | None, form_name: str | None,
              code: str, evidence: dict[str, Any], fact_ids: Iterable[str]) -> str:
    if code not in ERROR_CODES:
        raise V3Error("unknown error code")
    existing = conn.execute("SELECT id FROM v3_incidents WHERE issuer_id=? AND period_end IS ? AND form_name IS ? AND code=?",
                            (issuer_id, period_end, form_name, code)).fetchone()
    incident_id = existing["id"] if existing else _uid("incident")
    if not existing:
        conn.execute("INSERT INTO v3_incidents (id,issuer_id,period_end,form_name,code,evidence_json,created_at) VALUES (?,?,?,?,?,?,?)",
                     (incident_id, issuer_id, period_end, form_name, code, _json(evidence), _now()))
    for fact_id in fact_ids:
        conn.execute("INSERT INTO v3_incident_items VALUES (?,?) ON CONFLICT DO NOTHING", (incident_id, fact_id))
    return incident_id


def reconcile_document(document_id: str, *, actor: str = "pipeline") -> dict[str, Any]:
    """Compare a filing with every peer fact and create one evidence-rich incident per conflict group."""
    conn = _connection()
    try:
        init(conn)
        doc = conn.execute("SELECT * FROM v3_documents WHERE id=?", (document_id,)).fetchone()
        if not doc:
            raise V3Error("document is unknown")
        facts = conn.execute("SELECT * FROM v3_facts WHERE document_id=?", (document_id,)).fetchall()
        if not facts:
            _assessment(conn, document_id, "FAILED", ["no parsed facts"])
            conn.commit()
            return {"quality": "FAILED", "incidents": []}
        incident_ids: set[str] = set()
        for fact in facts:
            peers = conn.execute("""SELECT * FROM v3_facts WHERE issuer_id=? AND standard=? AND statement=? AND line_code=?
                                  AND period_end=? AND unit=?""", (fact["issuer_id"], fact["standard"], fact["statement"],
                                  fact["line_code"], fact["period_end"], fact["unit"])).fetchall()
            values = {row["normalized_value"] for row in peers}
            if len(values) > 1:
                evidence = {"issuer_id": fact["issuer_id"], "period_end": fact["period_end"], "statement": fact["statement"],
                            "line_code": fact["line_code"], "values": sorted(values),
                            "sources": [{"document_id": p["document_id"], "page": p["page"], "sheet": p["sheet"], "cell": p["cell"], "raw_label": p["raw_label"]} for p in peers]}
                incident_ids.add(_incident(conn, issuer_id=fact["issuer_id"], period_end=fact["period_end"], form_name=fact["statement"],
                                           code="VALUE_CONFLICT", evidence=evidence, fact_ids=[p["id"] for p in peers]))
        # Form 1 and Form 2 may be separate source documents. Require only the
        # lines the document actually claims to contain; the calculation gate
        # later requires the complete cross-form set for its reporting period.
        by_statement = {row["statement"] for row in facts}
        required = set()
        if "form1" in by_statement:
            required.update({"total_assets", "equity"})
        if "form2" in by_statement:
            required.update({"revenue", "net_income"})
        missing = sorted(required - {row["normalized_key"] for row in facts})
        if missing:
            incident_ids.add(_incident(conn, issuer_id=doc["issuer_id"], period_end=doc["period_end"], form_name=None,
                                       code="MISSING_REQUIRED_ROW", evidence={"document_id": document_id, "missing": missing}, fact_ids=[]))
        quality = "CONFLICT" if incident_ids else "READY"
        _assessment(conn, document_id, quality, sorted(incident_ids))
        _audit(conn, actor, "document.reconciled", "document", document_id, {"quality": quality, "incidents": sorted(incident_ids)})
        conn.commit()
        return {"quality": quality, "incidents": sorted(incident_ids), "missing": missing}
    finally:
        conn.close()


def set_security_class(*, issuer_id: str, class_id: str, ticker: str | None, isin: str | None, share_type: str,
                       price: Any | None, shares_outstanding: Any | None, priced_at: str | None = None,
                       status: str = "ACTIVE", actor: str = "pipeline") -> dict[str, Any]:
    conn = _connection()
    try:
        init(conn)
        if not conn.execute("SELECT 1 FROM v3_issuers WHERE issuer_id=?", (issuer_id,)).fetchone():
            raise V3Error("issuer is unknown")
        row = {"issuer_id": issuer_id, "class_id": class_id, "ticker": ticker, "isin": isin, "share_type": share_type,
               "price": decimal_text(price) if price is not None else None,
               "shares_outstanding": decimal_text(shares_outstanding) if shares_outstanding is not None else None,
               "priced_at": priced_at, "status": status, "updated_at": _now()}
        conn.execute("""INSERT INTO v3_security_classes VALUES (:issuer_id,:class_id,:ticker,:isin,:share_type,:price,:shares_outstanding,:priced_at,:status,:updated_at)
                     ON CONFLICT(issuer_id,class_id) DO UPDATE SET ticker=excluded.ticker,isin=excluded.isin,share_type=excluded.share_type,
                     price=excluded.price,shares_outstanding=excluded.shares_outstanding,priced_at=excluded.priced_at,status=excluded.status,updated_at=excluded.updated_at""", row)
        _audit(conn, actor, "security_class.updated", "security_class", f"{issuer_id}:{class_id}", row)
        conn.commit()
        return row
    finally:
        conn.close()


def _active_formula(conn: sqlite3.Connection, metric: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM v3_formula_versions WHERE metric=? AND state='ACTIVE'", (metric,)).fetchone()
    if not row:
        raise V3Error(f"no active formula for {metric}")
    return row


def create_formula_draft(*, metric: str, expression: str, required_inputs: Iterable[str], actor: str) -> dict[str, Any]:
    if metric not in _FORMULAS:
        raise V3Error("unsupported V3 metric")
    conn = _connection()
    try:
        init(conn)
        version = conn.execute("SELECT COALESCE(MAX(version), 0) + 1 FROM v3_formula_versions WHERE metric=?", (metric,)).fetchone()[0]
        row = {"id": _uid("formula"), "metric": metric, "version": version, "state": "DRAFT", "expression": expression,
               "required_inputs_json": _json(sorted(set(required_inputs))), "created_at": _now(), "activated_at": None, "archived_at": None}
        conn.execute("INSERT INTO v3_formula_versions VALUES (:id,:metric,:version,:state,:expression,:required_inputs_json,:created_at,:activated_at,:archived_at)", row)
        _audit(conn, actor, "formula.drafted", "formula", row["id"], row)
        conn.commit()
        return row
    finally:
        conn.close()


def preview_formula(formula_id: str, issuer_id: str, period_end: str) -> dict[str, Any]:
    conn = _connection()
    try:
        init(conn)
        formula = conn.execute("SELECT * FROM v3_formula_versions WHERE id=?", (formula_id,)).fetchone()
        if not formula:
            raise V3Error("formula is unknown")
        return _calculate_one(conn, issuer_id, _date(period_end, field="period_end"), formula["metric"], formula)
    finally:
        conn.close()


def activate_formula(formula_id: str, *, actor: str) -> dict[str, Any]:
    conn = _connection()
    try:
        init(conn)
        formula = conn.execute("SELECT * FROM v3_formula_versions WHERE id=?", (formula_id,)).fetchone()
        if not formula or formula["state"] != "DRAFT":
            raise V3Error("only a draft formula may be activated")
        conn.execute("UPDATE v3_formula_versions SET state='ARCHIVED', archived_at=? WHERE metric=? AND state='ACTIVE'", (_now(), formula["metric"]))
        conn.execute("UPDATE v3_formula_versions SET state='ACTIVE', activated_at=? WHERE id=?", (_now(), formula_id))
        _audit(conn, actor, "formula.activated", "formula", formula_id, {"metric": formula["metric"], "version": formula["version"]})
        conn.commit()
        return dict(conn.execute("SELECT * FROM v3_formula_versions WHERE id=?", (formula_id,)).fetchone())
    finally:
        conn.close()


def _facts_by_key(conn: sqlite3.Connection, issuer_id: str) -> dict[str, list[sqlite3.Row]]:
    rows = conn.execute("SELECT * FROM v3_facts WHERE issuer_id=? ORDER BY period_end, created_at", (issuer_id,)).fetchall()
    out: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        if not _fact_is_conflicted(conn, row["id"]):
            out[row["normalized_key"]].append(row)
    return out


def _fact_is_conflicted(conn: sqlite3.Connection, fact_id: str) -> bool:
    return bool(conn.execute("""SELECT 1 FROM v3_incident_items i JOIN v3_incidents x ON x.id=i.incident_id
                              WHERE i.fact_id=? AND x.status<>'RESOLVED'""", (fact_id,)).fetchone())


def _period_fact(rows: list[sqlite3.Row], period_end: str) -> sqlite3.Row | None:
    hits = [r for r in rows if r["period_end"] == period_end]
    return hits[-1] if hits else None


def _ltm(rows: list[sqlite3.Row], period_end: str) -> tuple[Decimal | None, dict[str, Any] | None]:
    current = _period_fact(rows, period_end)
    if not current:
        return None, None
    end = date.fromisoformat(period_end)
    annual_end = date(end.year - 1, 12, 31).isoformat()
    prior_end = date(end.year - 1, end.month, end.day).isoformat()
    annual, prior = _period_fact(rows, annual_end), _period_fact(rows, prior_end)
    if end.month == 12:
        return _decimal(current["normalized_value"]), {"current": current["id"], "annual": current["id"], "prior": None}
    if not annual or not prior:
        return None, None
    return (_decimal(annual["normalized_value"]) + _decimal(current["normalized_value"]) - _decimal(prior["normalized_value"]),
            {"annual": annual["id"], "current_ytd": current["id"], "prior_ytd": prior["id"]})


def _market_cap(conn: sqlite3.Connection, issuer_id: str) -> tuple[Decimal | None, dict[str, Any], str | None]:
    rows = conn.execute("SELECT * FROM v3_security_classes WHERE issuer_id=? AND status='ACTIVE'", (issuer_id,)).fetchall()
    if not rows:
        return None, {}, "SECURITY_CLASS_INCOMPLETE"
    missing = [r["class_id"] for r in rows if r["price"] is None or r["shares_outstanding"] is None]
    if missing:
        return None, {"missing_classes": missing}, "SECURITY_CLASS_INCOMPLETE"
    components = {r["class_id"]: decimal_text(_decimal(r["price"]) * _decimal(r["shares_outstanding"])) for r in rows}
    return sum((_decimal(value) for value in components.values()), Decimal(0)), {"classes": components}, None


def _calculate_one(conn: sqlite3.Connection, issuer_id: str, period_end: str, metric: str, formula: sqlite3.Row) -> dict[str, Any]:
    facts = _facts_by_key(conn, issuer_id)
    cap, cap_inputs, cap_reason = _market_cap(conn, issuer_id)
    inputs: dict[str, Any] = {"period_end": period_end, "market_cap": cap_inputs}
    if metric == "market_cap":
        return {"metric": metric, "value": decimal_text(cap) if cap is not None else None, "status": "READY" if cap is not None else "BLOCKED",
                "null_reason": cap_reason, "formula_id": formula["id"], "inputs": inputs}
    if cap is None:
        return {"metric": metric, "value": None, "status": "BLOCKED", "null_reason": cap_reason, "formula_id": formula["id"], "inputs": inputs}
    revenue, rev_refs = _ltm(facts["revenue"], period_end)
    profit, profit_refs = _ltm(facts["net_income"], period_end)
    equity = _period_fact(facts["equity"], period_end)
    assets = _period_fact(facts["total_assets"], period_end)
    end_date = date.fromisoformat(period_end)
    opening_end = date(end_date.year - 1, 12, 31).isoformat()
    opening_equity = _period_fact(facts["equity"], opening_end)
    opening_assets = _period_fact(facts["total_assets"], opening_end)
    average_equity = ((_decimal(equity["normalized_value"]) + _decimal(opening_equity["normalized_value"])) / 2
                      if equity and opening_equity else None)
    average_assets = ((_decimal(assets["normalized_value"]) + _decimal(opening_assets["normalized_value"])) / 2
                      if assets and opening_assets else None)
    inputs.update({"revenue_ltm": {"value": decimal_text(revenue) if revenue is not None else None, "facts": rev_refs},
                   "net_income_ltm": {"value": decimal_text(profit) if profit is not None else None, "facts": profit_refs},
                   "equity": equity["id"] if equity else None, "assets": assets["id"] if assets else None,
                   "average_equity": {"value": decimal_text(average_equity) if average_equity is not None else None,
                                      "facts": [opening_equity["id"], equity["id"]] if opening_equity and equity else None},
                   "average_assets": {"value": decimal_text(average_assets) if average_assets is not None else None,
                                     "facts": [opening_assets["id"], assets["id"]] if opening_assets and assets else None}})
    if metric == "pe" and profit is not None and profit < 0:
        return {"metric": metric, "value": None, "status": "LOSS", "null_reason": "LOSS", "formula_id": formula["id"], "inputs": inputs}
    if metric in {"pe", "roe", "roa", "net_margin"} and profit is None:
        reason = "MISSING_REQUIRED_ROW"
    elif metric in {"ps", "net_margin"} and revenue is None:
        reason = "MISSING_REQUIRED_ROW"
    elif metric == "pb" and equity is None:
        reason = "MISSING_REQUIRED_ROW"
    elif metric == "roe" and average_equity is None:
        reason = "MISSING_REQUIRED_ROW"
    elif metric == "roa" and average_assets is None:
        reason = "MISSING_REQUIRED_ROW"
    else:
        reason = None
    if reason:
        return {"metric": metric, "value": None, "status": "BLOCKED", "null_reason": reason, "formula_id": formula["id"], "inputs": inputs}
    if metric == "pe": denominator = profit
    elif metric == "ps": denominator = revenue
    elif metric == "pb": denominator = _decimal(equity["normalized_value"])
    elif metric == "net_margin": denominator = revenue
    elif metric == "roe": denominator = average_equity
    else: denominator = average_assets
    numerator = cap if metric in {"pe", "ps", "pb"} else profit
    if denominator == 0:
        return {"metric": metric, "value": None, "status": "BLOCKED", "null_reason": "ZERO_DENOMINATOR", "formula_id": formula["id"], "inputs": inputs}
    return {"metric": metric, "value": decimal_text(numerator / denominator), "status": "READY", "null_reason": None,
            "formula_id": formula["id"], "inputs": inputs}


def calculate_issuer(issuer_id: str, period_end: str, *, actor: str = "pipeline") -> list[dict[str, Any]]:
    end = _date(period_end, field="period_end")
    conn = _connection()
    try:
        init(conn)
        if not conn.execute("SELECT 1 FROM v3_issuers WHERE issuer_id=?", (issuer_id,)).fetchone():
            raise V3Error("issuer is unknown")
        rows = []
        for metric in _FORMULAS:
            formula = _active_formula(conn, metric)
            result = _calculate_one(conn, issuer_id, end, metric, formula)
            payload = _json(result["inputs"])
            previous = conn.execute("""SELECT * FROM v3_calculations WHERE issuer_id=? AND period_end=? AND metric=? AND formula_id=? AND inputs_json=?""",
                                    (issuer_id, end, metric, formula["id"], payload)).fetchone()
            if previous:
                rows.append(dict(previous))
                continue
            calculation = {"id": _uid("calculation"), "issuer_id": issuer_id, "period_end": end, "metric": metric,
                           "value": result["value"], "status": result["status"], "null_reason": result["null_reason"],
                           "formula_id": formula["id"], "inputs_json": payload, "created_at": _now()}
            conn.execute("INSERT INTO v3_calculations VALUES (:id,:issuer_id,:period_end,:metric,:value,:status,:null_reason,:formula_id,:inputs_json,:created_at)", calculation)
            rows.append(calculation)
        _audit(conn, actor, "issuer.calculated", "issuer", issuer_id, {"period_end": end, "calculation_ids": [r["id"] for r in rows]})
        conn.commit()
    finally:
        conn.close()
    # Publication is a consequence of a successful, complete computation.  A
    # blocked calculation stays available to operators but cannot replace the
    # public pointer. The call is idempotent, so retries cannot create versions.
    if all(row["status"] in {"READY", "LOSS"} for row in rows):
        publish_issuer(issuer_id, end, actor=actor)
    return rows


def publish_issuer(issuer_id: str, period_end: str, *, actor: str = "pipeline") -> dict[str, Any]:
    end = _date(period_end, field="period_end")
    conn = _connection()
    try:
        init(conn)
        calculations = conn.execute("SELECT * FROM v3_calculations WHERE issuer_id=? AND period_end=? ORDER BY created_at DESC", (issuer_id, end)).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in calculations:
            latest.setdefault(row["metric"], row)
        blockers = [r["metric"] for r in latest.values() if r["status"] not in {"READY", "LOSS"}]
        cap = latest.get("market_cap")
        if not cap or cap["status"] != "READY" or blockers:
            raise V3Error("publication blocked: " + ", ".join(sorted(set(blockers or ["market_cap"]))))
        payload = {r["metric"]: {"value": r["value"], "status": r["status"], "null_reason": r["null_reason"], "formula_id": r["formula_id"], "inputs": json.loads(r["inputs_json"])} for r in latest.values()}
        fingerprint = _json(payload)
        old = conn.execute("SELECT p.* FROM v3_publication_pointers x JOIN v3_publications p ON p.id=x.publication_id WHERE x.issuer_id=?", (issuer_id,)).fetchone()
        if old and old["payload_json"] == fingerprint:
            return {**dict(old), "idempotent": True}
        publication = {"id": _uid("publication"), "issuer_id": issuer_id, "period_end": end,
                       "calculation_ids_json": _json([r["id"] for r in latest.values()]), "payload_json": fingerprint,
                       "status": "PUBLISHED", "created_at": _now(), "superseded_at": None}
        conn.execute("INSERT INTO v3_publications VALUES (:id,:issuer_id,:period_end,:calculation_ids_json,:payload_json,:status,:created_at,:superseded_at)", publication)
        if old:
            conn.execute("UPDATE v3_publications SET status='SUPERSEDED', superseded_at=? WHERE id=?", (_now(), old["id"]))
        conn.execute("INSERT INTO v3_publication_pointers VALUES (?,?,?) ON CONFLICT(issuer_id) DO UPDATE SET publication_id=excluded.publication_id, updated_at=excluded.updated_at", (issuer_id, publication["id"], _now()))
        _audit(conn, actor, "publication.published", "publication", publication["id"], {"replaces": old["id"] if old else None})
        conn.commit()
        return {**publication, "idempotent": False}
    finally:
        conn.close()


def rollback_publication(publication_id: str, *, actor: str, reason: str) -> dict[str, Any]:
    conn = _connection()
    try:
        init(conn)
        publication = conn.execute("SELECT * FROM v3_publications WHERE id=?", (publication_id,)).fetchone()
        if not publication or publication["status"] != "PUBLISHED":
            raise V3Error("only the current publication can be rolled back")
        prior = conn.execute("SELECT * FROM v3_publications WHERE issuer_id=? AND status='SUPERSEDED' ORDER BY superseded_at DESC LIMIT 1", (publication["issuer_id"],)).fetchone()
        if not prior:
            raise V3Error("there is no earlier publication to restore")
        conn.execute("UPDATE v3_publications SET status='ROLLED_BACK' WHERE id=?", (publication_id,))
        conn.execute("UPDATE v3_publications SET status='PUBLISHED', superseded_at=NULL WHERE id=?", (prior["id"],))
        conn.execute("UPDATE v3_publication_pointers SET publication_id=?, updated_at=? WHERE issuer_id=?", (prior["id"], _now(), publication["issuer_id"]))
        _audit(conn, actor, "publication.rolled_back", "publication", publication_id, {"restored": prior["id"], "reason": reason})
        conn.commit()
        return dict(prior)
    finally:
        conn.close()


def document(document_id: str) -> dict[str, Any] | None:
    conn = _connection()
    try:
        init(conn)
        row = conn.execute("SELECT * FROM v3_documents WHERE id=?", (document_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data.pop("original", None)
        assessment = conn.execute("SELECT quality,reasons_json,assessed_at FROM v3_document_assessments WHERE document_id=? ORDER BY assessed_at DESC LIMIT 1", (document_id,)).fetchone()
        data["assessment"] = {**dict(assessment), "reasons": json.loads(assessment["reasons_json"])} if assessment else None
        return data
    finally:
        conn.close()


def original(document_id: str) -> bytes | None:
    conn = _connection()
    try:
        init(conn)
        row = conn.execute("SELECT original FROM v3_documents WHERE id=?", (document_id,)).fetchone()
        return bytes(row["original"]) if row and row["original"] is not None else None
    finally:
        conn.close()


def incident(incident_id: str) -> dict[str, Any] | None:
    conn = _connection()
    try:
        init(conn)
        row = conn.execute("SELECT * FROM v3_incidents WHERE id=?", (incident_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["evidence"] = json.loads(result.pop("evidence_json"))
        result["facts"] = [dict(r) for r in conn.execute("SELECT f.* FROM v3_incident_items i JOIN v3_facts f ON f.id=i.fact_id WHERE i.incident_id=?", (incident_id,))]
        return result
    finally:
        conn.close()


def resolve_incident(incident_id: str, *, actor: str, resolution: dict[str, Any]) -> dict[str, Any]:
    conn = _connection()
    try:
        init(conn)
        row = conn.execute("SELECT * FROM v3_incidents WHERE id=?", (incident_id,)).fetchone()
        if not row:
            raise V3Error("incident is unknown")
        conn.execute("UPDATE v3_incidents SET status='RESOLVED', resolved_at=?, resolution_json=? WHERE id=?", (_now(), _json(resolution), incident_id))
        _audit(conn, actor, "incident.resolved", "incident", incident_id, resolution)
        conn.commit()
        return incident(incident_id) or {}
    finally:
        conn.close()


def audit(*, limit: int = 100) -> list[dict[str, Any]]:
    conn = _connection()
    try:
        init(conn)
        return [{**dict(row), "payload": json.loads(row["payload_json"])} for row in conn.execute("SELECT * FROM v3_audit ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 1000)),))]
    finally:
        conn.close()


def issuer_snapshot(issuer_id: str) -> dict[str, Any] | None:
    """Read-only issuer card for the V3 operational console."""
    conn = _connection()
    try:
        init(conn)
        issuer = conn.execute("SELECT * FROM v3_issuers WHERE issuer_id=?", (issuer_id,)).fetchone()
        if not issuer:
            return None
        documents = []
        for row in conn.execute("SELECT id FROM v3_documents WHERE issuer_id=? ORDER BY created_at DESC", (issuer_id,)):
            item = document(row["id"])
            if item:
                documents.append(item)
        calculations = [dict(row) for row in conn.execute("SELECT * FROM v3_calculations WHERE issuer_id=? ORDER BY created_at DESC", (issuer_id,))]
        incidents = [dict(row) for row in conn.execute("SELECT * FROM v3_incidents WHERE issuer_id=? AND status<>'RESOLVED' ORDER BY created_at DESC", (issuer_id,))]
        publication = conn.execute("SELECT p.* FROM v3_publication_pointers x JOIN v3_publications p ON p.id=x.publication_id WHERE x.issuer_id=?", (issuer_id,)).fetchone()
        return {"issuer": dict(issuer), "security_classes": [dict(row) for row in conn.execute("SELECT * FROM v3_security_classes WHERE issuer_id=?", (issuer_id,))],
                "documents": documents, "calculations": calculations, "incidents": incidents,
                "publication": dict(publication) if publication else None}
    finally:
        conn.close()


def scan_openinfo(*, actor: str = "pipeline") -> dict[str, Any]:
    """Create a traceable scan request without inventing report periods.

    The existing collector remains the network adapter.  The V3 worker consumes
    its downloaded originals and calls :func:`add_document`; this command only
    makes the requested scan visible and auditable.
    """
    conn = _connection()
    try:
        init(conn)
        candidates = 0
        try:
            candidates = conn.execute("SELECT COUNT(*) FROM catalog_reports").fetchone()[0]
        except sqlite3.OperationalError:
            pass
        event = {"id": _uid("scan"), "candidate_reports": candidates, "requested_at": _now(), "state": "QUEUED"}
        _audit(conn, actor, "openinfo.scan_requested", "scan", event["id"], event)
        conn.commit()
        return event
    finally:
        conn.close()
