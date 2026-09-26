"""News articles operations with explicit dependencies."""
from __future__ import annotations
from typing import Any

from urllib.parse import urlsplit
import collectors.news.settings as collectors_news_settings
import collectors.news.sources as collectors_news_sources
import re
import requests


_ARTICLE_MAX_BYTES = 900_000


_ARTICLE_STRIP = ("script", "style", "noscript", "nav", "header", "footer", "aside", "form",
                  "figure", "figcaption", "iframe", "button", "svg")


_ARTICLE_ROOTS = ("article", "main", "[itemprop='articleBody']", ".article-content",
                   ".article__content", ".entry-content", ".post-content", ".news-content",
                   ".content__text", "#content")


_FITCH_API_URL = "https://api.fitchratings.com"


_FITCH_RESEARCH_QUERY = """query UZStockResearchItem($slug: String!) {
  getResearchItem(slug: $slug) {
    abstract
    paragraphs { fieldID header subHeader showHeader content }
  }
}"""


def _fitch_article_text(session: requests.Session, page_url: str, timeout: int = 20) -> str:

    """Return Fitch's public research prose from the API used by its own page.



    Fitch's HTML response is a client-rendered shell, so ordinary HTML extraction sees no

    article. Its public GraphQL ``getResearchItem`` response carries the same public

    paragraphs rendered on the page. Premium Navigator PDFs are deliberately out of scope:

    when there are no public paragraphs, only the public abstract is returned.

    """

    parts = [part for part in urlsplit(page_url).path.split("/") if part]

    try:

        research_index = parts.index("research")

    except ValueError:

        return ""

    slug = "/".join(parts[research_index + 1:])

    if not slug:

        return ""

    try:

        response = session.post(

            _FITCH_API_URL,

            json={"query": _FITCH_RESEARCH_QUERY, "variables": {"slug": slug}},

            headers={

                "Accept": "application/json",

                "Content-Type": "application/json",

                "Origin": "https://www.fitchratings.com",

                "Referer": page_url,

            },

            timeout=timeout,

        )

        if response.status_code != 200:

            return ""

        item = (response.json().get("data") or {}).get("getResearchItem")

    except (requests.RequestException, ValueError, AttributeError) as exc:

        collectors_news_settings.logger.debug("Fitch article API fetch failed for %s: %s", page_url, exc)

        return ""

    if not isinstance(item, dict):

        return ""



    try:

        from bs4 import BeautifulSoup

    except ImportError:

        collectors_news_settings.logger.error("beautifulsoup4 is not installed — run: pip install beautifulsoup4")

        return ""



    blocks: list[str] = []

    seen: set[str] = set()

    for paragraph in item.get("paragraphs") or []:

        if not isinstance(paragraph, dict):

            continue

        content = collectors_news_sources._clean_text(BeautifulSoup(

            str(paragraph.get("content") or ""), "html.parser"

        ).get_text(" ", strip=True))

        key = re.sub(r"\s+", " ", content).strip().casefold()

        if len(content) < 40 or key in seen:

            continue

        seen.add(key)

        header = collectors_news_sources._clean_text(str(paragraph.get("header") or ""))

        if paragraph.get("showHeader") and header and not content.casefold().startswith(header.casefold()):

            blocks.append(f"{header}\n{content}")

        else:

            blocks.append(content)

    if blocks:

        return "\n\n".join(blocks)



    abstract = collectors_news_sources._clean_text(str(item.get("abstract") or ""))

    return abstract if len(abstract) >= 80 else ""


def _article_text(session: requests.Session, page_url: str, timeout: int = 20) -> str:
    """The readable prose of one article page — held in memory, never stored.

    This is the one place the collector reads a source's body text, and what it is read FOR
    is a model call that writes our own account of it (``news_classifier.write_detail``). The
    text itself does not enter the database, is not pushed, and is not returned to any
    reader; that is what keeps the legal invariant (headline + our own summary + link) intact
    while still giving the story page more than a one-sentence teaser.

    Deliberately dumb extraction: take the paragraphs of the likeliest container and drop the
    short ones. A wrong guess yields navigation noise, which ``write_detail`` is instructed to
    answer with empty strings rather than an invented article.
    """
    parsed = urlsplit(page_url)
    if (parsed.hostname or "").lower() in {"fitchratings.com", "www.fitchratings.com"}:
        return _fitch_article_text(session, page_url, timeout=timeout)

    try:
        from bs4 import BeautifulSoup  # lazy: only this pass needs it
    except ImportError:
        collectors_news_settings.logger.error("beautifulsoup4 is not installed — run: pip install beautifulsoup4")
        return ""
    try:
        resp = session.get(page_url, timeout=timeout)
        if resp.status_code != 200:
            return ""
        raw = resp.content[:_ARTICLE_MAX_BYTES]
    except requests.RequestException as exc:
        collectors_news_settings.logger.debug("article fetch failed for %s: %s", page_url, exc)
        return ""
    soup = BeautifulSoup(raw.decode(resp.encoding or "utf-8", "replace"), "html.parser")
    for tag in soup(list(_ARTICLE_STRIP)):
        tag.decompose()
    root = None
    for selector in _ARTICLE_ROOTS:
        root = soup.select_one(selector)
        if root is not None:
            break
    paragraphs = [collectors_news_sources._clean_text(p.get_text(" ", strip=True))
                  for p in (root or soup).find_all("p")]
    # 80 chars keeps datelines, share prompts, photo credits and menu items out while
    # keeping every real paragraph: the shortest genuine one measured across our sources
    # (uza.uz, trend.az, kursiv, spot) was 118.
    # Malformed publisher markup can nest one paragraph inside another, producing the exact
    # same text twice in BeautifulSoup. Deduplicate before the model sees it: repeated source
    # text otherwise becomes repeated claims in the generated article.
    body, seen = [], set()
    for paragraph in paragraphs:
        key = re.sub(r"\s+", " ", paragraph).strip().casefold()
        if len(paragraph) < 80 or key in seen:
            continue
        seen.add(key)
        body.append(paragraph)
    return "\n\n".join(body)


def has_article_page(item: dict[str, Any], sources: dict[str, dict[str, Any]]) -> bool:
    """Whether this item's source publishes a body we can read.

    ``article_body: false`` is the flag for that, and it is the ONLY flag for it. This used
    to also treat ``content: "none"`` as "no article page", which conflates two different
    facts: `content` describes what the LISTING or feed ships, `article_body` what stands
    behind the link. They coincide for the rating agencies, so the conflation went unnoticed
    — but napp.uz ships no snippet on its listing page and perfectly readable articles behind
    it (measured 2026-08-09: 756, 1449 and 1084 characters of prose), and every one of its
    regulatory items was being written off as bodyless because of it.

    An openinfo filing is the separate case: it has no page of its own at all, the portal
    404s every per-fact URL.
    """
    src = sources.get(item.get("source_id")) or {}
    return bool(item.get("url")) and not (
        src.get("type") == "openinfo" or src.get("article_body") is False)
