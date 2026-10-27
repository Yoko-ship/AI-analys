"""Local browser-test app: the real HTML renderer with an unavailable bond store.

Run uvicorn e2e.seo_failure_app:app --lifespan off after npm run build.
This module is never imported by the production application.
"""
import asyncio

from api import app
import server.seo.routes as seo


async def unavailable_bonds():
    # Reproduce the expired six-second deadline without a wall-clock sleep.
    raise asyncio.TimeoutError


seo._bonds_board = unavailable_bonds
