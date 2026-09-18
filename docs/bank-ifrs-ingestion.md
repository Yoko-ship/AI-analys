# Bank IFRS recovery

NSBU workbooks and IFRS PDFs are independent sources. The generic OpenInfo
indicator feed is not an IFRS fallback. Bank IFRS also has interest income and
interest expense, not an industrial revenue/gross-profit presentation.

`ifrs_financials.py` publishes the reviewed PDF ledger in
`ifrs_reviewed_financials.json`. It verifies the current source bytes against
SHA-256 before every import, checks the issuer's catalog URL, year columns,
page bounds, currency, signed expenses and balance identity, and records
original amounts, units, page numbers and labels in source passports.
Storage remains thousands of UZS; passports retain the PDF's actual scale.

The initial recovery contains nine figures for each of BRBN's seven available
annual documents: 2016, 2018, 2019, 2021–2024. The 2019 PDF is mislabelled 2020
in OpenInfo's listing; the reviewed statement year is preserved during sync.
Comparative columns are not published as standalone annual filings. No revenue,
gross profit, quarterly IFRS or NSBU-derived ratios are invented.

## Verify and apply

Run inside the deployed image with the persistent `/app/data` volume mounted:

```sh
python ifrs_financials.py --ticker BRBN
python ifrs_financials.py --ticker BRBN --apply
```

The default is read-only verification. `--apply` writes the catalog. Back up
`reports_catalog.db` first. The persistent bank-history job also reapplies
matching reviews after discovery. Failures are logged and mark the run partial.
Imports are idempotent and never write NSBU rows.

## Extending coverage

1. Discover the issuer's MSFO documents using the existing catalog sync.
2. Download the actual PDF. Extract text with pdfplumber where usable; render
   and visually inspect statement pages when scanned or when its text layer is
   corrupt. BRBN 2024/2022/2019 are scans; 2018/2016 have unreliable OCR layers.
3. Verify issuer identity, consolidated perimeter, annual year, currency and
   unit declaration. Select the current-year column, not notes or comparatives.
4. Add a ledger entry with SHA-256, file-page count, literal signed decimal
   amounts, one-based PDF page numbers, exact row labels and evidence notes.
5. Run verification and tests, then apply to the persistent catalog. Check the
   public annual MSFO response and passports against the PDF, including units.

This is a reviewed recovery pipeline, **not an unattended OCR parser**. Other
banks and newly filed PDFs remain unparsed until reviewed. A missing review is
not evidence that OpenInfo lacks the report. If a PDF changes at the same URL,
the old review is rejected; re-inspect it before updating the hash. Never change
the hash alone to bypass this safeguard.
