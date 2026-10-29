from agent_runtime.models import ToolDefinition
from agent_runtime.registry import ToolRegistry

class Plugin:
    def tools(self, context):
        registry = ToolRegistry()
        services = context.services
        skill_registry = services['skills']
        if skill_registry is not None:
            registry.register(ToolDefinition(
                name="skill_load",
                description=(
                    "Load the full instructions for one capability package after selecting it "
                    "from the compact skill catalog."
                ),
                input_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string", "minLength": 1}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=lambda args: skill_registry.load_for_runtime(
                    str(args["name"]),
                    available_tools=(
                        {tool.name for tool in services['registry'].list()} | set(services['registry'].aliases())
                    ),
                    automatic=True,
                ),
                idempotent=True,
                max_retries=1,
                capabilities=("skill:read",),
            ))

        actor = context.get_user()
        if services.get('skill_installer') and (context.runtime == 'cli' or (actor and actor.get('role') == 'admin')):
            def install(args):
                actor = context.get_user()
                if context.runtime == 'web' and not (actor and actor.get('role') == 'admin' and actor.get('status') == 'active'):
                    raise PermissionError('skill_install_requires_admin')
                result = services['skill_installer'].install(args)
                result['missing_tools'] = sorted(set(result['required_tools']) - {t.name for t in services['registry'].list()} - set(services['registry'].aliases()))
                return result
            registry.register(ToolDefinition(
                name='skill_install',
                description='从公开 HTTPS 链接安装 Skill 到配置的技能目录并注册。支持 GitHub 技能目录、SKILL.md 链接；不覆盖已有技能，不执行脚本或安装依赖。仅在用户明确要求安装时调用。',
                input_schema={'type': 'object', 'properties': {
                    'url': {'type': 'string', 'minLength': 1, 'maxLength': 4096},
                    'name': {'type': 'string', 'pattern': '^[A-Za-z0-9_-]+$'},
                }, 'required': ['url'], 'additionalProperties': False},
                handler=install, risk_level='medium',
                capabilities=('skill:install', 'network:public-read'), timeout=180,
            ))

        return registry.list()

def create_plugin():
    return Plugin()
