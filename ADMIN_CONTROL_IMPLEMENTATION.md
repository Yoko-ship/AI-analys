# Admin control implementation — 30 August 2026

The two supplied HTML files were treated as product requirements. The implementation extends the existing React/FastAPI application; it does not replace the existing financial engine or change source financial values by hand.

**Delivery status: implemented core workflows; full specification acceptance remains incomplete.**

## Available locally

- `/admin` opens the operational overview. Grouped navigation covers incidents, jobs, coverage, issuers, documents, sources, parser runs, facts, mappings, formulas, calculations, templates, signals, analyses, publications, securities, audit and access. Existing product metrics and system pages remain available.
- The interface uses the application's light/dark themes and RU/UZ/EN selection. It includes a collapsible sidebar, phone navigation, global search, source/detail drawers, loading/error/empty states, and keyboard focus handling.
- Registries filter and paginate on the server. Filters survive in the URL. Saved views and column selection are available; saved views are local to the browser/user/environment. CSV/JSON exports use the full filtered result, not the visible page. Spreadsheet formula injection is escaped.
- `/api/admin/control` requires a human account. Viewer, analyst, rule editor and administrator capabilities are enforced by the server. The collector secret cannot open this API. Administrator/editor mutations require an authenticator code. Changes require a reason, request ID, idempotency key and, for existing objects, the current version.
- SQL persistence stores indexed resources, immutable revisions, append-only audit and a durable job queue. Database triggers prohibit audit/revision updates and deletes. Environment keys scope records and commands.
- Jobs support checkpoints, leases, cancellation at a checkpoint, backoff, retained attempts and explicit results. Retrying manually creates a new job linked to its predecessor.
- Stored document originals are addressed by SHA-256. Byte sniffing distinguishes PDF/XLSX/HTML. Duplicate source URLs point to one canonical checksum; aliases are excluded from default registry and coverage totals. Metadata changes create new revisions and invalidate prior verification.
- Temporal classification rejects impossible periods and recognizes a six-month statement ending June 2026. Source/header classification success is explicitly separate from financial verification.
- The authenticated viewer exposes inert workbook values and server-rendered PDF pages, with page/sheet/row/cell links, search, zoom and original downloads. Formula/macro/script execution is not exposed in the browser.
- Actual domain formula definitions are indexed as baseline rules. Typed drafts can change formula inputs, line aliases, conservative OKED routing, freshness thresholds and literal header classification. No arbitrary executable formula or manual financial-value override is accepted.
- Draft testing records regression results and a conservative full impact set. Another reviewer must approve activation. Shadow runs precede activation; failed financial verification after activation restores prior rules and schedules a repair run. Parser shadow runs compare classifications from the same stored bytes and retain their results.
- Analyses, source facts, enterprise calculation inputs, instruments and publications are projected from existing domain output. Calculation traces retain unrounded values, units, method versions and source rows. Missing physical lineage is a blocker in the control registry.
- Publication status follows the existing domain's actual current-version pointer. Reindexing historical runs cannot promote them. The controlled rollback workflow requires an incident and a second reviewer; the domain changes its publication pointer atomically. The administrative projection reconciles afterwards.
- The older sector-monitor endpoints cannot activate template overrides or roll back publications directly; they direct users into the governed workflows.

## Runtime configuration

No production deployment, role assignment or live filing correction was performed.

| Variable | Purpose |
| --- | --- |
| `ADMIN_ENVIRONMENT` | Explicit environment label; defaults to the configured platform environment or `local`. Use separate credentials/databases/volumes for real staging and production. |
| `ADMIN_ROLES` | JSON email-to-role mapping. Supported roles: `viewer`, `analyst`, `rule_editor`, `administrator`; invalid/disabled assignments deny access. Stored access assignments take precedence. Existing `ADMIN_EMAILS` remains the initial administrator fallback. |
| `ADMIN_CONTROL_DB` | Local SQLite path. Defaults to `APP_DATA_DIR/admin_control.sqlite3`. The existing `dbx` PostgreSQL configuration is reused when selected. |
| `ADMIN_DOCUMENT_DIR` | Durable original-document directory; defaults to `APP_DATA_DIR/admin_documents`. |
| `ADMIN_DOCUMENT_HOSTS` | Comma-separated approved HTTPS hosts; defaults to `openinfo.uz,api.openinfo.uz,uzse.uz`. Redirects and public DNS addresses are checked. |
| `ADMIN_CONTROL_WORKER` | `1` by default: run the compatibility worker within the API. Set `0` when running a dedicated `python -m admin_control.worker` service. |

`python -m admin_control.worker --sync --once` indexes existing catalog/domain records and processes one queued job. Normal API startup also indexes periodically. Worker operation requires the application's existing catalog and analysis dependencies. PDF rendering adds the pinned `pypdfium2` dependency in `requirements-server.txt`.

The implementation uses a SQL job queue and a filesystem original store. It does **not** provision the separately described Redis/S3 infrastructure.

