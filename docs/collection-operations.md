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
