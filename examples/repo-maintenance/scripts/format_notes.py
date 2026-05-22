from __future__ import annotations

from pathlib import Path

raw_notes = ["trim trailing spaces   ", "normalize bullet text", "write deterministic output"]
formatted = "# Formatted notes\n\n" + "\n".join(f"- {note.strip()}" for note in raw_notes) + "\n"
Path("formatted-notes.md").write_text(formatted, encoding="utf-8")
print("style-cleanup wrote formatted-notes.md")
