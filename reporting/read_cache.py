"""Reuse completed reports while their saved inputs and review decisions agree."""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock
from time import monotonic
import os

import dbx
import issuer_financials as financials
import securities_catalog
from admin_control import rules
from catalogue.storage import _catalog_db_path
from collectors.openinfo import cache, settings
from financial_analysis.sector_numbers import digest
from . import store

CONFIG_DIR = Path(__file__).resolve().parents[1] / 'config'
_entries = OrderedDict()
_lock = RLock()
_build_locks = [RLock() for _ in range(32)]


def get_or_build(issuer, standard, period, scope, lang, build):
    # File revisions cover SQLite writers in other processes, including imports.
    # PostgreSQL needs a database revision feed before it can use this shortcut.
    if dbx.backend() != dbx.SQLITE:
        return build()[0]
    key = digest([issuer, standard, period, scope, lang,
                  os.getenv('SECTOR_ANALYSIS_DB'), os.getenv('ADMIN_CONTROL_DB')])
    with _build_locks[int(key[:8], 16) % len(_build_locks)]:
        revision = _revision(issuer, standard, scope, lang)
        with _lock:
            entry = _entries.get(key)
            if entry and entry[0] == revision and monotonic() < entry[1]:
                _entries.move_to_end(key)
                return deepcopy(entry[2])
        report, complete = build()
        # Never label an old result with inputs that changed during preparation.
        if complete and revision == _revision(issuer, standard, scope, lang):
            with _lock:
                _entries[key] = (revision, monotonic() + 300, deepcopy(report))
                _entries.move_to_end(key)
                while len(_entries) > 128:
                    _entries.popitem(last=False)
        return report


def _revision(issuer, standard, scope, lang):
    workbook = cache._excel_cache_file()
    paths = [workbook, workbook.with_name(workbook.name + '.filings')]
    for database in (_catalog_db_path(), securities_catalog.DB_PATH):
        paths.extend(Path(str(database) + suffix) for suffix in ('', '-wal', '-journal'))
    paths.extend(sorted(CONFIG_DIR.glob('*.json')))
    partition = standard if scope != 'consolidated' else f'{standard}/consolidated'
    with store.connect() as connection:
        holds = [dict(row) for row in connection.execute(
            'SELECT * FROM sector_publication_holds WHERE issuer_id=? AND language=? AND standard=?',
            (str(issuer['id']), lang, partition)).fetchall()]
        overrides = [dict(row) for row in connection.execute(
            'SELECT * FROM sector_overrides WHERE issuer_id=? ORDER BY version',
            (str(issuer['id']),)).fetchall()]
    return digest([financials.now().date().isoformat(), [_stamp(path) for path in paths],
                   settings.EXCEL_PARSER_VERSION, settings.EXCEL_CACHE_TTL_SECONDS,
                   rules.active(), holds, overrides])


def _stamp(path):
    try:
        stat = path.stat()
        return str(path.resolve()), stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    except FileNotFoundError:
        return str(path.resolve()), None
