"""Real production HTML renderer with local data for landing startup checks."""
from e2e.seo_news_app import app  # noqa: F401
from fastapi.responses import JSONResponse
import server.seo.routes as seo


async def stocks():
    return [{"ticker": "UZTL", "name": "Uztelecom", "last_price": 17999,
             "last_trade_date": "2026-10-09", "market_cap": 14192315150331.78}]


seo._stock_board = stocks


async def bonds():
    return []


seo._bonds_board = bonds


@app.middleware("http")
async def local_api(request, call_next):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"ok": True, "items": [], "stocks": [], "companies": []})
    return await call_next(request)
