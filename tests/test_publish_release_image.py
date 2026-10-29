"""Run the publication step with Docker's observed push response."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TAG = 'ghcr.io/yoko-ship/ai-analys:57699d703db03985e4f6d33c00d36bf2e1420f5b'
DIGEST = 'sha256:49e98b2f60d953b01319bfc3137ac3bfc4d8dda0024f602bf1d40407ad4d657d'
PUSH_LINE = f'{TAG.rsplit(":", 1)[1]}: digest: {DIGEST} size: 2776'


def publish(tmp_path, output=PUSH_LINE, status=0):
    log = tmp_path / 'docker-calls.jsonl'
    result_file = tmp_path / 'github-output'
    docker = tmp_path / 'docker'
    docker.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
args = sys.argv[1:]
with open(os.environ['DOCKER_TEST_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[0] == 'push':
    print(os.environ['PUSH_OUTPUT'])
    sys.exit(int(os.environ['PUSH_STATUS']))
if args[:2] == ['image', 'inspect']:
    # A local alias is not the remote repository's immutable reference.
    print('uz-stock-bot@sha256:' + 'a' * 64)
''')
    docker.chmod(0o755)
    env = {**os.environ, 'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
           'DOCKER_TEST_LOG': str(log), 'IMAGE_TAG': TAG, 'GITHUB_OUTPUT': str(result_file),
           'PUSH_OUTPUT': output, 'PUSH_STATUS': str(status)}
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text())
    step = next(s for s in workflow['jobs']['docker']['steps'] if s.get('id') == 'publish')
    result = subprocess.run(['bash', '-eo', 'pipefail', '-c', step['run']], cwd=ROOT,
                            env=env, text=True, capture_output=True)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    return result, result_file.read_text() if result_file.exists() else '', calls


def test_publish_uses_digest_reported_by_push_not_local_alias_metadata(tmp_path):
    result, output, calls = publish(tmp_path)
    assert result.returncode == 0, result.stderr
    assert output == f'image={TAG.rsplit(":", 1)[0]}@{DIGEST}\n'
    assert calls == [['push', TAG]]


@pytest.mark.parametrize('response,status', [
    (PUSH_LINE, 1),
    ('Layer already exists', 0),
    (PUSH_LINE.replace(DIGEST, 'sha256:not-valid'), 0),
    (PUSH_LINE + '\n' + PUSH_LINE.replace(DIGEST, 'sha256:' + 'b' * 64), 0),
    (PUSH_LINE.replace(TAG.rsplit(':', 1)[1], 'another-tag'), 0),
])
def test_failed_or_ambiguous_push_never_records_a_release(tmp_path, response, status):
    result, output, _ = publish(tmp_path, response, status)
    assert result.returncode != 0
    assert output == ''
