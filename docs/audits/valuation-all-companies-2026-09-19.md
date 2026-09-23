# All-company P/E and P/B check — uzstock.uz

Checked: 2026-09-19T11:01:16.448Z

Checked all **100 share listings across 68 companies**: 89 active and 11 inactive. Every equity on the live market board and in the securities catalog is covered; bonds do not use P/E or P/B.

**Result:** no remaining inactive-preferred-share blockers, no arithmetic discrepancies against published inputs, and no differences between the live market table and its API.

This checks the deployed inclusion rule and published inputs. It does not independently verify the source financial statements. A calculated ratio is not a claim that all underlying financial data has been audited.

## Companies affected by the preferred-share fix

| Company | Excluded preferred | P/E | P/B |
|---|---|---:|---:|
| GRBK | GRBKP | 196.80 | 14.71 |
| IPKY | IPKYP | 13.88 | 2.62 |
| KSCM | KSCMP | 52.70 | 0.12 |
| PLST | PLSTP | 30.34 | 10.39 |
| QATT | QATTP | 19.01 | 0.84 |
| UZAL | UZALP | 52.73 | 1.62 |

## Remaining limitations

- 40 companies have both P/E and P/B with status `ok`.
- 11 companies lack a usable ordinary-share price: AGMK, DRBK, FRAZ, MXUS, OCBK, ORFI, TGBK, UTHK, UZGF, UZIN, UZNG. DRBK, OCBK and ORFI have prices older than 90 days; the other eight lack a verified trade price.
- Other warnings concern losses, missing or unverified financial data, or ratios outside configured ranges. These warnings were retained.
- GRBKP has a separate P/E audit block (`audit_blocked`); the ordinary GRBK row has P/E 196.80. This is not a preferred-share capitalization gap.

## Every company

Values below are the published ratio when status is `ok`. For other statuses, the status is shown; the CSV contains any warning-associated numeric candidate and the actual browser text.

| Company | Share listings | P/E | P/B |
|---|---|---:|---:|
| AGBA | AGBA, AGBAP | 41.78 | 0.48 |
| AGMK | AGMK, AGMKP | no_market_cap | no_market_cap |
| ALKB | ALKB, ALKBP | 11.11 | 0.66 |
| ALSM | ALSM, ALSMP | loss_making | 1.41 |
| BECM | BECM, BECMP | loss_making | 1.25 |
| BIOK | BIOK | 7.07 | 0.66 |
| BNGP | BNGP, BNGPP | 166.61 | 2.36 |
| BRBN | BRBN, BRBNP | 15.84 | 1.13 |
| BTRL | BTRL | 34.31 | 3.86 |
| CBSK | CBSK | 6.98 | 1.82 |
| DORI | DORI | loss_making | 0.78 |
| DRBK | DRBK | no_market_cap | no_market_cap |
| EQQU | EQQU | 5.74 | 0.39 |
| FRAZ | FRAZ, FRAZP | no_market_cap | no_market_cap |
| GRBK | GRBK, GRBKP | 196.80 | 14.71 |
| HMKB | HMKB, HMKBP | 6.70 | 1.63 |
| INFB | INFB | no_financials | no_financials |
| IPKY | IPKY, IPKYP | 13.88 | 2.62 |
| IPTB | IPTB, IPTBP | 6.37 | 1.46 |
| JASM | JASM | 15.84 | 1.71 |
| KASU | KASU, KASUP | 63.67 | 3.12 |
| KFSK | KFSK, KFSKP | out_of_range | out_of_range |
| KSCM | KSCM, KSCMP | 52.70 | 0.12 |
| KVTS | KVTS | 5.99 | 1.32 |
| MCBA | MCBA, MCBAP | 35.82 | 1.16 |
| METQ | METQ | 6.78 | 1.75 |
| MIQE | MIQE | 32.28 | 1.22 |
| MXUS | MXUS | no_market_cap | no_market_cap |
| NGQS | NGQS | out_of_range | 1.93 |
| OCBK | OCBK | no_market_cap | no_market_cap |
| OHDN | OHDN | 11.82 | 0.74 |
| ORFI | ORFI, ORFIP | no_market_cap | no_market_cap |
| ORGS | ORGS | 2.30 | 0.34 |
| PLST | PLST, PLSTP | 30.34 | 10.39 |
| QATT | QATT, QATTP | 19.01 | 0.84 |
| QZSM | QZSM | 20.65 | 0.22 |
| SANE | SANE | 179.02 | 8.25 |
| SQBN | SQBN, SQBNP | 4.60 | 0.77 |
| TGBK | TGBK | no_market_cap | no_market_cap |
| TGPG | TGPG | unverified | out_of_range |
| TKDM | TKDM, TKDMP | loss_making | 0.35 |
| TMYS | TMYS | 5.03 | 0.99 |
| TNBN | TNBN, TNBNP | 69.60 | 1.06 |
| TRSB | TRSB, TRSBP | 18.84 | 4.57 |
| UNVB | UNVB | 6.39 | 1.68 |
| UPOS | UPOS, UPOSP | out_of_range | 2.34 |
| UQEQ | UQEQ | 2.64 | 1.25 |
| URTS | URTS | 10.89 | 7.69 |
| UTGA | UTGA, UTGAP | 33.98 | out_of_range |
| UTHK | UTHK | no_market_cap | no_market_cap |
| UTYK | UTYK | 12.49 | 5.55 |
| UVGT | UVGT | 153.71 | out_of_range |
| UZAL | UZAL, UZALP | 52.73 | 1.62 |
| UZAS | UZAS, UZASP | 250.65 | out_of_range |
| UZGF | UZGF, UZGFP | no_market_cap | no_market_cap |
| UZHM | UZHM | loss_making | 2.60 |
| UZIN | UZIN, UZINP | no_market_cap | no_market_cap |
| UZIR | UZIR, UZIRP | out_of_range | 2.10 |
| UZMK | UZMK, UZMKP | 8.15 | 0.74 |
| UZML | UZML | unverified | 19.85 |
| UZMT | UZMT | 4.13 | 0.99 |
| UZNF | UZNF | 24.53 | 1.15 |
| UZNG | UZNG | no_market_cap | no_market_cap |
| UZNGP | UZNGP | no_financials | out_of_range |
| UZPN | UZPN | 3.37 | 0.21 |
| UZTL | UZTL, UZTLP | 10.45 | 4.70 |
| YGSY | YGSY | loss_making | 0.76 |
| YRFS | YRFS | 9.05 | 4.92 |

## Evidence

- [Live market table](https://uzstock.uz/market)
- [Live multiples API](https://uzstock.uz/api/market/multiples)
- [100-listing CSV with inputs, statuses and browser values](valuation-all-companies-2026-09-19.csv)
- [Machine-readable audit](valuation-all-companies-2026-09-19.json)
