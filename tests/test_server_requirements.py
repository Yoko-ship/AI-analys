"""Runtime packages are local code, but their dependencies must be declared."""
import importlib.util
from pathlib import Path


def test_runtime_package_dependencies_are_checked(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "requirements_check", Path(__file__).parents[1] / "scripts/check_server_requirements.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    (tmp_path / "app.py").write_text("import local_package\n", encoding="utf8")
    package = tmp_path / "local_package"
    package.mkdir()
    (package / "__init__.py").write_text("from . import rules\n", encoding="utf8")
    (package / "rules.py").write_text("import external_dependency\n", encoding="utf8")
    requirements = tmp_path / "requirements-server.txt"
    requirements.write_text("", encoding="utf8")
    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "ENTRYPOINTS", ("app.py",))
    monkeypatch.setattr(checker, "_preflight_required", lambda: set())
    assert checker.main() == 1
    requirements.write_text("external_dependency>=1\n", encoding="utf8")
    assert checker.main() == 0
