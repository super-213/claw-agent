"""Do not reuse historical library answers after deletion or access changes.

Stored history remains visible to its original reader. Model input discards old
derived answers and summaries and obtains current evidence through tools again.
"""
from copy import deepcopy


def has_knowledge(messages):
    return any((message.get('name') or '').startswith('knowledge_') or any(
        (call.get('function', {}).get('name') or '').startswith('knowledge_')
        for call in message.get('tool_calls', [])) for message in messages)


def fresh_knowledge_context(messages):
    result = deepcopy(messages)
    last_user = max((i for i, m in enumerate(result) if m.get('role') == 'user'), default=-1)
    tainted = False
    for index, message in enumerate(result):
        if index >= last_user:
            break
        if has_knowledge([message]):
            tainted = True
        if not tainted:
            continue
        if message.get('role') in {'assistant', 'tool'}:
            message['content'] = '[历史资料与记忆回答仅保留在界面；本次必须调用 knowledge_search 获取当前授权来源。]'
            if message.get('tool_calls'):
                for call in message['tool_calls']:
                    call['function']['arguments'] = '{}'
    return result
