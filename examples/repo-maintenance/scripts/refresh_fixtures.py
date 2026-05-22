from __future__ import annotations

import json
from pathlib import Path

fixtures = {
    "example": "repo-maintenance",
    "records": [
        {"id": "alpha", "status": "ready"},
        {"id": "beta", "status": "done"},
    ],
}
Path("fixtures.json").write_text(json.dumps(fixtures, indent=2) + "\n", encoding="utf-8")
print("tests-fixtures wrote fixtures.json")
