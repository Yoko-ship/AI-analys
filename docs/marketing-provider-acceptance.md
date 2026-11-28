# Marketing integration acceptance

This records the implemented boundary, not the user's current account state.
No live social-account login, publication, advertising purchase or model pilot
was performed for this implementation checkpoint. Controlled HTTP/model tests
exercise the real application handlers, persisted jobs and UI. A provider is
operational only after its separately authorized live checks succeed.

| Integration | Implemented local path | Owner/operator setup still needed | Live acceptance still open |
| --- | --- | --- | --- |
| Claude / Ollama | Bounded structured role calls, persisted handoffs, interruption recovery and visible errors | Owner model login, or installed local model and running Ollama service | A real brief completes through its required roles; record latency, failures and usable outputs |
| Telegram | Exact-channel probe; text, images, photo groups and video; durable dispatch; observation-backed reconciliation | Dedicated bot credential and access to the exact selected channel | Verify that channel; send one separately approved pilot; inspect the actual result and reconcile its identity |
| Facebook Page | Meta OAuth and explicit Page selection; text, single/multiple photos and Reels; persisted uploads and independent confirmation | Owner login, app configuration and the exact Page grant | Inspect text/media ordering and Reel disclosure; confirm a real post and its public visibility; exercise revoke/expiry behavior |
| Instagram | Meta OAuth and explicit professional-account selection; JPEG, photo carousel, Reel and image Story; container processing and independent confirmation | Owner login/grant and reachable configured media origin | Inspect each approved pilot format; verify account, media, actual post identity and exact profile-link destination where used |
| Personal LinkedIn | Separate OAuth, verified member identity, encrypted grant; text/media publishing and explicit visibility review | Owner personal-profile login and app configuration | Confirm the exact personal profile, approved founder wording, visible post and stored provider identity |
| Native website analytics | Dated registration starts/completions, session links, typed product actions, durable receipts and report ingestion | Explicit source/dataset configuration; existing application database connection | Confirm observations from the intended environment and compare a closed inventory; missing identity or history remains incomplete |
| Paid advertising | Proposal, policy-review record, exact creative/source approval, goal-budget reservation and revocation | Separate paid-provider implementation and owner advertising authorization | Execution, spend ingestion, stop/expiry monitoring, uncertain-result reconciliation and measured evaluation are unfinished |

## Boundaries that remain visible

- Login and publication permission are separate. An account configured for
  drafts stays closed for release after successful login. Organic rights never
  authorize paid execution or personal direct messages.
- A prepared content-plan step always produces internal drafts. It may select
  a currently configured account before login; the production binding must still
  match when the worker starts and accepts its results. The owner can later
  explicitly enter the account's release workflow on that same candidate. This
  records the exact candidate/account versions, refreshes tracking and repeats
  final checks. Manual release still requires approval; automatic failure is
  terminal. Login does not make this decision. Subsequent recipient changes block
  release; a connection refresh for the same recipient is allowed.
- Individual-event automation starts disabled and needs an explicit owner rule.
  Draft mode cannot authorize a send. Account mode still requires that account's
  current release permissions, login and final checks. Verified urgent news
  changes queue order only. Revocation is checked again after provider preparation.
  An owner release of an internal rule draft reviews the current account but
  preserves the original rule, strategy, evidence-inventory and founder guards.
- A script is not a finished video. The worker publishes only valid, checked
  media assets with their recorded versions and rights.
- Generated destinations must match the owner's exact brief/edited choice or
  a destination declared by the selected originals used in the candidate.
  Language selection cannot approve a guessed URL. URL checks apply with and
  without visit tracking, including paths that normalize to the homepage.
  This binding does not prove that a live page loads or that every URL mentioned
  in prose is semantically correct; inspect those during the live pilot.
- The Instagram implementation offers an exact profile-link route. It does
  not add a native Story link sticker. A mismatched profile destination blocks
  release rather than silently sending readers to the home page.
- Facebook Stories are not offered. Facebook video is a Reel, with its stated
  visibility/disclosure behavior; it is not a generic private-video upload.
- The owner forms use the server's provider capability catalog. Unsupported
  formats are disabled in account settings and excluded from content, team and
  recurring-rule choices. Instagram has no text-only post; Telegram, Facebook
  and LinkedIn have no Story adapter. A text digest/calendar therefore requires
  an account allowing text posts. Saving legacy account rules removes unsupported
  format permissions without deleting their material history. Capability is
  separate from login and current publication permission.
- An accepted provider ID and a confirmed visible publication are separate
  states. Uncertain writes remain unknown and are not blindly retried.
  Known-ID verification and unknown-ID recovery do not have identical provider
  coverage. In particular, unknown Facebook text/photo writes must stay unknown
  where independent proof cannot be obtained.
- A restored workspace has an independent release lock. Reconnecting an account
  or removing an ordinary pause does not reconcile the backup gap. The owner can
  complete a version-bound review of every original recipient and record missing
  publications. Completion quarantines old unconfirmed releases and reserves
  the found event keys; it retains both pauses and unverified connections.
  This is a manual gap review, not an automatic provider-history inventory or
  proof that every publication has been found.

## Record for each later live pilot

Record the authorized account identifier, permitted format, exact candidate and
approval versions, source and media digests, requested release time, provider
acceptance ID, independent confirmation/visibility result and any unresolved
error. Use an approved test account or a separately approved real publication;
do not present a controlled test receipt as a live one. Never record tokens,
passwords, private login codes or credential-bearing URLs in tracked files.

Runtime configuration and per-provider details are in
[marketing-operations.md](marketing-operations.md). The current implementation
and test results, including unfinished requirements, are in the
[acceptance ledger](marketing-implementation.md). Deployment remains the existing
uzstock.uz CI image/digest process and is not implied by this local verification.
