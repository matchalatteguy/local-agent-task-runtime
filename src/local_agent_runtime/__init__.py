"""Local-first runtime for durable agent and script task execution."""

from .backlog import export_backlog, load_backlog, register_backlog
from .config import RuntimeConfig
from .dispatch import Dispatcher
from .models import DispatchResult, StaleTask, TaskEvent, TaskRecord, TaskStatus, WorkerSpec
from .runtime import AgentTaskRuntime
from .sessions import FakeSessionManager, SessionManager, TmuxSessionManager
from .store import SqliteRuntimeStore
from .workspaces import DirectoryWorkspaceManager, GitWorktreeWorkspaceManager

__version__ = "0.2.0"

__all__ = [
    "AgentTaskRuntime",
    "DirectoryWorkspaceManager",
    "DispatchResult",
    "Dispatcher",
    "export_backlog",
    "FakeSessionManager",
    "GitWorktreeWorkspaceManager",
    "load_backlog",
    "register_backlog",
    "RuntimeConfig",
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
