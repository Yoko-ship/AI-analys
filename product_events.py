"""Durable receipts for typed, client-observed successful product actions.

These are UI observations, not payment evidence or proof of human readership.
Transport retries retain an ID; unavailable collection never becomes measured zero.
"""
from datetime import datetime, timedelta, timezone
import hashlib
from typing import Literal
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, model_validator

import web_analytics

KINDS = {'issuer_open', 'news_open', 'chart_open', 'report_open', 'search', 'search_empty', 'search_open', 'favorite', 'publication_visit'}


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: UUID
    observed_at: datetime
    visitor_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,64}$')
    session_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,64}$')
    kind: Literal['issuer_open', 'news_open', 'chart_open', 'report_open', 'search', 'search_empty', 'search_open', 'favorite', 'publication_visit']
    language: Literal['ru', 'uz', 'en']
    internal: bool = Field(default=False, strict=True)
    ticker: str | None = Field(default=None, pattern=r'^[A-Z0-9._-]{1,20}$')
    news_id: int | None = Field(default=None, strict=True, ge=1)
    standard: Literal['nsbu', 'ifrs'] | None = None
    scope: Literal['separate', 'consolidated'] | None = None
    period: str | None = Field(default=None, pattern=r'^\d{4}(Q[1-4])?$')
    version: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,200}$')
    query_type: Literal['ticker', 'other'] | None = None
    result_count: int | None = Field(default=None, strict=True, ge=0, le=1000)
    search_scope: Literal['complete', 'partial'] | None = None
    search_area: Literal['news_feed', 'issuer_directory', 'catalog'] | None = None
    publication_token: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{32}$')
    route_fingerprint: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')

    @model_validator(mode='after')
    def bound_object(self):
        if self.observed_at.tzinfo is None:
            raise ValueError('A timezone is required')
        allowed = set()
        required = set()
        if self.kind == 'publication_visit':
            allowed = required = {'publication_token', 'route_fingerprint'}
        if self.kind in {'issuer_open', 'chart_open', 'favorite', 'report_open'}:
            allowed = required = {'ticker'}
        if self.kind == 'report_open':
            allowed = required = allowed | {'standard', 'scope', 'period', 'version'}
        if self.kind == 'news_open':
            allowed = required = {'news_id'}
        if self.kind == 'search_open':
            allowed = {'ticker', 'news_id', 'search_area'}
            required = {'search_area'}
            if bool(self.ticker) == bool(self.news_id):
                raise ValueError('One opened result is required')
        if self.kind in {'search', 'search_empty'}:
            allowed = {'query_type', 'result_count', 'search_scope', 'ticker', 'search_area'}
            required = {'query_type', 'result_count', 'search_scope', 'search_area'}
            if (self.query_type == 'ticker') != bool(self.ticker):
                raise ValueError('Only an exact known ticker can represent a query')
            if self.kind == 'search_empty' and (self.result_count != 0 or self.search_scope != 'complete'):
                raise ValueError('Empty requires a completed search without results')
        optional = {'ticker', 'news_id', 'standard', 'scope', 'period', 'version', 'query_type', 'result_count', 'search_scope', 'search_area', 'publication_token', 'route_fingerprint'}
        if any(getattr(self, key) is None for key in required) or any(getattr(self, key) is not None for key in optional-allowed):
            raise ValueError('Action fields do not identify the declared object')
        return self

    def object_id(self):
        if self.kind == 'publication_visit':
            return 'publication:' + self.publication_token
        if self.kind == 'report_open':
            reference = f'report:{self.ticker}:{self.standard}:{self.scope}:{self.period}:{self.language}:{self.version}'
            # The exact tuple remains in the durable receipt; long link versions
            # use a collision-resistant object reference in the marketing ledger.
            return reference if len(reference) <= 200 else f'report:{self.ticker}:sha256:{hashlib.sha256(reference.encode()).hexdigest()}'
        if self.kind in {'search', 'search_empty'}:
            return f'search:{self.search_area}:{self.query_type}:{self.ticker or "other"}:{self.search_scope}:{self.result_count}'
        return f'news:{self.news_id}' if self.news_id else f'issuer:{self.ticker}'


class ReceiptConflict(ValueError):
    pass


class ReceiptClockError(ValueError):
    pass


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS web_product_events (
        id BIGSERIAL PRIMARY KEY, event_id UUID NOT NULL UNIQUE,
        observed_at TIMESTAMPTZ NOT NULL, received_at TIMESTAMPTZ NOT NULL,
        visitor_id TEXT NOT NULL, session_id TEXT NOT NULL, user_id BIGINT,
        traffic TEXT NOT NULL, kind TEXT NOT NULL, object_id TEXT NOT NULL, payload JSONB NOT NULL)''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_web_product_events_received ON web_product_events(received_at)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_web_product_events_session ON web_product_events(visitor_id,session_id)')


def _now():
    return datetime.now(timezone.utc)


def record(action, *, user_id, internal, automated):
    # Revalidate callers as well as HTTP input; model_copy can bypass validation.
    action = Action.model_validate(action.model_dump())
    now = _now()
    if not now-timedelta(days=1) <= action.observed_at <= now+timedelta(minutes=2):
        raise ReceiptClockError('Observation is outside the accepted clock window')
    payload = action.model_dump(mode='json')
    traffic = 'automated' if automated else 'internal' if internal or action.internal else 'external'
    if not web_analytics.DATABASE_URL:
        raise RuntimeError('Product observation storage is not configured')
    with psycopg.connect(web_analytics.DATABASE_URL, connect_timeout=3, row_factory=dict_row) as conn:
        conn.execute("SET LOCAL statement_timeout = '3s'")
        inserted = conn.execute('''INSERT INTO web_product_events
            (event_id,observed_at,received_at,visitor_id,session_id,user_id,traffic,kind,object_id,payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO NOTHING RETURNING id''',
            (action.event_id, now if action.kind == 'publication_visit' else action.observed_at, now, action.visitor_id, action.session_id, user_id,
             traffic, action.kind, action.object_id(), Jsonb(payload))).fetchone()
        if not inserted:
            old = conn.execute('SELECT payload,user_id,traffic FROM web_product_events WHERE event_id=%s', (action.event_id,)).fetchone()
            if Action.model_validate(old['payload']).model_dump(mode='json') != payload or old['user_id'] != user_id or old['traffic'] != traffic:
                raise ReceiptConflict('Observation ID already has another value')
    return bool(inserted)
