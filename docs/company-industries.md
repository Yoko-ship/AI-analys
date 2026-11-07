# Company industry organization

The company directory at `/issuers` follows section → subgroup → issuer →
share class. Its baseline is the user-provided `UZStock_OKED_tree-1.pdf`,
reviewed on 2026-11-07: 69 issuers, 102 securities, 8 sections and 29 subgroups.
Subgroups are navigation categories, not additional official OKED levels.

`config/company_industries.json` is the single display registry used by Python
and the frontend. Each issuer records explicit ticker membership, a subgroup,
the PDF page, an optional OKED code, verification status and source notes.
`aliases` joins catalog names to exchange tickers (TNGB → TGBK) without adding
a security. Do not infer an issuer by removing a trailing P: BNGP is an ordinary
share, and BNGPP is its preferred class.

## Evidence and corrections

- `documented`: the PDF provides the code; registration was not independently
  verified. There are 16 such issuer rows.
- `inferred`: the PDF groups by business activity without a confirmed code.
- `verified`: a source was checked and linked. UZGF / UZGFP use 71120 from
  [UZSE](https://uzse.uz/reports/3286/financial), so geophysics sits in M rather
  than the PDF's mining section B. This verifies the cited disclosure, not a
  guarantee that registration has never changed.
- `conflict`: sources disagree. ORGS is provisionally in F / electrical
  installation using 43210 in its
  [2025 disclosure](https://openinfo.uz/media/msfo/7ea36ac7-22cf-48a2-aac8-1894e1e4ea72.pdf),
  while the PDF puts it in M / engineering. Its registration needs verification.
- CBSK remains provisionally in G / trading complexes. Legacy OKONH 83200 is
  not an OKED code. Trade versus real estate remains unresolved.

The two corrected subgroups move with their issuers; totals remain 8 sections
and 29 subgroups. UI notes and evidence links distinguish all of these states.

## Updating the registry

Add an issuer's actual tickers and its existing/new subgroup to the registry.
Record the evidence and use `inferred` or `conflict` until the classification
has been checked. Supply Russian, English and Uzbek labels for new groups,
sections and notes. An alias must target an existing ticker, not another alias.
Do not add speculative share classes. New catalog companies absent from the
registry remain visible in an unclassified subgroup.

The securities endpoint overlays `industry_classification` on read, so a
collection rerun or database rewrite is unnecessary. The instrument catalog,
heatmap, market filters, previews and company headers use this display grouping.
Legacy `securities.sector` is preserved for financial-template compatibility;
display classification must not change financial formulas or accounting rules.
The client bundles the same registry, and Docker copies it into the frontend
build stage. Registry changes require a normal application release.

Search matches names, all share tickers, aliases and ISINs; a match keeps the
issuer's share classes together. Each share retains its own price and turnover.
Missing prices remain missing. PDF issuers without current quotes still appear.

## Verification

Run backend and frontend suites, then build and run the feature browser checks:

```sh
python -m pytest -q
npm run test:unit
npm run lint
npm run build
npm run test:e2e -- e2e/industry-directory.spec.js e2e/heatmap-metrics.spec.js e2e/company-preview.spec.js
```
