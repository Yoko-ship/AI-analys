# Value quarantine: measurement for review (T-03, decision D4)

D4 (customer, 2026-10-17): measure the quarantine rules over the stored
history first, review what they would hide, and only then switch them on.
**Nothing below is switched on yet.**

The measurement covers every series production served on 2026-10-17:
- 70 issuers;
- annual NSBU, annual MSFO and quarterly NSBU;
- 3,373 balance periods.

Every hit is in `quarantine-measurement-2026-10-17.csv`, with the ticker,
period, field, value, assets, both neighbours, the rule that fired and a
judgement. Only balance-total hits and the named cases were checked one by
one; flow and cash hits are judged by category.

## The two named cases: causes

| Case | What the filing says | Why we showed it |
|---|---|---|
| **KVTS 2020**: equity −1.268e20 | Report 3758, line 770 (total liabilities): the issuer typed the opening (126,803,840) and the closing (559,840,271) into ONE cell, giving 1.268e17. The closing cell is 0. Lines 780 and 480 are correct. | The parser reads liabilities with a fallback to the opening column when the closing one is 0, and derives equity as assets − liabilities. So the glued cell went into liabilities and, through the identity, into equity. |
| **ODMP 2020–21**: net profit 888bn and 792bn against assets of about 8bn | Reports 3606 and 3932: the header says «тыс.сум», but form 2 was filed in sums while the balance is in thousands. The change in retained earnings (line 450) is +767m sums, which fits a profit of about 888m, not 888bn. | We apply one unit to the whole filing. |

## How each candidate rule performs

Counts are distinct ticker-periods. There are 21 bad ticker-periods across
12 issues in total.

| Rule | Hits | Real errors | Not errors | Errors missed |
|---|---|---|---|---|
| (a) \|profit\| or \|equity\| > 1.5 × assets | 13 | 12 | 1 (UZNF 2025Q1, a fund's first quarter) | 9 |
| (b) > 20× both neighbours, every money line | 63 | 9 | 54 (mostly cash on a tiny base) | 12 |
| (b) > 20× both neighbours, balance totals only | 7 | 6 | 1 | 15 |
| (b) > 20× either neighbour | 629 | 17 | 612 | 4 |
| (a) + (b) both neighbours, balance totals | 18 | 16 | 2 | 5 |

A 20× rule on flows would hide real extremes that the filings themselves
confirm:
- MCBA 2017 loss of −88bn and MCBA 2024 loss of −1.7trn;
- UPOS 2018 loss of −27.8bn;
- UZNGP 2016 one-off income of 911bn;
- UZNGP 2017Q4, IPTB 2024Q2 and GRBK 2018.

## Recommendation for the customer to approve

1. **Switch on (a) as the ТЗ states it**: profit or equity above 1.5 × assets
   is quarantined. It caught 12 of the 13 periods it flagged.
2. **Switch on (b) only for total assets, equity and liabilities**, and only
   when the value is more than 20× away from BOTH neighbours. Not for profit,
   revenue, expenses or cash, where it would mostly hide real figures.
3. **Primary gate (new, in the parser):** the form's own arithmetic, by line
   code. It names the wrong cell instead of guessing, and covers KVTS, CBSK,
   BECM, AGBA, IPKY, PLST, METQ, UZHM and ODMP:
   - 400 = 780 and 780 = 480 + 770;
   - the opening balance equals the prior period's closing balance;
   - net profit (line 270) against the change in retained earnings (line 450)
     catches a form 2 filed in sums.

   (a) and (b) then serve as a backstop.
4. **No exemptions for banks, funds or negative-equity issuers.** None of the
   real errors needed one, and none of their real extremes crossed (a).

A quarantined value is not shown; it is written to the journal as
`value_quarantine` (Критично) with the filing link, and the coverage matrix
shows the cell red.
