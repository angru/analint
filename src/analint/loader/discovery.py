from __future__ import annotations

from pathlib import Path

_EXCLUDE_DIRS = {"__pycache__", ".venv", ".git", "node_modules", "dist", "build"}


def discover_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path] if path.suffix == ".py" else []

    result: list[Path] = []
    for item in sorted(path.rglob("*.py")):
        if any(part in _EXCLUDE_DIRS for part in item.parts):
            continue
        result.append(item)
    return result
