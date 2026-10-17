# 05 — Central Bank (CBU) data

ТЗ tasks: T-21, T-22, T-23, T-25. Out of scope: payment-system statistics,
MFO and pawnshop data (deferred for bonds), the PDF bulletin.

## R-C1 Monthly bank tables (T-21, T-22) — MISSING

- **Intent:** load the monthly «показатели банковской системы» Excel tables
  (state on the 1st of each month, in bn сум) from January 2020:
  - NPL per bank (portfolio, NPL, NPL share);
  - bank assets, loans, equity and deposits, and market shares;
  - loans and deposits split into individuals and legal entities;
  - sector capital adequacy, liquidity (LCR/NSFR) and profitability.
- **Mapping:** a «CBU name → ticker» table for the 17 listed banks (AGBA,
  SQBN, BRBN, MCBA, ALKB, TNBN, IPTB, HMKB, IPKY, ORFI, DRBK, INFB, TRSB,
  TNGB, OCBK, UNVB, GRBK). Unlisted banks are used only for medians and
  market shares.
- **Display rules:** CBU sector numbers are shown as a «bank vs sector»
  reference, never as the bank's own figure. CBU data (1st of the month)
  and NSBU data (quarter end) always carry their date and source and are
  never summed together. NPL > 5% gets a flag (BRBN, GRBK and MCBA as of
  01.09.2026).
- **Acceptance:** NPL share and market share on 01.09.2026 equal the CBU
  files for all 17 banks.
- **Already there:** nothing for these tables. CBU access already exists in
  `server/currency/routes.py` (JSON rates) and `gov_bonds_collector.py:163`
  (key rate off the front page).
- **Approach:** a collector beside the existing ones. Locate each table by
  its **header titles**, not by fixed cell positions (as the bond auctions
  parser does). If a header is missing, emit `load_format_changed`
  (Критично) and load nothing. Keep the name map as data, with a test that
  fails when a listed bank has no mapping.

## R-C2 Average deposit/loan rates (T-23) — MISSING

- **Intent:** monthly average rates on deposits and loans, in sum and in
  foreign currency, from 2019 (acceptance: August 2026 term deposits 17.2%,
  loans 21.9%).
- **Use:** dividend yield and E/P against the deposit rate (DVD, EQS);
  the cost of debt for company interest coverage; a bank's spread against
  the market.
- **Approach:** the same collector pattern as R-C1, or SDMX (R-C4) if that
  series is published there.

## R-C3 CBU exchange-rate archive (T-23) — PARTIAL

- **Intent:** the official rate on any date (acceptance: USD on any date
  equals CBU's figure).
- **Already there:** `/api/currency/rates` serves **today's** USD/EUR/RUB
  only, cached for 30 minutes (`server/currency/routes.py:25,45-93`). The
  CBU JSON API itself serves any date.
- **Gap:** no stored history and no by-date lookup.
- **Approach:** add an `as_of` parameter to the existing currency module,
  backed by a small table filled from the CBU archive (year ends and
  period ends at minimum). Do not create a second currency service. This
  unblocks the сум/$ toggle (01 R-U7) and CAGR in $ (03 R-A6).

## R-C4 SDMX sector series (T-25) — MISSING

- **Intent:** load sector series automatically from CBU SDMX/XML (financial
  soundness indicators, rates, loans by industry for company context), so
  that the sector references update themselves every month.
- **Approach:** prefer SDMX over Excel wherever a series exists in both, as
  the ТЗ suggests (its format is more stable). This can replace part of R-C1
  and R-C2 later.

## R-C5 Valuation parameters from CBU (feeds 03 R-A11)

- Policy rate (14%, decision of 16.09.2026, next meeting 28.10); inflation
  by year: 11.1 · 10.0 · 12.3 · 8.8 · 9.8 · 7.3 for 2020–2025, and 6.4 for
  September 2026. These are entered in ADM as parameters with their source
  and date, refreshed after each CBU meeting and monthly. The Damodaran
  inputs (8.89% equity risk premium, 3.06% default spread) are refreshed in
  January and July.
