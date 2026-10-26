"""Authorized personal/household library with versioned, source-aware retrieval."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from services.knowledge_parser import extract_document
from services.task_store import TaskError, TaskStore


def terms(text):
    text = str(text).lower()
    words = set(re.findall(r'[a-z0-9]+', text))
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(run[i:i + 2] for i in range(len(run) - 1))
        if len(run) == 1:
            words.add(run)
    # Match common household expressions without relying on an external service.
    for aliases in [('空调', '冷气'), ('滤网', '过滤网'), ('钥匙', '备用钥匙'), ('清洁', '清洗'), ('冰箱', '冷藏柜')]:
        if any(alias in text for alias in aliases):
            words.update(aliases)
    return words


class KnowledgeService:
    def __init__(self, root, members, *, ocr=None):
        self.root = Path(root).resolve()
        self.blobs = self.root / 'blobs'
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.store = TaskStore(self.root / 'knowledge.json')
        self.members, self.ocr = members, ocr

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def actor(user):
        if not user or user.get('status') != 'active':
            raise TaskError('unauthorized', status=401)
        return user['id']

    def household_member(self, user):
        try:
            return bool(self.members.actor(user))
        except TaskError as error:
            if error.code == 'member_not_bound':
                return False
            raise

    def readable(self, row, user):
        return row.get('status') != 'deleted' and (row['owner_user_id'] == self.actor(user)
            or (row['visibility'] == 'household' and self.household_member(user)))

    def _row(self, doc, kind, identity, user, *, owner=False):
        row = doc.get(kind, {}).get(identity)
        if not row or not self.readable(row, user):
            raise TaskError('knowledge_not_found', '资料或记录不存在，或当前无权访问。', status=404)
        if owner and row['owner_user_id'] != user['id']:
            raise TaskError('knowledge_owner_required', '只有保存者可以删除或修改共享范围。', status=403)
        return row

    def _visibility(self, value, user):
        if value not in {'personal', 'household'}:
            raise TaskError('invalid_visibility')
        if value == 'household':
            self.members.actor(user)
        return value

    @staticmethod
    def _version(row, expected):
        if expected != row['version']:
            raise TaskError('version_conflict', '内容已更新，请刷新后重试。', status=409)

    @staticmethod
    def _text(value, name, limit=500, *, required=False):
        if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
            raise TaskError('invalid_' + name, f'{name} 为空或超出长度限制。')
        return value.strip()

    def _operation(self, doc, user, request_id, payload):
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200:
            raise TaskError('request_id_required')
        key = f'knowledge:{self.actor(user)}:{request_id}'
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        existing = doc['operations'].get(key)
        if existing and existing['fingerprint'] != fingerprint:
            raise TaskError('request_id_conflict', status=409)
        return key, fingerprint, existing

    @staticmethod
    def public(row, *, detail=False, user=None):
        value = {k: deepcopy(v) for k, v in row.items() if k not in {'blob', 'chunks', 'fingerprint', 'content_hash'}}
        if not detail:
            value.pop('history', None)
        if user and row['owner_user_id'] != user['id']:
            value['source'] = {k: v for k, v in value.get('source', {}).items() if k in {'type', 'filename'}}
            for event in value.get('history', []):
                event.pop('before', None)
        if row.get('blob') and row['status'] != 'deleted':
            value['file_url'] = f"/api/knowledge/documents/{row['id']}/file"
        value['source_url'] = f"/home/{'library' if row.get('filename') else 'memories'}?id={row['id']}"
        return value

    def list(self, user, kind, *, query='', include_outdated=False):
        self.actor(user)
        with self.store.transaction() as doc:
            rows = [self.public(row, user=user) for row in doc.get(kind, {}).values() if self.readable(row, user)
                and (include_outdated or row['status'] != 'outdated')
                and (not query or terms(query) & terms(' '.join(str(row.get(k, '')) for k in ('title', 'object_name', 'content', 'aliases'))))]
        return sorted(rows, key=lambda row: row['updated_at'], reverse=True)

    def get(self, user, kind, identity):
        with self.store.transaction() as doc:
            return self.public(self._row(doc, kind, identity, user), detail=True, user=user)

    def file_path(self, user, identity):
        with self.store.transaction() as doc:
            row = self._row(doc, 'documents', identity, user)
            path = self.blobs / row['blob']
            if path.parent != self.blobs or not path.is_file():
                raise TaskError('knowledge_file_missing', '原文件缺失，请替换资料。', status=404)
            return path, row['filename']

    def save_document(self, user, path, *, request_id, title='', object_name='', source=None,
                      replace_id=None, expected_version=None):
        self.actor(user)
        path = Path(path)
        if not path.is_file() or path.stat().st_size > 25 * 1024 * 1024:
            raise TaskError('invalid_knowledge_file', '文件不存在或超过 25MB。')
        title = self._text(title or path.name, 'title', required=True)
        object_name = self._text(object_name, 'object_name')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        payload = {'action': 'save_document', 'digest': digest, 'title': title, 'object_name': object_name,
                   'replace_id': replace_id, 'expected_version': expected_version, 'source': source or {}}
        # Parse outside the ledger lock. The final write rechecks version and idempotency.
        with self.store.transaction() as doc:
            key, fingerprint, prior = self._operation(doc, user, request_id, payload)
            if prior:
                return self.public(self._row(doc, 'documents', prior['id'], user), detail=True)
            duplicate = self._duplicate_document(doc, user, digest, title, object_name) if not replace_id else None
            if duplicate:
                doc['operations'][key] = {'fingerprint': fingerprint, 'id': duplicate['id']}
                return self.public(duplicate, detail=True)
            if replace_id:
                self._version(self._row(doc, 'documents', replace_id, user, owner=True), expected_version)
        identity = replace_id or 'doc_' + uuid.uuid4().hex
        blob = uuid.uuid4().hex + path.suffix.lower()
        copied = self.blobs / blob
        committed = False
        old_blob = None
        try:
            with os.fdopen(os.open(copied, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as target, path.open('rb') as origin:
                shutil.copyfileobj(origin, target)
                target.flush()
                os.fsync(target.fileno())
            if hashlib.sha256(copied.read_bytes()).hexdigest() != digest:
                raise TaskError('source_file_changed', '文件在保存时发生变化，请重试。', status=409)
            directory = os.open(self.blobs, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            try:
                chunks, warnings = extract_document(copied, self.ocr)
                state = 'ready' if chunks and not warnings else 'partial' if chunks else 'failed'
            except Exception:
                chunks, warnings, state = [], ['正文处理失败，原文件已保存；可重新处理或提供文字版。'], 'failed'
            now = self.now()
            with self.store.transaction() as doc:
                key, fingerprint, prior = self._operation(doc, user, request_id, payload)
                if prior:
                    return self.public(self._row(doc, 'documents', prior['id'], user), detail=True)
                duplicate = self._duplicate_document(doc, user, digest, title, object_name) if not replace_id else None
                if duplicate:
                    doc['operations'][key] = {'fingerprint': fingerprint, 'id': duplicate['id']}
                    return self.public(duplicate, detail=True)
                previous = self._row(doc, 'documents', replace_id, user, owner=True) if replace_id else None
                if previous:
                    self._version(previous, expected_version)
                    old_blob = previous['blob']
                row = {'id': identity, 'title': title, 'object_name': object_name, 'aliases': [],
                    'filename': (source or {}).get('filename') or path.name,
                    'owner_user_id': user['id'], 'visibility': previous['visibility'] if previous else 'personal',
                    'version': previous['version'] + 1 if previous else 1, 'created_at': previous['created_at'] if previous else now,
                    'updated_at': now, 'status': state, 'warnings': warnings, 'blob': blob,
                    'source': source or {}, 'chunks': chunks, 'chunk_count': len(chunks), 'content_hash': digest,
                    'history': [*(previous or {}).get('history', []), {'action': 'replace' if previous else 'save', 'at': now, 'by': user['id']}]}
                doc.setdefault('documents', {})[identity] = row
                doc['operations'][key] = {'fingerprint': fingerprint, 'id': identity}
                result = self.public(row, detail=True)
            committed = True
        finally:
            if not committed:
                copied.unlink(missing_ok=True)
        if old_blob:
            (self.blobs / old_blob).unlink(missing_ok=True)
        return result

    @staticmethod
    def _duplicate_document(doc, user, digest, title, object_name):
        return next((r for r in doc.get('documents', {}).values() if r['owner_user_id'] == user['id']
            and r['status'] != 'deleted' and r.get('content_hash') == digest and r['title'] == title
            and r['object_name'] == object_name), None)

    def save_record(self, user, *, request_id, title, content, kind='fact', object_name='', source=None):
        self.actor(user)
        title = self._text(title, 'title', required=True)
        content = self._text(content, 'content', 20_000, required=True)
        object_name = self._text(object_name, 'object_name')
        if kind not in {'fact', 'event', 'preference'}:
            raise TaskError('invalid_record_kind')
        payload = {'action': 'save_record', 'title': title, 'content': content, 'kind': kind,
                   'object_name': object_name, 'source': source or {}}
        with self.store.transaction() as doc:
            key, fingerprint, prior = self._operation(doc, user, request_id, payload)
            if prior:
                return self.public(self._row(doc, 'records', prior['id'], user), detail=True)
            # Exact duplicates reuse the existing record, rather than creating competing facts.
            duplicate = next((r for r in doc.get('records', {}).values() if r['owner_user_id'] == user['id']
                and r['status'] == 'active' and all(r[k] == payload[k] for k in ('title', 'content', 'kind', 'object_name'))), None)
            if duplicate:
                doc['operations'][key] = {'fingerprint': fingerprint, 'id': duplicate['id']}
                return self.public(duplicate, detail=True)
            if kind in {'fact', 'preference'}:
                conflicts = [r for r in doc.get('records', {}).values() if r['owner_user_id'] == user['id']
                    and r['status'] == 'active' and r['kind'] == kind and r['content'] != content
                    and (r['title'].lower() == title.lower() or (object_name and r['object_name'].lower() == object_name.lower()))]
                if conflicts:
                    raise TaskError('knowledge_record_conflict', '已有同一对象的记录，请先选择更正原记录或使用更具体的名称。', status=409,
                        candidates=[{'id': r['id'], 'title': r['title'], 'version': r['version'], 'content': r['content'][:400]} for r in conflicts[:5]])
            now, identity = self.now(), 'mem_' + uuid.uuid4().hex
            row = {'id': identity, 'title': title, 'content': content, 'kind': kind, 'object_name': object_name,
                'aliases': [], 'owner_user_id': user['id'], 'visibility': 'personal', 'version': 1,
                'status': 'active', 'created_at': now, 'updated_at': now, 'source': source or {},
                'history': [{'action': 'save', 'by': user['id'], 'at': now}]}
            doc.setdefault('records', {})[identity] = row
            doc['operations'][key] = {'fingerprint': fingerprint, 'id': identity}
            return self.public(row, detail=True)

    def change(self, user, collection, identity, patch, *, expected_version, request_id, delete=False):
        allowed = {'title', 'object_name', 'aliases', 'visibility'} | ({'content', 'status'} if collection == 'records' else set())
        if not isinstance(patch, dict) or set(patch) - allowed:
            raise TaskError('invalid_knowledge_fields')
        patch = deepcopy(patch)
        for field in ('title', 'object_name', 'content'):
            if field in patch:
                patch[field] = self._text(patch[field], field, 20_000 if field == 'content' else 500, required=field != 'object_name')
        if 'aliases' in patch and (not isinstance(patch['aliases'], list) or len(patch['aliases']) > 20
                or any(not isinstance(a, str) or not a.strip() or len(a) > 100 for a in patch['aliases'])):
            raise TaskError('invalid_aliases')
        if 'status' in patch and patch['status'] not in {'active', 'outdated'}:
            raise TaskError('invalid_record_status')
        if 'visibility' in patch:
            self._visibility(patch['visibility'], user)
        old_blob = None
        with self.store.transaction() as doc:
            key, fingerprint, prior = self._operation(doc, user, request_id,
                {'collection': collection, 'id': identity, 'patch': patch, 'delete': delete, 'version': expected_version})
            if prior:
                previous = doc.get(collection, {}).get(identity)
                if delete and previous and previous['owner_user_id'] == user['id'] and previous['status'] == 'deleted':
                    return {**self.public(previous, detail=True, user=user), 'deletion_note': '已停止检索并删除资料库副本。原上传文件及历史聊天中的内容保留。'}
                return self.public(self._row(doc, collection, identity, user), detail=True, user=user)
            row = self._row(doc, collection, identity, user, owner=delete or 'visibility' in patch)
            self._version(row, expected_version)
            now = self.now()
            row.setdefault('history', []).append({'action': 'delete' if delete else 'update', 'by': user['id'], 'at': now,
                'before': {k: deepcopy(row.get(k)) for k in patch}})
            row.update(patch)
            row.update(updated_at=now, version=row['version'] + 1)
            if delete:
                row['status'] = 'deleted'
                old_blob = row.pop('blob', None)
                row.pop('chunks', None)
                row.pop('content', None)
                row['history'] = [{'action': 'delete', 'by': user['id'], 'at': now}]
            doc['operations'][key] = {'fingerprint': fingerprint, 'id': identity}
            result = self.public(row, detail=True, user=user)
        if old_blob:
            (self.blobs / old_blob).unlink(missing_ok=True)
        if delete:
            result['deletion_note'] = '已停止检索并删除资料库副本。原上传文件及历史聊天中的内容保留。'
        return result

    def search(self, user, query, *, limit=8, identity=None):
        self.actor(user)
        query_terms = terms(query)
        matches = []
        with self.store.transaction() as doc:
            for collection in ('documents', 'records'):
                for row in doc.get(collection, {}).values():
                    if (identity and row['id'] != identity) or not self.readable(row, user) or row['status'] in {'outdated', 'failed'}:
                        continue
                    meta = ' '.join([row['title'], row['object_name'], *row.get('aliases', [])])
                    meta_terms = terms(meta)
                    units = self._units(row, collection)
                    for index, chunk in enumerate(units):
                        overlap = query_terms & terms(chunk['text'])
                        matched_meta = query_terms & meta_terms
                        if query_terms and not overlap and not matched_meta:
                            continue
                        score = len(overlap) * 2 + len(matched_meta) * 3
                        url = f"/api/knowledge/{collection}/{row['id']}/source?version={row['version']}&chunk={index}"
                        matches.append({'id': row['id'], 'collection': collection, 'version': row['version'],
                            'title': row['title'], 'object_name': row['object_name'], 'location': chunk['location'],
                            'page': chunk.get('page'), 'text': chunk['text'], 'source_url': url, 'updated_at': row['updated_at'],
                            'status': row['status'], 'warnings': row.get('warnings', []), 'score': score})
        matches.sort(key=lambda row: (row['score'], row['updated_at']), reverse=True)
        return {'query': query, 'items': matches[:max(1, min(limit, 20))],
                'notice': '资料和记录是历史信息；请核对来源和时间。未找到时不要补写家庭事实。'}

    def source(self, user, collection, identity, version, chunk=0):
        with self.store.transaction() as doc:
            row = self._row(doc, collection, identity, user)
            self._version(row, version)
            if row['status'] in {'outdated', 'failed'}:
                raise TaskError('knowledge_source_inactive', status=409)
            units = self._units(row, collection)
            if chunk < 0 or chunk >= len(units):
                raise TaskError('knowledge_chunk_not_found', status=404)
            return {'record': self.public(row, user=user), 'chunk': deepcopy(units[chunk])}

    @staticmethod
    def _units(row, collection):
        if collection == 'documents':
            return row.get('chunks', [])
        return [{'text': row['content'][i:i + 1100], 'location': '信息记录', 'page': None}
                for i in range(0, len(row.get('content', '')), 900)]

    def current_tool_context(self, messages, user):
        """Recheck current-run evidence as well as future requests after ACL changes."""
        result = deepcopy(messages)
        with self.store.transaction() as doc:
            for message in result:
                if message.get('role') != 'tool' or not (message.get('name') or '').startswith('knowledge_'):
                    continue
                try:
                    payload = json.loads(message.get('content') or '{}')
                except ValueError:
                    continue
                output = payload.get('output') or {}
                if not isinstance(output, dict):
                    continue
                candidates = output.get('items', []) if 'items' in output else [output.get('record', output)]
                for evidence in candidates:
                    if not isinstance(evidence, dict) or not evidence.get('id') or 'version' not in evidence:
                        continue
                    collection = evidence.get('collection') or ('documents' if evidence.get('filename') else 'records')
                    row = doc.get(collection, {}).get(evidence['id'])
                    if not row or not self.readable(row, user) or row['version'] != evidence['version']:
                        message['content'] = json.dumps({'status': 'error', 'error': 'knowledge_evidence_changed',
                            'message': '来源已变更、被删除或撤回共享，请重新检索；不得继续引用旧内容。'}, ensure_ascii=False)
                        break
        return result

    def finalize_answer(self, user, content, messages):
        checked = self.current_tool_context(messages, user)
        if any(a.get('content') != b.get('content') for a, b in zip(messages, checked)):
            return '资料或记忆在回答期间发生了变更，请重新查询以获取当前有效来源。'
        sources = {}
        for message in checked:
            if message.get('role') != 'tool' or message.get('name') != 'knowledge_search':
                continue
            try:
                payload = json.loads(message.get('content') or '{}')
            except ValueError:
                continue
            for item in (payload.get('output') or {}).get('items', []):
                if item.get('source_url') and item['source_url'] not in sources:
                    sources[item['source_url']] = item
        missing = [item for url, item in sources.items() if url not in content]
        if missing:
            def label(value):
                return str(value).replace('[', '（').replace(']', '）').replace('\n', ' ')
            content += '\n\n本次检索来源：\n\n' + '\n'.join(
                f"- [{label(item['title'])} · {label(item['location'])}]({item['source_url']}) · {item['updated_at'][:10]}"
                for item in missing[:3])
        return content
