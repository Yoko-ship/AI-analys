import textwrap
import re
import shlex
from pathlib import Path
from collection_ops.registry import JOBS

ROOT = Path(__file__).resolve().parents[1]

def units():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    start = workflow.index("          def worker(")
    end = workflow.index("          for name, content in units.items():", start)
    namespace = {}
    exec(textwrap.dedent(workflow[start:end]), namespace)
    return namespace["units"], workflow

def test_host_monitor_is_installed_and_started_without_privileging_the_web():
    installed, workflow = units()
    service = installed["/etc/systemd/system/uzstock-collection-monitor.service"]
    timer = installed["/etc/systemd/system/uzstock-collection-monitor.timer"]
    assert "python3 -m collection_ops.host" in service
    assert "--env-file /root/uzstock/app/.env" in service
    assert "WorkingDirectory=/root/uzstock/app" in service
    assert "OnUnitInactiveSec=30s" in timer
    assert "uzstock-collection-monitor.timer" in workflow[workflow.index("systemctl daemon-reload"):]
    assert "/var/run/docker.sock:" not in workflow
    for job in JOBS.values():
        assert "/etc/systemd/system/" + job.unit in installed
        assert "/etc/systemd/system/" + job.unit.replace(".service", ".timer") in installed


def test_monitor_connects_to_the_published_host_port_not_the_container_port():
    installed, workflow = units()
    # Production regression: the web container exposes 8000 on host port 8001.
    # Read the deployment mapping so changing it cannot silently break monitoring.
    address, port = re.search(r"-p (127\.0\.0\.1):(\d+):8000", workflow).groups()
    service = installed["/etc/systemd/system/uzstock-collection-monitor.service"]
    command = shlex.split(next(line.removeprefix("ExecStart=") for line in service.splitlines()
                              if line.startswith("ExecStart=")))
    assert "--api-url" in command
    assert command[command.index("--api-url") + 1] == f"http://{address}:{port}"
