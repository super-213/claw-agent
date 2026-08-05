"""Bounded external storage for large tool outputs."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

from .models import ToolResult


class ArtifactStore:
    def __init__(self, root_dir: str | Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def externalize(self, result: ToolResult, *, max_chars: int) -> ToolResult:
        encoded = json.dumps(result.output, ensure_ascii=False, default=str)
        if len(encoded) <= max_chars:
            return result
        artifact_id = uuid.uuid4().hex
        path = self.root_dir / f"{artifact_id}.json"
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_text(encoded, encoding="utf-8")
        os.replace(tmp, path)
        result.artifacts.append({
            "id": artifact_id,
            "path": str(path),
            "media_type": "application/json",
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        result.output = {
            "preview": encoded[:max_chars],
            "truncated": True,
            "artifact_id": artifact_id,
            "original_characters": len(encoded),
        }
        return result
