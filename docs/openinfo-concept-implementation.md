# OpenInfo events and purple concept additions

References reviewed: `UZStock_Openinfo_Events_Before_After.pdf` (11 pages) and
`UZStock_Purple_Concept_Improved.html` supplied on 2026-10-26.

## Comparison with the existing site

| Reference capability | Existing / implemented |
| --- | --- |
| Market map, sector filters, company detail, CSV, currency converter and bank comparison | Already implemented; existing real-data screens retained. |
| Calendar with selected date, event filters and event details | Already implemented, including month/week/list views. |
| Watchlist, issuer alerts, notes, profile editing, language and theme | Already implemented with account persistence. |
| Eight corporate-event categories and all 46 public fact codes | Added to the Corporate news tab. |
| Simple titles, priority, stage, original source and separate dates | Added, with Russian, English and Uzbek UI. |
| Important / My companies, date/code/security filters, ISIN search and sorting | Added. My companies uses the authenticated watchlist. |
| Source documents and revision history | Added; editorial day summaries retain each underlying document. |
| Saved screeners with gain/loss selection | Added to the market table. Browser-local storage is explicitly labeled. |
| Watchlist search and CSV | Added to Profile; export respects search and preserves missing values. |
| Home-page upcoming events and personal watchlist | Added using the existing calendar and account data. |

## Evidence boundary

The PDF's UZGF (41/577), TKVK (41/521), and HMKB (announce/20828)
examples are regression fixtures from the actual OpenInfo documents. Portal
`status=approved` is publication moderation, never shareholder approval.
A meeting register date is never presented as a dividend entitlement date.

P0–P3 are starting attention levels from the supplied specification. Conditional
priorities remain marked provisional. Unrecognised or incomplete extraction is
marked **Under review**; the detail view can retrieve the original evidence.
A failed fetch does not erase previously confirmed fields.

Stories link dividend stages only when issuer and an explicit reporting period
are known. Same-company/same-day disclosures are not enough. Every source remains
available, and observed revisions retain their earlier contents. Existing news
rows without retained structured evidence remain available with review status;
new collector runs retain source-level evidence, and checking a document enriches
an older row. No dates, payment completion or share classes are inferred.

The HTML contains simulated market data, demo security status, demo portfolio
positions and local topic toggles. Those examples are not production data. The
existing intentionally hidden portfolio remains hidden; no dummy prices, account
verification, 2FA status or nonfunctional controls were introduced.

## Verification

Tests were written and run failing before implementation. Coverage includes the
three real disclosures, all 46 codes, conservative grouping, source retention,
revisions, source retrieval boundaries, saved filter persistence, and browser
flows on desktop/mobile in light/dark themes. Run the full Python suite, Node
unit tests, ESLint, Vite build and the focused Playwright specs.
