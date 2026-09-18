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
