# Marketing workspace implementation and acceptance

Contract: `UZStock_AI_Marketing_Team_Spec (1).md` and
`UZStock_Marketing_Admin (2).html`, supplied on 2026-11-23. The HTML is a visual
reference, not permission to present its demonstration figures as live data.
The existing UZStock React/Python application and uzstock.uz deployment remain
the implementation target. External account login belongs to the owner.

Production integration (2026-11-28) uses the current `API` branch and places the
team at `/admin/ai-marketing`. The existing `/admin/marketing` editorial desk
and all 578 prior HTTP contracts remain unchanged; 154 team/tracking routes are
added. The new coexistence regression first failed with 404, then passed; both
phone/desktop navigation regressions first failed before the new tab was wired.
The release branch has 402 passing frontend unit tests, a passing build/import
dependency audit and a clean Gitleaks scan. Its Windows full-suite run passed
6,132 cases and skipped 3; 16 failures concern existing Linux `fcntl`/Unix-mode
assumptions. Both causes were reproduced on unchanged commit `603f4e48`.
The full Linux CI suite is therefore a mandatory release gate, not a waived test.
Live deployment evidence is the release workflow's tested commit, image digest,
server revision and production smoke results; earlier local checkpoints below
do not establish that deployment.

## Acceptance ledger

This is the current scope summary; dated checkpoints below preserve the earlier
implementation history. Controlled local acceptance and live service acceptance
are separate. Final combined checks are recorded at the end of this document.

| Requirement | Implemented behavior and evidence | Owner/deployment boundary or known limit |
| --- | --- | --- |
| DEV-01: goal, versions and authority | Owner-gated API/UI; immutable goals, strategies, permissions and history; durable approved-plan steps, dependencies, dates, bounded revisions and exact owner decisions | Human administrator access only; delegated employee roles require a separate permission feature |
| DEV-02: CMO and strategy | Actual model adapter, persisted dialogue, missing-data questions, three typed conditional scenarios, full versioned plans and measured-basis validation; report continue/change/stop decisions | Real model usefulness, latency and pilot targets require owner login and measured work |
| DEV-03: evidence and monitoring | Authorized internal news/market/published-analysis and bounded RSS adapters; source rights, original versions, verification, duplicate/event grouping, corrections, dated theme observations and research references | New authenticated sources need an authorized adapter; absent originals, dates, rights or completeness remain visible blockers |
| DEV-04: team production | Eleven role contracts, persisted handoffs, distinct account/language variants, reviewed language selection, founder facts, references and competitor observations; Claude/Ollama options | Controlled model tests establish the workflow; actual copy/research quality requires the model pilot |
| DEV-05: final checks and terminal skip | Seven rubric contracts; exact originals, amounts/units, dividend states, quarterly differences/deep links, structured daily digests/weekly calendars, source-bound charts and holiday/game context; independent dispatch rechecks and terminal automatic failure | Bounded text rules supplement editorial review; they do not prove arbitrary prose semantically correct |
| DEV-06: real media and export | Local JPEG/carousel/story/chart/MP4 jobs, actual hashes, text alternatives, source/renderer versions, previews, CSV/ZIP export, bounded retry and crash recovery; rendered phone/desktop inspection | Local MP4/ffprobe checked; production image build/smoke belongs to CI; scripts without valid media remain drafts |
| DEV-07: queue and channels | Durable queue, time windows/intervals, pauses, no-earlier-than time, expiry, partial outcomes and no blind retries; Telegram, personal LinkedIn, Facebook Page and Instagram adapters with explicit provider capability choices | Owner app/account setup and live pilot required; unsupported formats disabled; uncertain outcomes remain unknown where independent proof is unavailable |
| DEV-08: analytics and reports | Dated deduplicated events, typed website receipts, identity/attribution rules, 22 metric families with exact inputs/coverage, refunds/entities/monetization stages, immutable weekly snapshots, corrections, comparisons, plan/fact and organic experiment evaluations | Configure real datasets and coverage; unsupported surfaces and payment/platform sources are not inferred; observational experiments do not prove causal lift |
| DEV-09: operation and recovery | Worker lifecycle/heartbeat, separate pauses, persistent role/media state, error diagnostics, verified SQLite/PostgreSQL archives; independent restore lock and owner gap review/quarantine | Operator configures backup schedule; host failover/release rollback must be rehearsed in its intended environment |
| Owner cabinet / HTML reference | Overview, goal/CMO, workflow, content/calendar, sources, reports, settings and experiment screens; live status refresh preserves unsaved edits; empty/error states and source reasons; phone/desktop browser journeys | Demo data are isolated test fixtures, not live marketing results |
| Paid proposals and approvals | Exact creative/source/recipient/parameter approval, budget reservations and revocation; unavailable execution is explicit | A paid executor is a separately scoped integration; §10.9 excludes autonomous spending from initial launch |
| Untrusted inputs | External content is data; model calls have no publishing/secret tools; typed output and server permissions reject authority changes | Production must retain the same server-side permission boundaries |
| Handoff | [Owner guide](marketing-owner-guide.md), [provider matrix](marketing-provider-acceptance.md), [operations and authority](marketing-operations.md), retention/disposal/access policy, release/rollback procedure and section 11 acceptance map below | Owner login, operator configuration, production release and live pilots have not been performed by these local tests |

## Evidence rules and scope

- Test doubles verify logic, not successful publication to social networks.
- No actual social account, model, source or payment integration is marked
  connected merely because its configuration exists.
- Login-dependent live publication checks remain explicit owner handoff items;
  implementation and controlled test coverage must still be completed first.
- Section 10.9 excludes autonomous ad spending and unrestricted internet/social
  management from the initial launch. Paid proposals, exact-version owner
  approval, budget reservation and truthful unavailable-execution status are in
  scope; a new live advertising executor is not a prerequisite for this launch.
  It remains a separately scoped integration, with no campaign or spend implied.
  Likewise the seven rubric contracts do not require new automatic education,
  holiday or product selection engines. Acceptance case 18 does require distinct,
  grounded holiday and game-release treatment in the content workflow.
- Scope check against sections 2 and 5.4 and acceptance case 9: Facebook Stories
  are not a required Facebook format. They are an optional extension, not a
  release requirement; unsupported choices must be clearly unavailable in the
  owner UI. Unknown publication outcomes may remain explicitly unknown when no
  reliable reconciliation is available, provided blind retry stays impossible.
  Do not treat universal provider lookup as mandatory or claim unavailable proof.
- Preserve all pre-existing unrelated worktree changes. Do not deploy an
  unreviewed mixed worktree or build a second image on the production server.
- Each new feature is tested before implementation. On Windows, the mandated
  Python suite uses `.venv\Scripts\python.exe -m pytest -q`.
- The Windows process needs `PYTHONUTF8=1` and `C:\Program Files\Git\bin` in
  PATH for the existing deployment-script tests. The first broad run failed
  only because `bash` was absent from PATH; all 16 affected tests then passed
  without editing deployment code. An earlier full run passed 5,011 tests
  with 98 skipped (194.84 seconds); feedparser emits two upstream deprecation warnings.
  `e2e/admin-panel.spec.js` and `e2e/ai-marketing-workspace.spec.js` passed all 74
  cases together (3.8 minutes). The growing
  `e2e/ai-marketing-workspace.spec.js` covers persisted goals, sources, production,
  reviewed language selection, media JPEG/CSV/ZIP, founder confirmation/revocation,
  terminal skips and responsive navigation. Reports now cover source completeness,
  exact snapshot cuts, late data, source amendments, preserved originals,
  incomparable definitions, real JSON/CSV downloads, owner decisions and actual
  analyst-to-CMO handoffs, including 390px and 1440px flows. The dividend editor
  also verifies a terminal false-payment rejection beside a valid approval,
  with actual API persistence and no delivery side effect.
  Report comparisons use horizontal scrolling with readable numeric columns on
  a phone. The active tab remains visible after reloading a mobile deep link.
  Frontend unit tests passed 352/352; lint has zero errors and one existing
  `AdvancedChart.jsx` rounding warning. Build has the existing chunk-size warning.
  Logs for that earlier checkpoint: `tmp/marketing-reels-full.log`,
  `tmp/marketing-reels-unit.log`, `tmp/marketing-reels-browser-all.log`,
  `tmp/marketing-reels-build.log`, `tmp/marketing-reels-lint.log`.
  The server dependency check also passed with cryptography declared explicitly.
  Telegram/settings, scheduled queue and recovery-lock views were inspected at
  390px and 1440px. The operator CLI also created, inspected and restored a real
  isolated goal snapshot in `tmp/marketing-recovery-cli-20261126`; it preserved
  the goal and returned a paused destination. Tests use controlled providers,
  not live Telegram/Meta/LinkedIn publication or real advertising spend.

- Personal LinkedIn now has owner-only OAuth start/finish, an HttpOnly browser
  binding, single-use durable intents, actual server profile retrieval, account
  and app change checks, encrypted current grants, expiry-aware readiness,
  probe/disconnect and a text/media transport. Login preserves draft/manual/
  automatic permissions; it cannot change an already specified person.
  Real request serialization is intercepted in tests for profile identity,
  minimal scopes, literal punctuation, original links, 201 receipts, explicit
  rejection, numeric/date/daily-reset throttling and uncertain no-replay outcomes.
  Browser tests at 390px and 1440px cover missing configuration, owner consent,
  profile display, refresh, probe, token expiry, local disconnect and stale login
  rejection. The missing control and stale-success expiry message were observed
  failing before their fixes. Ready screens and the media visibility dialog were visually inspected at both sizes.
  Credentials and login intents stay outside portable archives; restore rejects
  existing credentials/intents as well as ordinary records and media, verified
  by extending the existing empty-destination regression. No live LinkedIn login
  or publication occurred. Unknown-post reconciliation remains unfinished.

- LinkedIn now uploads checked local images, ordered multi-image carousels and
  MP4 video, with encrypted upload tickets and durable confirmed-part progress.
  Tests intercept real request serialization and bytes, including upload URL
  validation, exact range coverage, credential placement, lost-finalize status
  reads, processing failure, crash recovery and stale-worker fencing. Changes
  to a reviewed media version/hash block release even when its provenance fields
  still match. The existing real-video test first reproduced a 69,178-byte MP4
  below LinkedIn's 75 KB minimum; renderer v4 writes a standard free-space box
  and the same ffprobe check verifies the resulting video.
  Created post IDs now remain `submitted` until explicit owner visual review;
  201 receipts alone do not prove visibility. The review binds the exact delivery
  version and outgoing payload, records the observation method and never resends.
  New desktop/phone browser cases cover image/carousel/video rendering, approval,
  processing/resume, review, confirmation and persistence. The missing review UI
  and unsafe editing state were observed failing before implementation.

- Meta now supports the owner login boundary for Facebook Pages and linked
  professional Instagram accounts. Separate login configurations, encrypted
  pending choices, explicit target selection, current Page tasks/token identity,
  probe/disconnect and effective access expiry are implemented. The server checks
  app/user/type/scopes and current data-access deadlines; pagination rebuilds
  requests on a fixed host. Account/configuration changes during network I/O
  invalidate the result. Simulated slow responses reproduced expired-intent and
  expired-grant acceptance; Meta and LinkedIn now recheck time after the response.
  Four new real-API browser flows cover Meta login return, selection across
  reload, unchanged draft permissions, probe, expiry and disconnect at 390px and
  1440px. The missing control was observed red before UI implementation, and the
  final selection screens were visually inspected. Facebook text and photo
  publishing now have a separate adapter; Instagram image publishing is described below.
  No real login or platform write occurred.

