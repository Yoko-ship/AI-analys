# Financial columns

The catalog financial view reads a separate, source-preserving matrix. Monetary
amounts are displayed in **thousands of UZS**; per-share amounts remain UZS.
Existing published financial APIs remain public, and catalog access remains
restricted to administrators.

## Data and publication

* NSBU workbook imports retain every physical sheet, row and cell in immutable
  `financial_form_versions`, with a current pointer per legal issuer and period.
  The existing catalog parser records these during refresh. The NSBU history
  processor's implementation digest invalidates old checkpoints for this release.
* IFRS candidates retain BS, PL/OCI, CF, equity and Notes text, exact mapped
  source rows, and explicit shareholder disclosures. They follow the existing
  validation, review and publication process. A new parser version does not
  silently replace an approved publication.
* The API performs no downloads. Earlier headline-only publications remain
  available in the expandable legacy view while original forms are imported.
* Unreadable scans, ambiguous columns, unresolved units/scope and missing Notes
  remain visibly incomplete. OCR availability and the existing bounded OCR job
  determine recovery; extraction is not a promise that every PDF was readable.

The existing production history job should run with `--nsbu-history` after
deployment. For a bounded manual backfill, use the existing command:

```sh
python -m financial_ingestion.nsbu_history --ticker ALKB --max-periods 20
```

Use the established IFRS worker's propose, approve and publish workflow to
upgrade older snapshots. Inspect candidates and original pages before replacing
published figures. Missing ratio bases are not filled with estimates.

## Calculation contract

* FY, standalone Q, interim YTD and TTM have distinct period semantics. TTM
  requires matching current YTD, prior YTD and prior FY. A stock remains tied to
  a reporting date. EPS is not additive. A conflicting reported quarter and YTD
  calculation are blocked.
* Scope, legal issuer and insurance accounting model are kept separate. Legacy
  insurance and IFRS 17 require explicit policy evidence rather than a year rule.
* ROE/ROA use matching opening/closing bases. NIM requires interest-earning
  assets; CoR requires the matching loan portfolio. Bank CIR uses income before
  credit losses. ROCE needs an explicit NOPAT/invested-capital policy. Combined
  insurance ratios require expenses explicitly excluding claims.
* NSBU interest-bearing debt uses F1 570 + 580 + 730 + 740 + 750. Total
  liabilities are not substituted for debt. Construction or PPE movement is
  not cash CAPEX. NAV per share is restricted to UZNF with verified share counts.
* Zeros, missing cells, dashes and crossed cells retain their meaning. Source
  reconciliation checks flag differences without rewriting the source totals.
* OpenInfo-published ratios remain separate from UZStock calculations.

## Interfaces

`GET /api/company/{ticker}/financials/columns` accepts `form=NSBU|MSFO`,
`scope=separate|consolidated|unknown`, `freq=annual|quarter|interim`, and
`view=full|template|overview` (default `full`). The terminal requests
`view=template`: only the fields listed in the supplied
`UZStock_Financial_Terminal_NSBU_IFRS_Corrected.html` are displayed, in that
reference’s sector/standard order. `reference_fields.json` records all twelve
field lists and explicit source-form/code/metric selectors. Its `overview_rows`
follow the HTML overview's first eight fields per section, in their exact order,
with placeholders for undisclosed fields. HMKB NSBU therefore has 24 overview
rows. Multiple source components share one display row but retain separate
amount buttons and passports; no total is invented. The longer reference list
is available under Original forms. Overview exports request `view=overview` and
retain each component's source code and amount as separate export records.
Table values and passports remain unchanged. Unavailable fields are not inferred, and an empty selection
does not fall back to an unrestricted table. Raw imports remain accessible via
the full API for audit. The reference’s bank tax label is matched to the actual
verified income-tax field (9а), not the unrelated adjustment at its demo code 10а.
The `.csv` and `.xlsx` routes export period, accounting context, source code,
source location/version, quality and formula, including published ratios and
shareholder evidence. The normal v2 aliases are registered too.

The interface includes original forms, source passports, calculation inputs,
history charts, shareholders and data-quality explanations. The new module
contains no fair-value model, DCF or forecast.

## Verification

Tests cover actual ALKB, IPTB, KFSK, UZAL and UZTL workbook layouts, a damaged
HMKB PDF text layer, period and scope boundaries, namespace collisions,
source versioning, API/export persistence and the rendered desktop/mobile flow.
Real PDF checks also found scanned or damaged pages in HMKB, KVTS and UZAL;
these need OCR and review rather than invented numeric recovery.
