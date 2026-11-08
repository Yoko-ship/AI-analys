"""Reuse only history whose source, parser and saved values still match."""
from dataclasses import dataclass


@dataclass(frozen=True)
class VerifiedHistory:
    periods: frozenset[tuple[str, int, int]]
    complete_issuers: frozenset[str]


def verified_history(tickers=None) -> VerifiedHistory:
    # Share the loader's proof rather than treating cache age as completeness.
    # Keep this outside nsbu_history: adding a consumer must not invalidate its
    # implementation digest and force all existing statements to be re-parsed.
    from . import nsbu_history as history, store

    implementation = history.implementation_digest()
    verified, complete = set(), set()
    for issuer, aliases in history._issuers(tickers):
        periods = history._periods(aliases)
        all_match = bool(periods)
        conn = history._connect()
        try:
            for (year, quarter), rows in periods.items():
                _, relationships = history._source(rows)
                key = store.digest([issuer, year, quarter, relationships, implementation, aliases])
                if history._checkpoint_matches(conn, key, aliases, year, quarter):
                    verified.update((alias, year, quarter) for alias in aliases)
                else:
                    all_match = False
        finally:
            conn.close()
        if all_match:
            complete.update(aliases)
    return VerifiedHistory(frozenset(verified), frozenset(complete))
