"""Decide whether runtime or deployment files differ from the running release."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

import yaml


NON_RUNTIME_PREFIXES = ('tests/', 'e2e/', 'docs/')
NON_RUNTIME_FILES = {'AGENTS.md', 'README.md', 'pytest.ini', 'requirements-dev.txt',
                     'playwright.config.js', 'eslint.config.js'}


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True, stderr=subprocess.DEVNULL)


def _deployment_configuration(text: str) -> dict:
    workflow = yaml.safe_load(text)
    if not isinstance(workflow, dict) or not isinstance(workflow.get('jobs'), dict):
        raise ValueError('Invalid CI workflow')
    # The rest includes image building, release planning, deployment, and live checks.
    workflow['jobs'] = {name: job for name, job in workflow['jobs'].items()
                        if name not in {'backend', 'frontend', 'secret-scan'}}
    return workflow


def plan_release(repo: Path, running: str, head: str, *, force: bool = False) -> dict:
    if not re.fullmatch(r'[a-f0-9]{40}', head):
        raise ValueError('Expected a full commit SHA')
    if force:
        return {'deploy': True, 'reason': 'Explicit release requested'}
    if not re.fullmatch(r'[a-f0-9]{40}', running):
        return {'deploy': True, 'reason': 'Running image has no known revision'}
    try:
        paths = _git(repo, 'diff', '--name-only', '--no-renames', '-z', running, head).split('\0')
    except subprocess.CalledProcessError:
        return {'deploy': True, 'reason': 'Running revision is unavailable in repository history'}
    relevant = []
    for path in filter(None, paths):
        if path.startswith(NON_RUNTIME_PREFIXES) or path in NON_RUNTIME_FILES:
            continue
        if path == '.github/workflows/ci.yml':
            try:
                old = _deployment_configuration(_git(repo, 'show', f'{running}:{path}'))
                new = _deployment_configuration(_git(repo, 'show', f'{head}:{path}'))
                if old == new:
                    continue
            except (subprocess.CalledProcessError, ValueError, yaml.YAMLError):
                pass  # Unknown or malformed configuration must never suppress a release.
        relevant.append(path)
    return {'deploy': bool(relevant), 'reason': 'Runtime/deployment changes' if relevant else 'Only tests or documentation changed',
            'paths': relevant}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--running', default='')
    parser.add_argument('--head', required=True)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    plan = plan_release(Path.cwd(), args.running, args.head, force=args.force)
    print(json.dumps(plan))
    if args.output:
        with args.output.open('a') as output:
            output.write(f"deploy={str(plan['deploy']).lower()}\n")


if __name__ == '__main__':
    main()
