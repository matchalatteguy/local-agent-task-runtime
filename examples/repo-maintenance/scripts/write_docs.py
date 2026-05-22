from __future__ import annotations

from pathlib import Path

OUTPUT = Path("quickstart-notes.md")
OUTPUT.write_text(
    "# Quickstart notes\n\n"
    "- Confirmed the local runtime can prepare this task workspace.\n"
    "- Replace these notes with project-specific documentation edits.\n",
    encoding="utf-8",
)
print("docs-quickstart wrote quickstart-notes.md")
