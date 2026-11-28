# Marketing workspace operations

The workspace is part of the existing UZStock application at
`/admin/ai-marketing`. It requires a human administrator session. Collector
secrets and non-owner administrative roles cannot access its routes.

The production branch also has an existing editorial marketing desk. Its
`/admin/marketing` page and `/api/admin/marketing` routes remain unchanged.
This team workspace uses `/admin/ai-marketing` and `/api/admin/ai-marketing`;
provider OAuth callbacks must use the team workspace path in `.env.example`.
No data migration from the editorial desk is implied.

## Implemented owner actions

- Save a goal draft, separately approve its exact version, and inspect history.
  Editing an approved goal creates a draft; the prior approved version remains
  effective until the new version is approved.
- Send a brief to CMO. The background worker saves each role's result before
  advancing. The discussion uses actual model responses; unavailable model
  calls preserve input and show an error. The visible workspace refreshes every
  15 seconds and on focus; a manual refresh is also available. Open edits retain
  their original version and require explicit conflict resolution.
- Set account-specific organic scopes, languages, rubrics, formats, expiry,
  Tashkent windows and intervals. These permissions do not authenticate an
  account. Changing the recipient invalidates its connection proof.
- Pause processing and publication independently. Pause prevents new work;
  it cannot recall an already-dispatched request. Cancel/retry model tasks
  through their exact versions; completed output stays in history.
- Register a source, review its rights, and authorize monitoring separately.
  The worker reads stored UZStock news, full market sessions and published
  analyses internally; public RSS uses bounded public-only fetching. Sources
  requiring login remain unavailable until a supported authorized adapter is
  configured. An access failure is distinct from a successful empty result.
- Import an original and its extracted facts/units, then explicitly record the
  basis for owner verification. Imports cannot grant themselves trusted
  verification. Headline-only permission strips the full extract and facts;
  excerpt rights cannot enable full document retention. Changing source
  configuration or revoking display/commercial rights blocks old evidence.
- Create an account-specific material with originals and selected claims, run
  checks, approve an exact manual version, and add it to the durable queue.
  Editing an unsent material invalidates approval; after rechecking and
  reapproval it updates the existing unsent delivery. Automatic failed checks
  show a terminal skipped card with its reasons and no reopen action.
  A changed or stale original caught immediately before dispatch also ends an
  automatic candidate; a manual candidate returns for revision and reapproval.
  Cancelling or editing a pending post updates its outbox entry immediately.
- Dividend facts require an explicit source state (`proposed`, `approved`,
  `paid`), security class (`ordinary`, `preferred`) and finite amount in
  `UZS/share`, `USD/share` or `EUR/share`. The text must state the current status,
  class and amount per share in the source currency. A date/window does not
  prove payment. This check also applies to dividend claims in news posts.
  The dividend rubric additionally requires all three selected fact fields.
  The checker uses a conservative RU/UZ/EN vocabulary; ambiguous wording stays
  blocked and cannot be rescued by a model's approval. It does not claim to
  understand arbitrary prose or combine several distinct decisions implicitly.
- Quarterly links come from the actual published analysis and carry its exact
  standard, scope, period, language and version. Do not replace them with a
  generic company link. A changed publication shows an explicit version error;
  the reader can deliberately open the company page to choose current data.
- Open the queue calendar and history. Dates represent the next possible
  attempt, not a claim that a post will be accepted. A platform ID is only
  shown after transport confirmation.
  The material editor and team brief accept **Publish no earlier than** in
  Tashkent time. The value must precede content expiry and survives restarts and
  language selection. Changing it on a manual material invalidates the previous
  check and approval. Account windows, intervals, current evidence and permission
  still apply when the chosen time arrives.
- Give the team one scoped production brief, with selected accounts, evidence,
  languages and primary language per account. Each role sees saved handoffs.
  The copywriter creates distinct platform/language variants; selecting another
  reviewed language replaces the same material and invalidates prior approval.
  Quality reviews exact draft digests, including rendered media when required.
- Create local JPEG cards, carousels, portrait stories, source-backed charts or
  actual silent MP4 slideshows with burned-in text. The worker saves checksums,
  source versions and text alternatives. Editing text or original data invalidates
  the media proof. Missing/corrupt files cannot pass release or be downloaded;
  an explicit render request can repair them from saved inputs.
  Dividend status and class remain visible on each generated frame. A change
  to the rendering contract invalidates older media for release; request a new
  render, recheck and reapprove the material. Historical files remain intact.
- The chart rubric requires an actual rendered chart whose source ID/field,
  exact series, unit and scale match a currently selected original. A plain fact
  card cannot satisfy it even when its file checksum and general text basis are
  valid. Rendering and final review share the same bounded series/date validator;
  mixed chart sources in one material are rejected. Existing image and Story
  rendering remains available subject to the destination's own format support.
- Chart production pins `production.chart` (selected evidence ID and field).
  Task creation validates current verified series and copywriting cannot discard
  that original. Variant rendering receives the same pinned reference. Owner
  forms expose the choice; recurring chart rules select their exact `chart_field`
  from consistent originals and pin that source's reviewed UZStock link. Missing
  or conflicting data create no assignment. Plain posts cannot be chart tasks.
  Chart carousels render a cover plus plot; only the plot carries series/CSV
  metadata. Renderer v9 invalidates prior media proof without deleting files.
- Preview files from authenticated routes, download media and exact chart CSV,
  or export a ZIP containing draft text, evidence/metadata, media and alternatives.
  Failed rendering creates no pretend asset. Retry is explicit and bounded;
  interrupted render work resumes from its saved inputs.
- Maintain the founder fact map in Settings: proof URL, verification note,
  approved sentences in each language, validity date and explicit confirmation.
  Production tasks receive the actual selected map. Personal first-person
  experience must use approved wording; final checks reject missing, expired,
  revoked and untranslated facts. The dispatcher rechecks exact fact versions.
  This syntactic gate supplements the quality role's review of implications
  and third-person statements; it does not claim general semantic verification.

- Before committing the goal, use **Цель и стратегия → Обсуждение с CMO** to
  request three feasibility scenarios. Each scenario records assumptions, actions,
  resources, budget, limits, risks and a checkpoint. Without comparable measured
  inputs, the result contains a formula and measurement plan, not a numeric forecast.
  For a conditional calculation, select up to ten frozen report snapshots in the
  discussion. The server checks the same KPI, units, currency, complete historical
  window and equal duration, and calculates the measured baseline × assumed factor.
  Test snapshots remain visibly test data. Owner-entered baseline text alone is
  not an independently measured forecast basis.
- After approving the goal, request a full strategy and open **Открыть полный
  план**. Review segments, channels/rubrics, dated steps, role responsibilities,
  dependencies and deliverables, every planned expense, KPI sources, three
  alternative scenarios and the CMO's allowed changes before approving inside
  that screen. The scenario budgets are alternatives; the execution-step budgets
  are summed. Neither strategy approval nor budget per target authorizes a paid
  action or establishes actual CAC. Versions retain the original proposal and
  approval. A changed goal or measured basis blocks further approval until a new
  proposal uses recalculated inputs; historical approved records remain visible.
  The plan itself is not evidence that its actions have occurred.
- In the approved plan, choose **Добавить шаги в рабочий цикл**. This records the
  exact approved version once. In **Рабочий цикл**, assign a ready step immediately,
  or use **Подготовить заранее** to save its inputs before its start date or before
  prerequisites finish. The background worker starts the saved assignment once
  those conditions are met, without an open browser. Its start date, accepted prerequisites and current goal/measurement
  basis must permit work. The responsible role hands its saved result to CMO;
  revision requests preserve previous tasks and are limited to three assignments.
  The board distinguishes pending, running, review, revision, blocked and completed
  work, and shows overdue dates independently from completion. Owner-assigned
  steps require a recorded result and supporting reference, visibly attributed
  to the owner rather than treated as an external-system confirmation.
- Prepared work records exact evidence, theme reviews, measurement bases,
  account versions and founder facts. Edit or cancel its automatic start from
  the step card; saved versions remain in history. Changed, unavailable or
  expired inputs block assignment until explicitly prepared again. The worker
  rechecks the same binding before and after model work, orders ready steps by
  deadline and ignores paused plans. Prepared internal operations, research and
  measurements can use CMO revision feedback automatically, within the same
  three-assignment limit. Drafts and paid proposals retain their separate review
  paths. A later manual assignment does not re-enable a cancelled automatic
  binding. Two workers or two briefs for one event cannot create a second post.
- Organic plan work uses a scoped **draft** production brief. Its selected account
  must match the planned platform and rubric. After quality checks, a separate
  CMO task reviews the actual saved candidates. Open the language variants and
  media from the plan step. A language/content change withdraws the current
  artifact basis without rewriting the historical acceptance. Recheck corrected
  content and use **Передать текущие черновики CMO** for a bounded new review;
  it does not create another publication. Failed automatic posts retain their
  terminal rules outside this draft preparation workflow.
- Paid plan work must produce actual saved experiment proposals within the step's
  platform, currency and cumulative budget. A narrative handoff is not a completed
  paid proposal. Campaign approval and execution remain separate owner actions.
  Pause a working plan to stop new role claims/acceptance. Activating a revised
  version of the same strategy replaces its older run while preserving history;
  that replaced run cannot simply be resumed. A goal change or expired goal period
  blocks further work. Previously dispatched external actions are not recalled.
  Selecting sources is still explicit; autonomous source selection, urgent-news
  priority rules and remaining editorial selection packs are still being completed.