- Facebook Page text, single-photo and multi-photo posts now upload exact
  reviewed local files as unpublished photos, checkpoint completed uploads and
  create one post with the ordered IDs. All files are validated before any
  upload; repeated remote IDs cannot replace distinct slides. Preparation can
  resume without repeating completed files. Current Page rights, grant expiry,
  permissions, pause, reviewed content and media hashes are checked before the
  public write. Explicit Graph rate rejection preserves the full Retry-After
  and business-use-case recovery delay; lost or malformed publication responses
  remain unknown without replay. Accepted post IDs stay submitted until a
  separate worker read verifies the Page, exact copy, complete ordered photos,
  visibility and publication time. Reads work during a publication pause and
  cannot overwrite concurrent changes. Hidden or mismatched posts stay submitted
  with a scheduled read and an explicit no-resend explanation. These controlled
  tests do not establish live Meta delivery. Facebook Stories and unknown
  photo/text-post reconciliation remain unfinished.

- Facebook videos now use the separate Reels API. Actual local MP4 metadata is
  checked for codec, aspect ratio, dimensions, frame rate, duration and any audio
  streams before upload. Renderer v5 produces fixed 25 fps H.264/yuv420p with a
  two-second closed GOP; the real ffprobe regression first exposed excessive
  keyframe spacing and now checks the generated keyframes. Earlier render
  contracts require a new render and quality review before release.
  Encrypted upload checkpoints bind the file, grant, release and remote video.
  Interrupted uploads read the provider offset before resuming; processing polls
  preserve the public-attempt budget. Expired unpublished uploads can use
  at most three sessions; an already-published/scheduled or mismatched upload cannot
  enter that path. The public finish is sent once unless Meta explicitly rejects
  it. The Page, exact caption, known video ID, processing/publication state and
  actual publication time are independently read before confirming visibility.
  A lost finish response or worker crash can be reconciled through that same
  saved ID without resending. Missing Page membership stays unresolved. A rolling
  30-Reel limit spans local aliases of the same Page and reserves unknown writes
  and in-flight work. Settings and candidate cards disclose the public audience
  and AI label. Desktop/mobile browser flows exercise processing, reload, normal
  acceptance, lost finish, unavailable proof and later successful confirmation.

- Instagram images and photo carousels now publish reviewed JPEG bytes through
  short-lived encrypted fetch URLs. Anonymous fetch requires a valid ticket bound
  to the release, environment, grant, content, asset version and hash; expired,
  altered, disconnected and withdrawn preparations cannot expose the file.
  Private container creation is separate from the single public publish boundary.
  Processing resumes from checkpoints; explicit expiry and throttle responses
  have bounded recovery; provider quota is checked before preparation and send.
  A separate worker read confirms the account, caption, ordered media metadata,
  timestamp and permalink. Missing publish IDs stay unknown without replay.
  Renderer v6 uses a packaged sRGB profile; the repair regression first reproduced
  changing JPEG bytes caused by the profile's embedded clock, then verified exact
  byte preservation. Visual inspection also caught internal source keys used as
  card labels: unknown fields now use a readable RU/UZ/EN fallback in the card
  and its alt text. The media preview and download extension now follow the
  actual MIME type; browser tests verify JPEG signatures in downloaded files.
  Original JPEG, publication and UI regressions were observed
  failing before implementation. Four browser cases cover image/carousel review,
  processing/reload, acceptance, mismatched readback and later confirmation at
  390px and 1440px; resulting screens were inspected. Unknown-ID recovery and live owner-login pilots
  remain unfinished.

- Instagram Reels now reuse durable container preparation and protected MP4
  delivery. The actual file is checked before provider I/O. Renderer v7 removes
  MP4 edit lists, keeps metadata before media and preserves the measured frame
  rate, duration and closed keyframe groups. A real-file regression first failed
  on the previous encoder's edit list. The published Reel must match the known
  ID, owner, caption, video type, Reels surface, timestamp and permalink before
  confirmation. The UI discloses AI labeling and disabled additional feed sharing.
- Instagram image Stories send text inside the reviewed portrait JPEG; no caption
  or link sticker is promised or sent. RU/UZ regressions cover fact cards and chart
  layouts. Independent confirmation requires the known media ID in the selected
  account's active Stories, with matching owner, surface and publication time.
  An expired display window stays unverified and stops polling without resending,
  including when credentials have since been disconnected. The UI explains the
  Business-account requirement and shows the confirmed display deadline or the
  unresolved expiry. New Reels and Story backend/browser cases were observed red
  before implementation; desktop and phone Story images and states were inspected.

- Instagram materials and owner production targets now select `none` or `profile`
  as the reader route. Models cannot add this field to their draft contract. A
  shared localized CTA appears in reviewed media and non-Story captions; changing
  the route invalidates approval and media. Existing releases without the new
  field retain their original content digests. Conservative RU/UZ/EN checks reject
  freeform profile, caption-link, Story-sticker and swipe-up instructions while
  permitting ordinary discussion of company profiles.
  The adapter reads the selected account's `id,website` before media preparation
  and again immediately before publication. The entire URL must equal the exact
  material destination; a homepage, other language/query, different account or
  changed link stops release. Automatic candidates are skipped; manual candidates
  require another review and owner decision. The legacy ready flag is not proof.
  The final payload records the URL, recipient and verification time. The UI shows
  the setup requirement, exact preview link and dated pre-send proof. Browser
  checks exercise manual recovery after a mismatch; this also fixed an existing
  queue-button condition that hid safe reapproval after confirmed non-delivery.
  Renderer v8 reserves room for the CTA and keeps three-fact units inside their
  cards; actual portrait images and the dense three-fact layout were inspected.

- Analysis links now preserve the actual standard, scope, period, language and
  publication version. API regressions prove that pinned reads never regenerate
  a different report and reject changed or mismatched versions. Browser checks
  exercise exact teaser/detail requests, shared URLs, reload/close behavior and
  replaced-version recovery at 390px and 1440px. Company-report browser APIs are
  controlled fixtures; the matching backend tests use the actual report store.
  All 85 cases in `e2e/sector-analysis.spec.js` and `e2e/smoke.spec.js` passed.
  The wider 96-case run exposed a separate timing race in the language test:
  a raw outside click could precede popover listener registration. The test now
  waits for the visible/focused menu and uses an actionable outside target;
  no account-menu product code changed. That regression passed three consecutive
  runs, followed by all 11 cases in `e2e/language-urls.spec.js` (8.5 seconds).
- Dividend regressions use ORFI filing 4061's observed 458.88 UZS/class values,
  with clearly synthetic contradictory copy and proposed/paid alternatives.
  A correct sidecar cannot approve paid wording against an approved original.
  Missing state, a payment window alone, mixed originals, wrong class/currency,
  changed scale and malformed source fields fail safely. Supported negative
  payment wording remains valid for an approval. Real RU/UZ PNGs were inspected;
  their visible status/class captions and versioned media invalidation are tested.

## Decisions

Telegram reconciliation checkpoint (2026-11-26): unknown deliveries now have an
owner workflow backed by actual Bot API observations. Direct channel updates or
intact forwards preserve original channel/message/date identity; ordinary private
text is ignored. A durable cursor acknowledges only committed observations, and
an existing webhook is never removed. Prepared payload snapshots and original
evidence revisions preserve what was sent. Matching requires recipient, bounded
send time, exact text, media type and complete album membership. Duplicate matches,
two indistinguishable pending candidates, changed observations and a previously
bound publication cannot be confirmed. Media still requires explicit owner review
of the actual platform post; caption/count matching is not a visual-equivalence
claim. Confirmation records immutable IDs and history without retrying. A test
reproduced and fixed a late transport timeout overwriting an already confirmed
match. Empty reads never prove absence, and the global backup-gap lock remains.
The backend/API regressions first failed before implementation; follow-up cases
reproduced the late timeout overwrite, ambiguous partial/complete albums and a
conflicting update batch. Browser journeys at 390px/1440px simulate a lost response,
read an empty batch, ingest a controlled original forward, review the exact match,
confirm, reload and assert that the worker does not send again. Both rendered
confirmation dialogs were inspected. All provider responses are local fixtures;
this proves the implemented flow, not a live account pilot.

Telegram/scheduling/recovery checkpoint (2026-11-26): a dedicated bot adapter
checks actual bot/channel identities and posting rights. The worker uses it only
with current credential proof and account permission. Prepared HTTP requests,
actual generated media uploads, album receipt IDs, explicit rate limits and
uncertain outcomes are exercised against an intercepted Telegram peer. Changes
to source, token, recipient or pause during the provider's rights check stop the
write. No actual Telegram credentials or account were used. Other three platform
adapters remain unfinished; the newer Telegram reconciliation checkpoint is above.

Future publication times are entered in Tashkent time in both the material editor
and team brief, survive restart/language selection, and remain subject to final
permissions and source validity. Backend and browser regressions first failed
before implementation. A real single-slide carousel discovered during multipart
testing now receives a cover; renderer version v3 invalidates older proofs.

Backup rehearsals preserve full immutable history and real media in a separate
empty environment. Corrupt, missing, unsafe and inconsistent archives fail before
restore writes; existing state is never overwritten. Restored connections need
new verification. A regression proved that a queued post can have been sent in
the original system after the backup cut, so restoration now applies a separate
publication lock that the normal pause API cannot remove. The UI explains that
platform reconciliation/unlock is still unavailable. This is a verified recovery
foundation, not completed production failover or a live deployment rehearsal.

The same restore acceptance function was also executed against a disposable
local PostgreSQL 17.12 schema on 2026-11-26. It preserved exact candidate history
and actual media hashes, left the source environment unchanged, converted an
in-flight send to unknown, invalidated connections and kept publication blocked
by the independent recovery lock after the ordinary pause was removed. The
schema was removed afterward; the test archive remains under
`tmp/marketing-pg-restore-di7v_8oj`, with output in
`tmp/marketing-postgres-restore-rehearsal.log`. This is a controlled application
archive restore, not a server/database failover or backup-gap reconciliation.

Paid-experiment checkpoint (2026-11-26): owner UI and typed model proposals now
produce durable records; approvals pin campaign parameters, creative hashes and
evidence/recipient versions. Stale goal/evidence/creative, a changed budget or
currency, missing policy review and reserved-budget overflow block action.
Models cannot replace an owner-approved proposal. Red-to-green backend/API
tests and 390px/1440px browser journeys cover creation of a paid creative,
fact checking, proposal, separate approval, explicit missing-connection result,
edited budget losing permission, history/reload and a real persisted role
handoff using a controlled model response. Both rendered layouts were inspected.
These tests perform no actual advertising action. Provider authorization and
execution, reconciliation, stop monitoring and measured evaluation remain open.

Post-publication correction acceptance (2026-11-26): source changes create
versioned incidents without modifying the confirmed post or its delivery.
Owner preparation binds current evidence or an explicit replacement, retains a
visible notice/link, and requires the current account correction policy.
Recipient changes, stale decisions and uncertain previous sends block release.
Revoked sources are detected without reingestion. A second source change during
dispatch produces one current comparison against the newly confirmed post.
API gates, reserved event IDs, immutable history and these races have regression
coverage. Desktop/phone browser journeys exercise preparation, exact approval,
queueing, simulated platform confirmation, reload and reasoned dismissal of a
later editorial change. Actual rendered dialogs and before/after views were
inspected. No real social post was sent. Telegram now has the reconciliation
workflow described above; other provider reconciliation remains pending.

- Reuse `dbx` for SQLite/PostgreSQL compatibility; marketing data has separate
  tables, environment scope, and append-only revisions.
- Owner means an authenticated existing administrator. Agent role messages
  cannot grant themselves that identity.
- Keep account authentication separate from publication permission. Changing a
  recipient invalidates its connection proof. LinkedIn requires explicit
  personal-profile authorization.
- Use the established Claude adapter and prepare a local-model option. Do not
  require a new OpenAI API key for the workspace.
- Final automatic quality failure is terminal. Transport uncertainty has its
  own state and cannot trigger a blind retry.
- Keep unavailable data distinct from measured zero and all forecasts distinct
  from actual business results.

