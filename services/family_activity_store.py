"""Family activity ledger with a separate, content-free destruction journal."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from services.task_store import TaskStore, TaskError


class FamilyActivityStore(TaskStore):
    collections = ('activities', 'drafts', 'participations', 'publications', 'operations', 'notifications')

    @staticmethod
    def empty():
        return {**{key: {} for key in FamilyActivityStore.collections}, 'schema_version': 1, 'revision': 0}

    @property
    def journal(self):
        return self.path.with_name(self.path.stem + '-destroyed.json')

    def destroyed(self):
        try:
            value = json.loads(self.journal.read_text()) if self.journal.exists() else {}
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (OSError, ValueError) as exc:
            raise TaskError('activity_journal_corrupt', status=503) from exc

    def private_unavailable(self):
        """Read-only boundary check for history readers, without nested ledger locks."""
        gone = self.destroyed()
        if not self.path.exists():
            return gone
        try:
            doc = json.loads(self.path.read_text())
            now = self.clock()
            for collection, deadline in (('activities', 'expires_at'), ('drafts', 'draft_expires_at')):
                for key, row in doc[collection].items():
                    if row.get(deadline) and now >= datetime.fromisoformat(row[deadline]):
                        gone[key] = 'unavailable'
            for key, row in doc['drafts'].items():
                if row.get('committed_id') in gone:
                    gone[key] = 'unavailable'
        except (ValueError, TypeError, KeyError, OSError) as exc:
            raise TaskError('activity_ledger_corrupt', status=503) from exc
        return gone

    def sanitize(self, doc, *, discover=True):
        now = self.clock() if hasattr(self, 'clock') else datetime.now(timezone.utc)
        gone = self.destroyed()
        for collection, deadline in (('activities', 'expires_at'), ('drafts', 'draft_expires_at')):
            for key, row in list(doc[collection].items()):
                due = row.get(deadline)
                if key in gone or row.get('committed_id') in gone or (discover and due and now >= datetime.fromisoformat(due)):
                    gone.setdefault(key, now.isoformat())
        # Journal is written first: interrupted destruction and backup restore fail closed.
        if gone != self.destroyed():
            self.write_atomic(self.journal, gone)
        for collection in ('activities', 'drafts'):
            doc[collection] = {key: row for key, row in doc[collection].items()
                               if key not in gone and row.get('committed_id') not in gone}
        for collection in ('participations', 'publications', 'notifications'):
            doc[collection] = {key: row for key, row in doc[collection].items() if row['activity_id'] not in gone}
        return doc

    def destroy(self, doc, identifier):
        gone = self.destroyed()
        gone[identifier] = self.clock().isoformat()
        self.write_atomic(self.journal, gone)
        self.sanitize(doc)

    @contextmanager
    def transaction(self):
        with super().transaction() as doc:
            self.sanitize(doc)
            yield doc

    def backup_document(self, doc):
        return self.sanitize(deepcopy(doc), discover=False)

    def cleanup_backups(self):
        with self.transaction():
            for path in (self.path.parent / 'backups').glob(self.path.stem + '-*.json'):
                try:
                    snapshot = json.loads(path.read_text())
                    clean = self.backup_document(snapshot)
                except (OSError, ValueError, KeyError) as exc:
                    raise TaskError('activity_backup_corrupt', status=503) from exc
                if clean != snapshot:
                    self.write_atomic(path, clean)