- Configure reporting separately from the goal: dataset, currency, attribution
  and conversion windows, activation and active-user definitions, agreed cost
  categories, applicable legal entities and actual launch dates. Changing rules
  creates a new version and does not rewrite saved snapshots.
- In Reports, select explicit Tashkent dates (the end is exclusive), calculate,
  inspect each numerator/denominator and source status, and freeze a named cut.
  Source completeness is a dated confirmation for a category, dataset and period;
  a permanent settings flag cannot turn missing events into measured zero.
  A later source-gap notice withdraws the earlier completeness claim for the
  affected interval. Test data is visibly separated from business outcomes.
- Formula version 4 evaluates completeness separately for each metric. Open
  "Расчёт и источник" to see the required dates in Tashkent time, whether the
  end is inclusive, whether earlier history is needed, and the actual dated
  confirmation or missing window. The source table below the metrics describes
  only the report period; it does not certify longer cohort or attribution windows.
  A complete period can therefore show visits and cash revenue while activation
  or conversion still lacks its follow-up. First-payer counts need earlier
  payment history even when current cash totals do not.
  Confirm the whole required interval and its history where requested; separate
  partial confirmations are not silently joined into one completeness claim.
  A known later refund that changes service-period income extends that metric's
  required payment window to the adjustment. It does not extend unrelated cash
  totals into another period. A cohort rate remains incomplete until both its
  registration period and the actual cohort's follow-up have closed.
  Adding coverage can enable a new calculation without importing any new event.
  Frozen values and coverage remain unchanged; an analyst summary is no longer
  reused when that new evidence changes the metric's basis.
- Import confirmed events with stable IDs and pseudonymous subjects. The server
  records arrival time. Late events appear only in later calculations. A source
  correction uses `corrections` with `event_id`, `dataset`, `replacement`, `reason`
  and `expected_version` (zero for the first amendment). A null replacement
  retracts an erroneous event; it does not delete the original. Conflicting
  transaction copies reject the entire batch. No freehand override of a metric
  bypasses recalculation of its dependent formulas.
- Formula version 3 checks that every refund identifies a confirmed payment
  with the same customer, legal entity and currency, occurs no earlier than the
  payment and does not make cumulative refunds exceed it. A reconciliation
  problem preserves the imported evidence and blocks affected cash or service
  metrics. The report identifies the records to correct; aggregate exports and
  analyst input include the issue summary without transaction or event IDs.
  A legitimate refund of an earlier-period payment can make current cash
  revenue negative. Zero-value receipts do not enter new-payer or ARPPU bases;
  free subscriptions do not enter the paid churn base. Moving from paid service
  to a free plan counts as leaving the paid base.
- The ИП/ООО section shows actual expenses by entity and category, including
  before paid services launch. Unassigned expenses stay in a separate row;
  currencies are never added together. Missing or incomplete expense coverage
  shows unknown totals rather than zero.
- An LTV stability decision applies to one closed calendar month, dataset,
  currency and set of legal entities. Supply the three immediately preceding
  measured months and their sources, the assessed `period`, a timezone-aware
  `reviewed_at` after month end, the matching `opening_customers` and
  `lost_customers`, and the owner's reason. Future-dated decisions are rejected.
  A different month or basis, stale history, zero churn or changed customer
  counts makes the estimate unavailable until reviewed again. Legacy decisions
  lacking this binding remain readable but cannot enable a new LTV estimate.
- Open a saved snapshot, create a separately named recalculation with a reason,
  compare two snapshots or a snapshot with the current calculation, and download
  aggregate JSON or CSV. Incompatible definitions, currencies, source bases or
  differently elapsed weeks suppress differences. Relative change requires a
  nonzero baseline. Exports omit raw event and user identifiers.
- Read team counts from immutable action history, independently from business
  results. Goal/plan versions and owner decisions are retained at the report cut.
  Plan/fact requires the complete goal period and matching units; no monthly
  target is silently divided into weekly targets. Request an analyst/CMO review
  from the computed aggregate report, then refresh to view actual saved outputs.
  The model cannot change the report's calculations, owner target or budget.
- A report cut before the requested period ends retains the observed KPI but
  does not calculate a completed-goal difference. Incomplete or estimated inputs
  cannot become realized plan/fact. Plan/fact is included in the analysis basis,
  so a review for an earlier comparison state is not reused silently.
- Accepted CMO report output requires `cmo_review`: continue/change/stop decisions
  with metric references, concrete next actions, responsible roles, review dates,
  hypothesis references and optional approved strategy-step references. Hypotheses
  retain parent relationships, tests, success metrics/criteria and priority.
  IDs must be unique, references must exist in this report, parent cycles are
  rejected, and checkpoints are bounded to the next 90 Tashkent days.
  Only the CMO in an accepted report task may return this contract. Invalid local
  references produce a specific safe diagnostic; raw provider/schema failures
  still do not expose their responses or credentials.
- The server binds decisions to the exact report cut, dataset, goal/strategy
  versions, plan/fact and selected metric values, completeness, units and sources.
  Models cannot submit a replacement numerical basis. Late events leave the
  original decision intact; a changed calculation basis needs a new analysis.
  The Reports view shows the proposal and test tree and freezes them with a named
  snapshot. These records do not execute a plan edit, spend money, change the goal
  or grant publication rights. Test criteria are proposed hypotheses, and prose
  explanations still require editorial judgment; structured references do not
  independently establish causation.
- Opt in to automatic closed-week snapshots in reporting settings. The worker
  saves the previous completed Tashkent week once per dataset. Restart/retry
  cannot overwrite it. Processing pause also pauses automatic report cuts;
  manual recalculation is separate and preserves the original.

Further product-action coverage, provider setup and remaining editorial rules are being
completed. Refer to
`marketing-implementation.md` for the full remaining scope; this document does
not claim production readiness.

New website registrations now retain separate start and successful-completion
timestamps in the account database. Completion follows the actual path: accepted
email code, successful direct registration when mail verification is disabled,
or authenticated OAuth identity. It is committed with the account transaction,
preserved on later logins and not inferred for legacy accounts. These dates are
used by the native reporting adapter described below. They do not establish
complete historical registration coverage.

### Acquisition evidence and observed counts

Formula version 6 checks acquisition evidence separately from source completeness.
A complete billing export does not prove a customer's acquisition source. ROI,
ROAS, registration cost, CAC and payback remain incomplete when relevant customer
links are missing. The metric details show the applicable customer count and
specific missing evidence. Cash and actual expenses remain available under their
own completeness rules. An unknown numerator or denominator stays unknown.

The last non-direct rule treats an explicitly observed direct visit separately
from an unknown source. A direct return does not replace a known non-direct
source. A later unknown touch cannot reuse an older known channel. Conflicting
touches with exactly equal timestamps are not ordered by their event IDs. The
channel can be known while the particular publication is ambiguous; its report
then shows incomplete attribution. A payment cannot borrow acquisition from a
registration observed after that payment.

Readiness uses the metric's applicable population. Nonpaying registrations can
prevent complete registration-cost attribution without preventing a fully linked
paid-customer CAC. Out-of-period, other-currency and zero-value receipts do not
invalidate current revenue attribution. First receipts without a registration
remain unresolved within their possible cohort conversion window. Complete
evidence of direct/other-channel acquisition, or complete data with no revenue,
can still produce measured ROAS=0 and ROI=-100% with positive spend.

Channel and cohort rows retain their observed counts. `count_basis` records
independent completeness, observation windows and attribution checks for each
kind of count. Channel table headers surface this status; a partial observed
zero is not a complete total. First-payer channel counts use the actual earlier
acquisition window, not only the payment week. Old snapshots without this basis
are explicitly labelled. Coverage-only changes invalidate outdated analyst
context; earlier saved snapshots remain unchanged.

Downloaded ZIPs now use the exact sending-preview text, including tracked links,
original URLs and Instagram profile instructions. `material.json` includes the
publication preview and its route. For media-only Stories, `draft.txt` is empty
because no separate caption is sent; the original material and rendered files
remain in the archive. Released/submitted/uncertain versions retain their pinned
original evidence and dispatch platform, even after source or account changes.

### Metric input provenance

Formula version 7 records source names and the latest event timestamp from each
calculation's selected observations and blocking evidence. Report details show
the categories separately from the actual source names. They do not substitute
the newest upload in a category for the latest relevant observation.

Period visits, completed registrations, activation actions and retention use
their own populations/windows. Money uses the selected currency, entity and
cash/service basis; first-paying-customer counts remain customer counts across
eligible currencies. Acquisition metrics include their applicable registration,
receipt and touch evidence plus the selected costs. Refund reconciliation and
excluded financial records that block a metric are also named. Subscription
metrics retain the latest applicable state, including cancellations; churn uses
the opening base and its closing state. LTV includes the approved stability
review's monthly reference sources. A zero with complete coverage but no input
observations has no invented source or event date.

Platform CTR cites the matching click/impression windows and the latest version
of a cumulative observation. Superseded observations, unrelated publications,
reach-only measurements and unmatched click windows cannot refresh its date.
An object with clicks but no impressions retains its observed click source and
an unavailable ratio. Saved snapshots retain their original formula and sources.

