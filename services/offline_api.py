"""Explicit metadata cache export and a narrowly scoped, idempotent memo pilot."""
from datetime import datetime, timezone
import hashlib
import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from services.task_store import TaskError


class SnapshotRequest(BaseModel):
    revision: str | None = None


class OfflineMemo(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    task_id: str | None = None
    expected_version: int | None = None
    scope: dict[str, str]


def offline_router(require_user, get_tasks, get_members, get_knowledge, sessions):
    router = APIRouter(prefix='/api/offline', tags=['offline'])

    @router.post('/snapshot')
    def snapshot(payload: SnapshotRequest, user=Depends(require_user)):
        members = get_members()
        actor = members.actor(user)  # revalidate binding on EVERY sync
        household = members.home.household().get('id', 'household_default')
        scope = {'user_id': user['id'], 'household_id': household, 'member_id': actor}
        tasks = get_tasks().list(user, limit=100)['items']
        # No descriptions, attachments, contents, chat messages or tool outputs.
        data = {
            'tasks': [{k: row['task'].get(k) for k in ('id', 'title', 'space_type', 'temporal_type', 'version', 'due_date', 'updated_at')}
                      for row in tasks],
            'sessions': [{k: row.get(k) for k in ('id', 'title', 'updated_at')}
                         for row in sessions(user) if row.get('owner_user_id') == user['id']][:30],
            'documents': [{k: row.get(k) for k in ('id', 'title', 'version', 'updated_at')}
                          for row in get_knowledge().list(user, 'documents')][:50],
        }
        revision = hashlib.sha256(json.dumps([scope, data], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return {'scope': scope, 'revision': revision, 'synced_at': datetime.now(timezone.utc).isoformat(),
                'ttl_seconds': 86400, 'data': data if revision != payload.revision else None}

    @router.post('/memos')
    def memo(payload: OfflineMemo, user=Depends(require_user)):
        actor = get_members().actor(user)
        household = get_members().home.household().get('id', 'household_default')
        if payload.scope != {'user_id': user['id'], 'household_id': household, 'member_id': actor}:
            raise TaskError('offline_scope_changed', status=403)
        service = get_tasks()
        if payload.task_id:
            task = service.get(user, payload.task_id)['task']
            if (task['space_type'] != 'personal' or task['space_owner_id'] != actor
                    or task['temporal_type'] != 'undated' or task.get('recurrence')):
                raise TaskError('offline_personal_memo_required', status=403)
            if payload.expected_version is None:
                raise TaskError('expected_version_required')
            return service.change(user, task['id'], 'update', expected_version=payload.expected_version,
                request_id='offline:' + payload.request_id, patch={'title': payload.title})
        if payload.expected_version is not None:
            raise TaskError('invalid_offline_create')
        return service.create(user, [{'title': payload.title}],
            {'command': '备忘', 'space_type': 'personal', 'temporal_type': 'undated',
             'mentions': [], 'actionable': True, 'completion_mode': 'all'}, request_id='offline:' + payload.request_id)

    return router
