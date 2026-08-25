from __future__ import annotations

import csv
import io
import json
from typing import Any


def to_json(records: list[Any]) -> bytes:
    return json.dumps(records, ensure_ascii=False, indent=2).encode("utf-8")


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if not isinstance(value, dict):
        return {prefix or "value": value if not isinstance(value, (list, dict)) else json.dumps(value, ensure_ascii=False)}
    out: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            out.update(_flatten(item, name))
        elif isinstance(item, list):
            out[name] = json.dumps(item, ensure_ascii=False)
        else:
            out[name] = item
    return out


def to_csv(records: list[Any]) -> bytes:
    rows = [_flatten(item) for item in records]
    fields = sorted({key for row in rows for key in row}) or ["value"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")
