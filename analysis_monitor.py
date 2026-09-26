"""Command-line entry point for the reporting worker.

Run ``python analysis_monitor.py`` for one bounded queue pass.
Persistence and publication interfaces live in the reporting package.
"""
import json

from reporting.worker import run_pending

if __name__ == "__main__":
    print(json.dumps({"processed": run_pending()}, ensure_ascii=False))
