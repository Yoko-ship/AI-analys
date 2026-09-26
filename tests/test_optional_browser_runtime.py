"""The API's parsing path must not import the optional browser/proxy stack."""
import os
from pathlib import Path
import subprocess
import sys


def test_data_parser_import_does_not_initialize_selenium():
    result = subprocess.run([sys.executable, "-c", """
import sys
import main
assert not any(name == 'seleniumwire' or name.startswith('seleniumwire.') for name in sys.modules)
"""], cwd=Path(__file__).resolve().parents[1], env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
        text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