## Product observation acceptance (2026-11-26)

PASS WITH LIMITATIONS for this increment. The native source is opt-in and reads
accounts, visits and durable product receipts in resumable batches. The public
receipt endpoint acknowledges committed PostgreSQL records, rejects changed-ID
replays and unbound/private fields, derives account identity on the server, and
keeps observation and arrival times separate. Full report references preserve
standard/scope/period/language/version; long versions remain exact in receipts.
Shared-browser evidence from visits and receipts must agree before linking an
anonymous session. Original observations and frozen report cuts stay intact.

Browser journeys exercise real rendered issuer headers, populated charts, full
AI reports and editorial articles, safe news-feed search, confirmed search-result
opens and successful favourite additions. Failure/removal does not become
success. One transport retry retains its ID. A failed search destination cannot
claim a later direct open. Missing browser observation APIs do not break content.
The full browser run includes one real UI ? receipt API ? PostgreSQL ? native
reader ? marketing report journey and two real PostgreSQL source-panel journeys.
Content/auth/social/model fixtures remain controlled; these checks make no live
provider or production-readiness claim. Phone/desktop chart and source-panel
screenshots were inspected without clipping or overflow.

Validation: **5,162 Python passed, 2 skipped**; **353 frontend unit passed**;
**109 browser passed**, in one invocation after the current build:

- `e2e/product-actions.spec.js`
- `e2e/visit-tracking.spec.js`
- `e2e/company-chart-history.spec.js`
- `e2e/advanced-chart-history.spec.js`
- `e2e/news-tabs.spec.js`
- `e2e/ai-marketing-workspace.spec.js`
- `e2e/admin-panel.spec.js`

Build passes. Lint has zero errors and the existing AdvancedChart rounding
warning. Logs: `tmp/marketing-product-final-full.log`,
`tmp/marketing-product-browser-full.log`, `tmp/marketing-product-unit.log`,
`tmp/marketing-product-build.log`, `tmp/marketing-product-lint.log`.
Coverage remains incomplete: blocked/lost browser events and legacy account
history cannot be reconstructed. Other product surfaces, publication-specific
click attribution, financial boundary cases and remaining scope below still
require review. This checkpoint does not complete the full requested service.

## Financial reporting acceptance (2026-11-26)

Formula version 3 adds refund reconciliation before cash and service-margin
metrics use the imported amounts. Missing original payments, different customer,
entity or currency, reversed dates and cumulative excess refunds retain their
evidence and block affected calculations with specific owner-facing diagnostics.
Decimal sums distinguish an exact 0.10 + 0.20 refund of 0.30 from a real excess;
valid refunds of earlier-period payments may produce negative current cash.
Zero-value receipts do not add paying customers or ARPPU customers. Free plans
do not enter the opening/closing paid subscription base, and a paid-to-free
downgrade counts as leaving that base. Hard calculation restrictions
remain explicit when a source is also incomplete.

The report separates actual expenses by ИП, ООО and unassigned form, with
advertising, marketing, sales and other categories. Costs exist before paid
services launch, different currencies remain separate, and incomplete coverage
does not become a zero total. An LTV assessment now binds a closed month,
currency, dataset, legal-entity set and measured opening/lost customer counts.
It needs the three immediately preceding measured months and a dated owner
review after month end and before the report cutoff. Stale, legacy unbound,
future-dated and changed-basis decisions cannot enable an estimate.

The initial regressions failed before implementation, including excessive and
mismatched refunds, a zero-value first receipt, absent entity expenses, stale
LTV history and future-dated owner confirmation. The real owner API also
reproduced raw diagnostic IDs entering aggregate exports; exports and analyst
context now share a summary projection that preserves issue codes and reasons
while keeping event and transaction identifiers in the owner's detailed report.
The focused report/API suite passes 67 cases.

Desktop and 390px browser checks exercise calculation, entity costs, an excessive
refund, freezing the warning, importing a correction, recomputing 100,000 UZS,
and reloading the unchanged original snapshot. Visual inspection found wrapped
expense amounts on a phone; a failing layout assertion now requires each number
to occupy one line. Only the new report panels receive accessible region names,
avoiding duplicate labels on existing queue and incident regions.

Final validation: 5,173 backend tests passed with local PostgreSQL enabled,
2 skipped (240.42 seconds); 353 frontend unit tests passed. Both
`e2e/ai-marketing-workspace.spec.js` and `e2e/admin-panel.spec.js` passed together
(78 cases, 5.3 minutes). After the last paid-base calculation fix, all four
report calculation/reconciliation cases passed again at both widths. The built
phone and desktop expense/reconciliation panels were visually inspected;
numeric cells stay on one line inside the scrolling table. Build passes and
lint has zero errors with the existing AdvancedChart rounding warning.
Logs: `tmp/marketing-finance-verified-full.log`,
`tmp/marketing-finance-targeted-final.log`, `tmp/marketing-finance-unit.log`,
`tmp/marketing-finance-browser-final.log`,
`tmp/marketing-finance-browser-reports-final.log`,
`tmp/marketing-finance-build.log`, `tmp/marketing-finance-lint.log`.
This is controlled local acceptance, not live billing/provider or production
deployment proof. The full specification remains unfinished as listed below.

## Metric completeness acceptance (2026-11-26)

Formula version 4 replaces one shared category window with the observation
window and history required by each metric. Current-period visits, registrations,
cash revenue and first-paying counts no longer inherit unrelated attribution or
cohort follow-up windows. Cash does not require prior first-payment history;
unique first-payer counts still do. Entity cash and payer totals use the same
respective completeness rules as their metric families.

Retention needs the prior registration cohort and current-period activity.
Activation and conversion use the actual last registration's configured
deadline, including an event exactly at that deadline; a date-only coverage
interval ending at that midnight does not cover the inclusive event. A current
registration period cannot be considered mature merely because its early
registrants have already completed their follow-up. ROI/ROAS attribution uses
the acquisition windows of the actual paying customers, including acquisition
before the report period. Known later adjustments extend the required service
income window; payback also requires its CAC cohort follow-up.

Coverage evidence remains scoped to dataset and arrival cutoff. A newer gap
notice can withdraw the history needed for unique-customer metrics while leaving
current cash completeness intact. Gaps outside a metric's required window do
not block it. A replacement confirmation must cover the whole required basis;
partial confirmations are not automatically stitched together. The report stores
the required dates, inclusive/exclusive boundary, history requirement, chosen
confirmation and status per metric. Older frozen snapshots remain unchanged.
The summary source table explicitly describes only the report period.

Analyst context now includes metric values, statuses and chosen coverage
confirmations. A separately reproduced regression showed that removing this
basis allowed reuse of a stale summary after coverage alone enabled a metric;
the restored implementation invalidates that summary. The focused backend/API
suite passes 75 cases. New 390px/1440px browser flows cover current-period totals,
missing follow-up details, importing coverage without new events, recomputation,
and reloading the untouched original snapshot. Rendered cash and follow-up
details were inspected at both sizes.

Final checks: 5,181 backend tests passed with local PostgreSQL enabled, 2 skipped
(332.71 seconds); 353 frontend unit tests passed. The built application passed
all 80 cases in `e2e/ai-marketing-workspace.spec.js` and `e2e/admin-panel.spec.js`
together (5.4 minutes). Build passes; lint has zero errors and the existing
AdvancedChart rounding warning. Logs:
`tmp/marketing-metric-windows-full.log`,
`tmp/marketing-metric-windows-targeted.log`,
`tmp/marketing-metric-windows-browser-all.log`,
`tmp/marketing-metric-windows-unit.log`,
`tmp/marketing-metric-windows-build.log`,
`tmp/marketing-metric-windows-lint.log`.
The full specification and live-provider acceptance remain unfinished.

## Publication attribution acceptance (2026-11-26)

Formula v5 adds publication-bound landing receipts. The canonical report URL is
preserved; an opaque outgoing URL is shown before approval and included in its
digest. Revisions and attached media issue a new binding. Exact account identity,
dataset, route and content are checked; profile routing uses the same outgoing
URL. Legacy links and approval digests are preserved. Draft previews and arrivals
before the provider request cannot claim publication credit, and later visibility
confirmation cannot rewrite earlier report cuts.

The public browser receipt contains only the token and route fingerprint in
addition to the existing pseudonymous action envelope. It waits for visibility,
survives SPA URL rewriting and retains separate A → B → A arrivals in one session.
PostgreSQL commits the receipt with server arrival time. The native reader
resolves it against confirmed publication evidence and keeps the existing dated
identity/exclusion behavior. Publication arrivals remain separate from platform
clicks and CTR. Reports show observed arrivals and last-non-direct registration
credit by publication/channel/promotion with explicit incomplete-coverage copy.
Coverage changes affecting only this table invalidate stale analyst context.

Red evidence: eight initial link-contract failures, two receipt/import failures,
the analytics regression, both owner-form browser sizes, the tagged-landing
browser regression, and both publication-table browser sizes were observed
before their implementations. Additional reproduced regressions cover account
identity changes, punctuation around outgoing links and publication-only
coverage changes. The full browser integration uses a controlled Telegram
adapter, the actual previewed outgoing URL, a rendered news page, committed
local PostgreSQL receipts, native source sweeps and the report result. No live
social publication or owner login was performed.

Final validation: **5,207 backend tests passed, 2 skipped** with real local
PostgreSQL enabled (284.65 seconds), **362 frontend unit tests passed**, and
**88 browser cases passed** in the rebuilt application (5.3 minutes):
`e2e/ai-marketing-workspace.spec.js`, `e2e/product-actions.spec.js`, and
`e2e/admin-panel.spec.js`. The final browser run includes channels with arrivals
but no registrations in the report filter. Phone/desktop reports and outgoing
previews were visually inspected. Build passes; lint has no errors and the
existing AdvancedChart rounding warning. Shared browser/Python URL fixtures
reproduced six normalization failures before fixing brackets, fragments and
encoded dot segments; all nine cases now agree. A separate archive rehearsal
restored the exact link, bound candidate and immutable history with publication
paused. Logs: `tmp/marketing-publication-final-full.log`,
`tmp/marketing-publication-browser-final.log`, `tmp/marketing-publication-unit.log`,
`tmp/marketing-publication-build.log`, `tmp/marketing-publication-lint.log`, and
`tmp/marketing-publication-archive.log`.

## Acquisition certainty and exact draft export (2026-11-26)

Formula v6 fixes the reproduced 1,000 UZS advertising / 5,000 UZS confirmed
payment case that previously reported complete ROAS=0 and ROI=-100% despite an
unknown acquisition source. Cash and expenses stay measured; acquisition-based
ratios expose the missing input and specific evidence gap. Checks use the
applicable customers for registration cost, paid-cohort CAC/payback, and current
payment/refund return metrics. Nonpaying or unrelated/zero-value observations do
not overblock other metrics. Complete direct/other-channel evidence and a
complete empty revenue population still permit a measured zero return.

Acquisition resolution distinguishes explicit direct from unknown sources,
rejects later unknown and simultaneous conflicting touches instead of reusing
older channel credit, and prevents payment attribution through a later
registration. Same-time publication ambiguity can preserve the known channel
without guessing a post. Publication counts expose the unresolved link and
remain incomplete. The report details show unresolved customer counts/reasons.

Observed channel/cohort counts retain their numeric observations but now carry
independent `count_basis` completeness. Channel headers label observations and
surface their status. First-payer channels require the actual historical
registration/visit window, independently of complete current payment counts.
Count-basis changes participate in analyst context. Acquisition metric provenance
includes relevant publication/click receipts. Other source/time selection was
still category-wide at this checkpoint; formula v7 below replaces that rule.

ZIP drafts share the sending preview's composer, evidence selection and route
metadata. The exact text includes tracking, original-source links and selected
Instagram CTA, while media-only Stories retain an empty caption. Released
evidence remains pinned after a correction, and the dispatch platform remains
pinned after account reconfiguration. Existing export/download acceptance was
extended rather than duplicated.

