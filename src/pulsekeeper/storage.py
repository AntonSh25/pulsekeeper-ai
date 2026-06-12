from __future__ import annotations

import json
from pathlib import Path

from pulsekeeper.domain import HealthEntry


def user_health_log_path(storage_dir: str | Path, user_id: str) -> Path:
    return Path(storage_dir) / "users" / user_id / "health.jsonl"


class JsonlHealthLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entry: HealthEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")

    def read_all(self) -> list[HealthEntry]:
        if not self.path.exists():
            return []
        entries: list[HealthEntry] = []
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    entries.append(HealthEntry.model_validate_json(line))
        return entries
