"""Authenticated message board HTTP adapter."""
from fastapi import APIRouter, Body, Depends, File, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from services.board_service import MAX_IMAGE_BYTES
from services.task_store import TaskError


class BoardCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(min_length=1, max_length=200)
    data: dict = Field(default_factory=dict)


class BoardChange(BoardCreate):
    expected_version: int


def board_router(get_service, require_user, session_context, resolve_source):
    router = APIRouter(prefix='/api/home/board', tags=['board'])

    def context(user, session_id, write=False):
        return session_context(user, session_id, write=write) if session_id else None

    @router.get('/posts')
    def listing(response: Response, cursor: str | None = None,
                limit: int = Query(30, ge=1, le=100), user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().list(user, cursor=cursor, limit=limit)

    @router.post('/posts', status_code=201)
    def create(payload: BoardCreate, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().create(user, **payload.model_dump(), context=context(user, session_id, True))

    @router.get('/posts/{post_id}')
    @router.get('/posts/{post_id}/card')
    def get(post_id: str, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().get(user, post_id, context=context(user, session_id))

    @router.patch('/posts/{post_id}')
    def update(post_id: str, payload: BoardChange, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().change(user, post_id, **payload.model_dump(), context=context(user, session_id, True))

    @router.post('/posts/{post_id}/withdraw')
    def withdraw(post_id: str, payload: BoardChange, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().change(user, post_id, **payload.model_dump(), action='withdraw', context=context(user, session_id, True))

    @router.post('/drafts', status_code=201)
    def draft(payload: BoardCreate, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().create(user, **payload.model_dump(), draft=True, context=context(user, session_id, True))

    @router.get('/drafts/{draft_id}')
    def draft_get(draft_id: str, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().get(user, draft_id, draft=True, context=context(user, session_id))

    @router.patch('/drafts/{draft_id}')
    def draft_update(draft_id: str, payload: BoardChange, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().change(user, draft_id, **payload.model_dump(), draft=True, action='save_draft', context=context(user, session_id, True))

    @router.post('/drafts/{draft_id}/commit')
    def commit(draft_id: str, payload: BoardChange, response: Response, session_id: str | None = None, user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        return get_service().change(user, draft_id, **payload.model_dump(), draft=True, action='publish', context=context(user, session_id, True))

    @router.post('/assets', status_code=201)
    async def upload(response: Response, file: UploadFile = File(...), user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        try:
            data = await file.read(MAX_IMAGE_BYTES + 1)
        finally:
            await file.close()
        return await run_in_threadpool(get_service().upload, user, data)

    @router.post('/assets/import', status_code=201)
    def import_asset(response: Response, payload: dict = Body(...), user=Depends(require_user)):
        response.headers['Cache-Control'] = 'private, no-store'
        path = resolve_source(user, payload.get('path'), payload.get('session_id'), payload.get('node_id'))
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise TaskError('board_image_too_large', '单张图片不能超过 10MiB。', status=413)
        return get_service().upload(user, path.read_bytes())

    @router.get('/assets/{asset_id}')
    def asset(asset_id: str, user=Depends(require_user)):
        path = get_service().asset(user, asset_id)
        return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})

    return router
