"""JSONL logging + timing. Stdlib only."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Any


def append_jsonl(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


class Timer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)
