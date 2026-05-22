from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Literal

from .runtime import AgentTaskRuntime
from .sessions import FakeSessionManager, SessionManager, TmuxSessionManager
from .store import SqliteRuntimeStore
from .workspaces import DirectoryWorkspaceManager

SessionKind = Literal["fake", "tmux"]


@dataclass(frozen=True)
class RuntimeConfig:
    """Reusable runtime settings for CLI entrypoints and embedding applications.

    Values can be supplied explicitly or read from the ``LOCAL_AGENT_RUNTIME_*``
    environment variables. The class keeps configuration parsing out of the CLI
    so library users can build the same runtime object without depending on
    argparse internals.
    """

    db_path: Path = Path(".agent-runtime/runtime.sqlite3")
    workspace_root: Path = Path(".")
    session: SessionKind = "tmux"

    ENV_PREFIX: ClassVar[str] = "LOCAL_AGENT_RUNTIME"
    VALID_SESSIONS: ClassVar[frozenset[str]] = frozenset({"fake", "tmux"})

    def __post_init__(self) -> None:
        object.__setattr__(self, "db_path", Path(self.db_path))
        object.__setattr__(self, "workspace_root", Path(self.workspace_root))
        if self.session not in self.VALID_SESSIONS:
            allowed = ", ".join(sorted(self.VALID_SESSIONS))
            raise ValueError(f"session must be one of: {allowed}")

    @classmethod
    def from_env(
        cls,
        *,
        db_path: str | Path | None = None,
        workspace_root: str | Path | None = None,
        session: str | None = None,
        environ: dict[str, str] | None = None,
    ) -> RuntimeConfig:
        """Create config from explicit values with environment fallback.

        Explicit arguments are intended for CLI flags or application config files.
        When they are ``None``, the method checks:

        - ``LOCAL_AGENT_RUNTIME_DB``
        - ``LOCAL_AGENT_RUNTIME_WORKSPACE_ROOT``
        - ``LOCAL_AGENT_RUNTIME_SESSION``
        """

        env = os.environ if environ is None else environ
        resolved_session = session or env.get(f"{cls.ENV_PREFIX}_SESSION") or "tmux"
        return cls(
            db_path=Path(
                db_path or env.get(f"{cls.ENV_PREFIX}_DB") or ".agent-runtime/runtime.sqlite3"
            ),
            workspace_root=Path(
                workspace_root or env.get(f"{cls.ENV_PREFIX}_WORKSPACE_ROOT") or "."
            ),
            session=resolved_session,  # type: ignore[arg-type]
        )

    def create_session_manager(self) -> SessionManager:
        """Build the configured session adapter."""

        if self.session == "fake":
            return FakeSessionManager(state_path=Path(str(self.db_path) + ".fake-sessions.json"))
        return TmuxSessionManager()

    def create_runtime(self) -> AgentTaskRuntime:
        """Build a complete local runtime from these settings."""

        return AgentTaskRuntime(
            SqliteRuntimeStore(self.db_path),
            self.create_session_manager(),
            DirectoryWorkspaceManager(self.workspace_root),
        )
