# Dynamic IFRS extraction and accounting scopes

New catalog reports are parsed without ticker-specific branches or manually
entered value ledgers. `financial_ingestion/statements.py` recognizes statement
headings, year columns, periods, units, labels and signed components.
`layout.py` preserves physical word spacing from native PDF words and OCR TSV
coordinates, separating note references and thousands groups from year columns.

The parser produces primary and comparative candidates. Notes and cash-flow
statements cannot supply balance/income totals. Non-calendar inaugural periods
and standalone three-month flows retain their actual start dates; they do not
become calendar annual or cumulative-YTD observations. Conflicting or ambiguous
cells stay missing. Calculated totals retain literal components and coefficients.

For scans, the worker surveys the first 16 pages at low resolution, then ranks
statement pages by their contents and refines at most eight pages. It does not
assume that statements occur at fixed page numbers. The complete OCR pass has a
240-second budget. The production image already includes English/Russian
Tesseract. No external AI service or new API credential is required.

The existing checked-in reviews remain evidence for the historical recovery.
They are not required to process a new PDF. New extraction creates database
candidates; review and publication use the existing generic commands. A passing
arithmetic check alone does not approve OCR, issuer identity or accounting scope.

## Inspect and register documents

```sh
python -m financial_ingestion.worker inspect --file report.pdf --ocr
python -m financial_ingestion.worker discover --ticker TICKER
python -m financial_ingestion.worker work --max-jobs 4 --ocr
python -m financial_ingestion.worker candidates --ticker TICKER
```

`inspect` is read-only and does not load financial amounts from a review ledger.
Discovery continues to consume all matching OpenInfo catalog documents. If an
issuer original is absent from that catalog, register its verified source page
and PDF as data, without adding a hostname/path rule or financial values to code:

```sh
FINANCIAL_SOURCE_POLICY=reviewed_issuers python -m financial_ingestion.worker register-source --ticker TICKER \
  --url https://issuer.example/reports/annual.pdf \
  --source-page https://issuer.example/investors \
  --actor REVIEWER --reason 'Verified official issuer source and identity'
```

The page and PDF must share a public HTTPS origin. Registration is attributed;
downloads remain size-bounded and reject redirects. Registered sources participate
in refresh and parser-version reprocessing. Registration does not approve figures.
This is source registration, not an automatic crawler of every issuer website.
This compatibility command is disabled under the production OpenInfo-only
policy described below. Do not use it for future production updates.

## Separate and consolidated views

The financials page offers **Consolidated group** and **Separate entity** when
IFRS is selected. The selected scope travels with annual/interim series requests
and every source-passport request. A missing scope returns an empty result and
never falls back to the other scope or unclassified legacy values.

```text
/api/company/TICKER/financials?form=MSFO&scope=separate
/api/company/TICKER/financials?form=MSFO&scope=consolidated&freq=quarterly
/api/company/TICKER/financials/passport?form=MSFO&scope=separate&period=2021&field=net_profit
```

Requests without `scope` preserve the existing default: consolidated when
published, otherwise separate. Growth comparisons remain inside one scope.
NSBU requests reject an IFRS scope parameter.

## Validation and limits

The tests cover unseen issuers/reports, reversed year columns, note numbers,
space/comma grouping, OCR word geometry, wrapped labels, signed calculations,
non-calendar periods, conflicting values, and scope-specific API/passport reads.
The browser test switches between scopes, opens a passport, and returns from
an empty interim view.

The archived PDF evaluation includes damaged text layers and scans. Some native
text layers contain incorrect digits; some OCR pages remain incomplete. These
are review candidates, not a claim of complete unattended extraction. Missing
source documents and ambiguous evidence remain gaps. The parser has no rule
that invents figures to make a balance reconcile.

## Production verification — 18 September 2026

Release `5a5a366e0d41350fe945ca000e09aeafcc4b8771` is deployed to uzstock.uz.
The shared parser supplied seven reviewed separate-account periods: MCBA
2020–2022 and IPKY 2018–2021. Their 63 figures were checked against the original
statement pages before publication. No financial amounts were added to the
checked-in recovery ledger.

The public API and passports verified all 63 new figures and all 1,251 existing
figures. Browser checks confirmed separate/group switching and correctly scoped
passports. There are 146 published periods across both accounting scopes.
Existing default histories retain their previous values and source hashes.