`updated_at` in the metric payload denotes the latest selected **event time**,
as labelled in the UI. It is not an ingestion or last-source-sync timestamp;
source collection attempts, report generation and ledger arrival cuts remain
separate. Source/type-specific readiness and ingestion/amendment freshness
still require the remaining reporting acceptance pass.

### Publication arrival attribution

New materials created in the owner form and by the production workflow use an
opaque `uz_pub` tag by default. The owner can disable it in the material form;
legacy materials and API inputs without `track_visits` retain their old links.
The canonical destination remains unchanged for exact report validation. **Text
for sending** shows the actual tagged URL and its production/test dataset before
approval. The dataset is taken from report settings when the link is issued.
Copy, media, destination or routing changes invalidate approval and issue a new
link. Account identity changes require saving and reviewing the material again.
An Instagram profile route must match the tagged outgoing URL exactly.

The browser captures the landing URL before SPA routing, waits for visibility,
and sends a typed `publication_visit` receipt with an opaque token and a SHA-256
route fingerprint. It sends no raw query, URL or browser-asserted channel.
Report selectors, language paths and fragments remain part of the fingerprint;
only known tracking decorations are excluded. A new arrival in the same session
is retained, including A → B → A. Transport retries keep one event ID.

The server uses its receipt time for this arrival. The native reader attributes
it only when the matching content digest, account, dataset, destination and
confirmed publication are present, and receipt time follows the provider request.
Draft previews, unknown sends, mismatched links and earlier cutoffs cannot claim
publication credit. A later visibility confirmation can admit an earlier valid
receipt on the next full source sweep; frozen snapshots remain unchanged.
Public tokens and link bindings are included in the existing versioned backup.

Formula version 5 shows **Publication arrivals** separately from platform
impressions/clicks and CTR. Arrival counts represent received openings, not unique
readers. Registration credit follows the owner's last non-direct attribution
window, using the registration date for the report period. A later untagged
non-direct source removes credit from an earlier tagged publication. Paid and
organic rows stay separate. Missing coverage labels counts as observations;
coverage-only changes also invalidate stale analyst context. Native traffic
exclusion and dated identity linking apply to these receipts.

### Native website source

In Reports, **События сайта UZStock** connects the existing account and browser
event database. It reads through the application's `DATABASE_URL` and
`DATABASE_SCHEMA`; it does not visit public pages. Configure a stable private
`MARKETING_ANALYTICS_ID_KEY` in the service environment: 32 random bytes encoded
as URL-safe base64. Keep that key in the private secret backup and preserve it
across restarts/restores. It is never accepted by the browser form, exposed in
the workspace, or included in the portable marketing archive.

The owner explicitly selects test or production data, the earliest observation
date and the interval between full sweeps, then enables collection. The dataset
is fixed once the source is bound. Changing the database identity or pseudonym
key blocks collection rather than silently creating new customer identities;
database credential rotation alone does not change those identities.

Each worker step advances through at most 500 source cursor rows. Context queries
aggregate the associated sessions and team scope; all database reads have bounded
connection and query timeouts. Account, browser and product-action cursors survive process restart. The next sweep
revisits the configured range, including late commits below an earlier cursor.
**Прочитать сейчас** reads the next batch, or starts a new sweep after completion.
The processing pause stops this collection too. Disabling collection retains
the imported observations. Errors are redacted and retried after the configured
interval; a disabled or changed source cannot commit an earlier in-flight read.

Current imports cover one visit per browser/session pair, separate dated
registration starts/completions and successful product observations. A server-authenticated session with exactly one
account can link its anonymous visit to that account. Conflicting or withdrawn
identity evidence leaves it unlinked. Changes are dated observations; old report
cuts and frozen snapshots keep their old basis, and explicit owner corrections
have priority. Administrative allowlists, configured roles and the stored access
roster mark team observations internal, including known revoked team accounts.

The reader stores keyed pseudonyms and a fixed channel vocabulary. It does not
copy email, passwords, IP addresses, full referrers, UTM free text or search text
into marketing records. Native source coverage remains **incomplete**: the
browser buffer can lose events and old accounts lack dated registration proof.
Unmeasured activity, payments, platform impressions and publication-specific
clicks are not manufactured. Feature-click beacons do not become successful
report/chart opens.

The public `/api/track/actions` endpoint stores typed receipts directly in
`web_product_events`, independently of the lossy pageview buffer. A response
acknowledges a committed record. Retries keep the same UUID, event time and
payload; conflicting reuse returns an error. Server receipt time is separate
from the browser's observation time. Optional account identity comes only from
verified authentication; expired supplied credentials cannot become an anonymous
receipt. Input size, action vocabulary, object fields, clock skew and request
rate are bounded. No form contents or arbitrary search text are accepted.

Instrumentation currently covers a loaded issuer header, a populated visible
company/advanced price chart, an opened full AI report with exact issuer,
standard, scope, period, language and version, a loaded editorial news article,
and a favourite acknowledged as added. Failed loads, failed favourites and
removals do not produce those success events. Long report versions retain their
exact tuple in the receipt and use a hashed object reference in the marketing
ledger when needed. Browser observation is not proof that a human read or
understood the content; unavailable observation APIs leave the product usable.

News search records only its fixed `news_feed` scope, query category and the
number of matches among the loaded feed. A completed empty feed search is
distinct from a failed feed load. Entered text and hashes of that text are never
sent. A result becomes `search_open` only when its destination loads; failed or
abandoned destinations cannot claim a later direct open. Other search surfaces,
raw filing views and additional chart surfaces still need instrumentation.
The browser makes at most one delayed retry, retaining the same receipt ID;
lost observations keep source coverage incomplete. Confirmed source actions
participate in the same dated identity, correction and immutable-snapshot rules.

## Research references

In **Workflow → Research → New research**, select the research type and enter the
audience/platform question and select source records. A source-free task can
propose an original format. No publishing account is required. The existing
worker runs market analyst → media analyst → CMO; model access must still be
configured by the owner. Its outputs appear in **Role results** and survive
reloads with their task history.

The media analyst returns structured `reference_cards`: `adapt`, `reject`, or
`original`, with the observed excerpt, proposed technique, rationale and next
test. Adaptations must quote an exact passage from a selected, verified,
unexpired original with known rights. The server binds its URL, title, publisher,
version and publication/retrieval dates; the model cannot supply these fields.
Changed originals or revoked registry permission invalidate acceptance. Other
roles cannot supply reference cards. An accepted research step must include a
card or a concrete original-format proposal.

The current analysis capability is the supplied text excerpt. The cards label
this explicitly; they do not claim to watch the linked video, inspect frames or
transcribe speech. Unavailable examples can be rejected without invented
observations, while an original-format card continues to the CMO with no claimed
source. The proposed technique and test remain interpretations, not measured
evidence of another publication's performance. Source rights are displayed;
link-and-excerpt permission does not authorize copying artwork. Reference cards
can also participate in the media role's existing content-production handoff.

For **Competitors and inspiration**, the market analyst hands a structured
comparison to the CMO. Each card distinguishes direct, adjacent and inspiration
relationships. It includes purpose, audience, features, visible price,
communication, revenue, conversion and audience size; missing fields explicitly
remain undisclosed in the selected materials. A visible observation is an exact
excerpt, with a server-bound original link, version and publication/retrieval
date. Observed facts must belong to the named product: populate the original's
`entity` field with its product name when importing a comparison source. A quote
about another product cannot be transferred to this card. Historical pricing is
labelled as a dated observation, never automatically presented as today's price.
The proposed difference for UZStock is a separate hypothesis.

Measured trend histories and any additional media extraction capabilities
remain separate implementation work. Source monitoring
uses its existing explicit registry permissions; this workflow does not fetch
arbitrary links or change the pause on automatic public-site visits.

## Execution and storage

The server starts `marketing.worker.run_loop` with the application lifecycle
when `MARKETING_WORKER=1` (default). It can instead run as
`python -m marketing.worker` with the application's existing environment. Set
`MARKETING_WORKER=0` in the web process when running the dedicated worker.
No browser timer executes background jobs or publishes content.

State uses the existing `dbx` driver: SQLite in `MARKETING_DB` (default
`data/marketing.sqlite3`) or PostgreSQL when the established database backend
selects it. Records are scoped by `MARKETING_ENVIRONMENT`, falling back to
`ADMIN_ENVIRONMENT` and then `local`. Revisions are append-only. Production
must use its persistent data volume/schema. Model/transport work is performed
outside short database transactions; a durable claim precedes it.

Media is stored under `MARKETING_MEDIA_DIR`, or by default beside the marketing
database in `marketing-media`, with an environment-specific subdirectory. Include
this directory with database backups. Runtime needs Pillow, FFmpeg and a Cyrillic/
Uzbek font. The production image installs FFmpeg and retains the application's
Manrope font when frontend sources are removed. Local MP4 rendering and ffprobe
inspection were exercised; a container build is not available on this workstation.

Restart recovery retains confirmed role steps. An interrupted social dispatch
becomes `unknown` and is not blindly retried. An automatic candidate that
failed its final fact check is permanently `skipped`, including on a repeated
event trigger. Explicit platform rejections allow at most three attempts with
the requested delay and the account interval; uncertain acceptance does not.

