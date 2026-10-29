import hashlib
import json
from dataclasses import replace
from agent_runtime.registry import ToolRegistry

class Plugin:
    def tools(self, context):
        adapter = context.services['mcp']
        registry = ToolRegistry()
        adapter.register(registry, context.get_user, context.services['family_members'], context.get_execution_context)
        revision = hashlib.sha256(json.dumps(adapter.configs, sort_keys=True).encode()).hexdigest()
        return [replace(tool, replay_policy='revalidate', plugin_source={'provider_digest': revision})
                for tool in registry.list()]

def create_plugin():
    return Plugin()
