"""Purge activity-derived tool arguments when their authoritative resource is gone.

Original user messages are deliberately left under the chat retention policy.
The callback also runs on persistence, preventing a stale worker from restoring
scrubbed arguments after a lifecycle sweep.
"""
from copy import deepcopy
import json


def sanitize_activity_history(document, destroyed):
    if not destroyed:
        return document
    result = deepcopy(document)
    calls = set()

    def resource_id(value):
        resource = value.get('resource') if isinstance(value, dict) else None
        identifier = resource.get('id') if isinstance(resource, dict) else None
        return identifier if isinstance(identifier, str) else None

    def scan(value):
        if isinstance(value, list):
            for item in value:
                scan(item)
        elif isinstance(value, dict):
            output = value.get('output') or {}
            if resource_id(output) in destroyed:
                if value.get('call_id'):
                    calls.add(value['call_id'])
            if value.get('role') == 'tool':
                try:
                    parsed = json.loads(value.get('content') or '{}')
                    if resource_id(parsed.get('output')) in destroyed:
                        calls.add(value.get('tool_call_id') or parsed.get('call_id'))
                    scan(parsed)
                except (ValueError, AttributeError, TypeError):
                    pass
            for item in value.values():
                if isinstance(item, (list, dict)):
                    scan(item)
    scan(result)

    def scrub(value):
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if not isinstance(value, dict):
            return value
        if value.get('role') == 'user':
            return value
        if isinstance(value.get('id'), str) and value['id'] in calls:
            if isinstance(value.get('function'), dict):
                value['function']['arguments'] = '{}'
            if 'arguments' in value:
                value['arguments'] = {}
        resource = value.get('resource')
        if isinstance(resource, dict) and resource.get('id') in destroyed and value.get('type') != 'interactive_card':
            return {'resource': resource, 'destroyed': True, 'receipt': '该家庭活动已不可访问。'}
        if value.get('role') == 'tool':
            try:
                parsed = json.loads(value.get('content') or '{}')
                value['content'] = json.dumps(scrub(parsed), ensure_ascii=False)
            except (ValueError, TypeError):
                pass
        return {key: scrub(item) for key, item in value.items()}
    return scrub(result)


def cleanup_activity_history(service, runs, conversations, jobs=None):
    gone = service.store.private_unavailable()
    if not gone:
        return
    # Use each store's existing write locks and persistence callback.
    for path in runs.root_dir.glob('*.json'):
        with runs._lock:
            data = json.loads(path.read_text(encoding='utf-8'))
            if sanitize_activity_history(data, gone) != data:
                runs_document = sanitize_activity_history(data, gone)
                from services.task_store import TaskStore
                TaskStore.write_atomic(path, runs_document)
    for path in conversations.root_dir.glob('*.json'):
        with conversations._session_lock(path.stem):
            data = json.loads(path.read_text(encoding='utf-8'))
            if sanitize_activity_history(data, gone) != data:
                conversations._write_session(path.stem, data)

    if jobs is not None:
        jobs.sanitize_events()
