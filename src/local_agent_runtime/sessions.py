from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .models import WorkerSpec


class SessionManager(Protocol):
    """Adapters honor WorkerSpec.session_name as a unique launch identity.

    Returned ids must identify that attempt, so stopping an abandoned launch
    cannot affect its replacement. Explicit names supplied directly to an
    adapter retain their meaning.
    """

    def start(self, task_id: str, spec: WorkerSpec) -> str: ...
    def stop(self, session_id: str) -> None: ...
    def exists(self, session_id: str) -> bool: ...
    def attach_command(self, session_id: str) -> str: ...


@dataclass
class FakeSessionManager:
    """Deterministic adapter for tests and dry runs.

    When ``state_path`` is provided, live session ids persist across short CLI
    invocations. Without it, the adapter is purely in-memory for unit tests.
    """

    live: set[str] = field(default_factory=set)
    state_path: Path | None = None

    def __post_init__(self) -> None:
        self._load()

    def start(self, task_id: str, spec: WorkerSpec) -> str:
        session_id = spec.session_name or f"agent-runtime-{task_id}"
        self.live.add(session_id)
        self._save()
        return session_id

    def stop(self, session_id: str) -> None:
        self.live.discard(session_id)
        self._save()

    def exists(self, session_id: str) -> bool:
        self._load()
        return session_id in self.live

    def attach_command(self, session_id: str) -> str:
        return f"fake attach {shlex.quote(session_id)}"

    def _load(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        self.live = set(json.loads(self.state_path.read_text(encoding="utf-8")))

    def _save(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(sorted(self.live)), encoding="utf-8")


@dataclass(frozen=True)
class TmuxSessionManager:
    prefix: str = "agent-runtime"

    def start(self, task_id: str, spec: WorkerSpec) -> str:
        if shutil.which("tmux") is None:
            raise RuntimeError("tmux is not installed or not on PATH")
        session_id = spec.session_name or f"{self.prefix}-{task_id}"
        if "." in session_id or ":" in session_id:
            raise ValueError("tmux session names cannot contain '.' or ':'; choose another task id")
        if self.exists(session_id):
            raise RuntimeError(
                f"session already exists: {session_id}; inspect it before restarting"
            )
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) for key in spec.env):
            raise ValueError("worker environment names must be valid shell variable names")
        cwd = Path(spec.cwd or ".")
        env_parts = [f"{key}={shlex.quote(value)}" for key, value in sorted(spec.env.items())]
        command = " ".join([*env_parts, spec.command]).strip()
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_id, "-c", str(cwd), command],
            check=True,
        )
        return session_id

    def stop(self, session_id: str) -> None:
        if shutil.which("tmux") is None:
            raise RuntimeError("tmux is not installed or not on PATH")
        subprocess.run(["tmux", "kill-session", "-t", f"={session_id}"], check=False)

    def exists(self, session_id: str) -> bool:
        if shutil.which("tmux") is None:
            return False
        result = subprocess.run(
            ["tmux", "has-session", "-t", f"={session_id}"],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def attach_command(self, session_id: str) -> str:
        return "tmux attach-session -t " + shlex.quote(f"={session_id}")
