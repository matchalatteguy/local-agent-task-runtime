from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .models import TaskRecord, require_relative_or_contained


class WorkspaceManager(Protocol):
    def prepare(self, task: TaskRecord) -> Path: ...


@dataclass(frozen=True)
class DirectoryWorkspaceManager:
    root: Path

    def prepare(self, task: TaskRecord) -> Path:
        workspace = self._resolve(task.workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def _resolve(self, workspace: str) -> Path:
        safe = require_relative_or_contained(workspace, self.root)
        candidate = Path(safe)
        return candidate if candidate.is_absolute() else (self.root / candidate).resolve()


@dataclass(frozen=True)
class GitWorktreeWorkspaceManager:
    root: Path
    repository: Path
    base_ref: str = "HEAD"

    def prepare(self, task: TaskRecord) -> Path:
        workspace = DirectoryWorkspaceManager(self.root)._resolve(task.workspace)
        if (workspace / ".git").exists():
            return workspace
        workspace.parent.mkdir(parents=True, exist_ok=True)
        branch = task.branch or f"task/{task.id}"
        subprocess.run(
            [
                "git",
                "-C",
                str(self.repository),
                "worktree",
                "add",
                "-b",
                branch,
                str(workspace),
                self.base_ref,
            ],
            check=True,
        )
        return workspace
