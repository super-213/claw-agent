"""Authenticated deterministic activity actions and heterogeneous board feed."""
import base64
import json
from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from services.task_store import TaskError


class ActivityWrite(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=200)
    data: dict = Field(default_factory=dict)
    expected_version: int | None = None
    participation_version: int | None = None


def activity_router(get_service, get_board, require_user, session_context):
    router = APIRouter(tags=['family-activities'])

    def ctx(user, session_id, write=False):
        return session_context(user, session_id, write=write) if session_id else None

    def no_cache(response):
        response.headers['Cache-Control'] = 'private, no-store'

    def register(kind, plural):
        sub = APIRouter(prefix='/api/home/' + plural)

        @sub.get('')
        def listing(response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return {'items': get_service().list(user, kind, context=ctx(user, session_id))}

        @sub.post('', status_code=201)
        def create(payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().create(user, kind, payload.data, request_id=payload.request_id, context=ctx(user, session_id, True))

        @sub.post('/drafts', status_code=201)
        def create_draft(payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().create(user, kind, payload.data, request_id=payload.request_id, draft=True, context=ctx(user, session_id, True))

        @sub.get('/drafts/{identifier}')
        def get_draft(identifier: str, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().get(user, kind, identifier, draft=True, context=ctx(user, session_id))

        @sub.patch('/drafts/{identifier}')
        def save_draft(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'save_draft', **payload.model_dump(), draft=True, context=ctx(user, session_id, True))

        @sub.post('/drafts/{identifier}/commit')
        def commit(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'publish', **payload.model_dump(), draft=True, context=ctx(user, session_id, True))

        @sub.delete('/drafts/{identifier}')
        def delete_draft(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'delete', **payload.model_dump(), draft=True, context=ctx(user, session_id, True))

        @sub.get('/{identifier}')
        @sub.get('/{identifier}/card')
        def get(identifier: str, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().get(user, kind, identifier, context=ctx(user, session_id))

        @sub.patch('/{identifier}')
        def save(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'save', **payload.model_dump(), context=ctx(user, session_id, True))

        @sub.post('/{identifier}/close')
        def close(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'close', **payload.model_dump(), context=ctx(user, session_id, True))

        @sub.delete('/{identifier}')
        def delete(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'delete', **payload.model_dump(), context=ctx(user, session_id, True))

        route = '/{identifier}/my-' + ('vote' if kind == 'poll' else 'entry')

        @sub.put(route)
        def participate(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'participate', **payload.model_dump(), context=ctx(user, session_id, True))

        @sub.delete(route)
        def withdraw(identifier: str, payload: ActivityWrite, response: Response, session_id: str | None = None, user=Depends(require_user)):
            no_cache(response)
            return get_service().change(user, kind, identifier, 'withdraw', **payload.model_dump(), context=ctx(user, session_id, True))
        router.include_router(sub)

    register('poll', 'polls')
    register('relay', 'relays')

    @router.get('/api/home/board/feed')
    def feed(response: Response, cursor: str | None = None, limit: int = Query(30, ge=1, le=100), user=Depends(require_user)):
        no_cache(response)
        rows, next_page = [], None
        while True:
            page = get_board().list(user, cursor=next_page, limit=100)
            rows.extend(page['items'])
            next_page = page['next_cursor']
            if not next_page:
                break
        for view in get_service().list(user):
            row = view['activity']
            kind_label = '家庭投票' if row['kind'] == 'poll' else '家庭接龙'
            status = '进行中' if row['state'] == 'open' else '已结束'
            content = f"{kind_label} · {status}\n已有 {len(view['participants'])} 人参与"
            if row['participation_deadline_at']:
                content += '\n参与截止：' + row['participation_deadline_at']
            if row['kind'] == 'relay':
                for person in view['participants'][-2:]:
                    content += '\n' + str(person['sequence']) + '. ' + ' / '.join(str(v) for v in person['values'].values())
            rows.append(dict(**{k: v for k, v in view.items() if k not in ('activity', 'participants', 'own_participation')},
                activity_kind=row['kind'], post=dict(id=row['id'], title=row['title'], created_by=row['created_by'],
                    version=row['revision'], created_at=row['created_at'], published_at=row['published_at'], state='active',
                    content_blocks=[{'type': 'text', 'text': content}], audience_mode='household', recipient_ids=[],
                    retention_mode='until' if row['expires_at'] else 'permanent', expires_at=row['expires_at'], duration_hours=None)))
        rows.sort(key=lambda v: (v['post'].get('published_at') or v['post']['created_at'], v['post']['id']), reverse=True)
        if cursor:
            try:
                boundary = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                if not isinstance(boundary, list) or len(boundary) != 2 or not all(isinstance(s, str) for s in boundary):
                    raise ValueError()
                rows = [v for v in rows if (v['post'].get('published_at') or v['post']['created_at'], v['post']['id']) < tuple(boundary)]
            except (ValueError, TypeError):
                raise TaskError('invalid_cursor')
        selected = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = selected[-1]['post']
            next_cursor = base64.urlsafe_b64encode(json.dumps([last.get('published_at') or last['created_at'], last['id']]).encode()).decode()
        return {'items': selected, 'next_cursor': next_cursor, 'server_now': get_service().now().isoformat()}

    return router