## Verification evidence

Use the project `implementation-qa` skill for subsequent implementation changes.

**QA outcome for the implemented scope: PASS WITH LIMITATIONS.** Latest checks: 113 backend tests passed; 14 browser tests passed (7 new control-panel flows and 7 neighboring sector-analysis flows); targeted ESLint and the production build passed. Full-spec release acceptance remains incomplete as detailed below.

- Focused backend suite: `tests/test_admin_control.py`, `tests/test_admin_panel.py`, `tests/test_admin_console.py`, `tests/test_sector_contract_v22.py`, `tests/test_sector_analysis_service.py`. Run against isolated SQLite/catalog/document paths, with no production writes.
- Actual application integration: human-session gate → authenticated command → persisted job → worker → document revision → authenticated preview. Only identity/MFA validation and external source bytes are fixtures. The HTTP handlers, permission decisions, queue, document processing, persistence and audit are real.
- Actual domain publication tests exercise last-good preservation, historical reindexing, two-reviewer rollback and current-pointer reconciliation.
- Browser suite: `e2e/admin-control.spec.js` exercises seven flows against the built application with explicitly mocked API data: navigation, URL filters/deep links, source viewing, reasoned job submission, viewer permissions, draft creation, error/retry, phone layout and dark theme.
- The real interface was also inspected in the in-app browser at phone and desktop sizes, including Russian/Uzbek navigation and the dark document drawer. Preview data is synthetic, not a claim that a live UZNF filing was imported.
- Relevant JSX lint and the production build are checked. The existing main bundle remains larger than Vite's 500 kB warning threshold; existing Python dependencies emit deprecation warnings.

## Acceptance gaps and release blockers

These are not certified as passed by the tests above. The documents label all ADM-01–ADM-50 checks as release blocking, so the full requested release must **not** be presented as accepted yet.

| Requirement | Remaining work / limit |
| --- | --- |
| ADM-03, 43, 45: complete discovery → catalog → financial publication | The control worker indexes the existing source catalog, processes an original and signals the existing domain pipeline. It does not yet replace every collector/parser or write corrected interim metadata into every public catalog/financial series. Event discovery of a document absent from the existing catalog needs a source-adapter integration. |
| ADM-19, 31, 33, 37: universal provenance | Enterprise calculation inputs now have source-row tracing where the parser supplies it. The separate legacy P/E, P/B, ROE, ROA and bond calculations are not all migrated to this registry. Existing rows without exact locations remain incomplete; original bytes and financial snapshots still need an end-to-end checksum reconciliation contract. |
| ADM-08, 17, 20, 36: full rule catalog/editors | Typed safe rule families and shadow activation are available. The complete template/block/signal/decision taxonomy and every formula described by the specification are not editable through a full schema-driven visual editor yet. Impact is conservatively the full catalog, not a minimal dependency graph. |
| ADM-25, 29, 30: production behavior | Domain rollback is atomic; the separate admin projection is eventually reconciled. PostgreSQL failover, distributed lease contention, deployment credential isolation, service restarts under load and canary rollout have not been exercised in production. Exception exhaustion during a rollout needs further operational validation. |
| ADM-41, 42: full Parser Lab | Classification current/draft comparisons use real stored bytes. Side-by-side normalized tables/facts, complete unit/identity classifier coverage, artifact-pinned historical parser executables and a dedicated visual Parser Lab remain outstanding. |
| ADM-46–48: full public catalog/viewer redesign | The new authenticated admin viewer works for PDF, XLSX and plain HTML text. Public viewer access, PDF thumbnails/precise text overlays, legacy XLS conversion, structured XBRL contexts, two-report comparison and complete reverse paragraph-level lineage are not implemented. Workbook previews are bounded to 2,000 rows and 100 columns; downloads retain the complete original. |
| ADM-49–50: UZNF 2026H1 | The local catalog does not establish the official 2026H1 original. No financial values or missing filing were fabricated. A coverage incident records the unconfirmed source. Existing annual investment-fund routing and industrial-ratio exclusions are preserved, but the H1 source import, approved interim fund model and resulting catalog/analysis/valuation update remain unverified. |
| Other operational requirements | Central saved views, source schedule editing, notifications, immutable object-store retention, short privileged sessions/reauthentication across every legacy endpoint, distributed rate limiting and the stated 100,000-row latency targets require further implementation or production validation. |

## Main implementation files

- `frontend/src/admin/ControlPanel.jsx`, `DocumentViewer.jsx`, `controlConfig.js`, `control.css`
- `admin_control/api.py`, `store.py`, `service.py`, `documents.py`, `rules.py`, `worker.py`, `adapters.py`
- Integration in `api.py`, `web_auth.py`, `analysis_monitor.py`, `sector_analysis.py`, `sector_report_service.py`, `sector_admin_api.py`
- Regression coverage in `tests/test_admin_control.py`, `e2e/admin-control.spec.js`

Existing unrelated workspace changes were preserved. This work has not been committed or deployed.