The current worker collects authorized sources, schedules ready candidates,
renders files, runs model jobs and saves opted-in closed-week reports. Quality
waits until the required media jobs complete. Telegram transport is wired to the
worker; it cannot send without dedicated credentials, a current successful probe
and publication permission. Personal LinkedIn has owner OAuth, text/media posting
and owner visibility review. Meta has owner OAuth and explicit Page/Instagram
selection. Facebook text/photo posts and Reels and Instagram images, carousels,
Reels and image Stories have durable transport and independent visibility checks.
Unknown outcomes stay blocked when there is no reliable publication proof. Analysis
links preserve the exact published standard, scope, period, language and version.

## Telegram setup and delivery

Create a dedicated bot through [BotFather](https://t.me/BotFather) and give it
administrator posting rights in the intended channel. Save its token privately
as `MARKETING_TELEGRAM_BOT_TOKEN` in the service environment, then restart the
service with the updated environment. The workspace never reuses `TELEGRAM_TOKEN`
from another bot. Tokens are not entered into the owner form or stored in its
records/history. In Settings, save the immutable numeric channel ID (`-100…`)
and click **Check connection**. The probe checks bot identity, channel identity
and actual posting rights through the [Telegram Bot API](https://core.telegram.org/bots/api).
Changing the token or recipient invalidates readiness and requires a new probe.

The adapter sends text, images, MP4 video and 2–10-item albums. Channel stories
are unavailable. **Text for sending** shows the exact outgoing copy, including
the direct UZStock link and original source links; final checks include their
length. Media captions have a smaller platform limit than ordinary posts. A
single-card carousel now receives a separate cover; older renderer proofs need
regeneration before release. Media bytes are checked before upload.

Immediately before the write, the adapter rechecks posting rights and the current
local permission, evidence, pause, credential and content version. Confirmed
receipts must identify the intended channel and every album item. Explicit rate
limits retain the provider's full requested delay, even beyond one day; an
unrepresentable delay stops automatic retries. Expired evidence still blocks a
later attempt. Timeouts, malformed success responses and wrong-channel receipts
remain unknown and are never automatically replayed. Paid broadcasting is never
enabled. Manual entry of a post URL cannot manufacture platform confirmation.

For an unknown Telegram send, open **Content and queue → Publication
reconciliation**. **Get Telegram confirmations** reads a bounded batch of updates
from the dedicated bot. If the original is visible in the channel and forwarding
is permitted, forward it intact to that bot, retaining its origin and every album
item, then read again. Telegram supplies the original channel, message ID and date
for a channel forward. A normal private message or copied text is not proof.
No message is sent, edited or forwarded by this read. An active webhook is left
untouched and blocks polling; do not share the dedicated bot with another poller
or environment. A full batch exposes a prompt to read the next batch.

The system compares the original recipient, send-time interval, exact outgoing
text, media type and complete album membership. The outgoing payload is saved
immediately before the provider write, after final checks. Old jobs can use their
immutable evidence versions when available. Current source changes cannot rewrite
this historical comparison. Duplicate matches, missing album items, a changed
observation, a post already bound elsewhere or two indistinguishable pending
materials remain unresolved.

**Review match** opens the actual platform links and observed text. Review the
original text and every media item, select the confirmation checkbox, then
**Confirm match**. Caption/count matching does not claim visual or video semantic
equivalence; this step explicitly requires owner review. The server revalidates
the exact match version before storing the platform IDs, owner decision and
published state. A late transport timeout cannot overwrite that decision. A
reconciled clarification advances the same publication/incident history as a
normal confirmed response. No retry is sent.

Telegram retains pending bot updates for at most 24 hours. An empty response,
missing original or unforwardable post cannot prove non-publication; the outcome
stays unknown. The consumer acknowledges only the last durably saved batch.
Unrelated private message/sender data is not retained. A restored workspace's
separate recovery lock remains: matching known unknown sends does not prove that
the entire gap since an older backup has been reconciled.

## Personal LinkedIn setup and owner login

Use a [LinkedIn developer app](https://www.linkedin.com/developers/apps) with
**Sign in with LinkedIn using OpenID Connect** and **Share on LinkedIn** enabled.
The consent request uses `openid profile w_member_social`; it does not request
email, organization posting, advertising or restricted member-read access.
Register `https://uzstock.uz/admin/ai-marketing` as the exact HTTPS redirect URI.
The [OAuth flow](https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow)
and [profile endpoint](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2)
are called only against LinkedIn's fixed hosts, without redirects or retries.

Keep these values in the private service environment:

- `MARKETING_LINKEDIN_CLIENT_ID` and `MARKETING_LINKEDIN_CLIENT_SECRET` from the app.
- `MARKETING_LINKEDIN_REDIRECT_URI=https://uzstock.uz/admin/ai-marketing`.
- `MARKETING_CREDENTIAL_KEY`: a Fernet key, generated once with
  `cryptography.fernet.Fernet.generate_key()` and saved directly to the private
  environment or secret manager. Never put it in tracked files, history or chat.

Restart the service with that environment, then open **Settings → Personal
LinkedIn**. Save draft-only rules, check the separate personal-profile permission,
and leave the target ID blank for a first connection. **Sign in through LinkedIn**
opens LinkedIn's own login. The owner completes that login. The return binds the
actual `urn:li:person:…` from the server's profile read; an already specified,
different person is rejected. Inspect the displayed name and ID before enabling
publication. Login leaves the saved release mode and scope unchanged. A company
page cannot substitute for the personal profile.

The login intent expires after ten minutes and is single-use, owner-bound and
bound to an HttpOnly, Secure, SameSite=Lax browser cookie. Account or app changes
during login invalidate it. The return still requires the owner's administrator
session; the browser removes the authorization code and state from its URL.
Do not record OAuth query strings or request bodies in diagnostics.

Tokens are encrypted in a separate current-credential table, bound to environment,
provider and account. The portable marketing archive excludes both credentials
and pending login intents. Restore also rejects a destination with existing
credentials or pending intents, even if ordinary records are empty.
Keep the encryption key in separately protected
operator storage; key loss or deliberate rotation requires another owner login.
Access expiry is shown in Settings; programmatic refresh is not assumed.
**Check profile** reads LinkedIn; **Disconnect LinkedIn** deletes the local token
and invalidates its proof. It does not revoke the app at LinkedIn; the owner can
do that in LinkedIn's settings.

The worker supports personal **text posts, images, multi-image carousels and MP4 videos** with source links, a
conservative 3,000 UTF-16-unit limit, and escaped plain-text punctuation. It uses
the [Posts API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-06)
with version `202606`, deliberately pinned and supported until 2027-06-15.
Recheck the [migration schedule](https://learn.microsoft.com/en-us/linkedin/marketing/integrations/migrations)
before that date. Founder facts, exact approval where required, current evidence,
permission, pauses and recipient identity are rechecked before the post request.
HTTP 201 with a valid created share/UGC ID means **submitted**, not confirmed
visible: LinkedIn can continue processing or fail publication afterward. In
**Content and queue → LinkedIn publication visibility**, open the known post,
compare the frozen outgoing text and all media, then confirm visibility. This
records the owner's observation, identity and time; it does not pretend to be
an API visibility check or invent a publication timestamp. The submitted version
cannot be edited or resent. A missing receipt or timeout stays unknown and is
not replayed. Personal post reads require restricted `r_member_social` access;
automatic reconciliation of unknown LinkedIn posts remains unfinished.
An explicit HTTP 429 preserves the full numeric or HTTP-date
`Retry-After`; without one it waits for the next midnight UTC
[daily limit reset](https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/rate-limits).

The media upload path uses the versioned
[Images API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/images-api?view=li-lms-2026-06),
[MultiImage API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/multiimage-post-api?view=li-lms-2026-06)
and [Videos API](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/videos-api?view=li-lms-2026-06).
It verifies the reviewed file version/hash and actual local bytes before upload.
Carousels contain 2–20 ordered images. Local MP4 output is at least 75 KB,
with duration and decoding verified by the renderer's tests. Renderer v8 retains
a standard MP4 free-space box when a short slideshow compresses below that
provider minimum and uses a two-second closed GOP at 25 fps. Previous rendering
contracts require rendering and checking the material again. Upload URLs must match the returned media ID on the documented
LinkedIn upload host; redirects are rejected. Image uploads authenticate with
the bearer token; video byte-range uploads do not send it.

Confirmed upload parts and finalization are durable checkpoints. Upload tickets,
tokens and part receipts are encrypted and excluded from portable archives;
the owner sees only progress and remote media IDs in the upload history. A
recovered worker resumes confirmed parts, and an older worker cannot continue
after its claim is replaced. Video processing polls use scheduled 60–600 second
delays, consume no publication attempt and remain subject to content expiry.
Processing failure is recorded separately and creates no post. A lost finalize
response is checked against the same video's owner and status. Recovery after
the public post request starts remains unknown and never triggers a blind retry.
The image endpoint does not allow the current write-only member scope to read
processing status; the application does not claim such verification.

## Meta owner login and account selection

The Facebook and Instagram connection flows use
[Facebook Login for Business](https://developers.facebook.com/documentation/facebook-login/facebook-login-for-business).
Create separate **User access token** configurations for Facebook and Instagram;
the application deliberately rejects system-user grants in this flow. For an
owned/managed asset pilot, the owner needs the appropriate app role and Page
access. Serving other businesses requires Meta's applicable review/access
approval. Instagram must be a professional account linked to a Facebook Page.

Configure the following private server values, then restart with that environment:

```text
MARKETING_META_APP_ID
MARKETING_META_APP_SECRET
MARKETING_META_REDIRECT_URI=https://uzstock.uz/admin/ai-marketing
MARKETING_META_FACEBOOK_CONFIG_ID
MARKETING_META_INSTAGRAM_CONFIG_ID
MARKETING_CREDENTIAL_KEY
```

Use the existing credential encryption key. Register the exact redirect URI in
Meta's login settings. The Facebook configuration needs `pages_show_list`,
`pages_read_engagement`, `pages_manage_posts`; the Instagram configuration needs
`pages_show_list`, `pages_read_engagement`, `instagram_basic`,
`instagram_content_publish`. These configure organic connection and publishing
rights; paid execution remains a separate unfinished integration. The login URL
uses `config_id` and the authorization-code response, never a browser token.
Meta may require additional permissions when the Page role was assigned through
Business Manager; follow its
[Instagram publishing permission table](https://developers.facebook.com/documentation/instagram-platform/content-publishing)
for that account. A platform permission still cannot approve a paid action in UZStock.

In **Settings**, save draft rules for the desired platform; an empty target ID
allows selection after login. Click **Sign in through Meta**, complete Meta's
login yourself, and select the exact returned Page or linked Instagram account.
Even one returned account requires explicit selection. A preconfigured target
cannot silently switch to another account. The server rechecks the current Page
task, linked profile and Page token before saving. The selected ID, name, parent
Page and effective access expiry are shown; release mode/rubrics/windows remain
unchanged. **Check Meta account** repeats the server checks. **Disconnect Meta**
deletes local grants and pending choices; revoke the application separately in
Meta's business-integration settings when desired.

Code exchange, long-lived token exchange, token inspection and Page enumeration
use fixed Graph API hosts with no redirects/retries and bounded responses.
The [token inspection](https://developers.facebook.com/docs/graph-api/reference/debug_token/)
checks app, user, token type, granted scopes, Page identity and both access
deadlines. The effective expiry is the earliest current user/data/Page deadline;
an apparently non-expiring Page token does not bypass its parent user's expiry.
Graph API `v25.0` is deliberately pinned; its documented retirement is 2028-07-29
([version schedule](https://developers.facebook.com/docs/graph-api/changelog/versions/)).

Login intents are single-use, owner/browser/account/configuration-bound and
expire after ten minutes. The encrypted choice is tied to the newest login and
survives a page reload for the remainder of that period. Late network responses
cannot install an expired intent or grant. No access token, app secret or other
Page token appears in the workspace or immutable history. Current grants and
pending choices remain outside portable backups.

The connection UI and server checks are implemented and tested with controlled
HTTP peers. **Facebook text, single-photo and multi-photo publishing is implemented**.
The worker uploads checked PNG/JPEG bytes with descriptions through the
[Page Photos API](https://developers.facebook.com/docs/graph-api/reference/page/photos/)
using `published=false`, then attaches their ordered IDs to one
[Page Feed post](https://developers.facebook.com/docs/graph-api/reference/page/feed/).
Completed uploads are saved privately and reused for up to 23 hours. Preparation
checks all local files before writing and rechecks rights and content before
the public request. The application limits a multi-photo post to 2–10 files.

A valid Page post ID means **accepted**. A separate worker read must verify the
Page, exact text, complete ordered photos, published/not-hidden state and actual
creation time before the application marks it **published**. This read can run
while publications are paused. The content card shows the pending check and its
next scheduled time; mismatched, hidden or unavailable posts remain accepted
without resending. An uncertain response to the public write remains **unknown**;
unknown-post reconciliation is still pending. Explicit rate rejections preserve
the full provider retry delay, including business-use-case recovery minutes.
No raw provider error, token or private upload state is exposed in history.

For **Facebook video**, enable the video format in the Page's account rules.
The control explains that these are **public Reels with an AI disclosure**.
There is no private Page-Reel audience, collaboration or crossposting in this
workflow. The candidate card repeats the disclosure before approval or release.
The worker checks the actual MP4 (9:16, H.264, progressive yuv420p, fixed 24–60 fps,
3–90 seconds; the local renderer uses 1080×1920 at 25 fps with closed two-second
GOPs). Silent videos are supported; included audio must be stereo AAC-LC at
48 kHz and at least 128 kbps. Files remain within the local 30 MB asset limit.

The [Reels upload flow](https://developers.facebook.com/documentation/video-api/guides/reels-publishing)
saves its video ID and upload ticket privately. A disconnected upload resumes
from Meta's confirmed byte offset. Processing waits use scheduled checks without
consuming publication attempts. Expired unpublished uploads can be replaced with
a new session, with a maximum of three sessions. The final public request always
uses the approved caption and AI disclosure. An accepted request remains pending
until both the video's publication status and its exact membership/caption on the
selected Page are verified. Even a lost final response or worker crash can be
resolved using the saved video ID; the public request is not replayed. The UI
shows this read-back state and its next check time in Tashkent. The rolling
30-Reel allowance counts all local aliases for the same Page and conservatively
reserves unconfirmed public writes. It does not claim visibility into other
applications' API usage; Meta can still explicitly reject a rate-limited request.

**Facebook Stories remain pending**. No real
Facebook/Instagram login or publication has been tested.

### Instagram images and photo carousels

The worker now supports one image or an ordered carousel of 2–10 images. The
owner reviews the actual JPEG before approval. Renderer v8 produces RGB JPEGs
with a packaged sRGB profile; a fixed profile avoids timestamp-dependent hashes
when repairing a missing file. Video source frames remain PNG. A renderer
contract change requires a new render and check before release.

Instagram fetches the exact approved bytes from a temporary URL under
`/api/marketing/media/{ticket}` on the configured Meta callback origin. The
endpoint needs public HTTPS access, but does not expose a directory or accept
an asset ID alone. Each encrypted ticket expires after 24 hours and binds the
environment, release, content digest, account connection, asset version and
SHA-256. Disconnects, changed bytes and withdrawn unpublished releases make it
unavailable. GET, HEAD and single byte ranges are supported, with no-store
responses. Tickets are not stored in public workspace history.

The image, container, quota and published-media endpoints use the Facebook User
token specified by their individual reference pages. Every container is private
preparation until the separate `/media_publish` request. Preparation checkpoints
survive processing waits and worker restarts; explicit expiry can replace an
unpublished container within bounded attempts. Polling is spaced by at least a
minute and bounded. Provider-reported quota is checked before preparation and
again before publication, with other in-flight and unresolved local releases
reserved conservatively. Explicit throttling observes the full provider delay.

The final request includes only the saved container ID. Image captions and
ordered alt text are frozen beforehand; top-level media carries AI disclosure.
An accepted media ID remains **submitted** until a separate read verifies the
account, caption, media type, ordered image descriptions/count, timestamp and
Instagram permalink. This verifies provider metadata, not pixel equality after
Instagram recompression. A lost publish response stays **unknown**, with no
automatic replay or guessed ID. Unknown-ID reconciliation and live layout
verification remain work. Profile destination verification is described below.

Primary references: [image/container creation](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media),
[container states](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container),
[publishing limits](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit),
and [published media fields](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media).

### Instagram Reels and image Stories

Reels use the same temporary exact-file delivery and durable private-container
preparation. Actual MP4 metadata is checked before upload: supported video codec,
progressive 4:2:0 frames, frame rate, dimensions, duration and bitrate, plus audio
limits when audio is present. The MP4 must place its metadata before media and
contain no edit lists. Renderer v8 uses a closed GOP and no B frames or edit lists;
the real-file test verifies frame timing, duration, decoding and keyframe spacing.
The release sends `media_type=REELS`, AI disclosure and `share_to_feed=false`.
Acceptance remains submitted until a separate read confirms the known media ID,
owner, exact caption, VIDEO/REELS surface, time and Reel permalink.

Stories currently send one 9:16 JPEG with the body text drawn in the image,
including chart layouts. No separate caption, alt text, user tags or link sticker
is sent. The local preview retains accessible image descriptions. Meta supports
Story publication only for Business accounts; private container creation must
succeed before the public publish request. Creator accounts cannot use this
format. The UI explains this restriction without pretending the Facebook-login
IG User API exposes an `account_type` field.

Story confirmation checks the accepted media ID, owner, IMAGE/STORY surface and
publication time, then finds that ID in the selected account's active Stories.
Pagination is bounded and rebuilt on the fixed Graph host. A missing permalink
does not prevent ID-based confirmation or result in a fabricated link. A confirmed
Story displays its 24-hour deadline. After an unverified display window ends,
polling stops with **expired_unverified**, retaining the submitted status and ID;
it does not invent a successful publication or resend the Story. This expiry
also works when the owner has disconnected the credentials.

Profile routing can be selected for all supported Instagram formats. A raw URL
drawn into an image is not a clickable sticker. Owner login and a live Meta publication pilot
remain necessary to validate actual account eligibility and platform rendering.

Primary references: [media creation and Reel/Story limits](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media),
[active Stories](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/stories),
[Facebook-login account eligibility](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login).

### Financial originals from published analyses

The internal analysis collector retains each original's own period start/end and kind,
accounting standard, consolidation scope, currency, units and publication date.
A report's latest financial date does not replace a half-year original's period.
One original URL may contain several periods; those are separate evidence records.
Missing financial scope and conflicting values for one metric in the same scope
fail collection. Exact duplicate facts do not manufacture another original.
The current report contract keeps calculated ratios outside these original
monetary facts; those are not imported as purported raw original numbers.

Quarterly final checking compares used claims and calculation inputs with the
published report's exact original values, units and financial scope. A matching
number with a different period, standard, scope or currency fails. This also
blocks incorrectly scoped older evidence; no exception trusts a legacy collector.
Quarterly rules select the current published analysis, retaining its exact URL,
version and original filing dates. Event age begins at the first available
analysis for that issuer/standard/quarter; regenerating commentary does not
reset it. Shared original URLs do not merge different quarters. Replaced or
unavailable published analyses block unfinished assignments, including release.

Bounded RU/UZ/EN financial wording checks compare named flow amounts, currencies,
scales and explicit quarter/cumulative intervals. Missing units/start dates,
unrelated metric claims and ambiguous multiple amounts cannot prove quarter
profit. A derived quarter requires matching cumulative originals starting on
1 January and consecutive quarter ends, with the checked result displayed.
Explicit nine-month highlights remain valid without a quarter subtraction.
These checks do not prove arbitrary prose; historical comparative-original
assembly and broader editorial semantics remain work in progress.

### Verified Instagram profile links

In the material form or a team's Instagram target, select **Переход из Instagram →
Через ссылку в профиле** to add the localized reader instruction. The default is
no link instruction. The model uses the exact UZStock destination from the owner's
production brief or selected originals actually used by the draft. An owner can
repair a missing link in the material editor; the server records this choice for
the exact account, event and URL. Selecting a language variant is not a link
review. Generated destinations are revalidated at final check and dispatch,
even when visit tracking is disabled. Dot segments and encoded dot segments that
resolve to the homepage are rejected. These checks bind the declared route; they
do not request the live page or verify every URL embedded in prose.

Only the owner chooses whether to use the profile route. The production scope
carries this choice into each language variant's rendered material. The preview
links to the exact URL that must be configured in Instagram.

Set that URL in the selected Instagram profile yourself. The system reads
`id,website` using the connected User token, requires the selected account ID and
exact URL, and repeats the check after media preparation before the publish
request. It preserves query parameters and fragments, since they can identify
the report version, language or financial scope. It does not follow a redirect,
accept a homepage instead, or treat `instagram_link_ready` as evidence. The
[IG User reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user)
documents website reading and does not offer profile updates through this API.

A missing or different destination stops the release before a public request.
Automatic candidates become skipped; a manual candidate needs a fresh check and
owner decision after the profile is corrected. The UI allows requeueing only
where the delivery record proves no public post was sent. Processing waits,
transient provider errors and unknown publish outcomes retain their existing
handling; they do not authorize a duplicate publication.

The profile instruction is part of the reviewed image/video and caption (Stories
send only the image). Freeform profile/link-sticker/swipe-up copy is flagged for
revision rather than being treated as configuration. A route change invalidates
the previous approval and render. Renderer v8 reserves space for the instruction
without clipping financial units. Old accepted materials without the new field
retain their original content hashes.

The delivery payload records the verified destination and time. This proves the
profile state immediately before sending, not that nobody will edit the profile
later. Keep the promised destination available while relying on those posts for
traffic. Native Story link stickers and automatic profile editing are not part
of this route. Actual provider eligibility and rendering still require the owner
login and live pilot.

## Portable backup and recovery rehearsal

Run these commands with the application's database/media environment and a
private operator-controlled destination directory:

```sh
python -m marketing.backup create /private/backups/marketing-2026-11-26.zip
python -m marketing.backup inspect /private/backups/marketing-2026-11-26.zip
```

On Windows use `.venv\Scripts\python.exe` and an appropriate local path. The
archive includes current records, every immutable revision and every referenced
historical media file for the selected `MARKETING_ENVIRONMENT`. It excludes
service environment secrets and unrelated application databases. It contains
private workspace data; use the operator's protected backup storage. The
snapshot takes the same database write lock as other marketing mutations. A
missing historical file, a conflicting filename or a size limit fails the backup
instead of creating an incomplete archive. Existing destination files are never
overwritten. Portable limits are 32 MB for the manifest and 1 GB uncompressed;
larger installations need database-native backup plus the media directory.

Stop the worker for the **destination** before restoring. Select an empty database
or a new empty environment and its empty media directory. Never point a rehearsal
at the active production environment. Then run:

```sh
python -m marketing.backup restore /private/backups/marketing-2026-11-26.zip
```

Restore verifies the complete archive, revision continuity, current-record
agreement and file hashes before writing. It refuses an existing environment or
nonempty destination media directory. Original revisions and confirmed publication
IDs remain intact. New recovery revisions pause processing/publication, invalidate
connection proofs and mark in-flight sends unknown. A separate recovery lock
blocks dispatch even if someone removes the ordinary pause or reconnects a bot:
the original process may have sent queued posts **after** the backup cut.

The owner workspace displays this lock on every tab. Stop the original worker
before reviewing the gap. Keep both pauses enabled and use **Проверить промежуток
после копии**. Inspect every recorded original recipient from the backup cut
through the stated review time, record the evidence for each account, and add
every publication absent from the backup with its original event key, recipient,
type, publication time and URL. The server rejects stale workspace versions,
missing recipients, future review times and publications outside the reviewed gap.

Completing this owner review records an immutable decision and removes only the
recovery lock. Unconfirmed old candidates/deliveries become unknown and cannot be
replayed; found event/account/type keys are reserved against another release.
These manual records are not provider confirmation. Both pauses and invalidated
connections remain in place: verify the intended account, permissions and new
work before resuming. Matching an individual unknown delivery is a separate
operation. The review depends on the owner's complete platform-history check;
it does not automatically inventory every provider or infer missing event keys.

SQLite and PostgreSQL application-archive restores and owner gap completion were
rehearsed with actual stored history and generated media. No live database was
restored. Host failover and operational rollback still need their
deployment-specific rehearsal.

## Retention, disposal and staff access

The initial operating policy is below. These are operator duties; the application
does not claim that a backup schedule or deletion job has been configured.
Record the responsible operator and first successful backup before enabling a
live channel. Review storage usage and the backup inventory monthly.

| Material | Retention and disposal |
| --- | --- |
| Active workspace records, source versions, approvals, snapshots and referenced media | Keep for the lifetime of the active workspace. Immutable revisions and old media are part of the audit trail; do not prune individual rows/files to save space. Disable obsolete sources/rules and cancel drafts without erasing history. |
| Portable backups | Keep 30 daily copies and 12 month-end copies in protected storage. Inspect each archive; restore a sample into an empty isolated environment quarterly. Remove expired copies only after verifying a newer usable copy and checking that no incident investigation requires them. A portable archive is not a backup of unrelated UZStock databases or secrets. |
| Downloaded draft ZIPs, CSVs, screenshots and temporary working copies | Remove operator-created copies after 7 days once the authoritative material is verified in the workspace; retain longer only with a recorded purpose and expiry. Never treat the configured media directory as temporary storage. |
| Retired workspace | Stop all its workers, disable credentials, and make/inspect a final archive. Keep that archive for 12 months after retirement, or longer for a recorded unresolved incident. Remove the retired runtime copy only after an isolated restore proves the archive usable. At archive expiry, verify the exact environment and resolve all holds before disposal. |
| Credentials and login material | Keep only in the private service environment or encrypted provider store. Disconnect removes the supported provider's local grant; separately revoke it at the provider. Keep secret recovery material in restricted storage, outside source control and portable marketing archives. |

Disposal is an explicit operator operation, not an AI role action. Before deleting
anything, inventory the exact resolved paths, environment, archive and owner of
the data. Delete only the intended working copies, expired archives or fully
retired environment. Never drop a shared application database/schema, remove
another environment's media, or delete a current history reference. Keep a
disposal record with date, scope, reason and operator, without copying secrets.
The application has no selective erasure workflow for immutable history. If
source rights require removal, pause affected work, revoke source use and arrange
an explicit data migration/disposal review; do not claim that revocation erased
previously retained originals or already published material. Import only the
source content its reviewed retention rights permit.

The initial workspace is owner-only: human administrators can enter, while
collector secrets, ordinary users and other administrative roles cannot. AI role
names are workflow responsibilities, not employee login accounts. Do not share
the owner's login with staff. A staff member needing read/edit access requires
a separately implemented permission scope; until then the owner performs the
action and records the person's review as a reference. Infrastructure operators
need only the access required to run the service and protected backups; access
to a backup exposes workspace content and must be restricted accordingly.

## Release, rollback and host recovery

No production release is implied by local acceptance. Before deployment inspect
the host's active application directory, running image revision, persistent data
mounts and actual service manager. Obtain SSH details only from the private
git-ignored environment. Keep them out of this document and tracked files.

Use the existing CI release pipeline: test/build/smoke-test one image, publish it
to GHCR, and pull its immutable digest. The image revision label and server
checkout must match the tested commit. Compare changes against the running image
revision; a manual workflow run forces a release. Documentation/test-only changes
do not require a restart. Keep base digests pinned and remove short-lived registry
credentials after the pull. Do not build another image on the server.

Before replacement, record the running revision/digest and service configuration,
enable both marketing pauses, stop the old worker and capture a verified backup
with its cut time. Preserve the persistent database/media and private credentials.
After replacement verify health, data mounts, worker heartbeat, owner access,
source/model diagnostics and the two pauses. Run the prescribed production smoke
checks. Keep real-channel release disabled until the owner has completed login
and the separately authorized pilot in the provider acceptance matrix.

For rollback, first pause and stop the replacement worker. Prefer the previously
tested image digest with its matching checkout and the current compatible data.
Verify schema compatibility before starting an older image; if compatibility is
unknown, keep processing stopped and prepare a forward repair. A code rollback
does not undo publications. If data restoration is necessary, restore into an
empty destination and use the independent backup-gap review above. Keep the old
host/worker stopped to prevent two active dispatchers. Do not resume until
recipient checks, gap review and health checks are recorded.

Record each deployment/rehearsal's tested commit, digest, previous digest, backup
cut and inspection result, service/mount checks, smoke results, worker status,
owner decision and unresolved external outcomes. Record identifiers, not secrets.
Local SQLite/PostgreSQL restore tests establish archive behavior; they do not
establish successful failover on the production host.

## Model configuration to the login boundary

Only the service environment chooses a model or endpoint; no task/source text
can change them. Secrets are never stored in goal, source or content records.

| Setting | Meaning |
| --- | --- |
| `MARKETING_MODEL_PROVIDER` unset | Follow `NEWS_AI_PROVIDER`; use Claude when neither provider is set. An explicit marketing selection takes priority. |
| `MARKETING_MODEL_PROVIDER=codex` | Reuse the existing news Codex gateway, with `NEWS_CODEX_GATEWAY_URL` and `CODEX_GATEWAY_SECRET`; both are required. No local CLI fallback. |
| `MARKETING_MODEL_PROVIDER=claude` | Use the existing Claude gateway if configured, otherwise the server's Claude CLI |
| `MARKETING_MODEL_PROVIDER=ollama` | Use an installed local model through the configured Ollama service |
| `MARKETING_MODEL_PROVIDER=disabled` | Preserve tasks but report model unavailability instead of generating fake answers |
| `MARKETING_MODEL` | Model name override; required for Ollama, otherwise follows the selected provider's news model convention |
| `MARKETING_OLLAMA_URL` | Operator-configured service endpoint; defaults to loopback port 11434 |

Codex uses the same `POST /v1/json` contract and persistent subscription login
as the news collector. The web service already receives its private gateway
settings through `marketing-planner.env`. `NEWS_CODEX_MODEL`,
`NEWS_CODEX_FALLBACK_MODEL`, `NEWS_CODEX_REASONING` and `NEWS_CODEX_TIMEOUT`
retain their news meanings. `MARKETING_MODEL` can select a different primary
model without changing the news collector. Missing gateway configuration leaves
tasks unavailable rather than using another local login. The gateway keeps its
existing concurrency limit; news and marketing share that capacity.

Marketing role schemas include optional fields and open calculation maps that
Codex's strict output schema cannot represent directly. The gateway receives a
strict `result_json` string envelope and the original role schema in the model
instruction. The adapter decodes the inner object; the worker validates it
against the unchanged role contract before saving it. Invalid JSON or role data
cannot complete a task. Model errors use the marketing task's existing retry and checkpoint
flow. Gateway configuration is not proof of a working login: verify one completed
internal task, its saved role output and the absence of a publication before
enabling release rules. This connects the background worker to the gateway, not
to an interactive chat thread. Owner approvals and publishing permissions remain
separate from model access.

The Codex and Claude adapters are model-only: no built-in tools, MCP
tools, workspace instructions or shell actions are exposed to these role calls.
Its existing login remains the owner's responsibility. Ollama requires the
chosen model already installed and a running service. A configuration flag is
not evidence of a successful model call; the first real completed task is that
evidence. The local adapter uses Ollama's documented structured chat format:
<https://docs.ollama.com/api/chat>.

## Authority matrix

| Action | Owner | AI roles |
| --- | --- | --- |
| Change/approve goal, target, deadline, total budget | Separate versioned decision | Propose only |
| Propose strategy or internal draft | Yes | Within the brief and supplied context |
| Approve strategy | Exact goal/strategy version | No |
| Activate or replace a working plan | Exact approved strategy version | Coordinator creates its durable steps; cannot change the approved goal |
| Prepare future input bindings, edit or cancel an automatic start | Versioned owner action | Coordinator starts current bindings after dates/dependencies; up to three internal assignments |
| Accept internal work or return a revision | Owner can inspect history and pause the plan | Final CMO result required; stale sources or artifacts block acceptance |
| Record an owner-assigned step | Owner statement and supporting reference | Cannot claim the owner's external action occurred |
| Configure channel recipients and organic scopes | Yes | No |
| Verify financial claims | Evidence-based checks required | Model verdict cannot override deterministic checks |
| Publish organic content | Requires a permitted account and checked current version | Only the dispatcher may execute the approved scope |
| Paid campaign or spending | Separate exact-parameter approval required | Proposal only; organic rights never apply |
| Personal messages, founder replies, data exports | Separate explicit scope required | No implied authority |
| Change sources/model endpoints/secrets | Operator/owner configuration | No |

## Changes after publication

In **Content and queue → Changes after publication**, compare the immutable
source version used for the confirmed post with the current source. The worker
checks automatically; **Check source changes** runs the same comparison.
The processing pause also pauses this check. Arrival/expiry refreshes alone do
not create a factual-change incident. Changed facts, revoked source availability
and changed published analysis versions do. A detected difference requires an
owner assessment; it does not by itself prove the post was materially wrong.

Prepare a clarification with its reason, current facts, direct destination and
expiry. It is a separate candidate for the original account and platform, with
a visible clarification notice and the platform-confirmed original post link
when available. Replacing a withdrawn original requires an explicit source
mapping. Check the new candidate, approve its exact version when policy requires
it, and generate new assets for a media format. Old text, evidence and delivery
history remain intact. Only confirmed delivery marks the incident corrected.
Source/recipient changes block release; a source changing during dispatch is
compared again against the newly confirmed clarification. Unknown acceptance
blocks another clarification until reconciliation, whose provider workflow is
still pending implementation.

If the change does not affect the public statement, **Clarification not needed**
records the owner's explanation and cancels a prepared but unsent clarification.
Already sending or uncertain outcomes cannot be dismissed this way. A later
factual change creates a new incident; it does not reopen a rejected automatic
candidate. Generic candidate creation cannot use reserved correction event IDs.

## Dated theme observations

In **Sources**, import the permitted originals with **Material themes**. Use the
same event key for the same decision across reprints. A matching original URL
also joins duplicates; different headlines/URLs are not guessed to be independent
or equivalent. Source registry coverage topics do not automatically tag every
article. Earlier originals, including untagged originals, prevent a later reprint
from becoming a new mention.

Choose **Compare theme observations**, the exact theme and a fixed set of source
registry entries. Set the current window's start and exclusive end. Both windows
are equal, adjacent, completed Tashkent calendar-day periods (1–90 days each).
Counts use the first original publication date within that source population,
not the import date. The card names the selected sources and shows dated unique
event mentions, source counts, freshness, relevance, risk and a proposed format.
These are historical observations of the selected population, not a market-wide
trend or engagement measurement.

Leave completeness unchecked unless you have compared the full inventories in
**both** windows, checked theme assignments and reconciled event keys/reprints.
A successful RSS request or its last 100 entries is insufficient proof. Record
the basis of that review. Incomplete inventory can establish observed recurring
coverage, but never a measured growth percentage. Reviewed zero baselines allow
an absolute increase; their percentage remains unavailable. Flat and declining
counts retain their actual change and are never labelled growth. Relevance and
format remain editorial judgments, not measured audience response.

Each save freezes its input versions and counts in append-only history. Later
matching originals, corrections, source configuration or permission changes
withdraw the current growth claim until a fresh explicit review. The UI keeps
the previous counts clearly labelled as the earlier version; it does not rewrite
the historical record. Publishing-freshness expiry alone does not erase a dated
observation. Reopening the form always clears the completeness confirmation.

In **Workflow → New research**, select up to ten observations for the team.
The task pins their versions and dates. They are revalidated before the model
call and in the transaction that accepts a role result; changed observations
block that result and preserve completed steps. Such tasks cannot retry obsolete
context. Review the observations and start
a new task rather than silently replacing the old task's context. Original
quotes/claims for publication still need their own evidence and quality checks.

## Paid experiment proposals and decisions

Prepare a **paid creative** in Content and queue and run its fact check. Organic
permissions cannot release it. In **Experiments**, record the advertiser account,
campaign/placement, exact requested action, hypothesis, audience, reader question,
single tested variable, comparison, metric, minimum observations, campaign and
evaluation windows, budget limit, stop condition and creative brief. Include a
dated review of the platform's advertising rules and its validity period. Rules
are an owner-recorded review; the workspace does not pretend to fetch or verify
external policy pages automatically.

The targeting/PR/CMO task receives the approved goal and available paid creative
IDs. Targeting and CMO may save structured proposals in eligible planning tasks.
They cannot approve an action, overwrite an owner-approved experiment or release
its reserved budget. Missing account/placement inputs remain questions.

**Approve paid action** pins all parameters, creative digests, source/founder
versions and recipient identities. The currency and campaign period must match
the active goal, and approved limits cannot exceed its budget. Reservations in
a previous currency must be explicitly reviewed/revoked before new approval;
currencies are never added as if they were the same unit. Editing a proposal
removes its prior permission, while immutable history retains the exact approved
version. Revocation requires an owner reason. Reservations are not expenses and
do not create analytics spending events.

**Request paid action** rechecks approval, current goal, originals, creative
versions and budget. The current implementation then stops at the separate paid
connection boundary. Advertising provider authorization/execution, reconciliation,
ongoing expiry/stop monitoring and measured paid-campaign evaluation remain to be
implemented. Neither organic login nor a saved proposal can create, launch,
extend, increase the limit of, or pay for an external campaign at this checkpoint.
The UI states this limitation explicitly.

## Organic format experiments

The owner registers an immutable `editorial_experiment` from **Эксперименты →
Тесты рубрик**. The design pins the approved goal, dataset, exact creative digests,
account destination, language, disjoint control/variant publication IDs, reader
segment/question, single variable, comparison conditions, target product action
and exact object, enrollment dates, per-arm minimum readers, 1–30 day follow-up,
and a human-reviewed stop condition. Enrollment is at most 90 days inside the
approved goal period. Registration after its start is explicitly retrospective.
It neither releases content nor changes any publication or spending permission.

`experiment_results` reads the dated effective event ledger and existing coverage
confirmations at one cut. It excludes internal/automated/unconfirmed events,
other datasets, paid arrivals and wrong channels/publications. Each pseudonymous
reader enters an arm once via a confirmed publication arrival. The outcome is
counted once, on or after that arrival and within its inclusive follow-up window;
product objects must match exactly. Readers exposed to both arms, including an
opposite-arm arrival after enrollment but within follow-up, are excluded. For
registration, accounts registered before arrival are excluded and complete
registration history is required. Visit coverage also spans follow-up so that
late cross-exposure cannot be ignored. These rates describe observed readers,
not all platform impressions, randomized treatment or causal uplift.

Every calculation creates an immutable `experiment_evaluation`. A missing minimum
in either arm, incomplete coverage, an open follow-up window, changed creative
digest or changed destination keeps it preliminary and suppresses the comparison
difference. Observed counts/rates stay visible with that qualification. Owner
repeat/change/stop decisions pin one evaluation; later recalculation cannot move
their basis. The goal and budget remain unchanged. Stop conditions currently need
human review; stopping a design does not cancel or retract external posts.

Reports contain up to ten latest applicable evaluations known at their cut, the
original design and owner decision with its evaluation ID. The CMO task and its
server-bound result use that same evidence. A new evaluation or owner decision
changes the report context digest; historical cuts retain the prior evidence.
Late event corrections therefore create a new calculation without rewriting old
assessments. Model suggestions still need a separately registered design. Live
site identity/source completeness and provider observations need owner setup;
the isolated browser fixtures are explicitly test data.

## Test evidence and limits

Production and manually edited candidates accept an optional `occasion` with
`kind` (`holiday`/`gaming`), selected `evidence_id` and exact `evidence_version`.
The source must be verified, permitted, current and have an announced event date.
Task start, role claims, role completion and final candidate checking bind that
version. Every generated language retains the original. A changed occasion
invalidates media provenance and manual approval; older records without the
field keep their frozen content/tracking hashes.

Bounded RU/UZ/EN wording checks flag exchange schedules, popularity and market
effects inferred from an occasion. Supported statements use the exact selected
`exchange_schedule`, `popularity` or `market_effect` claim string, also present in
that original's excerpt. Ordinary claim, rights and expiry checks still apply.
The vocabulary and a few explicit negative formulations are supplementary checks,
not universal semantic or causal verification. The quality role must inspect the
exact wording and originals, and real model performance remains a login/pilot
acceptance item. Choosing a gaming theme does not grant rights to its artwork.

Owner editorial rules in **Рабочий цикл → Автоматический выбор событий** permit
bounded selection of individual news, market sessions, dividend decisions,
announced calendar dates, weekly calendar editions, source-bound charts,
published quarterly analyses and daily digest packs. Rules pin an approved strategy version, source list,
one account/target, rubric, languages/format, inclusive Tashkent dates, daily
assignment limit, maximum event age and draft/account mode. They are disabled
by default. Sources must have confirmed current access and storage/display/
commercial rights; selected originals must be verified and unexpired.

A weekly calendar rule sets `calendar_day` (Monday=0 through Sunday=6) and
`calendar_time` in Asia/Tashkent. Sunday prepares the next Monday–Sunday; other
days cover future events in the current week. A delayed worker can catch up
within that week using current announcements. Empty weeks create no task. At most
eight distinct event groups and thirty originals fit one edition. A notice may
have been published long ago; current verification and the future event date
control eligibility, rather than `max_age_hours`. Conflicting dates/types stay
unassigned. The edition expires no later than its first event or original expiry.
One rule/week identity survives title changes; canonical event/URL aliases prevent
rescheduled events from becoming new releases. Old rules without a calendar time
retain their individual-event behavior until explicitly saved as weekly rules.
Structured calendar text uses the existing source-bound item representation,
requires a Monday period, orders dates, and checks each paragraph against its own
originals before quality acceptance. It currently supports text posts.

The worker selects after collection, before model work. Canonical event and URL
groups reuse trend deduplication; immutable evidence history retains the earliest
known original date. A changed/reprinted original does not become fresh urgent
news. Urgent priority is restricted to news up to 24 hours old and reorders
production work and posts to the same account, preserving pause, window, interval,
approval, recovery lock and final checks. Daily limits count actual assignments
across rule revisions. Two workers cannot select one event/account twice.

Assignments retain exact rule, original inventory, account and founder versions.
The same authority is rechecked before/after model work, at final checking,
scheduling, dispatch and the provider's final write boundary. Rule revision or
revocation stops its old unfinished assignments; terminal automatic failures
never restart. Runtime status is separate from owner configuration history.
The UI displays actual assignments and their handoffs. Chart and other multi-input
editorial packs still need prepared inputs.

Digest rules require `digest_time` (`HH:MM`, Asia/Tashkent) and text-post format.
The selection window is `(cutoff - max_age_hours, cutoff]`; source freshness is
still checked at the actual work time. Before today's cutoff the rule waits.
After it, the selector combines 2–8 unused distinct news/dividend events, at most
30 originals, with valid UZStock destinations. Reprints retain the earliest
known original date and count once. The edition key binds the rule ID and cutoff,
so editing the rule does not create a second edition for the same cut. Existing
manual digest candidates and source-bound digest tasks also reserve their events
for that account. Paid creatives do not reserve organic editions; publication
type stays part of the release identity. Assignment retains all original versions and event aliases;
an automatic candidate cannot omit a selected event.

`digest_items` binds each paragraph to originals for one event. The server renders
issuer, publication/event dates, UZStock link and original URLs before model
quality review and candidate creation. Final checking evaluates financial claims
against each item's originals, requires all draft originals to be visible, and
checks the assembled body and platform limits. Owner edits rebuild the body and
invalidate approval. A visible monetary dividend statement without its own claim
is rejected in RU/UZ/EN; displayed dates must match original dates. These bounded
checks supplement the editorial review; they do not prove arbitrary prose.
The overall digest headline is neutral and the initial format is text-only.
Only the main destination currently carries publication attribution; additional
item links remain direct. Absent `digest_items` does not change older frozen
publication-link proofs. Legacy flat digests need structured items before a new
release check; published history is preserved.

Internal drafts can enter release through the owner-only
`POST /candidates/{candidate_id}/release-draft` endpoint. The request pins the
candidate and account versions; the server chooses the current account mode,
records the owner decision, refreshes tracking and runs final checks in the same
transaction. It does not create another candidate, grant account access or send
anything itself. A ready result becomes eligible for the existing worker. Manual
mode still needs exact-content approval, and a failed automatic check is terminal.
Draft-only, paused, expired or out-of-scope accounts and paid creatives cannot use
this path. Existing publication pauses and backup recovery locks still apply.

For an internal draft created by an editorial rule, this explicit decision reviews
the current account instead of the production-time account version. The recorded
recipient must continue to match; connection checks alone may advance its version.
Rule revocation, changed strategy, inventory, originals or founder facts are still
blocking and are checked again before dispatch. The model and language-selection
path cannot supply this owner decision.

Backend acceptance lives in `tests/test_marketing_*.py`. Browser acceptance
uses the `e2e/ai-marketing-*.spec.js` feature specs with real API handlers and an isolated
SQLite database; identity, model responses and social transport are controlled
test adapters. Existing admin navigation is covered by `e2e/admin-panel.spec.js`.
No social post, advertising purchase or payment was made by these tests.

On Windows, enable UTF-8 and include the installed Git Bash directory in the
test process's PATH, then use `.venv\Scripts\python.exe -m pytest -q`.
Build before Playwright: `npm run build`, then
`npm run test:e2e -- marketing- admin-panel.spec.js`.
Analysis deep-link changes also run `e2e/sector-analysis.spec.js` and
`e2e/smoke.spec.js`; language routing and keyboard recovery are covered by
`e2e/language-urls.spec.js`. The latest results and remaining requirements are
recorded in `docs/marketing-implementation.md`.

Deployment follows the existing uzstock.uz CI image/digest process. There is
no Railway deployment and no server-side rebuild. Production inspection,
the backup schedule and a release/rollback acceptance record remain required
before the feature is released. The operator policy above defines retention;
it does not assert that production jobs have been installed.