The release passed 156 focused backend tests, two browser tests, the frontend
build and lint (zero errors, 59 existing warnings). See the
[archive evaluation](dynamic-ifrs-evaluation-2026-09-18.json) and
[production verification](dynamic-ifrs-live-verification-2026-09-18.json).

Source absence, unreadable scans and unresolved candidates still limit coverage.
This release does not certify unattended extraction of every report, and source
registration does not automatically discover every issuer-site document.

## Historical gap recovery — statement parser v2

The shared parser now handles opening balance columns, annual income dates
confirmed by balance statements, consistent unit headers on adjacent statements,
wrapped note references, profit/loss label variants and isolated OCR note marks.
Extra financial columns cannot silently become note numbers. A single effective
interest category can supply a gross total only when the income/expense pair
reconciles with the printed net interest total.

OCR corrects small page rotations, groups overlapping glyph boxes into rows and
tries bounded alternative segmentation/resolution settings for incomplete pages.
It keeps the strongest whole-page extraction, including a balance reconciliation
check, within the existing 240-second report budget. Arithmetic checks remain
insufficient for publication: every released figure was checked against the PDF.

Official source pages may now link a PDF on a different public asset origin.
Registration checks both hosts, requires an exact link on the bounded source
page response, disallows redirects and records the page hash and linked origin.
There are no issuer hostname exceptions. Same-origin registration is unchanged.

The recovery review covers 16 additional annual periods and 144 figures; see
[the source audit](bank-ifrs-gap-recovery-2026-09-18.json). No financial amounts
were added to the historical review ledgers.

| Issuer | Consolidated additions | Separate additions |
| --- | --- | --- |
| GRBK | 2017–2021 | 2022–2023 |
| IPKY | 2016 | 2017, 2022–2023 |
| MCBA | 2013–2014, 2017 | 2018–2019 |

These additions give IPKY 2014–2025 and MCBA 2013–2025 annual coverage across
explicitly separate scopes. GRBK has 2014–2015 and 2017–2025 across scopes.
They do not establish uninterrupted consolidated histories: the other years
are available in the separate view. GRBK's 2016 IFRS source remains unverified
after checking the catalog, issuer archive and exchange/search results.

The issuer site labels GRBK's 2023 download as consolidated, but the actual
PDF statement headings describe bank-only accounts. Its 2022 comparative
is therefore also published as separate. The short 2022 consolidated download
has unresolved unit/standard evidence and is not used to relabel those figures.

The recovery release `500f3eb6afdbac2f2f0c16e9516e57617d8ef5da` is deployed
to uzstock.uz. Public API and passport checks verified all 1,458 figures across
162 published periods, including every previous figure and all 144 additions.
All 146 previous snapshot heads remain unchanged. The release passed 167
focused backend tests; production browser checks verified both scope views
and their source passports for each of the three recovery issuers. The
post-publication backup is verified, the ingestion timer is active, and
monitoring reports no incidents or stale publications. See the
[recovery production verification](bank-ifrs-gap-live-verification-2026-09-18.json).

## OpenInfo annual attachment follow-up — 18 September 2026

The GRBK 2016 source gap above is now resolved. OpenInfo annual disclosure
3946 (bank annual object 55) links a 61-page PKF MAK ALYANS consolidated IFRS
report for 2016 through its audit-opinion attachment. The dedicated IFRS and
audit catalogs did not list this attachment. Its cover, opinion and statement
pages were inspected directly. The existing shared OCR/parser extracted all
nine figures without code changes or manually entered financial amounts.

The reviewed 2016 period is published: 163 periods / 1,467 figures total,
with all 162 previous snapshot heads preserved. Public API checks verified
the new values and passport hashes, scopes and calculation components; browser
checks confirmed the 2016 consolidated column and source passport. A verified
post-publication backup is available and monitoring is healthy.

There are no missing annual years across both views combined for GRBK
2014–2025, IPKY 2014–2025 or MCBA 2013–2025. This is a bounded coverage result
for those issuers and ranges; individual accounting scopes can still have gaps.
The discovered attachment is registered for normal refresh/reprocessing. This
follow-up does not add automatic annual-disclosure attachment crawling. See
[the OpenInfo evidence and live verification](bank-ifrs-openinfo-2016-verification-2026-09-18.json).

## Automatic annual attachment discovery

The staging cycle now checks OpenInfo annual-disclosure details for `int_report`
and `audition_result_report[].conclusion_file`. Catalog sync remembers all annual
parents, including filings excluded from NSBU value ingestion; existing catalog
export links bootstrap older records. The implementation contains no issuer,
year or financial-value exceptions.

