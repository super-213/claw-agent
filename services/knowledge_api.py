"""HTTP library operations. Identity and attachment ownership are server-derived."""
from html import escape
from typing import Literal
from fastapi import APIRouter, Body, Depends, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from services.task_store import TaskError


class DocumentSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    path: str
    request_id: str
    title: str = ''
    object_name: str = ''
    source_session_id: str | None = None
    source_node_id: str | None = None
    replace_id: str | None = None
    expected_version: int | None = None


class RecordSave(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    title: str
    content: str
    kind: Literal['fact', 'event', 'preference'] = 'fact'
    object_name: str = ''


class KnowledgeChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str
    expected_version: int
    patch: dict = Field(default_factory=dict)


def knowledge_router(get_service, require_user, resolve_file, resolve_source):
    router = APIRouter(prefix='/api/knowledge', tags=['knowledge'])

    @router.get('/search')
    def search(q: str = Query('', max_length=2000), limit: int = Query(8, ge=1, le=20), user=Depends(require_user)):
        return get_service().search(user, q, limit=limit)

    @router.post('/documents', status_code=201)
    def save_document(payload: DocumentSave, user=Depends(require_user)):
        path = resolve_file(user, payload.path)
        source = resolve_source(user, payload.source_session_id, payload.source_node_id, path)
        return get_service().save_document(user, path, request_id=payload.request_id, title=payload.title,
            object_name=payload.object_name, source=source, replace_id=payload.replace_id,
            expected_version=payload.expected_version)

    @router.post('/records', status_code=201)
    def save_record(payload: RecordSave, user=Depends(require_user)):
        return get_service().save_record(user, **payload.model_dump(), source={'type': 'explicit_user_input'})

    @router.get('/documents/{identity}/file')
    def file(identity: str, user=Depends(require_user)):
        path, filename = get_service().file_path(user, identity)
        return FileResponse(path, filename=filename, headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    Collection = Literal['documents', 'records']

    @router.get('/{collection}')
    def listing(collection: Collection, q: str = '', include_outdated: bool = False, user=Depends(require_user)):
        return {'items': get_service().list(user, collection, query=q, include_outdated=include_outdated)}

    @router.get('/{collection}/{identity}/source', response_class=HTMLResponse)
    def source(collection: Collection, identity: str, version: int, chunk: int = 0, user=Depends(require_user)):
        value = get_service().source(user, collection, identity, version, chunk)
        row, unit = value['record'], value['chunk']
        link = f'<p><a href="{escape(row["file_url"], quote=True)}">打开原文件</a></p>' if row.get('file_url') else ''
        body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(row['title'])}</title><style>body{{max-width:850px;margin:40px auto;padding:0 20px;font:17px/1.7 system-ui}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#2455aa}}</style>
<h1>{escape(row['title'])}</h1><p>{escape(unit['location'])} · 更新于 {escape(row['updated_at'])}</p>{link}<pre>{escape(unit['text'])}</pre></html>'''
        return HTMLResponse(body, headers={'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})

    @router.get('/{collection}/{identity}')
    def detail(collection: Collection, identity: str, user=Depends(require_user)):
        return get_service().get(user, collection, identity)

    @router.patch('/{collection}/{identity}')
    def change(collection: Collection, identity: str, payload: KnowledgeChange, user=Depends(require_user)):
        return get_service().change(user, collection, identity, **payload.model_dump())

    @router.delete('/{collection}/{identity}')
    def delete(collection: Collection, identity: str, payload: KnowledgeChange = Body(...), user=Depends(require_user)):
        return get_service().change(user, collection, identity, **payload.model_dump(), delete=True)

    @router.post('/documents/{identity}/reprocess')
    def reprocess(identity: str, payload: KnowledgeChange, user=Depends(require_user)):
        service = get_service()
        row = service.get(user, 'documents', identity)
        if row['owner_user_id'] != user['id']:
            raise TaskError('knowledge_owner_required', status=403)
        path, _ = service.file_path(user, identity)
        return service.save_document(user, path, request_id=payload.request_id, title=row['title'],
            object_name=row['object_name'], source=row['source'], replace_id=identity, expected_version=payload.expected_version)

    return router
