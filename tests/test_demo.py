import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from local_agent_runtime.process import ProcessStore
from local_agent_runtime.store import SqliteRuntimeStore


@pytest.mark.skipif(os.name != "posix" or not hasattr(os, "waitid"), reason="requires POSIX waitid")
def test_packaged_demo_tests_builds_verifies_and_retains_failure(tmp_path):
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
        "counts": {"done": 3},
        "checks_attempt_exit_codes": [1, 0],
        "artifact": "workspaces/build/dist/report.zip",
        "verified_summary": {"items": 3, "total_units": 18, "inventory_value": "82.49"},
        "restored_states": {"checks": "done", "build": "done", "verify": "done"},
    }
    assert (output / report["artifact"]).is_file()
    assert (
        json.loads((output / "workspaces/verify/verified.json").read_text())
        == report["verified_summary"]
    )
    runs = ProcessStore(SqliteRuntimeStore(output / "runtime.sqlite3")).runs("checks")
    assert "FAILED (failures=1)" in Path(runs[0]["logs"]["stderr"]).read_text()
    assert "OK" in Path(runs[1]["logs"]["stderr"]).read_text()
    repeated = subprocess.run(
        [sys.executable, "-m", "local_agent_runtime.demo", "--output", str(output)],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert repeated.returncode == 1 and "File exists" in repeated.stderr
