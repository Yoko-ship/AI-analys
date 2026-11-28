from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import api
from server.auth import access


@pytest.mark.parametrize('module', ['checks', 'sources', 'content', 'worker'])
def test_marketing_modules_import_without_composition_root(module):
    result = subprocess.run(
        [sys.executable, '-c', f'import marketing.{module}'],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_ai_workspace_and_existing_editorial_workspace_keep_separate_state(monkeypatch, tmp_path):
    monkeypatch.setenv('CATALOG_DB_PATH', str(tmp_path / 'editorial.db'))
    monkeypatch.setenv('MARKETING_DB', str(tmp_path / 'team.db'))
    monkeypatch.setenv('MARKETING_ENVIRONMENT', 'integration-test')

    def owner(request: Request):
        request.state.control_actor = {'id': 1, 'role': 'administrator'}

    monkeypatch.setitem(api.app.dependency_overrides, access._control_gate, owner)
    monkeypatch.setitem(api.app.dependency_overrides, access._admin_panel_gate, lambda: None)
    client = TestClient(api.app)
    team = client.get('/api/admin/ai-marketing/workspace')
    assert team.status_code == 200
    assert team.json()['tasks'] == []
    editorial = client.get('/api/admin/marketing/workspace')
    assert editorial.status_code == 200
    assert editorial.json()['plans'] == []
    assert 'tasks' not in editorial.json()
    assert 'platforms' in team.json()
