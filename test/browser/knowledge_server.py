"""Temporary 011 browser environment. All data and model outputs are synthetic."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
data = Path(os.environ['KNOWLEDGE_TEST_DATA'])
for key, path in {'HOME_DATA_DIR': 'home', 'GENERATED_FILES_DIR': 'files', 'CONVERSATION_DIR': 'sessions',
                  'RUN_DIR': 'runs', 'USER_FILE': 'users.json'}.items():
    os.environ[key] = str(data / path)
os.environ['HOME_REMINDER_DELIVERY_ENABLED'] = 'false'
import web_app as w
from agent_runtime import AgentModelResponse, ToolCall

alice = w.user_store.create_user(username='library011', password='Library011-test', display_name='资料试用', role='admin')
bob = w.user_store.create_user(username='library011b', password='Library011-test', display_name='家人试用', role='user')
for user, identity in [(alice, 'A'), (bob, 'B')]:
    w.family_members.update(identity, {'user_id': user['id'], 'display_name': user['display_name']}, alice)


class FakeLLM:
    model = 'knowledge-browser-stub'
    context_window = 32768

    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass

    async def achat_with_tools(self, messages, tools):
        last_user = max(i for i, m in enumerate(messages) if m['role'] == 'user')
        current = messages[last_user:]
        results = [m for m in current if m['role'] == 'tool' and m.get('name', '').startswith('knowledge_')]
        if results:
            payload = json.loads(results[-1]['content'])
            if payload.get('status') != 'success':
                return AgentModelResponse(content='操作未完成，请检查保存条件。')
            output = payload['output']
            if 'items' in output:
                if not output['items']:
                    return AgentModelResponse(content='没有找到相关记录。')
                item = output['items'][0]
                return AgentModelResponse(content=f"{item['text']}\n\n[核对来源]({item['source_url']})")
            return AgentModelResponse(content='已记住，个人可见。')
        raw = str(current[0].get('content', ''))
        if '记住' in raw:
            return AgentModelResponse(tool_calls=[ToolCall('remember', 'knowledge_record_save', {'title': '备用钥匙位置', 'content': '备用钥匙在玄关第二层抽屉'})])
        if '说明书' in raw or '钥匙' in raw:
            return AgentModelResponse(tool_calls=[ToolCall('search', 'knowledge_search', {'query': raw})])
        return AgentModelResponse(content='我已看过材料。你可以选择保存到资料，换个对话继续问。')

    async def astream_with_tools(self, messages, tools):
        yield {'type': 'done', 'response': await self.achat_with_tools(messages, tools)}


w._new_llm_client = FakeLLM
import uvicorn
uvicorn.run(w.app, host='127.0.0.1', port=int(os.environ['KNOWLEDGE_TEST_API_PORT']), log_level='warning')
