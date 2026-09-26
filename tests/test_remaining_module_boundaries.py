"""Protect ownership rules for the second refactor."""
import ast
import builtins
import symtable
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path,forbidden", [
    ("catalogue/parsing.py", {"reports_catalog", "openinfo_collector", "requests", "db"}),
    ("catalogue/storage.py", {"reports_catalog", "openinfo_collector", "requests"}),
    ("financial_analysis/metrics.py", {"analyzer", "main", "openai", "anthropic", "db"}),
    ("financial_analysis/sector_report.py", {"sector_analysis", "reports_catalog", "openai", "anthropic"}),
    ("identity/credentials.py", {"web_auth", "psycopg", "fastapi"}),
    ("collectors/news/sources.py", {"news_collector", "news_classifier", "news_store"}),
])
def test_module_does_not_reach_back_into_its_orchestrator(path, forbidden):
    target = ROOT / path
    assert target.exists(), f"Missing independently usable module: {path}"
    tree = ast.parse(target.read_text(encoding="utf-8"))
    dependencies = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            dependencies.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            dependencies.add((node.module or '').split('.')[0])
    assert not dependencies.intersection(forbidden), (path, dependencies.intersection(forbidden))


def test_extracted_modules_have_no_unresolved_global_names():
    """Catch moved helpers missed by a narrow runtime fixture (including annotations)."""
    def referenced_globals(table):
        return {symbol.get_name() for symbol in table.get_symbols()
                if symbol.is_global() and symbol.is_referenced()} | set().union(
                    *(referenced_globals(child) for child in table.get_children()))

    missing = {}
    for package in ("catalogue", "financial_analysis", "identity", "collectors"):
        for path in (ROOT / package).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            table = symtable.symtable(source, str(path), "exec")
            bound = {symbol.get_name() for symbol in table.get_symbols()
                     if symbol.is_assigned() or symbol.is_imported()}
            unknown = referenced_globals(table) - bound - set(dir(builtins)) - {
                "__name__", "__file__", "__conditional_annotations__"}
            for node in ast.walk(ast.parse(source)):
                annotation = (node.annotation if isinstance(node, (ast.arg, ast.AnnAssign))
                              else node.returns if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                              else None)
                if annotation is not None:
                    unknown |= {item.id for item in ast.walk(annotation) if isinstance(item, ast.Name)} - bound - set(dir(builtins))
            if unknown:
                missing[str(path.relative_to(ROOT))] = sorted(unknown)
    assert not missing
