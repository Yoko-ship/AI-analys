"""Exercise image transfer without a registry or production credentials."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
IMAGE = 'ghcr.io/example/app@sha256:' + 'b' * 64


@pytest.fixture
def docker(tmp_path):
    log = tmp_path / 'calls.jsonl'
    executable = tmp_path / 'docker'
    executable.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
args = sys.argv[1:]
with open(os.environ['DOCKER_TEST_LOG'], 'a') as log:
    log.write(json.dumps({'args': args, 'config': os.environ.get('DOCKER_CONFIG')}) + '\\n')
if args[0] == 'login':
    assert '--password-stdin' in args
    assert sys.stdin.read().strip() == 'ephemeral-test-token'
    sys.exit(int(os.environ.get('LOGIN_FAILURE', '0')))
if args[:2] == ['image', 'inspect']:
    print(os.environ['IMAGE_REVISION'])
''')
    executable.chmod(0o755)
    env = {'PATH': str(tmp_path) + os.pathsep + os.environ['PATH'],
           'TMPDIR': str(tmp_path), 'DOCKER_TEST_LOG': str(log), 'IMAGE_REVISION': SHA}
    return env, log


def run(docker, image=IMAGE, sha=SHA):
    env, log = docker
    result = subprocess.run(['bash', str(ROOT / 'scripts/pull_release_image.sh'), image, sha, 'example'],
                            input='ephemeral-test-token\n', text=True, capture_output=True, env=env)
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert 'ephemeral-test-token' not in result.stdout + result.stderr
    assert all(not Path(call['config']).exists() for call in calls)
    return result, [c['args'] for c in calls]


def test_pull_verifies_revision_then_tags_release_and_removes_credentials(docker):
    result, calls = run(docker)
    assert result.returncode == 0, result.stderr
    assert calls[0] == ['login', 'ghcr.io', '--username', 'example', '--password-stdin']
    assert calls[1] == ['pull', IMAGE]
    assert calls[2][:2] == ['image', 'inspect']
    assert calls[3] == ['tag', IMAGE, 'uzstock-web:release-' + SHA]


@pytest.mark.parametrize('failure', ['revision', 'login'])
def test_failed_pull_preparation_never_tags_a_release(docker, failure):
    docker[0]['IMAGE_REVISION' if failure == 'revision' else 'LOGIN_FAILURE'] = 'wrong' if failure == 'revision' else '1'
    result, calls = run(docker)
    assert result.returncode != 0
    assert not any(c[0] == 'tag' for c in calls)


@pytest.mark.parametrize('image,sha', [('ghcr.io/example/app:latest', SHA), (IMAGE, 'not-a-commit'),
                                      ('ghcr.io/example/app@sha256:' + 'z' * 64, SHA)])
def test_unpinned_or_invalid_release_is_rejected_before_login(docker, image, sha):
    result, calls = run(docker, image, sha)
    assert result.returncode != 0
    assert calls == []
