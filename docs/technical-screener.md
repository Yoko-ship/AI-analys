# Technical screener

Administrators can open **Market → Columns → Technical**. The group is hidden
for guests, readers and analysts, including when column selections remain in
browser storage. `/api/market/technical` and its v2 alias require an authenticated
administrator and return `Cache-Control: private, no-store`.

“Show Technical” adds SMA20/50/200, 52W High/Low, RSI (14), session change,
change from open, gap and volume in shares. The normal price column remains
visible. ATR (14) and Beta are optional and off by default. Each metric and the
price have inclusive minimum/maximum filters; empty bounds mean no restriction.
A bounded filter excludes missing values. Filtering does not require showing
that column. Sorting uses unrounded values with missing values last. CSV follows
the visible columns and filtered/sorted rows, and includes the active bounds and
individual snapshot dates. Column selections and order persist in this browser;
filter bounds belong to the current signed-in account and view.

The endpoint reads the latest 600 stored daily records in one batch. Ordinary
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
| ATR (14) | Wilder-smoothed true range in UZS, seeded by the mean of 14 ranges. Missing or inconsistent OHLC restarts the warm-up. |
| Beta | Unavailable until a verified market-index history and benchmark methodology are provided. No unrelated index is substituted. |

Periods count stored daily observations, not necessarily consecutive exchange
trading days for an illiquid security. These are daily-history diagnostics;
the independently refreshed board price can be newer than the technical snapshot.
Reference for the requested column meanings: [Finviz screener definitions](https://finviz.com/help/screener).

Coverage: `tests/test_market_technical.py`, `e2e/market-technical.spec.js`.
