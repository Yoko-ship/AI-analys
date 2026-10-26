# OpenInfo events and purple concept implementation

References: `UZStock_Openinfo_Events_Before_After.pdf` (11 pages) and
`UZStock_Purple_Concept_Improved.html`, supplied on 2026-10-26.

## Reference coverage

| Capability | Production implementation |
| --- | --- |
| Purple visual system | Shared light/dark colors, card shapes, typography and responsive dashboard/profile layouts from the concept. |
| Public landing page | Original Tashkent skyline, introduction, live market preview, company preview, news and market entry points restored on 26 October. Full market, heatmap, calendar and watchlist remain in their dedicated workspaces. |
| Market and research tools | Existing real-data company pages, market table, chart, converter, bank comparison and CSV retained. |
| Profile workspace | Overview, watchlist, portfolio, notes and settings tabs; account-derived counters; existing account editors and alert settings. |
| Portfolio | Enabled navigation and bookmarks, transaction ledger, position calculations, fees, priced/unpriced valuation and account isolation. Login required. |
| Investment interests | Eleven persisted topics with an editor and a link to the personalized corporate-event feed. |
| Account security | Actual email-verification and two-factor status, with links to the existing security controls. |
| Saved screeners | Gain/loss filters and named configurations saved to signed-in accounts across devices; guest browser storage and explicit import. |
| Watchlist tools | Search, CSV export, issuer alerts and company navigation. |
| Shared header | Information/rates strip and global search removed on request; navigation, account controls, theme and text size retained. |
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

The concept initially replaced the public landing page with four market counters,
an interactive map/table view, market table beside watchlist and currency cards,
then news and upcoming events. That homepage replacement was selectively reverted
on 26 October: the original public landing composition is restored, with the
shared header typography fix retained. The profile overview places watchlist and
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

The issuer directory uses a quote table backed by the same settled market rows
as the main board. Bank offers can be sorted by buy, sell or spread, and the
currency page links related economic news. Profile saved-screener shortcuts
apply the selected account configuration on the market page. Portfolio
allocation is shown only when the account's valuation is complete; incomplete
positions never become a fabricated allocation chart.

## Unified workspace and calendar (26 October 2026)

`styles/workspace-ui.css` provides the shared Manrope heading family, 16 px card
radius, 10 px control radius, 20 px layout spacing, theme-aware surfaces and
violet focus states. Existing data tables and chart layouts retain their own
information density. The month grid sits beside the selected day's agenda on
wide screens and above it on phones. Today is selected initially; empty dates,
arrow-key navigation, month/week/list views, filters and CSV remain available.
Calendar details use a native modal with trapped focus, Escape, scroll locking
and focus restoration. Publication-based entries label their date explicitly.

The timing audit fetched 196 actual announcements. Portal metadata sometimes
contains an upload date instead of the meeting described in the body. For
example, announcement 21404 says 23 October 2026 at 11:00 in its text, while its
metadata says 2 October; 21414 says 31 October at 10:00, not 7 October.
`announcement_dates.py` accepts explicit scheduling paragraphs in Russian,
Uzbek and English, retains the quoted evidence, and excludes registry,
registration, supervisory-board and previously announced meeting dates. In this
audit, 89 dates were supported by body text, 18 corrected the previous date,
and six contradictory dates required review. Other announcements retain their
metadata dates; these are not claimed to have been parsed from the body.
Conflicting body dates, or a conflicting body date before publication, are
withheld from the calendar and remain reviewable in corporate documents.

The calendar reads saved announcement evidence without fetching upstream pages
in user requests. Corrected events can move into another query window; notices
stay on their original publication day. Extraction version 4 refreshes stored
evidence through the existing bounded worker. Numeric summaries use localized
grouping and decimal separators. Empty per-security income fields stay in the
source evidence but do not compete with actual bond income in lead summaries.

Regression tests were run failing before each change. Real source timing
fixtures cover both corrections and false candidates (board decisions,
registry dates, prior meetings and a conflicting historical year).

## Purple theme scope, excluding the screener

The application shell marks every workspace except the `/market` screener with
`data-ui="purple"`. `styles/purple-workspace.css` scopes reference navigation,
controls and surfaces to that marker. The screener keeps its previous styling;
desktop and phone captures in both themes were compared before and after.

The catalog no longer overrides the dark theme with a black/amber terminal
palette. Its issuer rail, command controls, report cards, NSBU year-column
controls and IFRS investor panels use the same application roles. The effective
HTML reference values remain violet `#7454df`, hover `#5635c8`, selected wash
`#f0ebff`, canvas `#f7f7fb`, ink `#251b38` and border `#e9e7f0`. Filled primary
buttons retain the reference violet with white text in both themes; dark-mode
links use the reference's soft violet. Financial gains/losses retain their
semantic green/red. Headings use Manrope, controls use Inter, and financial
values retain tabular numerals. Cards use 16 px corners; controls use 10 px
corners and a 40 px minimum height.
