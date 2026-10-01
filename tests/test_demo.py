import json
import subprocess
import sys


def test_real_worker_demo_and_persisted_output(tmp_path):
    output = tmp_path / "demo"
    completed = subprocess.run(
        [sys.executable, "-m", "local_agent_runtime.demo", "--output", str(output)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(completed.stdout)
    assert report == {
        "counts": {"done": 1},
        "events": ["registered", "start_claimed", "started", "heartbeat", "done"],
        "summary": {"items": 3, "total_units": 18, "inventory_value": "82.49"},
    }
    assert (
        json.loads((output / "workspaces/inventory/summary.json").read_text()) == report["summary"]
    )

    repeated = subprocess.run(
        [sys.executable, "-m", "local_agent_runtime.demo", "--output", str(output)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert repeated.returncode == 1
    assert "File exists" in repeated.stderr
