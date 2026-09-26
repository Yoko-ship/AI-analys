"""News enrichment operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from news_classifier import write_brief_detail
from news_classifier import write_detail
from urllib.parse import urlparse
import collectors.news.articles as collectors_news_articles
import collectors.news.http as collectors_news_http
import collectors.news.settings as collectors_news_settings
import os
import requests
import time


_DETAIL_CAP = int(os.getenv("NEWS_DETAIL_CAP", "40"))


_DETAIL_TAIL_SHARE = float(os.getenv("NEWS_DETAIL_TAIL_SHARE", "0.35"))


def enrich_details(items: list[dict[str, Any]], sources: dict[str, dict[str, Any]],
                   *, max_fetch: int | None = None,
                   usage: Any = None) -> dict[str, dict[str, str]]:
    """``{url: {"ru":…,"en":…,"uz":…}}`` — our own long read, by whichever route an item has.

    Two routes, because "open the source's article page" only exists for some of them:

    * the source publishes a body — read it once, in memory, and have the model write our
      own account of it (:func:`news_classifier.write_detail`);
    * it does not — an openinfo filing or a headline-only source — lay out the material we
      already hold, the disclosure's own figures and our summary
      (:func:`news_classifier.write_brief_detail`), which adds no fact and may return
      nothing when there is nothing to lay out.

    Before this second route, a third of the feed could never have a body at all: 36 of the
    200 items on the live feed are openinfo filings, and a filing's figures are exactly the
    part a holder opens the page for.
    """
    if max_fetch is None:
        max_fetch = _DETAIL_CAP
    todo, brief = [], []
    for it in items:
        (todo if collectors_news_articles.has_article_page(it, sources) else brief).append(it)
    if max_fetch <= 0 or not (todo or brief):
        return {}
    out: dict[str, dict[str, str]] = {}
    # ONE budget across both routes, or a cap of 40 quietly means 80 model calls on a day
    # with filings AND articles. Half each when both have work, and whatever one route does
    # not spend is left to the other.
    brief = [it for it in brief if it.get("url")]        # the url is the write key
    brief_budget = max_fetch if not todo else max(1, max_fetch // 2)
    thin = 0
    for it in brief[:brief_budget]:
        detail = write_brief_detail(it, usage=usage)
        if detail.get("ru"):
            out[it["url"]] = detail
        else:
            thin += 1
    if brief:
        collectors_news_settings.logger.info("detail pass: %d item(s) with no article page; %d laid out from stored "
                    "material%s", len(brief), len(out),
                    f", {thin} too thin to state anything" if thin else "")
    max_fetch -= min(len(brief), brief_budget)
    if not todo or max_fetch <= 0:
        return out
    if len(todo) > max_fetch:
        collectors_news_settings.logger.info("detail pass: %d candidate(s) with an article; reading %d this run "
                    "(NEWS_DETAIL_CAP), the rest on the next one", len(todo), max_fetch)
    session = requests.Session()
    last_hit: dict[str, float] = {}
    empty = wrote = fell_back = 0
    for it in todo[:max_fetch]:
        src = sources.get(it.get("source_id")) or {}
        session.headers.update(collectors_news_http._source_headers(src))
        host = urlparse(it["url"]).netloc
        if host in last_hit:
            wait = float(src.get("crawl_delay_s", 2) or 0) - (time.monotonic() - last_hit[host])
            if wait > 0:
                time.sleep(min(wait, 30))
        last_hit[host] = time.monotonic()
        text = collectors_news_articles._article_text(session, it["url"])
        detail = write_detail(it, text, usage=usage) if text else {"ru": ""}
        # The page was there and gave us nothing readable — a paywall, an SPA shell, an
        # extraction miss. Falling back to the stored material is what stops such an item
        # from being retried forever and reaching the reader as a bare headline every time;
        # it costs the same one call the retry would have cost.
        if not detail.get("ru"):
            detail = write_brief_detail(it, usage=usage)
            fell_back += 1 if detail.get("ru") else 0
        if detail.get("ru"):
            out[it["url"]] = detail
            wrote += 1
        else:
            empty += 1
    session.close()
    collectors_news_settings.logger.info("detail pass: %d of %d article(s) produced a long read%s%s",
                wrote, min(len(todo), max_fetch),
                f" ({fell_back} from stored material)" if fell_back else "",
                f", {empty} yielded nothing" if empty else "")
    return out
