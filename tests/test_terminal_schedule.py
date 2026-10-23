from datetime import date
from pathlib import Path


def test_daily_refresh_checks_late_previous_month_and_current_month():
    from scripts.terminal_cbu_sync import refresh_months
    assert list(refresh_months(date(2026,1,5)))==[(2025,12),(2026,1)]
    assert list(refresh_months(date(2026,10,23)))==[(2026,9),(2026,10)]


def test_deploy_installs_and_restarts_persistent_terminal_jobs():
    text=Path('.github/workflows/ci.yml').read_text()
    for name in ('uzstock-terminal-alerts','uzstock-terminal-cbu'):
        assert f'/etc/systemd/system/{name}.service' in text
        assert f'/etc/systemd/system/{name}.timer' in text
        assert text.count(f'{name}.timer')>=3 # install, stop, enable
        assert text.count(f'{name}.service')>=2 # install, stop
    assert 'python -m scripts.terminal_cbu_sync --refresh' in text
    assert 'docker exec -u appuser uzstock-web python -m server.terminal.alerts' in text
