"""Compatibility imports for news_collector; implementations have explicit owners."""
from dotenv import load_dotenv
load_dotenv()

from collectors.news.articles import (
    _ARTICLE_MAX_BYTES,
    _ARTICLE_ROOTS,
    _ARTICLE_STRIP,
    _FITCH_API_URL,
    _FITCH_RESEARCH_QUERY,
    _article_text,
    _fitch_article_text,
    has_article_page,
)

from collectors.news.backfill import (
    _prod_detail_candidates,
    _prod_items_with_image,
    _prod_items_without_image,
    _prod_items_without_translation,
    _source_registry,
    backfill_details,
    backfill_facts,
    backfill_images,
    backfill_translations,
    purge_failed,
    rejudge_source,
    upgrade_stored_images,
)

from collectors.news.cli import (
    main,
)

from collectors.news.delivery import (
    _prod_request,
    known_urls_in_prod,
    push_details,
    push_images,
    push_news,
    push_news_usage,
    push_snippets,
    push_translations,
)

from collectors.news.enrichment import (
    _DETAIL_CAP,
    _DETAIL_TAIL_SHARE,
    enrich_details,
)

from collectors.news.facts import (
    _FIGURE_FORMATTERS,
    _FIGURE_MAX_FETCH,
    _NON_PAYMENT_MAX,
    _amount_uz,
    _fact_detail,
    _fact_figures,
    _filing_snippet,
    _fmt_accrual,
    _fmt_dividend_payment,
    _fmt_license,
    _fmt_meeting,
    _fmt_obligation,
    _fmt_transaction,
    _join_few,
    _org_short,
    _pct,
    _plural_ru,
    _ru_date,
)

from collectors.news.filings import (
    _FACT_TYPE_MAP,
    _OPENINFO_ORG_URL,
    fetch_openinfo,
)

from collectors.news.http import (
    _source_headers,
)

from collectors.news.images import (
    _BACKFILL_IMAGE_CAP,
    _GENERIC_IMAGE_RE,
    _HEAD_MAX_BYTES,
    _OG_IMAGE_PATTERNS,
    _og_image,
    _upgrade_image,
    enrich_images,
    upgrade_images,
)

from collectors.news.issuers import (
    _openinfo_ticker_map,
    _prod_issuers,
    build_universe,
    issuers_from_prod,
)

from collectors.news.runner import (
    _FETCHERS,
    _skip_triage,
    _split_for_triage,
    fetch_pending,
    run,
)

from collectors.news.settings import (
    DEFAULT_PUSH_URL,
    DEFAULT_UA,
    SOURCES_FILE,
    logger,
)

from collectors.news.sources import (
    _RATING_GRADE,
    _RU_MONTHS,
    _SLUG_ACRONYMS,
    _TAG_RE,
    _TITLE_SMALL_WORDS,
    _TRACKING_PARAMS,
    _WS_RE,
    _canonical_url,
    _clean_text,
    _is_recent,
    _iso,
    _parse_list_date,
    _recase_title,
    _rss_image,
    _title_from_slug,
    fetch_html_list,
    fetch_rss,
    fetch_sitemap,
    load_sources,
)


if __name__ == "__main__":
    raise SystemExit(main())

import os
import sys
import time
from pathlib import Path
import requests
from news_classifier import NewsClassification
