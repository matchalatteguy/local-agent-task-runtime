"""Local-first runtime for durable agent and script task execution."""

from .dispatch import Dispatcher
from .models import DispatchResult, StaleTask, TaskEvent, TaskRecord, TaskStatus, WorkerSpec
from .runtime import AgentTaskRuntime
from .sessions import FakeSessionManager, SessionManager, TmuxSessionManager
from .store import SqliteRuntimeStore
from .workspaces import DirectoryWorkspaceManager, GitWorktreeWorkspaceManager

__version__ = "0.1.0"

__all__ = [
    "AgentTaskRuntime",
    "DirectoryWorkspaceManager",
    "DispatchResult",
    "Dispatcher",
    "FakeSessionManager",
    "GitWorktreeWorkspaceManager",
    "SessionManager",
    "SqliteRuntimeStore",
    "StaleTask",
    "TaskEvent",
    "TaskRecord",
    "TaskStatus",
    "TmuxSessionManager",
    "WorkerSpec",
    "__version__",
]
