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

## Completed reference follow-up

The home page now follows the supplied composition: four market counters,
interactive map/table view, market table beside watchlist and currency cards,
then news and upcoming events. The profile overview places watchlist and
portfolio beside quick actions, interests and actual account security status.
The news page uses compact rows and an events sidebar. The currency workspace
includes four actual-data counters, a bank table, ranked exchange offers,
official CBU history, a converter and a bank/CBU comparison. Existing detailed
market, screener, calendar and account tools remain accessible. The public
issuer directory is `/issuers`; `/catalog` remains the existing financial
research workspace. Manrope is self-hosted with its OFL licence.

`corporate_event_fields.py` defines content-field contracts for all 46 forms.
The fixtures preserve 86 real disclosures across 44 public codes. The public
API returned no samples for codes 26 and 46 during this audit; their contracts
have explicit synthetic tests, not fabricated historical examples. Extracted
facts retain the exact source field path, label and unit. Nested decisions,
positions, asset descriptions and before/after holdings are retained alongside
amounts, dates and percentages. Unknown numeric enumerations remain source
codes; undocumented monetary units remain source units.

Priority rules distinguish voluntary licence return from enforced suspension,
issue-size changes from administrative amendments, routine shareholder
resolutions from dividend/capital decisions, and security-specific events from
company shutdown. A malformed historical code-16 filing with a resolutions
body remains under review. Empty body fields, empty table rows, nonfinite
numbers and inconsistent payment totals cannot confirm an event. These are
transparent editorial rules, not unrestricted understanding of every possible
free-text filing. Unrecognized evidence is deliberately left for review, as
required by the PDF.

The enrichment worker records its extraction version. A new version checks
recently processed documents once, including failed fetches, before returning
to the normal seven-day cooldown. Requests remain bounded, paced and ordered
with unseen/oldest evidence first. Existing source revisions are retained.
