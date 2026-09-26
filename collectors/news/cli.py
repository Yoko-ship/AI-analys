"""News cli operations with explicit dependencies."""
from __future__ import annotations

from datetime import datetime
from datetime import timezone
from news_classifier import classifier_model_name
from runtime_preflight import NEWS_REQUIREMENTS
from runtime_preflight import preflight
from uuid import uuid4
import argparse
import collectors.news.backfill as collectors_news_backfill
import collectors.news.delivery as collectors_news_delivery
import collectors.news.runner as collectors_news_runner
import collectors.news.settings as collectors_news_settings
import json
import logging
import news_store
import sys


def main() -> None:
    ap = argparse.ArgumentParser(description="Collect, classify, and push Uzbek market news.")
    ap.add_argument("--source", help="only this source id")
    ap.add_argument("--limit", type=int, default=40, help="max items per source")
    ap.add_argument("--no-push", action="store_true", help="store locally, do not push to prod")
    ap.add_argument("--dry-run", action="store_true", help="fetch+classify, print, do not store/push")
    ap.add_argument("--backfill-images", action="store_true",
                    help="fill preview images on already-stored items (no LLM calls)")
    ap.add_argument("--backfill-facts", action="store_true",
                    help="re-read stored openinfo filings and replace bare snippets with their "
                         "own figures (no LLM calls)")
    ap.add_argument("--backfill-translations", action="store_true",
                    help="give rows stored before the English/Uzbek summary columns existed "
                         "their translations (one small LLM call per 10 items)")
    ap.add_argument("--backfill-details", action="store_true",
                    help="write the story-page long read for feed items without one "
                         "(one page fetch + one LLM call per item, capped by --limit)")
    ap.add_argument("--refresh-details", metavar="SOURCE_ID",
                    help="rewrite recent long reads for one source after its extractor improves")
    ap.add_argument("--upgrade-images", action="store_true",
                    help="replace stored feed thumbnails with the full-size originals "
                         "behind them (no LLM calls)")
    ap.add_argument("--purge-failed", action="store_true",
                    help="delete items whose classification failed so the next run retries them")
    ap.add_argument("--rejudge", metavar="SOURCE_ID",
                    help="delete this source's REJECTED items (relevant=0) so the next run "
                         "classifies them again — for when the gate changed, not the item")
    args = ap.parse_args()
    # The log names Russian/Uzbek drop reasons and issuer titles; on Windows the console
    # defaults to a legacy codepage and renders them as mojibake, which makes the prefilter's
    # counts undiagnosable. Force UTF-8 where the stream supports it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):  # not a real console / already fixed
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # feedparser missing from the image made every cron run collect 0 items while
    # exiting 0 — name the gap in the log instead of shrugging it off.
    preflight(NEWS_REQUIREMENTS, label="news-collector")
    from codex_usage import read_codex_rate_limit

    run_id = uuid4().hex
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    before_limit = read_codex_rate_limit()
    if args.rejudge:
        result = collectors_news_backfill.rejudge_source(args.rejudge, push=not args.no_push)
    elif args.purge_failed:
        result = collectors_news_backfill.purge_failed(push=not args.no_push)
    elif args.backfill_images:
        result = collectors_news_backfill.backfill_images(limit=args.limit, push=not args.no_push)
    elif args.upgrade_images:
        result = collectors_news_backfill.upgrade_stored_images(push=not args.no_push)
    elif args.refresh_details:
        result = collectors_news_backfill.backfill_details(limit=args.limit, push=not args.no_push,
                                  dry_run=args.dry_run, source_id=args.refresh_details,
                                  replace=True)
    elif args.backfill_details:
        result = collectors_news_backfill.backfill_details(limit=args.limit, push=not args.no_push,
                                  dry_run=args.dry_run)
    elif args.backfill_translations:
        result = collectors_news_backfill.backfill_translations(limit=max(args.limit, 60), push=not args.no_push,
                                       dry_run=args.dry_run)
    elif args.backfill_facts:
        result = collectors_news_backfill.backfill_facts(limit=max(args.limit, 60), push=not args.no_push,
                                dry_run=args.dry_run)
    else:
        result = collectors_news_runner.run(only=args.source, limit=args.limit, push=not args.no_push, dry_run=args.dry_run)

    finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    after_limit = read_codex_rate_limit()
    before_pct = before_limit.get("used_percent") if before_limit else None
    after_pct = after_limit.get("used_percent") if after_limit else None
    delta_pct = round(after_pct - before_pct, 1) if before_pct is not None and after_pct is not None else None
    resets_at = ((after_limit or before_limit or {}).get("resets_at"))
    result.update({
        "codex_limit_used_before_pct": before_pct,
        "codex_limit_used_after_pct": after_pct,
        "codex_limit_delta_pct": delta_pct,
        "codex_limit_resets_at": resets_at,
    })

    mode = next((name for name, enabled in (
        ("rejudge", bool(args.rejudge)),
        ("purge_failed", args.purge_failed),
        ("backfill_images", args.backfill_images),
        ("upgrade_images", args.upgrade_images),
        ("refresh_details", bool(args.refresh_details)),
        ("backfill_details", args.backfill_details),
        ("backfill_translations", args.backfill_translations),
        ("backfill_facts", args.backfill_facts),
    ) if enabled), "collect")
    usage_record = {
        "run_id": run_id,
        "mode": mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "model": result.get("model") or classifier_model_name(),
        "calls": int(result.get("calls") or 0),
        "prompt_tokens": int(result.get("prompt_tokens") or 0),
        "completion_tokens": int(result.get("completion_tokens") or 0),
        "cached_input_tokens": int(result.get("cached_input_tokens") or 0),
        "total_tokens": int(result.get("tokens") or 0),
        "subscription_tokens": int(result.get("subscription_tokens") or 0),
        "codex_before_pct": before_pct,
        "codex_after_pct": after_pct,
        "codex_delta_pct": delta_pct,
        "codex_resets_at": resets_at,
        "fetched": result.get("fetched"),
        "classified": result.get("classified"),
        "relevant": result.get("relevant"),
        "pushed": result.get("pushed"),
        "status": "push_failed" if result.get("push_failed") else "completed",
    }
    try:
        news_store.record_news_usage(usage_record)
        tracked_prod = args.no_push or collectors_news_delivery.push_news_usage(usage_record)
    except Exception:  # noqa: BLE001 — telemetry must not turn a good news run red
        collectors_news_settings.logger.exception("could not persist news usage")
        tracked_prod = False
    result["usage_tracked"] = bool(tracked_prod)
    if before_pct is not None and after_pct is not None:
        collectors_news_settings.logger.info("Codex limit: %.0f%% -> %.0f%% (%+.1f percentage points); news tokens: %d",
                    before_pct, after_pct, delta_pct, usage_record["total_tokens"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    # A run that classified everything correctly and could not hand it to prod has
    # produced nothing a reader will ever see. Exiting 0 made that invisible: the
    # feed stood still from 2026-08-01 to 08-06 behind six green cron cards, because
    # the only symptom was one ERROR line in a log nobody reads on a green run.
    if result.get("push_failed"):
        collectors_news_settings.logger.error("run exiting non-zero: the collection was fine, the push to prod was not")
        raise SystemExit(1)
