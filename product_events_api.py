"""Bounded durable action receipt endpoint; collection failure is explicit."""
import asyncio
from functools import partial

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError
from psycopg import Error as DatabaseError

import product_events as events
import server.auth.limits as limits
from server.auth.access import _require_user
from identity.users import is_admin_email
from web_analytics import is_bot

router = APIRouter()


@router.post('/api/track/actions')
async def receive(request: Request):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 4096:
            raise HTTPException(413, 'Observation is too large')
    try:
        action = events.Action.model_validate_json(bytes(body))
    except ValidationError:
        raise HTTPException(422, 'Invalid product observation') from None
    key = f'product-actions:{limits._client_ip(request)}'
    if not limits._rate_limiter.allow(key, 120, 60):
        raise HTTPException(429, 'Please retry later', headers={'Retry-After': '60'})
    authorization = request.headers.get('authorization')
    try:
        user = await asyncio.to_thread(_require_user, authorization) if authorization is not None else None
        await asyncio.to_thread(partial(events.record, action, user_id=user.id if user else None,
                                       internal=bool(user and is_admin_email(user.email)),
                                       automated=is_bot(request.headers.get('user-agent', ''))))
    except events.ReceiptConflict:
        raise HTTPException(409, 'Observation ID has different data') from None
    except events.ReceiptClockError:
        raise HTTPException(422, 'Observation clock is outside the accepted window') from None
    except (RuntimeError, DatabaseError):
        raise HTTPException(503, 'Observation was not saved; retry later') from None
    return {'ok': True}