Red evidence includes eleven acquisition failures, a neutral zero-receipt
regression, two independent count-basis failures, ambiguous-publication
completeness, six export mismatches, changed-platform preview, and both browser
widths. The publication-source provenance regression was separately run against
the previous selection rule and observed failing before restoring the fix.
The targeted backend/API/real-PostgreSQL set passed 150 cases. The browser flow
imports missing dated source evidence, enables ROI/ROAS, recalculates, and reloads
the untouched original snapshot. The full backend passed 5,224 tests with two
skips (337.52 seconds). The first three-spec browser run passed 87/90; the
coverage fixture needed an explicitly direct return visit under the corrected
unknown-source rule, and one completed publication flow timed out during its
final screenshot. All four affected desktop/phone rechecks passed (24.6 seconds).
The subsequent provenance pass below reruns the integrated suites.

## Metric input provenance (2026-11-26)

Formula v7 replaces category-wide source selection with explicit input records
passed by every metric calculation. Cohort and activity windows, current cash,
service-period allocations and later refunds, selected acquisition costs,
customer attribution evidence, opening/closing subscription state and matched
CTR windows now retain their own evidence. Blocking refund/excluded-finance
records remain visible. Superseded platform snapshots and unrelated currencies,
actions, periods, publications and expense categories no longer refresh a
metric's last-event date. Customer counts remain independent of receipt currency.
LTV also names the owner-reviewed monthly stability references.

Report details distinguish required categories from the actual source names.
The browser regression reproduces a later USD upload incorrectly refreshing a
UZS revenue card; the fixed card shows `receipts-january` and 7 January instead
of the unrelated upload's 12 January. Desktop and phone flows preserve the
coverage/recalculation/original-snapshot checks. Both widths passed and rendered
source details were inspected. This is event-time provenance; ingestion and
amendment freshness, source/type readiness and the remaining attribution/identity
audit remain separate acceptance work.

Fifteen initial provenance cases failed before implementation. Seven additional
acquisition-family cases were checked against the previous category-wide rule
and all failed before restoring the fix. LTV reference and unmatched CTR-window
regressions also failed first. The final targeted backend/real-PostgreSQL set
passed 115 cases. Frontend unit tests passed 362/362; lint has no errors and the
existing AdvancedChart warning. The build and both targeted browser cases pass.
Final verification passed: 5,244 backend tests, two skips, two upstream
feedparser warnings (337.34 seconds); all 90 cases across
`e2e/ai-marketing-workspace.spec.js`, `e2e/product-actions.spec.js` and
`e2e/admin-panel.spec.js` (5.7 minutes). No browser schemas remained in the
disposable PostgreSQL instance, which was stopped after verification. Logs are
`tmp/marketing-provenance-full.log`, `tmp/marketing-provenance-browser-all.log`,
`tmp/marketing-provenance-unit.log`, `tmp/marketing-provenance-build.log` and
`tmp/marketing-provenance-lint.log`. Inspected phone/desktop source details and
acquisition diagnostics are preserved in `tmp/marketing-provenance-visuals`.
Provider tests use controlled adapters; no live login, publication or production
deployment was performed.

## Inspectable research references (2026-11-26)

The Workflow screen now starts a persisted research task without requiring a
social account. Selected evidence, actual role outputs and the existing market
analyst → media analyst → CMO handoff form the context. Structured reference
cards distinguish adapt/reject/original and retain the exact observed excerpt,
suggested technique, rationale and next test. Source metadata is bound by the
server to the selected immutable version. The cards show dates, link, rights
and excerpt-only capability; an unavailable video cannot be claimed as viewed.

Adaptations require verified/current evidence, a real exact excerpt and current
registry permission. Arbitrary sources, quotes, URLs and changed originals are
rejected. An unavailable reference can be rejected while an original-format
proposal reaches the CMO. The role cannot gain publication rights. Both desktop
and phone browser flows create the task, run controlled model steps, inspect the
source card and fallback, reload saved results and confirm no delivery exists.
The actual model pilot still belongs after owner setup/login.

Initial positive/required-output tests failed before implementation. The further
registry-revocation regression also failed before the fix. An isolated negative
control disabled binding/schema checks and all eleven invalid-reference tests
then failed, proving they exercise those controls rather than only a missing
feature. Targeted backend/agent/production checks passed 28 cases. Both browser
widths passed after a rebuild, and their rendered dialogs were inspected. Unit
tests pass 362/362; lint retains the one existing warning. The full backend passed
5,257 tests with two skips and two upstream feedparser warnings (340.64 seconds).
The integrated three-spec browser run passed 90/92 cases; both failures were
30-second test deadlines during final full-page screenshots after all business
assertions had passed. The multi-approval/edit/skip scenario now has a 60-second
budget (individual assertion deadlines are unchanged). Both widths plus both
research flows passed the four-case recheck (24.6 seconds). Thus all 92 distinct
cases have passing evidence. The specs were `e2e/ai-marketing-workspace.spec.js`,
`e2e/product-actions.spec.js` and `e2e/admin-panel.spec.js`.

Logs: `tmp/marketing-references-full.log`,
`tmp/marketing-references-browser-all.log`,
`tmp/marketing-references-browser-recheck.log`,
`tmp/marketing-references-negative-control.log`,
`tmp/marketing-references-unit.log`, `tmp/marketing-references-build.log` and
`tmp/marketing-references-lint.log`. Source and original-fallback dialogs were
visually inspected at both widths; screenshots are retained in
`tmp/marketing-reference-visuals`. Live model/provider access remains unverified
until owner login. No external publication or production deployment occurred.

## Dated competitor comparisons (2026-11-26)

Research now offers a competitor/inspiration task through the real owner UI.
Its market analyst → CMO handoff carries structured cards for purpose, audience,
features, pricing, communication, revenue, conversion and audience size.
All dimensions must be present exactly once; absent observations stay explicitly
undisclosed. Relationships (direct/inspiration/adjacent) and differentiation
hypotheses are separate from observed facts. Prices retain their original dates
and are not relabelled as current tariffs.

Every observed quote binds to selected, verified, available evidence and its
server-supplied metadata. The original's product identity must match the card;
a same-text price from another product cannot be borrowed. Shared
`research_evidence` binding keeps reference and competitor checks consistent,
including changed originals and registry permissions. Seven backend cases were
observed failing before their implementation/fix; the combined competitor,
reference and agent set passed 27 cases. Both competitor browser widths failed
before UI implementation; all four competitor/reference cases pass after the
build. A phone label-wrap issue was corrected during visual review. Final verification passed: 5,264 backend tests with two skips and two upstream
feedparser warnings (341.69 seconds); 362 frontend unit tests; all 94 browser
cases across `e2e/ai-marketing-workspace.spec.js`, `e2e/product-actions.spec.js` and
`e2e/admin-panel.spec.js` together (5.9 minutes). The build passes; lint has no
errors and one pre-existing AdvancedChart warning. Both widths' source/date
rows and undisclosed business metrics were visually inspected after the phone
label fix.

Logs: `tmp/marketing-competitors-full.log`,
`tmp/marketing-competitors-browser-all.log`,
`tmp/marketing-competitors-build.log`, `tmp/marketing-competitors-unit.log` and
`tmp/marketing-competitors-lint.log`. Final screenshots are retained in
`tmp/marketing-competitor-visuals`. The disposable PostgreSQL browser schemas
were cleaned and the local database was stopped after verification. Models and
providers remain controlled test adapters; owner login and a live pilot are
still required. This checkpoint does not complete the full specification.

## Dated theme observations and reviewed history (2026-11-26)

The Sources screen now distinguishes a dated new event, observed recurring
coverage, measured growth and an editorial hypothesis in a theme observation.
The owner selects a theme, fixed registry population and closed calendar window;
the preceding baseline is equal and adjacent. Both use Tashkent boundaries and
the original publication time. Counts merge canonical event keys and identical
original URLs transitively. Earlier originals, including untagged originals,
prevent later reprints from becoming new mentions. Source counts refer to the
selected registry entries with originals in the corresponding window.

Growth requires an explicit owner review of both complete inventories, theme
assignments and reprints, with a recorded basis. RSS collection success never
supplies that proof. Incomplete inventories show observed counts only; zero
baselines have an absolute change with no fabricated percentage. Flat and
declining counts are never classified as growth. Freshness, source population,
relevance, risk and proposed format are visible; the latter editorial judgments
are distinct from measured mentions, and engagement is explicitly unmeasured.

Saved observations pin their originals/configuration in immutable history.
Later matching records, amendments or revoked/changed sources invalidate the
current comparison while preserving its earlier numbers. Reopening the review
requires a fresh completeness confirmation. Publishing freshness expiry alone
does not erase historical counts. Native evidence lacking collector metadata
does not break the workspace. Dates with different offsets are compared as
instants, including the displayed freshness value.

Research tasks can select up to ten observations. The task stores their versions
and dated context; the worker checks them before calling the model and inside
the transaction that accepts its result. A changed inventory or reviewed version
stops acceptance and preserves completed steps; the owner starts a new task
after reviewing the change. The model cannot estimate or approve completeness.

Twenty-two focused backend cases cover these contracts. The initial feature
tests failed before implementation; targeted regressions additionally reproduced
cross-window source counting, untagged originals, old single mentions, missing
collector metadata and offset ordering before their fixes. A simulated-clock
regression also reproduced an arrival during a model call: final acceptance now
samples completion time, so the call's earlier cut cannot hide the new original.
Changed immutable context is a blocked task, not a retryable model outage; both
the API and UI prevent retrying that same obsolete input. The misleading retry
control was observed in visual QA and reproduced before correcting the state.
Browser regressions
at 390px/light and 1440px/dark failed on the missing controls before their UI
implementation. They exercise incomplete review, measured growth, reload,
late data invalidation, fresh review, preserved history, research selection,
visible pinned context and rejection of the next role after changed observations.
The existing source import flow now exercises theme input. Phone and desktop
counts, growth and invalidated states were visually inspected.

All 96 cases across `e2e/ai-marketing-workspace.spec.js`,
`e2e/product-actions.spec.js` and `e2e/admin-panel.spec.js` passed together in
6.0 minutes. After completion-time and blocked-state hardening, both complete
theme/research browser flows passed again (20.9 seconds), including preserved
role output, pinned context and no retry for changed observations. The final
blocked-state screenshot was inspected. The frontend build passes, all 362 unit
tests pass, and lint has no errors with the one pre-existing AdvancedChart
warning. The final full backend run passed **5,288 tests, with two skips and two
upstream feedparser warnings**, in 242.08 seconds, with local PostgreSQL enabled.

Logs: `tmp/marketing-trends-browser-all.log`,
`tmp/marketing-trends-browser-final.log`, `tmp/marketing-trends-build.log`,
`tmp/marketing-trends-unit.log`, `tmp/marketing-trends-lint.log` and
`tmp/marketing-trends-verified.log`.
Screenshots are retained in `tmp/marketing-trend-visuals`.
The browser PostgreSQL schema count was zero, and the disposable local database
was stopped after verification.
This checkpoint does not finish the remaining specification or claim live model
or provider acceptance. No external account login or publishing was performed.

## Structured strategy and owner review checkpoint — 2026-11-27

`Strategy.steps` and `scenarios` now use explicit contracts. The old loose sum
allowed a 4,000,000 UZS step to fit a 3,000,000 UZS goal by adding a negative
1,000,000 UZS step. Budgets are now nonnegative finite values, totals use decimal
arithmetic, dates stay within the goal, and dependency IDs are unique, existing,
acyclic and scheduled before their dependent steps. Planned channels/rubrics and
the owner's unchanged primary KPI/source/target/deadline are checked. The three
scenario budgets are alternatives, rather than three additive expenses.

