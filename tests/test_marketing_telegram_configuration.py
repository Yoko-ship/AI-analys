import os
from pathlib import Path
import subprocess
import sys

import pytest


TOKEN = '123456:' + 'a' * 35
SCRIPT = Path('scripts/configure_marketing_telegram.py')


def configure(path, token):
    return subprocess.run([sys.executable, str(SCRIPT), str(path)], input=token,
                          text=True, capture_output=True, check=False)


def test_token_is_replaced_privately_without_changing_other_settings(tmp_path):
    path = tmp_path / '.env'
    path.write_text('# Keep this comment\nNEWS_AI_PROVIDER=codex\n'
                    'MARKETING_TELEGRAM_BOT_TOKEN=old\n\n'
                    'MARKETING_TELEGRAM_BOT_TOKEN=duplicate\nOTHER=value=with=equals\n')
    result = configure(path, TOKEN)
    assert result.returncode == 0, result.stderr
    expected = ('# Keep this comment\nNEWS_AI_PROVIDER=codex\n\nOTHER=value=with=equals\n'
                f'MARKETING_TELEGRAM_BOT_TOKEN={TOKEN}\n')
    assert path.read_text() == expected
    assert TOKEN not in result.stdout + result.stderr
    assert configure(path, TOKEN).returncode == 0
    assert path.read_text() == expected
    assert list(tmp_path.iterdir()) == [path]
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('token', ['', 'invalid-secret', TOKEN + '\nOTHER=injected'])
def test_invalid_input_leaves_existing_environment_untouched(tmp_path, token):
    path = tmp_path / '.env'
    original = 'MARKETING_TELEGRAM_BOT_TOKEN=previous\nOTHER=keep\n'
    path.write_text(original)
    result = configure(path, token)
    assert result.returncode != 0
    assert 'Invalid Telegram bot token' in result.stderr
    assert path.read_text() == original
    if token:
        assert token not in result.stdout + result.stderr


def test_failed_atomic_replace_preserves_existing_environment(tmp_path, monkeypatch):
    from scripts.configure_marketing_telegram import configure as save

    path = tmp_path / '.env'
    path.write_text('OTHER=keep\n')

    def fail_replace(*_args):
        raise OSError('simulated storage failure')

    monkeypatch.setattr(os, 'replace', fail_replace)
    with pytest.raises(OSError, match='storage failure'):
        save(path, TOKEN)
    assert path.read_text() == 'OTHER=keep\n'
    assert list(tmp_path.iterdir()) == [path]
