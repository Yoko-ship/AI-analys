"""Keep real persistence and full browser coverage in the release gate."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ci_exercises_postgres_and_both_supported_python_versions():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    backend = workflow["jobs"]["backend"]
    assert {"3.12", "3.14"} <= set(backend["strategy"]["matrix"]["python-version"])
    assert backend["services"]["postgres"]["image"].startswith("postgres:16")
    suite = next(step for step in backend["steps"] if step.get("run") == "python -m pytest tests -q")
    assert suite["env"]["TEST_POSTGRES_URL"].startswith("postgresql://")
    assert suite["env"]["TEST_DATABASE_URL"] == suite["env"]["TEST_POSTGRES_URL"]
    assert suite["env"]["DATABASE_URL"] == ""


def test_ci_runs_the_complete_browser_suite():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["frontend"]["steps"]
    assert any(step.get("run") == "npx playwright test" for step in steps)


def test_local_review_evidence_is_excluded_from_container_context():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "output/refactor-finish-20260926" in lines or "output" in lines


def test_balance_repair_is_opt_in_and_runs_only_after_verified_production_deployment():
    workflow = yaml.safe_load((ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8'))
    job = workflow['jobs']['repair-financial-balances']
    assert job['environment'] == 'uzstock-production'
    assert job['needs'] == 'deploy-production'
    assert "refs/heads/API" in job['if']
    assert '[repair-financial-balances]' in job['if']
    run = job['steps'][-1]['run']
    assert 'git rev-parse HEAD' in run
    assert 'docker inspect' in run
    assert run.index('python -m catalogue.balance_repair\n') < run.index('python -m catalogue.balance_repair --apply')
    assert 'trap restore_timer EXIT' in run
    assert run.index('python -m catalogue.balance_repair --rollback-unverified --apply') < run.index('python -m catalogue.balance_repair\n')