Each conservative/base/target scenario includes assumptions, actions, resources,
constraints, risks, budget, checkpoint, formula and measurement plan. Without
measured inputs, its numerical projection remains absent. A projection references
a selected frozen reporting snapshot; the server verifies a complete measured KPI,
matching units/currency, a closed historical period with the goal's duration and
unchanged measurement definitions and evidence. It computes baseline × explicitly
assumed factor itself. Zero stays zero, nonfinite results and invalid percentage
ranges are rejected, and test data stays labelled. Unrelated later events outside
the baseline period do not invalidate it.

CMO can return feasibility before goal approval. An accepted strategy task must
deliver a full structured plan; other roles and unaccepted results cannot propose
one. The proposal and completed handoff are saved in the same transaction after
checking current goal and measurements at model completion. A relevant arrival
during reasoning blocks acceptance and preserves completed earlier work. Normal
non-report tasks with `report: null` no longer break report activity recomputation.

The owner selects measured snapshots in the discussion and opens the complete plan
before approval. The dialog shows segmentation, positioning, channels/rubrics,
calendar, role responsibilities, dependencies/deliverables, planned expenses, KPI
definitions/sources, three scenarios with dated proof, risks and permitted CMO
changes. Budget per target is explicitly a planning amount. Approval never grants
paid-action permission. Readiness is recalculated for workspace display and again
at approval; stale evidence blocks a new approval while preserving historical
proposal and approved versions.

Validation evidence: the new desktop/phone browser flows first failed on the absent
scenario UI and then passed through feasibility, selected evidence, full-plan
approval, reload/history and stale-baseline rejection. All 14 invalid-plan cases
failed under a disposable negative control restoring the former untyped budget-sum
gate, then passed under the new rules. There are 35 strategy cases, and the focused
strategy/core/agent/report/API/experiment run passed 104 tests. Frontend unit tests
passed 362 cases; build passed and lint retained only the existing chart warning.
Rendered plan/scenario/stale states were inspected at 1440px dark and 390px light.
Artifacts and logs are in `tmp/marketing-strategy-*`. The final backend run passed
**5,323 tests, with two skips and two feedparser deprecation warnings**, in 352.55s.
The combined browser run of `e2e/ai-marketing-workspace.spec.js`,
`e2e/product-actions.spec.js` and `e2e/admin-panel.spec.js` passed 96 cases; two
existing mobile screenshot cases hit their 30-second limits under concurrent
load. Both passed unchanged with `--last-failed --workers=1` in 9.6s and 11.0s.
All 98 cases therefore have passing evidence, with that initial timing limitation
recorded rather than hidden. No browser test assertions or timeouts were weakened.

This is a strategy contract/review checkpoint. Actual plan-step execution,
substantive CMO plan/fact decisions and the remaining specification work below
are still unfinished. Controlled model responses establish integration behavior;
they are not a live model pilot or provider login/publication acceptance.

## Coordinator work-board checkpoint — 2026-11-27

An owner can activate an exact approved strategy once. Durable work items preserve
the approved step, responsible role, start/due dates, prerequisites, assignment
attempts and task history. Assignment and task creation share one transaction.
Prerequisites unlock only after a saved accepted CMO result or an explicitly
recorded owner result with supporting reference. Future start dates and expired
goal periods block new work; overdue display does not imply completion. Repeated
approval of an already approved strategy is rejected. Activating a revised version
of the same strategy pauses its older run, which cannot then be resumed alongside
the replacement.

Internal operations, research and measurement work go to the responsible role and
CMO. Revision feedback survives bounded new assignments. Claim and completion
checks reject stale goals, selected evidence and measurement bases. The worker
reconciles durable results after interruption, without repeatedly adding identical
blocked revisions. Working-plan pause is separate from publication permissions.

Organic steps use a draft-only production scope bound to the planned channel and
rubric. Existing event/account identity still prevents duplicate production. After
quality checks, a separate CMO task receives actual candidate versions; recovery
rechecks original, media and founder proof before submitting that package. The
board exposes original handoffs, language variants and media jobs. A language or
content change invalidates the current artifact basis while retaining historical
acceptance. Corrected checked candidates can receive a bounded new CMO review
without a second post. Paid steps must produce stored experiment proposals; the
combined proposals across role handoffs cannot exceed that step's budget, currency
or platform. Neither accepted drafts nor proposals imply publishing or spending.

Twenty coordinator regressions and the owner-gated API/alias contract checks cover
these behaviors. The focused strategy/coordinator/agent/production/experiment/
API/worker/module integration run passed 114 tests. Four desktop/phone browser
journeys passed for full strategy review and the work board: dependencies, real
role handoffs, owner evidence, reload/history, pause/resume, draft variants and a
new CMO review after changing language. A late baseline change now leaves a visible
error inside the approval dialog, rather than behind it. Final rendered cards were
inspected at 1440px dark and 390px light. Build and 362 frontend unit tests pass;
lint retains only the existing chart warning. The full backend run passed 5,354
tests with two skips and two feedparser deprecation warnings in 257.65s. Across
the three browser specs, 98 of 100 cases passed in the broad run. The existing
admin screenshot passed unchanged on an isolated recheck; the existing desktop
product-chart screenshot timed out again, then passed unchanged in 9.7s. A
diagnostic run sampled stable chart dimensions without active animations and
also passed; no production change or relaxed assertion was justified. Both
failure traces are preserved. This is passing feature coverage with intermittent
local screenshot timing, not a clean broad run. PostgreSQL browser fixture
schemas were removed (zero remaining) and the local server stopped. Evidence is
under `tmp/marketing-execution-*`.

The owner currently selects the inputs for each new step. Automatic preparation
of versioned reusable input bindings, autonomous priority routing, substantive CMO
plan/fact decisions and the remaining specification work below are not complete.
These checks use controlled model/provider responses and do not establish a live
model pilot, external account login or successful real publication.

## Prepared-input scheduling checkpoint — 2026-11-27

Approved steps now support a versioned preparation before their date or accepted
dependencies are ready. The worker assigns ready work in deadline order, without
an open browser. Evidence, reviewed themes, measured snapshots, accounts and
founder facts are bound to their selected versions. Stale inputs block assignment
and acceptance until explicitly reviewed again. Cancellation and replacement
preserve history; paused plans retain their prepared work. Prepared internal
briefs, research and measurement can follow CMO revision feedback automatically,
within the existing three-assignment limit. A CMO block does not authorize new
work. Draft production and paid proposals retain their separate review paths.

The assignment transaction uses a savepoint to retain a meaningful blocker
without leaving a partial task. Concurrent-worker and duplicate-event checks
pass on SQLite and a disposable PostgreSQL schema. No re-preparation can create a
second event/account production task. Current manually corrected draft packages
can still be rechecked and submitted to CMO against their new evidence, preserving
the initial prepared assignment. Coordinator messages are attributed correctly.

The work board offers prepare, edit and cancel actions and shows saved input
versions. Both internal and draft forms retain their selected fields when reopened.
Browser checks cover dependency waiting, cancellation, reload, stale-original
recovery, actual background assignment, checked draft variants and owner results.
The first backend checks failed before the scheduler existed; later regressions
exposed account changes between assignment and acceptance, a stale preparation
retained during manual draft correction, and missing bounded internal retries.
An additional regression reproduced a manual assignment re-enabling a cancelled
automatic binding. Manual work now leaves that prior automatic scope cancelled.
The focused scheduler checks pass 19 cases, including two PostgreSQL cases.
Disabling the binding and production-identity guards in a disposable test plugin
makes the three account-change and two database-backed duplicate cases fail.
The final full backend suite passes 5,379 tests (two skips, two feedparser
warnings) in 249.77s, including the cancellation regression. Build and 362
frontend unit tests pass; lint has zero errors and the
existing chart warning. All 72 marketing browser cases have passing results:
62 in the broad run and all 10 timeouts on an unchanged single-worker recheck
(2.4m). Eight timeouts occurred during screenshot capture; two reached an action
after exhausting the overall budget. Traces are retained. The four planning
cases now live in `e2e/ai-marketing-planning.spec.js`, using the extracted shared
workspace fixture. Test listing confirmed the same 72 unique case names across
both specs. All eight final targeted cases passed in 3.3m after the extraction:
four in `marketing-planning.spec.js`, plus native website observations on both
viewports, the CMO queued-task round trip and the channel/language workflow in
`marketing-workspace.spec.js`. Desktop dark and phone light prepared, blocked
and accepted cards were visually inspected. No temporary PostgreSQL schemas
remained, and the local server was stopped. Evidence is under
`tmp/marketing-scheduling-*`. Live models/accounts have
not been exercised. The current Russian [owner guide](marketing-owner-guide.md)
describes these workflows and their remaining boundaries.

At that checkpoint, autonomous selection and urgent-news ordering remained open.
The following checkpoint adds bounded individual-event selection; substantive
CMO plan/fact and the other requirements remain open.

## Structured digests and cutoff selection — 2026-11-27

Digest production now preserves 2–8 separate source-bound paragraphs. Each item
contains one distinct confirmed event, with issuer, original publication/event
dates, exact UZStock destination and original URLs assembled by the server before
quality review. Per-item financial checks prevent an amount, share class or
payment status in another item from justifying the wrong statement. Every used
original belongs to its visible item; headlines stay neutral. Displayed dates
must match recorded dates, and a date number cannot excuse an unclaimed dividend.
RU/UZ/EN regressions retain valid share-price text while rejecting such claims.
The assembled text and platform lengths are checked, and owner edits rebuild
the body and invalidate approval. Older frozen publication-link proofs preserve
their basis when the new optional field is absent.

An owner digest rule fixes a Tashkent cutoff and lookback window. The coordinator
waits for that cut, groups reprints, excludes events already assigned organically
to that account, and selects 2–8 current verified news/dividend events with direct
UZStock links (at most 30 originals). Manual digest work also reserves its events.
Paid creatives remain separate from organic identity. An edition's rule/cut key
survives rule edits; an automatic model cannot silently drop a selected event.
Existing strategy, source, account, founder, pause and release checks remain in
force. A failed automatic digest is terminal and has no delivery record.

The UI supports editing individual items, viewing localized item failures,
saving/reopening/disabling cutoff rules and avoiding text digests on unsupported
accounts. Desktop/dark and phone/light screenshots of the editor, cutoff controls,
successful draft and rejection states were inspected. Focus, labels/help, reload,
approval invalidation, persisted output, no page overflow and no page errors were
exercised through real API handlers with isolated data and controlled model replies.

Regressions failed before the relevant fixes: item isolation, repeated event
identity, wrong dates, body length, absent dividend claims, omitted assigned events,
paid/organic separation and missing cutoff controls. Process-only negative
controls also failed when removing the eight-event cap, making edition identity
depend on rule version, relaxing cutoff/format validation or allowing an unclaimed
dividend. No production file was changed by those controls.

The final digest suite passed **5,534 tests, 2 skipped, 250.40s**, with local
PostgreSQL enabled. Zero temporary QA schemas remained and the server was stopped.
The focused digest/core/production set passed 183 tests (one PostgreSQL test skipped
there); the later paid-separation set passed 68 (one skipped there).
Frontend unit tests passed 362/362; lint has only the existing chart rounding
warning and the build passes. All 12 cases in `marketing-digest.spec.js`,
`marketing-quarterly.spec.js`, `marketing-automation.spec.js` and
`marketing-draft-release.spec.js` passed in 40.9s. After the paid/organic correction,
the 4 digest cases and 3 existing manual-post/dividend cases passed in 38.7s.
Logs: `tmp/marketing-digest-final-full.log`, `tmp/marketing-digest-browser.log`,
`tmp/marketing-digest-final-browser.log`, `tmp/marketing-digest-unit.log`,
`tmp/marketing-digest-lint.log`, `tmp/marketing-digest-cutoff-build.log`.
Inspected visuals are archived under `tmp/marketing-digest-visuals`.

