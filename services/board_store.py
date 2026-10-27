"""Independent message-board ledger with expiration-safe backup snapshots."""
from copy import deepcopy
from datetime import datetime, timezone
from services.task_store import TaskError, TaskStore


def purge_expired(doc, now, *, post_ids=(), draft_ids=()):
    """Remove note payloads, copied drafts and exclusively referenced image metadata.

    Keep only operation fingerprints/IDs so a delayed retry cannot republish a
    destroyed record. No note text or images are retained in those receipts.
    """
    def due(value):
        if not value:
            return False
        try:
            cutoff = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if cutoff.tzinfo is None:
                raise ValueError()
            return now >= cutoff
        except (ValueError, TypeError, AttributeError):
            raise TaskError('ledger_corrupt', '便笺截止时间损坏，无法安全清理。', status=503)

    removed_posts = set(post_ids) | {key for key, post in doc['posts'].items() if due(post.get('expires_at'))}
    removed_drafts = set(draft_ids) | {key for key, draft in doc['drafts'].items()
        if draft.get('committed_post_id') in removed_posts or (not draft.get('committed_post_id') and due(draft.get('draft_expires_at')))}
    candidates = set()
    for collection, removed in [('posts', removed_posts), ('drafts', removed_drafts)]:
        for key in removed:
            record = doc[collection].pop(key, None)
            if record:
                candidates.update(b['asset_id'] for b in record.get('content_blocks', []) if b.get('type') == 'image')
    referenced = {b['asset_id'] for collection in ('posts', 'drafts') for record in doc[collection].values()
                  for b in record.get('content_blocks', []) if b.get('type') == 'image'}
    removed_assets = candidates - referenced
    for asset_id in removed_assets:
        doc['assets'].pop(asset_id, None)
    # Audit entries contain only IDs, but their display history is no longer needed.
    doc['events'] = [event for event in doc.get('events', []) if event.get('resource_id') not in removed_posts | removed_drafts]
    return {'post_ids': removed_posts, 'draft_ids': removed_drafts, 'asset_ids': removed_assets}


class BoardStore(TaskStore):
    collections = ('posts', 'drafts', 'assets', 'operations')

    def backup_document(self, doc):
        result = deepcopy(doc)
        purge_expired(result, self.clock() if hasattr(self, 'clock') else datetime.now(timezone.utc))
        return result

    @staticmethod
    def empty():
        return {'schema_version': 1, 'revision': 0, 'posts': {}, 'drafts': {},
                'assets': {}, 'operations': {}, 'events': []}
