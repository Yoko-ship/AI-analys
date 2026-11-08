# Collector operations

Open **Admin → System → Collectors** (`/admin/streams`).

Each collector shows its latest observed attempt, result, next scheduled run,
publication receipts and any scheduling problem. Open **Details** for the failed
stage, sanitized journal excerpt, earlier runs and exact server commands.
The data freshness table is separate: an old data row does not prove a failed run.

## Run a collector by hand

Press **Run now**. The existing administrator authenticator check applies.
The request first appears as **Queued**, then **Start accepted**; completion is
reported separately. The server checks for requests about every 30 seconds.
Refreshing this page or clicking twice does not submit a duplicate active request.

Alternatively, in an authenticated shell on the existing production server:

```sh
sudo systemctl start --no-block uzstock-quotes-catchup.service
sudo systemctl status uzstock-quotes-catchup.service --no-pager
sudo journalctl --no-pager -n 200 _SYSTEMD_UNIT=uzstock-quotes-catchup.service + UNIT=uzstock-quotes-catchup.service + SYSLOG_IDENTIFIER=uzstock-quotes-catchup
```

Use the commands in that collector's Details for another service. These run the
same job and options as its scheduled run. They do not perform an arbitrary
historical backfill or bypass source rate limits.

The allowlist covers full financial collection, closing/final/catch-up quotes,
intraday bars, filings, bank history, financial document ingestion, bank FX,
Central Bank publications, corporate disclosures and news.

## Read the result

- **Completed** means the process exited successfully. Check **Publication**:
  acknowledged writes can include existing, unchanged records.
- **No change** requires an explicit source/collector receipt saying why nothing
  needed publication, such as an already published trading session.
- **Partial / Failed** includes recorded source or publication errors. Service
  timeouts, memory limits and signals are reported even if Python never logged an error.
- **Not observed / No confirmed write** means evidence is missing. Do not infer
  that updates arrived.
- **Start unconfirmed** means dispatch may have reached systemd but its confirmation
  was lost. Inspect the service and journal before clearing the request. Clearing
  does not stop a service. An uncertain start is never automatically repeated.
- An offline monitor disables Run now. Disabled/inactive timers and an observed
  missed schedule appear independently of the last process result.

Queued requests expire after 15 minutes. The database retains the last 50 observed
invocations per service (the panel initially lists 10) and 90 days of finished manual
requests. Logs are bounded excerpts; use journalctl for the complete retained log.
Earlier observed publication failures survive subsequent journal-tail updates.
History starts with deployment/observation, not retroactively for every past run.

## Management disclosures for every company

The **Corporate disclosures** job also discovers Openinfo form 8 history for every
issuer in the company and market-security catalogs, independently of the recent news feed.
Market-only securities use the existing exact ticker/ISIN issuer index; there is
also an exact, unambiguous company-name match within the market directory to
reuse a known issuer for another share class. There is no fuzzy name matching,
and an otherwise unresolved security can match an exact registered company name
in the Openinfo index. Company-page reads do not contact Openinfo. Ordinary
and preferred shares share one issuer check. It runs at most once per issuer per
day, processes 100 issuers per invocation, and rechecks cached documents after
seven days. New filings are discovered on each eligible run. The latest complete
executive roster and subsequent changes are kept separately from supervisory and
audit bodies. The decision-making body alone does not identify the affected body.

Use **Run now** for **Corporate disclosures** to process eligible issuers. To
bypass the daily check for an immediate retry, with the normal application
environment and catalog data mounted, run these commands:

```sh
python -m governance_collection --ticker HMKB --force
python -m governance_collection --force
```

`--force` bypasses the daily schedule, while preserving the document cache so a
bounded archive scan can resume immediately. `--max-documents 100` raises the
default 30 new-document budget per issuer. It does not bypass source pacing,
retries or the circuit breaker. To run the full scheduled job:

```sh
python corporate_event_backfill.py --limit 40 --days 120
```

For an operational release from GitHub Actions, manually run **CI** on the **API**
branch with **backfill_governance** enabled. The collection starts only after the
tested image is deployed and its revision matches the server checkout. A release
commit containing `[backfill-governance]` requests the same post-release collection.

Each issuer emits a JSON receipt with tickers, `checked_at`, `last_success_at`,
`state`, `reason`, and imported/examined counts. A failed receipt adds `stage`
(`listing` or `detail`). The persisted receipt is exposed in
`GET /api/company/{ticker}/shareholders` under `management.collection`; archived
people are retained if an update fails. Source failures cause a nonzero job exit.

| Reason | Meaning / action |
| --- | --- |
| `EXECUTIVE_ROSTER_FOUND` | A dated executive roster was found; newer changes are also retained. |
| `NO_FORM8_DISCLOSURES` | Openinfo returned no form 8 disclosures for this issuer. |
| `NO_EXECUTIVE_ROSTER` | Available history was checked, but contains no identifiable full executive roster; another disclosed body or partial changes may still be shown. |
| `MISSING_ISSUER_ID` | Match the catalog company to the correct Openinfo issuer before collecting. |
| `NOT_COLLECTED` | This issuer has not yet been checked by the new collector. |
| `ARCHIVE_LIMIT_REACHED` | The bounded scan is partial; rerun to resume cached history or raise `--max-documents`. |
| `HTTP_<status>`, `TIMEOUT`, `CONNECTION_ERROR` | The source request failed; inspect the stage and rerun after service recovery. |
| `SOURCE_PAUSED` | The shared Openinfo circuit breaker is open; remaining issuers wait for the next run. |
| `ISSUER_MISMATCH`, `WRONG_DISCLOSURE_TYPE`, `DISCLOSURE_ID_MISMATCH` | Source identity did not match the requested company/form/document; no unverified document is published. |
| `INVALID_SOURCE_RESPONSE`, `PAGINATION_STALLED` | Unexpected source structure or repeated pagination; inspect the source response before changing the parser. |

The result also lists `missing_identity` tickers, remaining issuers, failures and
partial scans. A successful process does not imply every company published a
roster. Dates and source links on the company page describe the underlying
disclosure, not a guarantee that the roster is current today.

## Deployment and recovery

The existing CI release installs `uzstock-collection-monitor.service` and its
30-second timer on the same production host. It uses standard-library Python,
the existing ignored application environment file and the loopback API. The web
container receives no Docker socket or general command-execution capability.
CI still builds and tests one image, publishes it by digest and uses the matching
server checkout; no second server build is introduced.

The host keeps a private, fsynced dispatch outbox in
`/var/lib/uzstock-collections`. Replaying an outbox entry only acknowledges the
existing dispatch; it never executes it again. API requests and observations are
durable in the catalog database. Machine observation endpoints use the existing
administrator push secret; browser mutations require a signed-in administrator
and the existing two-factor step-up.

If monitoring is offline, inspect its own service before restarting it:

```sh
sudo systemctl status uzstock-collection-monitor.service uzstock-collection-monitor.timer --no-pager
sudo journalctl -u uzstock-collection-monitor.service -n 100 --no-pager
sudo systemctl start uzstock-collection-monitor.service
sudo systemctl enable --now uzstock-collection-monitor.timer
```

Do not copy connection details or credentials into tracked configuration or logs.
No external email/Telegram notification is enabled by this feature.