Limits: this initial digest uses text posts; only its main destination receives
publication attribution. Bounded financial checks do not prove arbitrary prose.
CMO plan/fact changes begin after this checkpoint and are not included in its
passing full-suite count. External accounts/models remain at the owner-login
boundary; no social post, paid action or production deployment was performed.

## Published quarterly selection and explicit financial intervals — 2026-11-27

An owner rule can now select a current, checked published UZStock analysis with
at least two verified original metrics. The assignment pins the exact analysis
version, destination, period, source inventory and existing owner authority.
Original filing dates remain separate from report publication. Freshness uses
the first available analysis for the issuer/standard/quarter, so regenerating
old commentary cannot create fresh news. The same original URL does not merge
different quarters. A replaced publication or unavailable report store blocks
that assignment while independent rules can continue.

Evidence now preserves original start dates and period kind as well as end
dates. Same-end-date cumulative and standalone figures remain separate. A
quarter subtraction requires two cumulative originals beginning on 1 January,
consecutive quarter ends, matching scope/units and exact arithmetic. Bounded
RU/UZ/EN text checks compare explicit financial flow statements with those
intervals, currencies, scales and displayed results. Nine-month figures cannot
be called third-quarter profit. Missing units, wrong durations, unrelated metric
claims and ambiguous extra amounts fail. Legitimate numeric quarter labels are
treated as period labels without authorizing that number elsewhere in the copy.
This is not a general prose verifier; historical comparative-original assembly
and broader editorial semantics remain open.

The rule form explains analysis freshness and limits urgent priority to news.
Evidence dialogs show readable original lines, actual financial start/end dates
and source units, with the full stored extract still expandable. The internal
analysis-readiness flag is not presented as a financial metric. Final rejection
has a Russian explanation and remains terminal after refresh.

Tests first reproduced unsupported quarterly selection, replaced/unavailable
analysis handling, mismatched quarter wording, lost start intervals, invalid
cumulative operands, missing units, metric substitution and numeric quarter
labels. Isolated negative controls failed when allowing regeneration to refresh
age or allowing a second ambiguous amount. The focused backend set passed 135
tests (one PostgreSQL case skipped there and exercised in the full run).

The first full run found an existing analytics date-grouping bug after local
19:00: adding five hours to a timestamptz before a session-zone date cast applied
the Tashkent offset twice. Daily/hourly/analysis grouping now explicitly uses
`AT TIME ZONE 'Asia/Tashkent'`. The existing real PostgreSQL case was extended
with late-evening traffic under UTC, Tashkent and New York sessions; it failed
before the fix. All 44 focused analytics cases pass. The final full suite passes
**5,499 tests, 2 skipped, 247.53s**, including local PostgreSQL. Test schemas were
empty and the temporary server was stopped afterward.

Frontend unit tests pass 362/362; build passes and lint has only the existing
chart rounding warning. All 8 cases across `marketing-quarterly.spec.js`,
`marketing-automation.spec.js` and `marketing-draft-release.spec.js` passed in
1.8 minutes. After evidence-display polish, the two automatic-quarter cases
passed again; the two original-dialog cases passed in 22.1s after narrowing a
test selector that had matched both the readable quote and hidden raw record.
The updated dialog, rule and result screens were inspected at 1440px/dark and
390px/light, including keyboard navigation, help association, persisted status,
no overflow and no page errors. Logs and screenshots are under
`tmp/marketing-quarter-selection-*`; reproduced analytics failures are under
`tmp/marketing-analytics-timezone-*`. Models and external transports remain
controlled local fixtures; no social publication or production deployment ran.

## Quarterly original periods and financial scope — 2026-11-27

The internal analysis collector previously assigned every original the report's
latest financial date, merged repeated metric names from different periods in
one URL, and omitted the original currency. It now groups facts by original URL,
period, standard, scope and currency. Missing original scope and conflicting
same-period values fail collection; exact repeats remain one original. The
original publication date remains separate from report generation. Final
quarterly checks compare used claims and calculation inputs with the published
facts' exact financial scope, so older incorrectly labeled records also fail.
The existing report contract supplies original monetary facts separately from
calculated ratios; this does not turn derived ratios into raw evidence.

Seven initial collector regressions failed, followed by four final-check
scope regressions. A negative control removing conflict rejection failed on
the conflicting same-period value; logs are `tmp/marketing-quarter-*-red.log`.
The targeted run passed 81 tests. The final full run passed **5,457 tests,
2 skipped, 257.51s**, with local PostgreSQL enabled. Frontend unit tests passed
362/362; build passed and lint retained only the existing chart warning.
The 4 cases in `e2e/ai-marketing-quarterly.spec.js` and
`e2e/ai-marketing-draft-release.spec.js` passed (45.3s). The quarterly UI regression
first failed on the missing localized explanation, then passed after rebuilding.
Actual half-year/nine-month evidence details and terminal rejection were inspected
at 1440px/dark and 390px/light. Logs and screenshots are under
`tmp/marketing-quarter-originals-*`. PostgreSQL test schemas were empty and the
temporary server was stopped. Browser report fixtures use a separate report
database. At this checkpoint, automatic quarterly input selection,
comparative-original assembly and broader quarter-versus-cumulative prose
checks remained unfinished; the next checkpoint adds selection and bounded
period wording checks.

## Explicit release of internal drafts — 2026-11-27

Internal drafts previously remained permanently in draft mode after account
authorization. The owner can now request a fresh final check under the account's
current release rules on the same candidate. The request binds candidate/account
versions, records the selected recipient and refreshes tracking proof. Manual
mode waits for exact-version approval; automatic mode becomes ready or terminally
skipped. Login, paused/expired/closed accounts, changed recipients and paid
creatives cannot bypass this decision. An internal rule draft can be released
after same-recipient login while preserving rule/strategy/original/founder guards.
Changing language or model output cannot create this owner decision.

Fifteen backend cases and the HTTP request reproduced the missing path before
implementation. The corrected UI regression failed at the absent release button.
The generated-draft case then exposed tracking proof tied to the old mode; release
now issues current proof before checking. Final targeted checks passed 19 cases;
the adjacent run passed 126 (1 skipped without PostgreSQL). The final full suite
passed **5,446 tests, 2 skipped, 273.91s**, with local PostgreSQL enabled. Frontend
unit tests passed 362/362, build and route contracts passed, and lint reported only
the existing AdvancedChart rounding warning. Three selected browser cases passed
in `e2e/ai-marketing-draft-release.spec.js` and `e2e/ai-marketing-workspace.spec.js`
(46.3s), exercising real API handlers with controlled model/identity inputs.
Both release cases also passed with explicit keyboard-focus assertions and
the app's actual dark/desktop and light/phone settings (26.5s); rendered action
and saved-decision views were inspected. The local PostgreSQL test schemas were
empty after the full run and the temporary server was stopped.
Backend tests continue the release through a controlled transport, including
connection checks, pause, manual approval and exactly one confirmed receipt.
Logs: `tmp/marketing-draft-release-*`; screenshots:
`tmp/marketing-draft-release-visuals`. No live account was connected or posted.

## Generated destination binding — 2026-11-27

Production briefs can specify the exact reader destination. Generated candidates
must use that destination, a URL declared by their selected originals, or an
explicit owner edit recorded by the server. Missing and unrelated model-generated
destinations fail checks. Selecting a language variant cannot approve its URL.
Owner edits preserve the candidate's identity and reset its check/approval; a
skipped automatic candidate remains terminal. Direct URLs are checked with or
without visit tracking, including dot-segment paths that normalize to the homepage.
This does not prove live page availability or validate every URL embedded in prose.

Red regressions covered missing/unrelated generated destinations, absent brief
support, owner repair, language-selection authorization, normalized home paths
and tracking-disabled bypasses. Logs: `tmp/marketing-editorial-*-red.log` and
`tmp/marketing-editorial-language-control-red.log`. Final checks: 5,428 backend
tests passed, 2 skipped (251.34s, local PostgreSQL enabled); 362 frontend unit
tests passed; build passed and lint had only the existing AdvancedChart warning.
The 3 affected cases in `e2e/ai-marketing-planning.spec.js` and
`e2e/ai-marketing-workspace.spec.js` passed cleanly (1.9m). Logs are under
`tmp/marketing-editorial-links-*`; screenshots are in
`tmp/marketing-editorial-links-visuals`. Explicit release of checked internal
drafts still needs implementation; this checkpoint only fixes destination proof.

## Individual-event automation — 2026-11-27

Explicit owner rules bind an exact approved strategy, permitted sources, one
account, languages/format, rubric, Tashkent dates, daily count, maximum event age
and draft/account mode. The worker selects current verified originals without
an open browser. Supported individual-event rubrics are news, complete market
sessions, dividend decisions and announced calendar dates. Aggregate or complex
editorial packs are unavailable in this rule form until their selection semantics
are implemented.

Canonical/URL grouping reuses the trend implementation. It also considers earlier
originals and their immutable revisions, preventing new reprints or rewritten
publication dates from making an old event fresh. Selected originals, the whole
event inventory, account/founder versions and exact rule version are pinned and
rechecked before/after model work and throughout candidate release. A late
contradictory original blocks the old task. Revoked rules cannot queue/send a
previously checked candidate, including after provider preparation. Terminal
rejection remains terminal; an independent event can proceed. Assignment limits
use Tashkent days and survive rule edits. Runtime observations do not mutate
owner rule versions.

Confirmed urgent news up to 24 hours old takes precedence within production
work and the same account's delivery queue. Other owner jobs retain their slots.
Urgency does not bypass verification, manual approval, publication windows,
minimum intervals, pauses, restore lock or provider checks. No live channel or
model was used. Owner controls, saved selections, wait-for-verification, actual
assignment, reload, history and revocation passed initial browser checks at
1440px/dark and 390px/light; both rendered layouts were inspected.

Red/green evidence: nine initial selector failures before implementation; five
priority/worker/revocation failures before wiring those boundaries; a real old
original whose dates were amended reproduced the freshness bug; scheduling a
revoked ready candidate failed before its schedule guard; six unsupported pack
types failed before the API/form were bounded. Eight isolated negative controls
also fail when removing assignment, deduplication, date enforcement or the final
preparation guard. An oversized original bundle reproduced a worker interruption;
assignment now rolls back that rejected bundle, records the blocker and continues
to independent events without creating partial tasks or churning runtime history.
The normal targeted module passes 32 cases, including concurrent
SQLite/PostgreSQL workers and checked candidates for all four supported rubrics.
The final full suite passes 5,414 tests (2 skipped, 250.56s), including local
PostgreSQL cases. Frontend unit tests pass 362/362; build and lint pass with the
existing chart rounding warning. The initial two feature browser cases passed;
the expanded 15-case run across `marketing-automation.spec.js`,
`marketing-planning.spec.js` and `marketing-workspace.spec.js` passed 13 cases,
with two screenshot-capture timeouts. Both failed cases passed unchanged when
rerun singly with the same assertions and timeouts. Form and assignment views
were inspected in both themes and viewport sizes. Logs are in
`tmp/marketing-automation-*`, retained traces in
`tmp/marketing-automation-browser-failures`, and screenshots in
`tmp/marketing-automation-visuals`. No live publication, paid action or production
deployment occurred.

## CMO decisions and plan/fact acceptance checkpoint

Accepted CMO report outputs now require typed continue/change/stop decisions and
a linked hypothesis tree. The server checks metric, hypothesis, parent and approved
strategy-step references, cycles, duplicate IDs and dates within 90 days. It attaches
the exact original report period, dataset, metrics, source/formula/coverage details,
goal and strategy versions, plan/fact and context digest. Models cannot supply or
replace that basis. Invalid local contracts leave a visible bounded retry reason.
Analyst outputs cannot use the CMO contract. Proposals do not execute tests, alter
the goal or budget, or grant publication or paid-action permission.

