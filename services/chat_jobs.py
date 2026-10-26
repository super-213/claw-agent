"""Durable web chat jobs. HTTP readers never own the producer's lifetime."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .task_store import TaskError

ACTIVE = ('queued', 'running')
background_session = ContextVar('background_chat_session', default=None)


class ChatJobStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, session_id TEXT NOT NULL,
                request_id TEXT NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL,
                status TEXT NOT NULL, run_id TEXT, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, read_at REAL, error TEXT, last_sequence INTEGER DEFAULT 0,
                UNIQUE(user_id, request_id));
              CREATE UNIQUE INDEX IF NOT EXISTS one_active_chat ON jobs(session_id)
                WHERE status IN ('queued','running');
              CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, data TEXT NOT NULL);
              CREATE INDEX IF NOT EXISTS events_job ON events(job_id, sequence);
              CREATE TABLE IF NOT EXISTS chat_devices (
                id TEXT PRIMARY KEY, endpoint_hash TEXT UNIQUE NOT NULL, user_id TEXT NOT NULL,
                auth_hash TEXT NOT NULL, subscription TEXT NOT NULL, enabled INTEGER NOT NULL,
                updated_at REAL NOT NULL, last_error TEXT);
              CREATE TABLE IF NOT EXISTS chat_outbox (
                job_id TEXT NOT NULL, device_id TEXT NOT NULL, status TEXT NOT NULL,
                attempts INTEGER DEFAULT 0, next_at REAL NOT NULL, last_error TEXT,
                PRIMARY KEY(job_id, device_id));
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def public(row):
        return {key: row[key] for key in ('id', 'session_id', 'status', 'run_id', 'created_at', 'updated_at', 'error', 'last_sequence')}

    def get(self, job_id, user_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=? AND user_id=?', (job_id, user_id)).fetchone()
            if not row:
                raise TaskError('job_not_found', '任务不存在或无权访问。', status=404)
            return dict(row)

    def latest(self, session_id, user_id):
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE session_id=? AND user_id=? ORDER BY created_at DESC LIMIT 1', (session_id, user_id)).fetchone()
            return self.public(row) if row else None

    def create(self, user_id, session_id, request_id, payload, *, run_id=None):
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 128:
            raise TaskError('invalid_request_id', '请提供 8 至 128 位的请求标识。')
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        if len(encoded.encode()) > 2 * 1024 * 1024:
            raise TaskError('request_too_large', '问题内容过大，请使用文件附件。', status=413)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        now = time.time()
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE user_id=? AND request_id=?', (user_id, request_id)).fetchone()
            if row:
                if row['digest'] != digest or row['session_id'] != session_id:
                    raise TaskError('request_conflict', '同一个请求标识不能用于不同内容。', status=409)
                return self.public(row), False
            active = db.execute("SELECT id,user_id FROM jobs WHERE session_id=? AND status IN ('queued','running')", (session_id,)).fetchone()
            if active:
                detail = {'job_id': active['id']} if active['user_id'] == user_id else {}
                raise TaskError('session_busy', '当前对话仍有任务正在执行。', status=409, **detail)
            if payload.get('action') not in ('resume', 'approval'):
                waiting = db.execute("SELECT id FROM jobs WHERE session_id=? AND status IN ('waiting_approval','waiting_user') ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()
                if waiting:
                    raise TaskError('session_waiting_for_confirmation', '请先处理对话中的待确认操作，再发送新问题。', status=409)
            if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0] >= 16 or db.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status IN ('queued','running')", (user_id,)).fetchone()[0] >= 4:
                raise TaskError('too_many_jobs', '正在执行的任务较多，请稍后再试。', status=429)
            job_id = uuid.uuid4().hex
            db.execute('INSERT INTO jobs(id,user_id,session_id,request_id,digest,payload,status,run_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)', (job_id, user_id, session_id, request_id, digest, encoded, 'queued', run_id, now, now))
            if payload.get('action') in ('approval', 'resume') and run_id:
                db.execute("UPDATE jobs SET status='continued',updated_at=? WHERE run_id=? AND user_id=? AND id<>? AND status IN ('waiting_approval','waiting_user','interrupted')", (now, run_id, user_id, job_id))
                db.execute("UPDATE chat_outbox SET status='read' WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE run_id=? AND user_id=? AND status='continued')", (run_id, user_id))
            return self.public(db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()), True

    def recover(self):
        now = time.time()
        with self.db() as db:
            db.execute("UPDATE jobs SET status='interrupted', error='服务器重启，任务已中断；请核对记录后继续。', updated_at=? WHERE status IN ('queued','running')", (now,))
            db.execute("UPDATE chat_outbox SET status='pending' WHERE status='sending'")
            # Keep job identifiers/deduplication records for 30 days, events for 7 days.
            db.execute('DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE updated_at<? AND status NOT IN (\'queued\',\'running\'))', (now - 7 * 86400,))
            db.execute("UPDATE chat_outbox SET status='expired' WHERE status IN ('pending','sending') AND job_id IN (SELECT id FROM jobs WHERE updated_at<?)", (now - 86400,))
            db.execute("DELETE FROM chat_outbox WHERE job_id IN (SELECT id FROM jobs WHERE updated_at<? AND status NOT IN ('queued','running'))", (now - 30 * 86400,))
            db.execute("DELETE FROM jobs WHERE updated_at<? AND status NOT IN ('queued','running')", (now - 30 * 86400,))

    def is_active(self, session_id):
        with self.db() as db:
            return bool(db.execute("SELECT 1 FROM jobs WHERE session_id=? AND status IN ('queued','running')", (session_id,)).fetchone())

    def running(self, job_id):
        with self.db() as db:
            db.execute("UPDATE jobs SET status='running',updated_at=? WHERE id=? AND status='queued'", (time.time(), job_id))

    def append(self, job_id, event):
        now = time.time()
        with self.db() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row['status'] not in ACTIVE:
                return
            status, error = row['status'], row['error']
            if event['type'] == 'error':
                error = str(event.get('message') or '生成失败')[:1000]
            elif event['type'] == 'done':
                state = event.get('run_status')
                status = {'awaiting_approval': 'waiting_approval', 'waiting_approval': 'waiting_approval', 'waiting_user': 'waiting_user', 'interrupted': 'interrupted', 'cancelled': 'cancelled', 'failed': 'failed'}.get(state, 'succeeded' if state in (None, 'completed') else 'failed')
                if status == 'failed':
                    error = '任务没有正常完成，请查看对话中的执行记录。'
            sequence = db.execute('INSERT INTO events(job_id,data) VALUES(?,?)', (job_id, json.dumps(event, ensure_ascii=False))).lastrowid
            db.execute('UPDATE jobs SET status=?,run_id=COALESCE(?,run_id),updated_at=?,error=?,last_sequence=? WHERE id=?', (status, event.get('run_id'), now, error, sequence, job_id))
            if status in ('succeeded', 'waiting_approval', 'waiting_user', 'failed'):
                db.execute("INSERT OR IGNORE INTO chat_outbox(job_id,device_id,status,next_at) SELECT ?,id,'pending',? FROM chat_devices WHERE user_id=? AND enabled=1", (job_id, now + 5, row['user_id']))
            if event['type'] != 'model_delta':
                db.execute('DELETE FROM events WHERE job_id=? AND sequence < COALESCE((SELECT sequence FROM events WHERE job_id=? ORDER BY sequence DESC LIMIT 1 OFFSET 19999),0)', (job_id, job_id))

    def interrupt(self, job_id, reason='任务已停止，请核对已保存的结果。', status='interrupted'):
        with self.db() as db:
            allowed = "('queued','running','interrupted')" if status == 'cancelled' else "('queued','running')"
            db.execute(f"UPDATE jobs SET status=?,error=?,updated_at=? WHERE id=? AND status IN {allowed}", (status, reason, time.time(), job_id))

    def finish(self, job_id):
        with self.db() as db:
            row = db.execute('SELECT status,error FROM jobs WHERE id=?', (job_id,)).fetchone()
        if row and row['status'] in ACTIVE:
            if row['error']:
                self.append(job_id, {'type': 'done', 'run_status': 'failed', 'message': row['error']})
            else:
                self.interrupt(job_id, '执行未返回最终状态，请核对已保存记录。')

    def resolve_waiting(self, run_id, user_id, status):
        with self.db() as db:
            db.execute("UPDATE jobs SET status=?,updated_at=? WHERE run_id=? AND user_id=? AND status IN ('waiting_user','waiting_approval')", (status, time.time(), run_id, user_id))
            db.execute("UPDATE chat_outbox SET status='read' WHERE status='pending' AND job_id IN (SELECT id FROM jobs WHERE run_id=? AND user_id=?)", (run_id, user_id))

    def events(self, job_id, after):
        with self.db() as db:
            rows = db.execute('SELECT sequence,data FROM events WHERE job_id=? AND sequence>? ORDER BY sequence LIMIT 200', (job_id, after)).fetchall()
            return [dict(json.loads(row['data']), sequence=row['sequence'], job_id=job_id) for row in rows]

    def read(self, job_id, user_id):
        self.get(job_id, user_id)
        with self.db() as db:
            db.execute('UPDATE jobs SET read_at=? WHERE id=?', (time.time(), job_id))
            db.execute("UPDATE chat_outbox SET status='read' WHERE job_id=? AND status='pending'", (job_id,))


class BackgroundChat:
    def __init__(self, store: ChatJobStore, notifications=None):
        self.store = store
        self.notifications = notifications
        self.tasks = {}
        self.worker = None
        self.lock = None

    async def start(self):
        if self.lock:
            return
        lock = self.store.path.with_suffix('.worker.lock').open('a+')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            raise RuntimeError('聊天后台任务要求单个 Uvicorn worker，另一个进程已持有任务锁。')
        self.lock = lock
        await asyncio.to_thread(self.store.recover)
        if self.notifications:
            self.worker = asyncio.create_task(self._delivery_loop())

    async def submit(self, user_id, session_id, request_id, payload, factory, *, run_id=None):
        await self.start()
        job, created = await asyncio.to_thread(self.store.create, user_id, session_id, request_id, payload, run_id=run_id)
        if created:
            task = asyncio.create_task(self._produce(job['id'], session_id, factory))
            self.tasks[job['id']] = task
            task.add_done_callback(lambda _task: self.tasks.pop(job['id'], None))
        return job

    async def _produce(self, job_id, session_id, factory):
        token = background_session.set(session_id)
        try:
            await asyncio.to_thread(self.store.running, job_id)
            async for encoded in factory():
                event = json.loads(encoded) if isinstance(encoded, str) else encoded
                await asyncio.to_thread(self.store.append, job_id, event)
            await asyncio.to_thread(self.store.finish, job_id)
        except asyncio.CancelledError:
            await asyncio.to_thread(self.store.interrupt, job_id)
            raise
        except Exception:
            await asyncio.to_thread(self.store.append, job_id, {'type': 'error', 'message': '任务执行失败，请打开对话查看已保存记录。'})
            await asyncio.to_thread(self.store.finish, job_id)
        finally:
            background_session.reset(token)

    async def stream(self, job_id, user_id, after=0):
        last_heartbeat = time.monotonic()
        while True:
            job = await asyncio.to_thread(self.store.get, job_id, user_id)
            events = await asyncio.to_thread(self.store.events, job_id, after)
            for event in events:
                after = event['sequence']
                yield json.dumps(event, ensure_ascii=False) + '\n'
            if job['status'] not in ACTIVE and not events:
                # Expired event histories still expose a durable status via the job API.
                if job['status'] in ('interrupted', 'cancelled'):
                    yield json.dumps({'type': 'error', 'message': job['error'] or '任务已停止'}, ensure_ascii=False) + '\n'
                return
            if time.monotonic() - last_heartbeat > 10:
                yield '{"type":"heartbeat"}\n'
                last_heartbeat = time.monotonic()
            await asyncio.sleep(.15)

    async def cancel(self, job_id, user_id):
        self.store.get(job_id, user_id)
        task = self.tasks.get(job_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(self.store.interrupt, job_id, '用户已停止任务。', 'cancelled')

    async def _delivery_loop(self):
        while True:
            try:
                await asyncio.to_thread(self.notifications.deliver_due)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Durable outbox remains available for the next attempt.
            await asyncio.sleep(2)

    async def stop(self):
        if self.worker:
            self.worker.cancel()
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, *([self.worker] if self.worker else []), return_exceptions=True)
        self.tasks.clear()
        self.worker = None
        if self.lock:
            self.lock.close()
            self.lock = None
