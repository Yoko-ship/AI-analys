"""Preserve original worksheet coordinates for IFRS filing review."""
from datetime import date
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from openpyxl import load_workbook

MEDIA_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def check_package(content):
    if not content.startswith(b'PK\x03\x04'):
        raise ValueError('Source did not return an XLSX workbook')
    try:
        with ZipFile(BytesIO(content)) as package:
            entries = package.infolist()
            if len(entries) > 4096 or sum(e.file_size for e in entries) > 100 * 1024**2:
                raise ValueError('IFRS workbook exceeds the extraction limit')
            if ('xl/workbook.xml' not in package.namelist() or
                    b'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
                    not in package.read('[Content_Types].xml')):
                raise ValueError('Source did not return an XLSX workbook')
    except (BadZipFile, KeyError) as exc:
        raise ValueError('Source did not return an XLSX workbook') from exc


def draft(content):
    check_package(content)
    workbook = load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)
    evidence = []
    try:
        if not 1 <= len(workbook.worksheets) <= 500:
            raise ValueError('Invalid IFRS worksheet count')
        remaining = 250000
        for sheet in workbook.worksheets:
            cells = {}
            # Read the XML rows even when a producer forgot to set the dimensions.
            sheet.reset_dimensions()
            for row in sheet.iter_rows():
                remaining -= max(1, len(row))
                if remaining < 0:
                    raise ValueError('IFRS workbook exceeds the extraction limit')
                for cell in row:
                    if cell.value is not None:
                        cells[cell.coordinate] = cell.value.isoformat() if isinstance(cell.value, date) else str(cell.value)
            evidence.append({'sheet': sheet.title, 'cells': cells})
    finally:
        workbook.close()
    # Spreadsheet columns can be chronological, reverse chronological, or a mix
    # of date balances and extended flow periods. Preserve them for review.
    return {'classification': {}, 'figures': {}, 'worksheet_evidence': evidence,
            'extraction': {'format': 'xlsx', 'sheet_count': len(evidence)}, 'page_count': len(evidence)}
