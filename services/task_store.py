"""Atomic local ledger transactions. Never recover corrupt data as an empty ledger."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
from threading import RLock
import uuid


class TaskError(ValueError):
    def __init__(self, code, message=None, *, status=400, **details):
        super().__init__(code)
        self.code, self.message, self.status, self.details = code, message or code, status, details

    def payload(self):
        return {"error": self.code, "message": self.message, **self.details}


class TaskStore:
    _guard = RLock()
    _locks = {}

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._guard:
            self.lock = self._locks.setdefault(str(self.path.resolve()), RLock())

    @staticmethod
    def empty():
        return {"schema_version": 1, "revision": 0, "tasks": {}, "occurrences": {},
                "operations": {}, "events": [], "references": {}, "drafts": {},
                "legacy_map": {}, "migration_review": {}}

    @contextmanager
    def transaction(self):
        with self.lock, self.path.with_suffix(self.path.suffix + '.lock').open('a+') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                if self.path.exists():
                    try:
                        doc = json.loads(self.path.read_text(encoding='utf-8'))
                        if not isinstance(doc, dict) or doc.get('schema_version') != 1:
                            raise ValueError('unknown schema')
                        for key in ('tasks', 'occurrences', 'operations'):
                            if not isinstance(doc.get(key), dict):
                                raise ValueError('invalid collection')
                    except (ValueError, OSError) as exc:
                        raise TaskError('ledger_corrupt', '账本损坏，请从备份恢复；原文件未改动。', status=503) from exc
                else:
                    doc = self.empty()
                before = deepcopy(doc)
                yield doc
                if before != doc:
                    doc['revision'] = before['revision'] + 1
                    if self.path.exists():
                        from datetime import datetime, timezone
                        backups = self.path.parent / 'backups'
                        backups.mkdir(exist_ok=True)
                        daily = backups / (self.path.stem + '-' + datetime.now(timezone.utc).date().isoformat() + '.json')
                        if not daily.exists():
                            self.write_atomic(daily, before)
                    self.write_atomic(self.path, doc)
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def write_atomic(path, doc):
        path = Path(path)
        tmp = path.with_name(f'.{path.name}.{uuid.uuid4().hex}.tmp')
        try:
            with tmp.open('x', encoding='utf-8') as out:
                os.chmod(tmp, 0o600)
                json.dump(doc, out, ensure_ascii=False, indent=2)
                out.flush()
                os.fsync(out.fileno())
            os.replace(tmp, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            tmp.unlink(missing_ok=True)

    def snapshot(self):
        with self.transaction() as doc:
            return deepcopy(doc)
