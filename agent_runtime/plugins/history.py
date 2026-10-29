"""Conservative fallback when a historical tool is removed or needs fresh authority."""
from copy import deepcopy


class HistoricalToolPolicy:
    def __init__(self, registry):
        self.registry = registry

    def _sensitive(self, message):
        names = [message.get('name')] if message.get('role') == 'tool' else []
        names += [c.get('function', {}).get('name') for c in message.get('tool_calls', [])]
        for name in filter(None, names):
            if name == 'tool_load':  # per-run host control, never a removed business capability
                continue
            definition = self.registry.get(name)
            if definition is None or definition.replay_policy == 'revalidate':
                return True
        return False

    def preserve_history(self, messages):
        return any(self._sensitive(message) for message in messages)

    avoid_memory = preserve_history

    def prepare_history(self, messages):
        result = deepcopy(messages)
        last_user = max((i for i, m in enumerate(result) if m.get('role') == 'user'), default=-1)
        tainted = False
        for message in result[:last_user]:
            tainted = tainted or self._sensitive(message)
            if tainted and message.get('role') in {'assistant', 'tool'}:
                message['content'] = '[历史工具证据需要重新授权；本轮请调用当前可用工具重新查询，不能依赖旧结果。]'
                message.pop('ui_blocks', None)
                for call in message.get('tool_calls', []):
                    call.get('function', {})['arguments'] = '{}'
        return result
