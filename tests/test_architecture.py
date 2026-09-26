"""Executable direction rules for the modular application and reporting core."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def imports(file):
    name = ".".join(file.relative_to(ROOT).with_suffix("").parts)
    package = name.removesuffix(".__init__") if name.endswith(".__init__") else name.rpartition(".")[0]
    result = set()
    for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                parts = package.split(".")
                base = ".".join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
            result.add(base)
            result.update(base + "." + alias.name for alias in node.names)
    return name, result


def test_application_and_reporting_dependencies_are_acyclic():
    files = [*ROOT.joinpath("server").rglob("*.py"), *ROOT.joinpath("reporting").rglob("*.py")]
    files += [ROOT / name for name in (
        "issuer_financials.py", "sector_report_service.py", "analysis_service.py",
        "sector_analysis.py", "sector_regressions.py", "fund_analysis.py", "sector_access.py",
        "admin_control/adapters.py", "admin_control/worker.py", "admin_control/service.py",
        "admin_control/store.py", "admin_control/rules.py", "admin_control/documents.py",
    )]
    graph = dict(imports(file) for file in files)
    for name, dependencies in graph.items():
        assert "api" not in dependencies, f"{name} imports the composition root"
        assert "analysis_monitor" not in dependencies, f"{name} imports a CLI entry point"
        if not name.endswith(("routes", "notifications")) and name != "server.news.discovery":
            assert not any(dep.endswith(("_api", ".routes", "_routes")) for dep in dependencies), name
    seen = set()

    def visit(name, ancestors=()):
        assert name not in ancestors, "Circular dependency: " + " -> ".join((*ancestors, name))
        if name in seen:
            return
        for dependency in graph.get(name, ()):
            if dependency in graph:
                visit(dependency, (*ancestors, name))
        seen.add(name)

    for name in graph:
        visit(name)


def test_financial_and_persistence_modules_do_not_depend_on_http_or_workers():
    for module in ("issuer_financials.py", "server/company/financials.py", "reporting/store.py"):
        _, dependencies = imports(ROOT / module)
        assert not any(dep.startswith(("fastapi", "server.http", "reporting.worker", "reporting.publication", "admin_control")) for dep in dependencies), module