Discovery verifies the returned issuer and filing IDs and accepts only HTTPS
OpenInfo media PDFs. Each attachment records the parent page, detail API URL,
attachment field and hash of the canonical detail response. It does not inherit
the parent filing's accounting standard, scope or financial values: the PDF must
pass extraction and review before publication.

The regular bank staging cycle makes at most eight disclosure requests per pass,
stops starting requests after sixty seconds and resumes from persistent state.
Successful checks, including empty attachment sets, are cached for seven days;
failures retry after an hour and appear in ingestion monitoring. A refresh failure
retains the last verified links. Explicit ticker discovery also supports other
issuer types. Existing publications are never changed by discovery.

Validation: 207 focused tests pass. An isolated live OpenInfo check followed all
ten GRBK annual filings in two bounded passes and found fifteen PDF URLs,
including the previously missed 2016 audit attachment. It created fetch jobs and
zero publications. The check used the normal listing and attachment parser,
without an issuer-specific PDF URL in its inputs.

Release `56b4908e2c0b05de265d013057b94385a0050f38` is deployed to uzstock.uz.
The production backfill refreshed the current listings for all fifteen banks
and checked 157 annual disclosures, registering 200 attachment URLs with no
listing or discovery errors. All 163 published snapshot heads remained exactly
unchanged; public API checks verified all 1,467 existing figures and their source
passports. New PDFs are queued for extraction and review, not automatically
published. The post-discovery backup is verified and the ingestion timer remains
active. See [production evidence](annual-attachment-discovery-live-verification-2026-09-18.json).

### Annual attachment processing and shared validation (2026-09-18)

The annual attachment backfill downloaded all 200 discovered URLs (160 unique
PDF hashes). Native extraction ran for every unique PDF; 117 additionally used
bounded local OCR. Exact copies of already reviewed originals retain their
existing public snapshots. No new financial amounts were added to the Python
code or checked-in review ledgers.

`statement-columns-v3` handles printed dot-grouped amounts, OCR bracket shapes,
additional aggregate expense/associate labels, and effective-interest income
that reconciles against a direct expense total. Profit before tax, signed tax,
and any explicitly reported discontinued result must reconcile to net profit;
ambiguous tax cells block validation. OCR retries score these checks and retain
whole-page evidence. These are shared parsing rules, not ticker branches.

Identical PDF bytes for the same issuer and extraction version reuse staged
results and attributed approvals. Changed bytes, a different issuer, or a parser
upgrade require extraction again. Workers still cannot publish automatically.
The default financial perimeter follows the newest published period, preferring
consolidated on a date tie. Both explicit views remain available, so publishing
older consolidated history cannot hide newer separate statements.

Validation: 214 focused ingestion, parser, discovery, API, evidence and financial
regression tests passed. A broader run also encountered three existing failures
in the separate `v3_financial_pipeline` module: its `INSERT OR IGNORE` statements
are rejected by `dbx`; those files were not changed by this update.

The attachment batch is deployed in releases `22ad2f6` and `dd91c14`. All 200
sources were fetched and staged. Explicit source-page review published 15 new
periods (135 figures): DRBK consolidated 2016–2022 and separate 2015–2016; IPKY
separate 2016 and 2024; SQBN consolidated 2014; ALKB separate 2014–2015; GRBK
consolidated 2023. All 163 prior snapshot heads remain unchanged. Live API checks
verified all 178 periods and 1,602 values, including every figure's source hash,
accounting scope and calculation components. The post-publication backup has 240
verified originals, and the ingestion timer is active.

At the close of that batch, IPTB separate 2015–2016, ALKB separate 2016,
and MCBA separate 2017 still needed OCR/layout work; their consolidated years are
already published. The recovered DRBK 2014 comparative contains a balance sheet
without a full income statement. SQBN 2019Q2/2020Q2 proposals remain incomplete.
The wider pipeline retains queued work and review cases. The shared parser
contains no future-year ceiling tied to this release, but changing source APIs
or report layouts can require maintenance; failed checks cannot replace public
snapshots automatically. See [the processing audit](annual-attachment-processing-live-verification-2026-09-18.json).


### Appendix discovery and remaining scan recovery (2026-09-18)

