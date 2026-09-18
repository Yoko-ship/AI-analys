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
python -m financial_ingestion.worker register-source --ticker TICKER \
  --url https://issuer.example/reports/annual.pdf \
  --source-page https://issuer.example/investors \
  --actor REVIEWER --reason 'Verified official issuer source and identity'
```

The page and PDF must share a public HTTPS origin. Registration is attributed;
downloads remain size-bounded and reject redirects. Registered sources participate
in refresh and parser-version reprocessing. Registration does not approve figures.
This is source registration, not an automatic crawler of every issuer website.

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
