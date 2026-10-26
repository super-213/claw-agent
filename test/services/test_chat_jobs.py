import asyncio
import json

import pytest

from services.chat_jobs import BackgroundChat, ChatJobStore
from services.task_store import TaskError


def test_reader_disconnect_does_not_cancel_generation_and_request_is_deduplicated(tmp_path):
    async def scenario():
        store = ChatJobStore(tmp_path / 'jobs.sqlite3')
        engine = BackgroundChat(store)
        done = asyncio.Event()
        calls = []
        async def source():
            calls.append('started')
            yield json.dumps({'type': 'model_start', 'run_id': 'run-1'})
            await asyncio.sleep(.15)
            yield json.dumps({'type': 'model_done', 'content': 'answer'})
            yield json.dumps({'type': 'done', 'run_id': 'run-1', 'run_status': 'completed'})
            done.set()
        try:
            job = await engine.submit('alice', 'session', 'request-0001', {'message': 'question'}, source)
            same = await engine.submit('alice', 'session', 'request-0001', {'message': 'question'}, source)
            assert same['id'] == job['id']
            reader = engine.stream(job['id'], 'alice')
            await anext(reader)
            await reader.aclose()
            await asyncio.wait_for(done.wait(), 2)
            assert store.get(job['id'], 'alice')['status'] == 'succeeded'
            assert calls == ['started']
            with pytest.raises(TaskError) as exc:
                store.get(job['id'], 'bob')
            assert exc.value.status == 404
            with pytest.raises(TaskError) as exc:
                await engine.submit('alice', 'session', 'request-0001', {'message': 'different'}, source)
            assert exc.value.code == 'request_conflict'
        finally:
            await engine.stop()
    asyncio.run(scenario())


def test_restart_marks_work_interrupted_and_does_not_repeat_tools(tmp_path):
    async def scenario():
        store = ChatJobStore(tmp_path / 'jobs.sqlite3')
        engine = BackgroundChat(store)
        started = asyncio.Event()
        async def source():
            yield {'type': 'model_start', 'run_id': 'durable-checkpoint'}
            started.set()
            await asyncio.sleep(30)
        job = await engine.submit('alice', 'session', 'request-0002', {'message': 'question'}, source)
        await started.wait()
        await engine.stop()
        restarted = BackgroundChat(ChatJobStore(store.path))
        try:
            await restarted.start()
            saved = store.get(job['id'], 'alice')
            assert saved['status'] == 'interrupted'
            assert saved['run_id'] == 'durable-checkpoint'
            assert not restarted.tasks
        finally:
            await restarted.stop()
    asyncio.run(scenario())


def test_busy_session_cancel_and_worker_ownership(tmp_path):
    async def scenario():
        store = ChatJobStore(tmp_path / 'jobs.sqlite3')
        engine = BackgroundChat(store)
        other = BackgroundChat(ChatJobStore(store.path))
        async def source():
            yield {'type': 'model_start'}
            await asyncio.sleep(30)
        try:
            job = await engine.submit('alice', 'session', 'request-0003', {}, source)
            with pytest.raises(TaskError) as exc:
                await engine.submit('bob', 'session', 'request-0004', {}, source)
            assert exc.value.code == 'session_busy'
            assert 'job_id' not in exc.value.details
            with pytest.raises(RuntimeError):
                await other.start()
            await engine.cancel(job['id'], 'alice')
            assert store.get(job['id'], 'alice')['status'] == 'cancelled'
        finally:
            await engine.stop()
    asyncio.run(scenario())


def test_waiting_for_uncertain_tool_is_not_a_success_and_continuation_releases_session(tmp_path):
    store = ChatJobStore(tmp_path / 'jobs.sqlite3')
    job, _ = store.create('alice', 'session', 'request-0001', {'message': 'question'})
    store.append(job['id'], {'type': 'error', 'message': '工具结果需要确认'})
    assert store.get(job['id'], 'alice')['status'] == 'queued'
    store.append(job['id'], {'type': 'done', 'run_status': 'waiting_user', 'run_id': 'run-1'})
    assert store.get(job['id'], 'alice')['status'] == 'waiting_user'
    with pytest.raises(TaskError):
        store.create('alice', 'session', 'request-0002', {'message': 'new question'})
    store.resolve_waiting('run-1', 'alice', 'interrupted')
    resumed, _ = store.create('alice', 'session', 'request-0003', {'action': 'resume', 'run_id': 'run-1'}, run_id='run-1')
    assert store.get(job['id'], 'alice')['status'] == 'continued'
    store.append(resumed['id'], {'type': 'done', 'run_status': 'completed'})
    next_job, _ = store.create('alice', 'session', 'request-0004', {'message': 'next question'})
    assert next_job['status'] == 'queued'


def test_failed_approval_token_preserves_recoverable_waiting_state(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from contextlib import asynccontextmanager
    from services import chat_runner

    @asynccontextmanager
    async def client():
        yield

    async def invalid_token(*args, **kwargs):
        raise PermissionError('invalid_approval_token')
        yield  # Async generator interface used by the real orchestrator.

    orchestrator = SimpleNamespace(
        conversation=SimpleNamespace(get_messages=lambda: []),
        llm_client=client(), run={'status': 'waiting_approval'},
        resume_after_approval_stream_async=invalid_token,
    )
    monkeypatch.setattr(chat_runner, 'load_session_conversation', lambda *args: None)
    store = ChatJobStore(tmp_path / 'jobs.sqlite3')
    job, _ = store.create('alice', 'session', 'request-0001', {'action': 'approval'}, run_id='run-1')

    async def scenario():
        async for encoded in chat_runner.stream_run_approval_events(
            store=SimpleNamespace(load_session=lambda _: {}),
            build_orchestrator=lambda: orchestrator,
            session_run_locks=chat_runner.SessionRunLocks(), session_id='session',
            run_id='run-1', approval_token='stale-token', approved=True,
        ):
            store.append(job['id'], json.loads(encoded))
    asyncio.run(scenario())
    store.finish(job['id'])
    assert store.get(job['id'], 'alice')['status'] == 'waiting_approval'
    with pytest.raises(TaskError):
        store.create('alice', 'session', 'request-0002', {'message': 'new question'})
