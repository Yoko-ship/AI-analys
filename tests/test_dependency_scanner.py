from scripts.check_server_requirements import _package_sources


def test_server_package_scan_includes_subpackages_but_not_archived_repositories(tmp_path):
    package = tmp_path / "audit"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "runner.py").write_text("import requests")
    subpackage = package / "checks"
    subpackage.mkdir()
    (subpackage / "__init__.py").write_text("")
    (subpackage / "balances.py").write_text("import decimal")
    archived = package / "evidence" / "old-checkout"
    archived.mkdir(parents=True)
    (archived / "api.py").write_text("import an_archived_dependency")
    assert {str(path.relative_to(package)).replace("\\", "/") for path in _package_sources(package)} == {
        "__init__.py", "runner.py", "checks/__init__.py", "checks/balances.py",
    }
