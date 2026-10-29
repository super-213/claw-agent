"""Explicit dollar invocation must reach the final SDK request in both chat paths."""
import json
from types import SimpleNamespace as N
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agent_runtime import RunStore
from services import ConversationStore
from services.llm_client import LLMClient
from skills.registry import SkillRegistry
import web_app


@pytest.mark.parametrize('streaming', [False, True])
def test_registered_skill_list_and_explicit_context_reach_sdk(tmp_path, monkeypatch, streaming):
    skills = SkillRegistry(str(tmp_path/'configured-skills'))
    skills.create_skill('demo', '# Demo\nUnique explicit skill instructions')
    monkeypatch.setattr(web_app, 'skill_registry', skills)
    monkeypatch.setattr(web_app, 'store', ConversationStore(tmp_path/'conversations'))
    monkeypatch.setattr(web_app, 'run_store', RunStore(tmp_path/'runs'))
    monkeypatch.setattr(web_app, 'GENERATED_DIR', tmp_path/'files')
    monkeypatch.setitem(web_app.app.config, 'TESTING', True)
    route = AsyncMock(side_effect=AssertionError('explicit skill must bypass intent model'))
    monkeypatch.setattr(web_app.intent_router, 'route', route)
    payloads = []
    async def create(**kwargs):
        payloads.append(kwargs)
        if kwargs.get('stream'):
            async def chunks():
                yield N(choices=[N(delta=N(content='skill used', tool_calls=[]), finish_reason='stop')])
            return chunks()
        return N(choices=[N(message=N(content='skill used', tool_calls=[]), finish_reason='stop')])
    monkeypatch.setattr(LLMClient, 'async_client', property(lambda self: N(chat=N(completions=N(create=create)))))
    with TestClient(web_app.app) as client:
        listed = client.get('/api/skills').json()['skills']
        assert listed[0]['name'] == 'demo' and 'Demo' in listed[0]['summary']
        session = client.post('/api/sessions').json()['id']
        response = client.post('/api/chat/stream' if streaming else '/api/chat', json={'session_id':session,'message':'$ demo 帮我处理'})
        assert response.status_code == 200
        done = next(json.loads(line) for line in response.text.splitlines() if json.loads(line).get('type') == 'done') if streaming else response.json()
        assert done['run_status'] == 'completed'
        messages = payloads[-1]['messages']
        assert any('Unique explicit skill instructions' in m['content'] for m in messages if m['role'] == 'system')
        assert next(m for m in messages if m['role'] == 'user')['content'] == '帮我处理'
        assert web_app.run_store.load(done['run_id'])['active_skill'] == 'demo'
        route.assert_not_called()
