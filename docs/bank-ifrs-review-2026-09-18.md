# Bank IFRS review — 18 September 2026

The checked-in release contains **139 periods and 1,251 figures across 15 banks**.
The source review covers the available catalog history from 2014 through 2025,
with issuer originals filling missing SQBN, MCBA, IPTB and HMKB reports.
Every published figure retains the PDF URL, SHA-256, physical PDF page, literal
label, raw value, currency/unit scale, reporting year and primary/comparative role.
Calculated totals retain all components and signed coefficients.

## Coverage

| Ticker | Accounting scope | Annual years | Interim period ends |
| --- | --- | --- | --- |
| AGBA | consolidated | 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |
| ALKB | consolidated | 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |
| BRBN | consolidated | 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |
| DRBK | separate | 2022, 2023, 2024, 2025 | — |
| GRBK | consolidated | 2014, 2015, 2024, 2025 | — |
| HMKB | consolidated | 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |
| IPKY | consolidated | 2014, 2015, 2024, 2025 | — |
| IPTB | consolidated | 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |
| MCBA | consolidated | 2015, 2016, 2023, 2024, 2025 | — |
| OCBK | separate | 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |
| SQBN | consolidated | 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | 2024-06-30 |
| TNBN | consolidated | 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |
| TNGB | separate | 2020, 2021, 2022, 2023, 2024, 2025 | — |
| TRSB | consolidated | 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | 2019-06-30, 2018-06-30 |
| UNVB | separate | 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025 | — |

## Source gaps and exclusions

[Document dispositions](bank-ifrs-source-exclusions-2026-09-18.json) identify
excluded or incomplete sources by URL and hash. Missing values remain missing.
The inspected catalog does not supply compatible complete statements for GRBK
2016–2023, MCBA 2017–2022, or IPKY 2016–2023. Bank-only MCBA/IPKY reports are
not merged into their consolidated histories. ALKB's older bank-only reports
also do not extend its consolidated history before 2016.

DRBK's available reviewed history starts in 2022; BRBN and SQBN start in 2015.
UNVB's 2016 catalog attachment is an audit opinion without financial statements;
its complete reviewed history starts in 2017. TNGB's inaugural 2019 reporting
period begins on 18 May, so it is excluded from the calendar-year series.
These are limitations of the inspected sources and supported periods, not claims
that no additional historical documents exist elsewhere.

## Material review decisions

- MCBA 2024 uses the issuer's original audit to restore operating/net income and
  correct the erroneous 2025 comparative interest expense. The ledger explicitly
  records the previous source hash and corrected amount. Its 2023 operating
  income is calculated from individual lines because the pretax subtotal is misprinted.
- SQBN 2025 and IPTB 2025 come from issuer originals. SQBN's 2023 report also
  supplies three annual columns with explicit restatement roles.
- TRSB 2018/2019 catalog reports are half-year statements. Their primary columns
  publish as Q2 cumulative periods. The 2019 report's comparative income header
  explicitly covers the full 2018 year, so it supplies the separate annual 2018 record.
- TNBN's catalog 2022 PDF actually reports 2021; IPKY's catalog 2023 PDF reports
  bank-only 2022. Statement dates take precedence over catalog labels.
- Original historical statements remain identified as reported in their source.
  An opening balance restatement without the corresponding complete annual
  income statement is not spliced into an older annual record.
- Some older statements report non-interest expenses including other impairment
  charges. Their literal subtotal and this inclusion are recorded in the ledger.

## Release verification

The 105 focused ingestion, recovery, IFRS and bank-history tests pass. All prior
55 reviewed periods remain unchanged by this historical extension. An isolated
publication rehearsal verified all 139 periods and 1,251 figures.

Production release `21c6a43cc75cc80bcccd4622721f1fb29eecea49` was deployed via SSH
on 18 September 2026. An upstream non-200 response stopped the initial PDF
prefetch before publication. The 84 already-reviewed originals were then
transferred to production, checked against the ledger SHA-256 values, and
published after a verified backup. Redirect restrictions remain in place.

At 12:19 UTC, every public annual/interim value and all 1,251 source passports
matched the ledger. Browser checks confirmed the IPTB 2025 and MCBA 2024 tables
and source dialogs. The application health check and ingestion monitor passed;
the scheduled ingestion timer is active. Unprocessed catalog sources remain
staged and do not change the reviewed publication.

[Production verification](bank-ifrs-live-verification-2026-09-18.json) records
the deployed image, verified backup, coverage, public checks and browser checks.
The prior full backend run had 15 unrelated failures reproduced on its baseline;
those do not affect the 105 passing focused checks.
