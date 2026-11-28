"""Save a marketing bot token received on stdin in the private server environment."""
import argparse
import os
from pathlib import Path
import re
import sys
import tempfile


def configure(path: Path, token: str) -> None:
    if not re.fullmatch(r'[0-9]{5,}:[A-Za-z0-9_-]{20,}', token):
        raise ValueError('Invalid Telegram bot token')
    lines = path.read_text(encoding='utf-8').splitlines()
    lines = [line for line in lines
             if line.split('=', 1)[0].strip() != 'MARKETING_TELEGRAM_BOT_TOKEN']
    text = '\n'.join([*lines, f'MARKETING_TELEGRAM_BOT_TOKEN={token}']) + '\n'
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.marketing-token-')
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('environment', type=Path)
    args = parser.parse_args()
    try:
        configure(args.environment, sys.stdin.read())
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')
    print('Marketing Telegram credential saved privately.')