An open reporting period previously compared its observed value with the full
target. The regression reproduced this: the current observation remains visible,
but actual/difference are available only for a complete, closed, matching period
and non-estimated metric. Incomplete values were already unavailable; the new
tests preserve that existing behavior. The real estimated LTV case also cannot
be promoted to a final goal result. Late source changes invalidate current CMO
analysis while preserving its frozen original basis.

Evidence: the initial plan/fact regression failed once with two adjacent cases
passing; its desktop/phone browser cases both failed before the fix. CMO contract
tests initially failed three cases; removing the new binder in a process-only
negative control fails nine authority/reference cases. Removing the estimate gate
fails the existing LTV regression. Seven safe-error cases failed before localized
reasons were exposed. The stale queued-task banner also failed on both viewports
before being tied to the current analysis task ID.

The final full suite passes **5,548 tests, 2 skipped, 251.19s** with local PostgreSQL.
An earlier full run found one old refund-coverage fixture returning free text; it
now uses the typed CMO contract and still asserts the original incomplete value
and late-coverage invalidation. The focused rerun passed 35 tests. PostgreSQL
reported zero remaining QA schemas and was stopped afterward. Frontend unit tests
pass 362/362; the build passes and lint has only the existing chart rounding warning.
The final browser selection in `marketing-report-decisions.spec.js` and
`marketing-workspace.spec.js` passes **7/7, 30.1s**. Current screenshots were inspected
at 1440px dark and 390px light, including the hypothesis tree and decision cards.
Logs are `tmp/marketing-cmo-*` and `tmp/marketing-plan-fact-*`; screenshots are in
`tmp/marketing-cmo-decisions-visuals`. Model outputs were controlled fixtures;
live model quality and external publication remain unverified until owner login.

## Organic experiment evaluation acceptance checkpoint

The owner can register an immutable organic test design with all §6.2 conditions,
exact selected publications and their creative/account/goal/dataset basis. Designs
registered after enrollment begins are labelled retrospective. A calculation uses
the dated effective event ledger, exact action objects, unique confirmed external
readers and inclusive follow-up windows. Duplicate visits/actions, wrong datasets,
paid traffic and wrong channels are excluded. Cross-exposure includes an opposite
arm reached after enrollment closes but before follow-up ends. Existing accounts
are excluded for a registration KPI, with history completeness required.

Small samples in either arm, incomplete coverage, open windows, changed creatives
or destinations keep a result preliminary. Counts and rates remain visible; the
comparison difference is suppressed. Even a complete result is observational and
does not prove causal lift. Each evaluation is immutable. Repeat/change/stop
decisions reference one exact evaluation and never change the owner goal/budget.
Later corrections create another evaluation and leave prior decisions attached
to their original cut. Human stop-condition review does not automatically cancel
external posts. Reports and CMO tasks receive up to ten latest applicable saved
evaluations known at their cutoff; new evidence changes the context digest.

Eighteen backend feature cases cover the scope, reader logic, incomplete/empty
inputs, wrong-role/goal/publication cases, source corrections, immutable decisions
and point-in-time report integration. The initial 15 feature cases failed before
implementation; a separate cross-exposure regression failed for a post-enrollment
touch within follow-up. The corresponding outside-follow-up boundary passes. Four
process-only negative controls fail when removing dataset, paid-traffic,
minimum-sample or creative-change protections. The report integration test failed
before saved evaluations were included in the CMO context.

The first full run passed 5,571 cases and failed only the HTTP-route fixture, which
needed the three new owner-gated commands and their v2 aliases. Its focused rerun
passed 25 cases. The final full suite passes **5,572 tests, 2 skipped, 254.43s**,
with local PostgreSQL enabled. Zero QA schemas remained; PostgreSQL was stopped.
Frontend unit tests pass **362/362**, build passes and lint has only the existing
chart rounding warning. The combined browser selection in
`marketing-editorial-experiments.spec.js`, `marketing-workspace.spec.js` and
`marketing-report-decisions.spec.js` passes **8/8, 34.7s**. Desktop/phone report,
form, table and decision-history screenshots were inspected. History initially
omitted the owner's reasoning, displayed a raw status and joined the evaluation
reference to the actor label; regression checks exposed and fixed those issues.
The final history-layout rerun of experiment and paid-approval flows passes
**4/4, 26.8s**, including mobile keyboard scrolling and in-dialog overflow checks.
The invalid-form response is localized. Both history and validation browser cases
were observed failing before their fixes.

Logs are `tmp/marketing-editorial-*`; the current screenshots are in
`tmp/marketing-editorial-experiments-visuals`. All measurements here used isolated
test records and controlled model replies. No real publication, paid action,
login or production deployment was performed. Other specification work remains.

## Chart provenance acceptance checkpoint

A chart-rubric candidate previously passed final review with an ordinary rendered
fact card: file integrity and the general content basis alone did not prove that
the asset contained a source-bound chart. A real-render regression reproduced it.
Final review now requires chart metadata whose exact selected source/field,
series, units and scale match the current original. Multiple different chart
series cannot satisfy one chart material. Rendering and review share the same
bounded, finite, ordered, non-future series validator. The existing chart Story
renderer is accepted on Instagram while the independent Telegram format gate
continues to reject Stories.

The real image/Story test now checks final review as well as exported data and
rendered scale; the Story fixture uses the appropriate destination. The generic
card regression also proves that a manual candidate can be repaired by rendering
its selected series and then reaches owner approval. Initial regressions failed
two cases with the image positive case passing. The browser case failed before
the final check and then passed the rejection/repair/download/review flow.
Targeted media/rubric checks pass **42/42**. The full suite passes **5,573 tests,
2 skipped, 252.15s**, with local PostgreSQL enabled; zero QA schemas remained and
PostgreSQL was stopped. Both existing real image/chart browser cases in
`marketing-workspace.spec.js` pass **2/2, 17.2s** against the current build.
Screenshots were inspected and retained in `tmp/marketing-chart-provenance-visuals`;
logs are `tmp/marketing-chart-provenance-*`. No frontend application code changed
in this checkpoint; its preceding 362-unit-test/lint evidence remains applicable.
Automatic chart selection was a separate follow-up to this proof check; its
acceptance is recorded below.

## Chart preparation and recurring selection

Chart briefs now pin a selected original and series field, validated before a
task is saved. Every language variant must retain that original, and the media
worker receives the pinned reference. Recurring chart rules name the exact field
in incoming originals. Selection requires consistent series/units and a valid
UZStock destination from the selected source; reprints do not create another
release. Conflicts, missing units, future or unordered observations leave the
event unassigned. The owner UI exposes both a selected-original series picker and
the recurring rule field, preserves edits and revocation, and excludes text-only
chart tasks. Chart carousels now contain a cover and plot; only the plot is marked
as carrying chart data. The rendering contract is version 9.

Test-first evidence includes rejected chart schemas/scopes, a failing pinned-link
assertion, a real-render carousel failure, and both browser forms failing before
their UI implementation. A process-local negative control bypassing the pinned
source check makes the copywriter-omission regression fail as intended. Targeted
backend checks pass 91 cases (one PostgreSQL case skipped in that targeted run).
Frontend unit tests pass 362/362, build passes, and lint retains the pre-existing
chart rounding warning. All four desktop/phone cases in
`e2e/ai-marketing-chart-production.spec.js` pass, including two language variants,
real images/data previews, saved rule editing and disabling, no duplicate
candidate and no external delivery. Screenshots were inspected and retained in
`tmp/marketing-chart-production-visuals`; logs use `tmp/marketing-chart-production-*`.
The full PostgreSQL-enabled suite passed **5,586 tests, 2 skipped** in 251.21
seconds; no QA schemas remained and PostgreSQL was stopped. Seven adjacent
cases passed in 30.2 seconds across `marketing-workspace.spec.js` (language
selection and image/chart rendering), `marketing-digest.spec.js` (scheduled
editions), and `marketing-quarterly.spec.js` (automatic quarterly rules).

## Live workspace refresh and preserved edits

Live workspace refresh and version-preserving editors are implemented.
Six targeted cases in `e2e/ai-marketing-live-state.spec.js` pass after reproducing
stale task dialogs, erased goal edits, an inaccessible settings-conflict notice,
and an explicit status read incorrectly resetting source edits. A 15-second
visible-tab poll and foreground refresh keep workspace runtime data current;
polls do not overlap, and stale responses cannot override newer owner requests.
Failed reads retain the last workspace and display its successful timestamp with
a retry action. Goal/account/site/calculation editors preserve their original
write version while edited. Plan-step dialogs also retain their selected version.
All **100 marketing browser cases passed in 7.0 minutes** across
`marketing-workspace`, `marketing-report-decisions`, `marketing-quarterly`,
`marketing-planning`, `marketing-live-state`, `marketing-editorial-experiments`,
`marketing-draft-release`, `marketing-digest`, `marketing-chart-production`, and
`marketing-automation` specs. Build and all 362 frontend unit tests pass; lint
retains the existing chart warning. No backend code changed after the preceding
full 5,586-test PostgreSQL run. Error, conflict and role-dialog screenshots were
inspected and retained in `tmp/marketing-live-state-visuals`; red and green logs
are in `tmp/marketing-live-state-*`. Provider/model responses in these browser
flows are controlled fixtures, not evidence of live account access.

## Owner review of the backup gap

The recovery lock now has an owner workflow. It binds the decision to the exact
restored account scopes and current workspace versions, requires both pauses and
an attestation that the old worker has stopped, and records evidence for every
original recipient. Found publications must lie inside the reviewed gap and
reserve their event/account/type keys. Completion quarantines old unconfirmed
candidates and deliveries; a normal unpause cannot replay them. It retains the
pauses, invalidated connections and immutable history. A fresh independently
checked event can run after reconnection and an explicit unpause. Owner-entered
gap records do not claim provider confirmation or automatic inventory completeness.

The backend regressions first failed with the recovery module absent; the HTTP
test failed on the absent endpoint, and both browser cases failed without the
review action. Targeted contract checks passed 67 cases. The final full suite
passed **5,603 tests, 2 skipped, 251.13s**, including SQLite and PostgreSQL recovery
completion. No QA schemas remained; PostgreSQL was stopped. All **4 browser
cases passed in 14.1s** across `e2e/ai-marketing-recovery-review.spec.js` and the
existing recovery-lock cases in `e2e/ai-marketing-workspace.spec.js`, following a
fresh frontend build. All **362 frontend unit tests** pass; lint has the existing
chart rounding warning. Phone/desktop review and quarantine screens were
inspected and retained in `tmp/marketing-recovery-review-visuals`. Logs use
`tmp/marketing-recovery-review-*`. No live account or database was changed.

## Weekly calendar editions

Owner rules now expose a weekly day and Tashkent time. Sunday covers the coming
week; other days cover remaining future events in the current Monday–Sunday.
Selection accepts current older announcements, excludes past/out-of-week or
conflicting schedules, groups reprints, and binds up to eight events/thirty
originals to one stable rule/week identity. The first event or expiring original
limits the edition's validity. A changed date invalidates the prior candidate
without creating a new release identity. Every selected event must appear.
Source-bound text is assembled and ordered before editorial review, with each
paragraph checked against its own originals. Owner edits preserve these bindings.
New manual calendar forms request the Monday date and individual items; existing
single-event rules continue until explicitly switched to weekly selection.

Initial backend cases failed on missing weekly-rule fields; both browser cases
failed on the absent day control. Targeted calendar/digest/production/rubric
checks passed **107 cases, 1 skipped**. The full PostgreSQL-enabled suite passed
**5,617 tests, 2 skipped, 260.36s**; no QA schemas remained and PostgreSQL was
stopped. All **362 frontend unit tests** pass, build passes, and lint retains the
existing chart warning. Following a spacing correction and rebuild, all **6
browser cases passed in 21.3s** in `e2e/ai-marketing-calendar.spec.js` and
`e2e/ai-marketing-digest.spec.js`. The 14 calendar backend cases were rerun after
correcting a test announcement's sample wording and passed. Screens were inspected
at 390px/light and 1440px/dark; evidence is in `tmp/marketing-calendar-visuals`
and `tmp/marketing-calendar-*`. Providers/models are controlled fixtures.