Release `867e8e5` adds shared extraction improvements: native page discovery
finds statement appendices from section headings, tiled OCR preserves page
coordinates without duplicate overlap rows, and bounded language/contrast
retries retain faint printed zero dashes. Stacked date headers preserve each
column's actual date. An interim balance title cannot silently date an
unresolved comparative column. The OCR budget remains 240 seconds and eight
refined pages; at most 32 discovered appendix pages augment the initial 16.
Native page objects are released during the bounded 500-page discovery pass.

The parser recognizes wrapped expense labels and own-funds equity totals.
Missing gross interest expense can be derived from explicitly printed gross
income and net interest before credit-loss adjustments, retaining every source
component and coefficient. A net subtotal after impairment cannot supply that
calculation. No issuer IDs, company branches or financial amounts were added
to runtime code or checked-in review ledgers. Registered issuer URLs and
reviewed database snapshots remain data, independent of these parsing rules.

Six complete periods are now published: IPTB separate 2015–2016, MCBA separate
2017, ALKB separate 2016, and SQBN consolidated 2019Q2/2020Q2. The SQBN periods
are cumulative half-years, with the 2019 balance sourced from its own interim
report rather than the December comparative in the 2020 report. ALKB's issuer
brochure was discovered at pages 79–95 and its statements read at pages
83–84/91–92. Every added figure and calculation component was visually checked.

DRBK separate 2014 now exposes four verified comparative balance figures. Its
five income fields remain absent, with a missing-data notice and `NO_DATA`
passports; no zero or estimate is substituted. The recovered 2016 attachment
contains no 2014 income statement, and the current issuer audit archive lists
2023–2025 only. A suitable historical income source has not been located.
This is therefore not a claim that every possible bank period is complete.

Validation: 211 focused tests passed, including nine new parser/layout cases.
The deployment retained all 178 prior snapshot heads and published seven new
heads containing 58 figures. Live API checks verified all 185 periods and
1,660 published values, plus each value's source hash, scope and calculation
components. Browser checks passed for all seven added periods, including the
missing-income display. All six public PDF downloads matched their stored
SHA256 hashes when checked from the production host. The post-publication
backup contains 242 verified originals;
monitoring reports no incidents, stale publications or overdue sources, and
the staging timer is active. Workers continue to require attributed review
before publication; new report formats can still require parser maintenance.
See [the gap-recovery audit](remaining-ifrs-gaps-live-verification-2026-09-18.json).

### OpenInfo-only future updates (2026-09-19)

The default `FINANCIAL_SOURCE_POLICY=openinfo` restricts new financial document
work to HTTPS documents under `openinfo.uz/media/`. Discovery skips issuer-site
records, registration and downloads reject external URLs, and the worker retires
previously queued external fetch/extraction jobs as `SUPERSEDED`. Publication
also rejects new or replacement snapshots from external sources. Attribution,
evidence validation and explicit review remain required for OpenInfo documents.

Existing issuer-site publications, values, passports and archived PDFs remain
readable. An idempotent publication of an unchanged existing snapshot is allowed.
External sources are retained in the audit history and excluded from refresh
overdue counts. The `reviewed_issuers` compatibility setting exists for historical
workflow tests; production uses `openinfo` for all future updates.

This policy changes sourcing, not data coverage: Davr separate 2014 still has
four balance figures and five unavailable income figures. It does not certify
complete coverage of every bank, period or accounting scope.

A fresh inventory of the 185 published heads found no missing intervening
annual years within each issuer's published range when both scopes are counted.
The individual views retain these intervening gaps: DRBK separate 2017–2021,
GRBK consolidated 2022, IPKY consolidated 2017–2023, and MCBA consolidated
2018–2022. Each of those years exists in the other scope; the scopes must not
be substituted for each other. This inventory does not prove that OpenInfo
has no additional filings, earlier years, or interim periods to ingest.

Validation: 214 focused tests passed. The broader v3 pipeline suite has three
existing SQL compatibility failures (`INSERT OR IGNORE` rejected by `dbx`),
reproduced on the unchanged `ca1bab4` baseline.

Production verification retained all 185 snapshot heads and checked all 1,660
live API values and their passports, including source hashes, scopes and
calculation components. No external-source jobs remain pending. The staging
timer is active; 670 jobs remain queued, 186 sources await review and 26
OpenInfo sources are due for their first/next fetch. Those operational counts
are not evidence that every available filing has already been processed.
The pre-deployment backup verified 242 originals and 185 published periods.
See [the source-policy and coverage audit](openinfo-only-live-verification-2026-09-19.json).
