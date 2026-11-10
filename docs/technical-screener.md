# Technical screener

Administrators can open **Market → Columns → Technical**. The group is hidden
for guests, readers and analysts, including when column selections remain in
browser storage. `/api/market/technical` and its v2 alias require an authenticated
administrator and return `Cache-Control: private, no-store`.

“Show Technical” adds SMA20/50/200, 52W High/Low, RSI (14), session change,
change from open, gap and volume in shares. The normal price column remains
visible. ATR (14) and Beta are optional and off by default. The settings only
select columns; numeric range filters are not currently available. Hover or tap
the information icon beside a metric to read its full term and purpose in the
selected language. Sorting uses unrounded values with missing values last. CSV
follows the visible columns and filtered/sorted rows, and includes individual
snapshot dates. Column selections and order persist in this browser.

The endpoint reads the latest 600 stored daily records in one batch. Records
explicitly reporting zero quantity and zero turnover, without a positive trade
count, are carried-forward non-trading days and do not count as sessions or
reset the indicators. Unknown or contradictory activity remains subject to
price validation. Ordinary
and preferred shares keep separate histories. Bonds are excluded. Existing
corporate-action adjustments are applied before calculation. No upstream
requests, synthetic OHLC ranges, forward fills or substituted zeros are used.
The last snapshot date and observation count appear in each cell's tooltip.
The header reports the market's latest stored date, not a claim of live prices.

| Column | Definition |
| --- | --- |
| SMA20/50/200 | `(latest close / mean of the last N recorded closes − 1) × 100`; all N closes must be positive and finite. |
| 52W High/Low | `(latest close / highest high or lowest low in the last 52 calendar weeks − 1) × 100`. Window ends at the market snapshot date. Require history reaching its start and valid OHLC throughout the window. |
| RSI (14) | Wilder average gains/losses, initialized from 14 close-to-close changes. Flat history is 50, no losses with gains is 100, no gains with losses is 0. Missing closes restart the warm-up. |
| Session change | `(latest close / preceding recorded close − 1) × 100`. |
| Change from open | `(latest close / same-session open − 1) × 100`. |
| Gap | `(same-session open / preceding recorded close − 1) × 100`. |
| Volume | Latest session's share quantity, not monetary turnover. A reported zero stays zero. |
| ATR (14) | Wilder-smoothed true range in UZS, seeded by the mean of 14 ranges. Missing or inconsistent OHLC restarts the warm-up. Single-precision source noise is allowed up to one part per million of the range prices; genuine price conflicts remain invalid. |
| Beta | Unavailable until a verified market-index history and benchmark methodology are provided. No unrelated index is substituted. |

Unavailable ATR cells explain whether history is absent, fewer than 14 sessions
are available, or prices are incomplete. They are never replaced with zero.

Periods count stored trading observations, not necessarily consecutive exchange
trading days for an illiquid security. These are daily-history diagnostics;
the independently refreshed board price can be newer than the technical snapshot.
Reference for the requested column meanings: [Finviz screener definitions](https://finviz.com/help/screener).

To recover archival gaps, run `python -m catalogue.technical_history` against the
intended catalogue to preview, then add `--apply` to fill verified gaps. This
maintenance command uses the paced official archive transport, checks security
identity, preserves known prices, and writes only histories that yield ATR(14).
If daily summaries are insufficient, it checks OpenInfo's execution archive,
validates every page and security/date, and reconstructs completed stock-market
sessions. Negotiated T1/NC deals and other markets are excluded. Ambiguous
same-time prices do not become guessed opening or closing prices. Reconstructed
sessions retain the lower execution-source priority in storage.
It skips missing ISINs and already complete histories. Conflicting same-date
archive rows require corroboration from the stored close, quantity and turnover.
Prices are stored unadjusted so corporate actions are applied once on read.
The default search covers 240 months; a genuinely short or absent trading history
remains unavailable. Source reads are never added to market-page requests.

Coverage: `tests/test_market_technical.py`, `e2e/market-technical.spec.js`.
