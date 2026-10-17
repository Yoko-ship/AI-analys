# Catalog terminal — requirements

Source: «ТЗ: терминал каталога UZStock с логированием» (14.10.2026, amended
15.10.2026, 21 pages). Visual reference: `UZStock_terminal_TZ_maket.html`
(15.10), sent with the ТЗ.

## How to read this

The ТЗ states **intent**, not an implementation spec. Its author did not know
what the server already does, so where it says "create an API", "load X" or
"add a check", the capability often exists already under another name, in
another module, or as a partial version. Every requirement here is therefore
written as:

- **Intent** — what the customer wants to be true, in one or two lines.
- **Already there** — what the codebase does today, with `file:line`.
- **Gap** — what is actually missing.
- **Approach** — how to close the gap by extending what exists, not by
  building a parallel copy.

Status per requirement: **EXISTS** (only wiring/UI left), **PARTIAL**
(logic exists, needs extending or moving), **MISSING** (new work).

The codebase survey behind these files was done 2026-10-17 on commit
`68eafe6`. Re-check the `file:line` references before relying on them.

## Files

| File | Covers ТЗ tasks |
|---|---|
| [01-terminal-ui.md](01-terminal-ui.md) | Command line, navigation, screens, export, panels, сум/$ — T-09…T-12, T-19, T-24 |
| [02-data.md](02-data.md) | Empty files, duplicates, quarantine, backfill, quarters, IFRS, caps/dividends, insurers — T-01…T-06, T-16, T-28 |
| [03-analysis.md](03-analysis.md) | Verdict, annualising, ratio names, bank/company/fund/insurer sets, CAGR, templates, FV — T-07, T-08, T-17, T-18, T-20, T-26, T-27 |
| [04-logging-admin.md](04-logging-admin.md) | Event journal, admin «Терминал», alerts — T-13…T-15 |
| [05-cbu-data.md](05-cbu-data.md) | CBU bank tables, rates, FX archive, SDMX — T-21…T-23, T-25 |

## What the customer wants (short)

1. `/catalog` becomes a Bloomberg-style terminal: type `TICKER FUNC` and press
   Enter (`SQBN FA` opens the bank's financials within 2 s; `SQBN DQ` shows
   the problems in its data). This is fundamental analysis only, with no
   quotes or price charts.
2. Every user action and every data error goes into one journal, which the
   PM reads in the admin panel without developers.
3. The work is accepted when every task is «Принято» against its acceptance
   column, and the terminal logs no «Критично» error for 7 days on the live
   site.

## Order

The ТЗ orders the stages as data → analysis → terminal → control. We change
one thing: the **journal (T-13) goes first**. Every later task emits
events into it (load_empty, value_quarantine, cmd_run…), and building it
last would mean coming back to wire every task again.

1. Journal skeleton + `emit_event()` (04).
2. Data fixes at load time (02).
3. Terminal shell on the existing endpoints (01). This alone makes
   `SQBN FA` / `SQBN DQ` work end to end.
4. Analysis gaps (03) and CBU data (05).
5. Admin «Терминал» screens and alerts (04).

## Open decisions (need the customer)

| # | ТЗ says | What we have / why it matters |
|---|---|---|
| D1 | P/E > 100 prints «>100» (data rule 11) | Since 2026-08-12 the customer-approved practice is «н/зн» for out-of-range multiples, with the value in a tooltip; the range today is `pe_range [0.1, 300]` (`config/thresholds.json:43`). Pick one rule for the whole site. |
| D2 | History starts at 2020 annual / 2022 quarterly | We hold filings back to 2015. Proposal: the terminal *defaults* to 2020+ and the data stays. |
| D3 | Missing year → take the next report's «прошлый год» column (rule 3) | The NSBU **bank** form prints no comparative column, so this rule cannot fill bank years. It works for non-banks only. |
| D4 | Quarantine: profit/equity > 1.5× assets or a 20× jump (rule 5) | Must not hide extremes that are faithful to the filing (UZIR, GRBK multiples). The thresholds must be measured on real data before switching on (see 02, R-D3). |
| D5 | Verdict: risk **high** → «Требует внимания» (rule 8) | `financial_analysis/sector_verdict.py` sends only a high *red flag* there; a high *risk* signal caps at «Смешанно». Confirm which "high" is meant. |
| D6 | UZINP as «6th insurer» (T-28) | UZINP is a **preferred** share class. The insurer is its issuer, which is not a separate company. |
| D7 | Fund P/NAV for UZNF | Blocked today until the share basis is reconciled (`SHARE_BASIS_NOT_RECONCILED`). Confirm which share count is authoritative. |
| D8 | HDS (owners ≥5%, board) | Deferred in the ТЗ itself; out of scope. |
