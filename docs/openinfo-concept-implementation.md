# OpenInfo events and purple concept implementation

References: `UZStock_Openinfo_Events_Before_After.pdf` (11 pages) and
`UZStock_Purple_Concept_Improved.html`, supplied on 2026-10-26.

## Reference coverage

| Capability | Production implementation |
| --- | --- |
| Purple visual system | Shared light/dark colors, card shapes, typography and responsive dashboard/profile layouts from the concept. |
| Home dashboard | Live market counts, searchable sector/period heatmap, selectable tile area, expand/collapse, market-table links, news, calendar events and account watchlist. |
| Market and research tools | Existing real-data company pages, market table, chart, converter, bank comparison and CSV retained. |
| Profile workspace | Overview, watchlist, portfolio, notes and settings tabs; account-derived counters; existing account editors and alert settings. |
| Portfolio | Enabled navigation and bookmarks, transaction ledger, position calculations, fees, priced/unpriced valuation and account isolation. Login required. |
| Investment interests | Eleven persisted topics with an editor and a link to the personalized corporate-event feed. |
| Account security | Actual email-verification and two-factor status, with links to the existing security controls. |
| Saved screeners | Gain/loss filters and named configurations saved to signed-in accounts across devices; guest browser storage and explicit import. |
| Watchlist tools | Search, CSV export, issuer alerts and company navigation. |
| Global search | Header control and Ctrl/Cmd+K search for securities, ISINs and recent news. |
| Calendar | Existing month/week/list views, event filters, selected date and details retained. |
| Corporate classifications | All 46 public fact codes mapped to eight categories, with P0–P3 attention levels and source-dependent confidence. |
| Corporate filters | Important, My companies (watchlist plus holdings), For you (interests plus owned/followed companies), dates, fact code, security class, company/ISIN and sorting. |
| Corporate stages | Proposal, agenda, explicit shareholder approval, accrual, reported partial/full payment; payment totals retain their original units. |
| Corporate evidence | Separate publication/decision/event/payment dates, original source links, source wording, security registry metadata, reporting periods and revision history. |
| Historical evidence | Bounded, resumable source enrichment; daily systemd worker checks 40 documents, with a seven-day per-source recheck interval. |
| Corporate alerts | In-app high-priority events for holdings and subscribed watchlist companies, respecting existing notification preferences and Pro entitlement. |

## Evidence rules

The PDF's UZGF (41/577), TKVK (41/521), and HMKB (announce/20828)
examples remain regression fixtures. Additional real OpenInfo fixtures cover
UZMK's adopted dividend resolution, administrative shareholder decisions,
AGAT bond accrual, SAXOVAT's zero-amount disclosure and HMKB's reported payment.

Publication moderation is never shareholder approval. A meeting registration
date is never a dividend entitlement date. Source totals in thousands of UZS
are never converted into per-share dividends. Capitalization is labeled
separately from cash income. Payment completion requires consistent explicit
totals, payment percentage and outstanding balance.

Stories link stages using an explicit issuer and reporting period, or an
unambiguous issuer/security type/exact decision-date match to a confirmed
period. Same-company/same-day proximity is insufficient. Later agenda items do
not downgrade an already confirmed decision or payment. Observed source
corrections retain revision history and can return a disclosure to review.
Failed or empty source retrieval preserves the previous evidence.

Incomplete, contradictory or unrecognized source content stays **Under review**.
Conditional priority remains provisional. Priority indicates attention to an
event, not a price prediction. No demo prices, portfolio positions, security
badges, payment deadlines or unsupported per-security amounts are published.
Older editorial summaries lacking individual source identifiers cannot recover
those identifiers by inference; the original summary and its source remain
available. New collector runs retain the underlying structured documents.

## Verification

New behavior was covered by failing tests before implementation. Verification
includes the full Python suite, Node unit tests, ESLint, production Vite build
and the full Playwright suite, plus desktop/mobile visual checks. Browser
coverage includes account isolation and synchronization, save retry, interests,
portfolio editing and valuation, map controls, source details, existing account
editors, global search and personalized holdings/interests.

Deployment uses the existing `API` branch pipeline to the `uzstock.uz` server.
The `uzstock-event-evidence.timer` worker uses the same paced OpenInfo adapter
and stored source identifiers as manual document checking; it does not invoke
an AI provider or fetch arbitrary user-provided URLs.
