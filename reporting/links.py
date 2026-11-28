"""Public links identify one published analysis rather than a default company view."""
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from . import store


def parameters(report):
    return {"report": "ai", "report_standard": report["standard"], "report_scope": report.get("scope") or "separate",
            "report_period": report["period"], "report_lang": report["language"], "report_version": report["version"]}


def url(report):
    prefix = "/uz" if report["language"] == "uz" else ""
    return f"https://uzstock.uz{prefix}/company/{quote(report['issuer']['ticker'], safe='')}?{urlencode(parameters(report))}"


def matches(destination, report):
    actual, expected = urlsplit(destination), urlsplit(url(report))
    query = parse_qs(actual.query, keep_blank_values=True)
    return (actual.scheme == "https" and actual.hostname in {"uzstock.uz", "www.uzstock.uz"}
            and not actual.username and not actual.password and not actual.port
            and unquote(actual.path).rstrip("/") == unquote(expected.path)
            and all(query.get(key) == [value] for key, value in parameters(report).items()))


class LinkUnavailable(ValueError):
    def __init__(self, code, status):
        self.code, self.status = code, status
        super().__init__(code)


def pinned(issuer, standard, period, scope, language, version, *, summary=False):
    from sector_report_service import public_report
    report = store.get_run(version)
    if (not report or str(report["issuer"]["id"]) != str(issuer["id"])
            or report["standard"] != standard or report.get("scope", "separate") != scope or report["language"] != language
            or (period is not None and report["period"] != period) or report["status"] != "available"
            or (report.get("text_checks") or {}).get("status") != "passed" or report.get("source_refresh_failed")):
        raise LinkUnavailable("REPORT_VERSION_UNAVAILABLE", 404)
    current = store.latest_publication(issuer["id"], language, standard)
    if not current or current["version"] != version:
        raise LinkUnavailable("REPORT_VERSION_CHANGED", 409)
    result = public_report(report)
    result["ok"] = True
    if summary:
        keys = ("ok", "version", "issuer", "standard", "scope", "language", "period", "period_label", "status", "content_status",
                "headline", "headline_tone", "verdict_line", "card_text", "short_summary", "card_word_count", "availability", "source_snapshot_hash")
        return {**{key: result[key] for key in keys if key in result}, "deferred_full_report": True}
    return result
