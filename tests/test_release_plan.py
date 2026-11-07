"""Plan releases against the running revision, preserving unshipped changes."""
import subprocess
import shlex
from pathlib import Path

import pytest

from scripts.release_plan import plan_release


@pytest.mark.parametrize('origin', ['git@github.com:Yoko-ship/AI-analys.git',
                                  'ssh://git@github.com/Yoko-ship/AI-analys.git'])
def test_production_fetch_uses_public_https_without_changing_the_servers_origin(repo, origin):
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / '.github/workflows/ci.yml').read_text(encoding='utf-8'))
    update = next(step['run'] for step in workflow['jobs']['deploy-production']['steps'] if step.get('name') == 'Update VPS')
    command = shlex.split(next(line.strip() for line in update.splitlines() if line.strip().endswith('fetch origin API')))
    command = command[command.index('git') + 1:]
    # Resolve the effective URL with Git itself, using the production SSH-origin
    # shape that timed out during ad4ae12's release. No network or credentials.
    git(repo, 'remote', 'add', 'origin', origin)
    assert command[-3:] == ['fetch', 'origin', 'API']
    assert git(repo, *command[:-3], 'remote', 'get-url', 'origin') == 'https://github.com/Yoko-ship/AI-analys.git'
    assert git(repo, 'remote', 'get-url', 'origin') == origin


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'config', 'user.name', 'Release test')
    git(tmp_path, 'config', 'user.email', 'release@example.test')
    return tmp_path


def commit(repo, path, content):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'fixture')
    return git(repo, 'rev-parse', 'HEAD')


@pytest.mark.parametrize('path', ['tests/test_feature.py', 'e2e/feature.spec.js', 'docs/guide.md', 'AGENTS.md'])
def test_test_and_documentation_only_pushes_do_not_deploy(repo, path):
    base = commit(repo, 'api.py', 'original')
    head = commit(repo, path, 'new test or instructions')
    assert plan_release(repo, base, head)['deploy'] is False


@pytest.mark.parametrize('path', ['api.py', 'frontend/src/App.jsx', 'requirements-server.txt', 'Dockerfile',
                                  'scripts/nginx_edge.py', 'company_logos.json', 'new_runtime_file.py'])
def test_runtime_changes_and_unknown_paths_deploy(repo, path):
    base = commit(repo, 'AGENTS.md', 'instructions')
    head = commit(repo, path, 'runtime change')
    assert plan_release(repo, base, head)['deploy'] is True


def test_docs_after_failed_application_release_still_deploy_the_application(repo):
    running = commit(repo, 'api.py', 'original')
    commit(repo, 'api.py', 'not yet deployed')
    head = commit(repo, 'docs/guide.md', 'documentation')
    assert plan_release(repo, running, head)['deploy'] is True


def test_deleting_runtime_code_or_moving_it_into_tests_still_deploys(repo):
    base = commit(repo, 'api.py', 'original')
    (repo / 'tests').mkdir()
    (repo / 'api.py').rename(repo / 'tests' / 'old_api.py')
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'move')
    assert plan_release(repo, base, git(repo, 'rev-parse', 'HEAD'))['deploy'] is True


def test_unknown_running_revision_and_explicit_manual_release_deploy(repo):
    head = commit(repo, 'api.py', 'original')
    for base in ('', '<no value>', 'f' * 40):
        assert plan_release(repo, base, head)['deploy'] is True
    assert plan_release(repo, head, head, force=True)['deploy'] is True
    assert plan_release(repo, head, head)['deploy'] is False


def test_ci_testing_changes_skip_deploy_but_deployment_changes_do_not(repo):
    path = '.github/workflows/ci.yml'
    base = commit(repo, path, 'jobs:\n  backend:\n    steps: [old-test]\n  deploy-production:\n    steps: [old-deploy]\n')
    tests = commit(repo, path, 'jobs:\n  backend:\n    steps: [new-test]\n  deploy-production:\n    steps: [old-deploy]\n')
    assert plan_release(repo, base, tests)['deploy'] is False
    deployed = commit(repo, path, 'jobs:\n  backend:\n    steps: [new-test]\n  deploy-production:\n    steps: [new-deploy]\n')
    assert plan_release(repo, tests, deployed)['deploy'] is True


def test_invalid_workflow_is_never_silently_treated_as_test_only(repo):
    base = commit(repo, '.github/workflows/ci.yml', 'jobs: {}')
    head = commit(repo, '.github/workflows/ci.yml', 'jobs: [')
    assert plan_release(repo, base, head)['deploy'] is True
