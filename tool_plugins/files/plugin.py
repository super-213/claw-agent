from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        services = context.services
        files = services['files']
        registry.register(ToolDefinition(
            name="file_read",
            description="Read a UTF-8 text file from the project or generated-files directory. Uploaded images are already visual inputs; do not use this tool to view images.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "max_chars": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=lambda args: files.read(args),
            replay_policy="revalidate",
            idempotent=True,
            max_retries=1,
        ))

        registry.register(ToolDefinition(
            name="file_write",
            description="Write UTF-8 text inside the generated-files directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1, "maxLength": 1024},
                    "content": {"type": "string"},
                    "mode": {"type": "string", "enum": ["create", "overwrite", "append"]},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            handler=lambda args: files.write(args),
            risk_level="medium",
            approval_policy=lambda args: files.needs_approval(args),
        ))

        return registry.list()

def create_plugin():
    return Plugin()