## Holiday and game-release treatment (acceptance case 18)

An optional owner-selected occasion now pins its kind and the exact version of
a verified dated original. The production brief, all roles, both language drafts,
candidate and media provenance retain it. The worker checks the original before
and after model work; an amendment blocks acceptance while preserving earlier
handoffs. Forms expose the choice and source version, disable incomplete input,
and preserve it through owner editing and reload. Holiday and gaming prompts
specify different tone, leads and presentation, without inventing market data.

Bounded RU/UZ/EN wording checks reject unsupported exchange schedules, popularity
and market effects, including a disclaimer followed by a positive assertion.
An exact selected source statement can support such wording; editing beyond that
statement needs a new check. These checks supplement the quality role and do not
claim to prove arbitrary semantics or causal research. A real model pilot remains
necessary after login.

All 18 new backend cases first failed without the occasion contract. A separate
process that disabled the new risk checks made all ten relevant rejection cases
fail, confirming that they exercise the guard. Targeted production/media/link/
execution checks pass **106 cases**. The full PostgreSQL-enabled suite passed
**5,635 tests, 2 skipped, 258.33s**. Zero QA schemas remained; PostgreSQL was
stopped. Both new browser cases failed before the controls existed; the next
run found compound validation messages remaining in English. Two unit regressions
reproduced that delimiter bug before a general formatter fix. All **364 frontend
unit tests** now pass; build and lint pass with the existing chart warning.
All **8 browser cases passed in 28.2s** in `e2e/ai-marketing-occasions.spec.js`,
`e2e/ai-marketing-calendar.spec.js` and `e2e/ai-marketing-chart-production.spec.js`.
Real JPEG previews, phone/desktop forms and rejection states were inspected;
screenshots are in `tmp/marketing-occasions-visuals`, logs in
`tmp/marketing-occasions-*`. Model/provider replies are controlled test fixtures.

## Specification section 11: acceptance map

This map separates local application evidence from live-model/provider acceptance.
All listed Python modules are included in the latest full suite. Browser logs
and screenshots are recorded at the feature checkpoints above. Controlled
provider receipts establish state handling, not a real external publication.

| Case | Observable local evidence | External boundary |
| --- | --- | --- |
| 1: unsupported goal/budget assumptions | `test_marketing_strategy.py`: pre-approval dialogue, missing baseline, formula-only scenarios and immutable goal | Quality of actual model questions after login |
| 2: full strategy and below-plan review | Strategy contracts, approved plan steps and `test_marketing_report_decisions.py`; planning/report-decision browser specs | Real measured inputs and model review |
| 3: visible handoffs and internal revision | `test_marketing_agents.py`, `test_marketing_execution.py`; planning and live-state browser flows | Live role latency/quality |
| 4: missing comparable quarter original, terminal skip | `test_marketing_core.py`, `test_marketing_quarter_text.py`, quarterly browser spec; no delivery and no reopening | Real filing inventory |
| 5: duplicate sources and unsupported central facts | Source/trend/automation tests, independent checks, per-item digest/calendar checks | Provider/source availability |
| 6: four accounts and languages, confirmed founder | Production/founder tests and workspace language-selection browser flow | Actual copy quality and personal-profile pilot |
| 7: only explicitly authorized Telegram release | Core/channel/delivery tests; current permissions rechecked before provider write | Owner bot/channel login and authorized pilot |
| 8: paid approval, changes and no implicit spend | `test_marketing_experiments.py`: exact creative/parameter approval, reservations, revocation and unavailable execution | Paid execution is a separate integration, excluded from autonomous initial launch by §10.9 |
| 9: lost response versus definite temporary failure | Delivery/reconciliation/provider tests: unknown without blind resend, bounded explicit-rejection retry | Reliable live provider proof |
| 10: 600,000 / 30 / 3, duplicates, no payments, unavailable source | Analytics/business-metric/acquisition tests distinguish observed spend, first payments, maturity and missing data | Real expense/payment sources |
| 11: internal visit, registration cohort and later payment | Acquisition/website/metric-coverage tests; separate event/arrival cuts and identity completeness | Production identity coverage |
| 12: two immutable weeks, reload and late correction | Reports/snapshot tests and workspace report browser flows preserve old cuts and warn on incompatible definitions | Real source completeness |
| 13: no monetization, separate entities after launch | Business-metric/report tests distinguish targets, actual receipts, entities, refunds and source gaps | Owner's payment launch and accounting inputs |
| 14: unavailable platform, partial success and revocation | Delivery/channel/Meta/LinkedIn tests preserve independent statuses and stop revoked writes | Live access/expiry pilots |
| 15: responsive report and skip explanation/history | Workspace, report-decisions, live-state and draft-release browser cases at phone/desktop sizes | Live data remain explicitly unavailable until connected |
| 16: filing alone versus published analysis | Source-adapter/quarterly tests plus quarterly browser spec bind exact report version, original periods and destination | Real published analysis/source feed |
| 17: available reference versus unavailable example | `test_marketing_references.py` binds observed excerpt, source/version/rights and original-format fallback; workspace research UI | Actual reference research/model quality |
| 18: holiday/game event without invented market facts | `test_marketing_occasions.py`, negative-control guard test and occasion browser spec with real rendered JPEGs | Real model wording still needs the login pilot; vocabulary is bounded |
| 19: interrupted model/render and restart | Agent/media/worker tests preserve confirmed steps, original inputs and real-file proof; archive recovery/review tests cover old-queue replay | Host-specific stop/start and failover rehearsal before release |
| 20: external instruction changes recipient/authority | Agent/core/API tests reject untrusted authority fields; model calls expose no sending or secret-access tools | Apply the same permission configuration in the deployed environment |

## Current handoff and later acceptance

The local implementation covers the initial launch contract through the owner's
login boundary. The twenty specification scenarios are mapped above. The final
combined test run below is the closing check; historical “unfinished” notes in
dated checkpoints describe those earlier checkpoints, not new release requirements.

Before a live pilot:

1. The operator configures the intended persistent environment, model endpoint,
   provider app credentials/callbacks, media origin and protected backup schedule.
   The owner performs model/account login and exact recipient verification.
2. Start in draft mode with publication paused. Run a real grounded brief and
   inspect every required role, source, language, destination and actual media.
   Record measured latency and substantive owner corrections instead of claiming
   pilot quality from fixtures.
3. Separately authorize one channel/format pilot, inspect the provider result and
   record its independent confirmation in the provider matrix. Expand permissions
   only through owner decisions. Login itself cannot authorize release or spend.
4. Configure real analytical datasets and prove their intended period coverage.
   Missing identity, raw-filing observations, unsupported search/chart surfaces,
   platform clicks or payments stay unavailable until supplied by a reviewed
   source. The current report shows its cut, event dates and amendment arrival
   dates separately; an event timestamp is not claimed as collection freshness.
5. Follow the existing CI digest release process after inspecting the actual host.
   Record production backup/restore, health/smoke and rollback evidence. No local
   test proves the current production deployment or a live social publication.

Further adapters, broader semantic checks, delegated staff access, selective
history erasure, per-metric ingestion-freshness displays and paid execution are
extensions with explicit requirements. They must not be presented as available
or be inferred from a configured account. The implemented bounded checks, source
gaps and unknown delivery outcomes remain visible in the current product.

## Provider format acceptance — 2026-11-27

Account settings, new materials, team briefs and editorial rules share the
server's provider format catalog. Instagram permits image/carousel/video/Story;
Telegram, Facebook and personal LinkedIn permit text/image/carousel/video.
Text digest/calendar and non-text chart constraints intersect those capabilities
with the owner's account permissions. Legacy unsupported permissions disappear
only when the owner saves the rules; histories remain intact. Login, recipient
verification and release permission remain separate.

The extended API contract first failed for the missing catalog field. Both
390px/1440px browser regressions first failed because unsupported Stories remained
enabled. After implementation, 168 targeted backend cases and both browser cases
passed. The browser checks save all four account rules, verify draft/unconnected
state, check material/team choices and assert no task or delivery side effect.
Actual phone/light and desktop/dark settings screenshots were inspected in
`tmp/marketing-formats-visuals`; red/green logs are in `tmp/marketing-formats-*`.

## Final combined verification — 2026-11-27

**PASS WITH LIMITATIONS: local implementation through the owner login boundary.**

- Full Python suite with real PostgreSQL enabled: **5,635 passed, 2 skipped**
  in 376.27 seconds. The two warnings are upstream feedparser deprecations.
  No QA schemas remain; the temporary PostgreSQL service was stopped.
- All **108 marketing browser cases across 14 specs passed** in 8.1 minutes
  against the current built frontend. Provider/model responses are controlled;
  API handlers, persisted records and generated media are real local code.
- All **364 frontend unit tests passed**; `npm run build` passed. Lint has
  zero errors and one existing `AdvancedChart.jsx` rounding warning.
- Actual phone/light and desktop/dark views were inspected, including the final
  format controls, overview, strategy and report. Screenshots are preserved in
  `tmp/marketing-final-visuals`; feature-specific screenshots remain at their
  recorded checkpoint paths. All five handoff documents' local file links resolve.
- No live model login, social publication, advertising purchase or production
  deployment was performed. Live proof, production image build/smoke and host
  rollback acceptance remain the explicit later steps above.

Feature specs in the final browser run:

| Spec | Result |
| --- | --- |
| [`marketing-automation.spec.js`](../e2e/ai-marketing-automation.spec.js) | 2 passed |
| [`marketing-calendar.spec.js`](../e2e/ai-marketing-calendar.spec.js) | 2 passed |
| [`marketing-chart-production.spec.js`](../e2e/ai-marketing-chart-production.spec.js) | 4 passed |
| [`marketing-digest.spec.js`](../e2e/ai-marketing-digest.spec.js) | 4 passed |
| [`marketing-draft-release.spec.js`](../e2e/ai-marketing-draft-release.spec.js) | 2 passed |
| [`marketing-editorial-experiments.spec.js`](../e2e/ai-marketing-editorial-experiments.spec.js) | 2 passed |
| [`marketing-formats.spec.js`](../e2e/ai-marketing-formats.spec.js) | 2 passed |
| [`marketing-live-state.spec.js`](../e2e/ai-marketing-live-state.spec.js) | 6 passed |
| [`marketing-occasions.spec.js`](../e2e/ai-marketing-occasions.spec.js) | 2 passed |
| [`marketing-planning.spec.js`](../e2e/ai-marketing-planning.spec.js) | 4 passed |
| [`marketing-quarterly.spec.js`](../e2e/ai-marketing-quarterly.spec.js) | 4 passed |
| [`marketing-recovery-review.spec.js`](../e2e/ai-marketing-recovery-review.spec.js) | 2 passed |
| [`marketing-report-decisions.spec.js`](../e2e/ai-marketing-report-decisions.spec.js) | 4 passed |
| [`marketing-workspace.spec.js`](../e2e/ai-marketing-workspace.spec.js) | 68 passed |

Commands: `.venv/Scripts/python.exe -m pytest -q` with the isolated PostgreSQL
URLs, UTF-8 and Git Bash PATH described above; `npm run test:unit`, `npm run lint`,
`npm run build`, and `npm run test:e2e --` with all fourteen explicit spec paths.
Logs: `tmp/marketing-final-full.log`, `tmp/marketing-final-browser.log`,
`tmp/marketing-final-unit.log`, `tmp/marketing-final-lint.log`; latest build log:
`tmp/marketing-formats-build.log`. No frontend code changed after that build.
