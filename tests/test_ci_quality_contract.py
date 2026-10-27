"""Keep release checks while feature browser tests run during implementation."""
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


def test_ci_runs_backend_tests_once_per_python_version():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    commands = [step.get("run", "") for step in workflow["jobs"]["backend"]["steps"]]
    pytest_commands = [command for command in commands if "python -m pytest" in command]
    assert pytest_commands == ["python -m pytest tests -q"]


def test_push_ci_builds_and_checks_frontend_without_browser_install_or_suite():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["frontend"]["steps"]
    commands = [step.get("run", "") for step in steps]
    assert not any("playwright" in command for command in commands)
    assert {"npm run lint", "npm run test:unit", "npm run build"} <= set(commands)
    assert "frontend" in workflow["jobs"]["deploy-production"]["needs"]


def test_deployment_keeps_targeted_live_market_browser_checks():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    for name in ("verify-production-market", "check-public-market"):
        job = workflow["jobs"][name]
        assert job["needs"] == "deploy-production"
        browser_steps = [
            step for step in job["steps"]
            if "playwright test" in step.get("run", "")
        ]
        assert len(browser_steps) == 1
        assert "e2e/production-market.spec.js" in browser_steps[0]["run"]
        assert browser_steps[0]["env"]["E2E_PRODUCTION_SMOKE"] == "1"


def test_local_review_evidence_is_excluded_from_container_context():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "output/refactor-finish-20260926" in lines or "output" in lines


def test_terminal_collector_is_included_in_production_image():
    lines = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "!scripts/terminal_cbu_sync.py" in lines
    assert lines.index("!scripts/terminal_cbu_sync.py") > lines.index("scripts")


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
