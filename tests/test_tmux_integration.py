import shlex
import shutil
import sys
import time
import uuid

import pytest

from local_agent_runtime import AgentTaskRuntime, TmuxSessionManager
from local_agent_runtime.models import TaskStatus


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_real_tmux_worker_runs_in_workspace_and_completion_stops_session(tmp_path):
    sessions = TmuxSessionManager()
    runtime = AgentTaskRuntime.local(tmp_path / "runtime.sqlite3", sessions, tmp_path / "work")
    task_id = "integration-" + uuid.uuid4().hex[:12]
    command = shlex.join(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; import time; "
            "Path('result.txt').write_text('done'); time.sleep(30)",
        ]
    )
    runtime.register_task(task_id, "test", command, task_id)
    task = runtime.start_task(task_id)
    try:
        marker = tmp_path / "work" / task_id / "result.txt"
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert marker.read_text() == "done"
        assert task.session_id is not None
        assert sessions.exists(task.session_id)
        assert runtime.mark_done(task_id, "marker verified").status == TaskStatus.DONE
        assert not sessions.exists(task.session_id)
    finally:
        if task.session_id and sessions.exists(task.session_id):
            sessions.stop(task.session_id)
