from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry
from agent_runtime import builtin_tools as io

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        services = context.services
        executor = services['executor']
        if context.runtime == "cli" and not services.get("family_mode", False):
            registry.register(ToolDefinition(
                name="shell_execute",
                description=(
                    "Execute one non-interactive shell command in the generated-files directory. "
                    "Prefer dedicated datetime, file and HTTP tools when available."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"command": {"type": "string", "minLength": 1, "maxLength": 20000}},
                    "required": ["command"],
                    "additionalProperties": False,
                },
                handler=lambda args: io._shell_execute(args, executor),
                risk_level="high",
                approval_policy=io._shell_needs_approval,
                timeout=max(1, executor.timeout + 2),
            ))

        return registry.list()

def create_plugin():
    return Plugin()
