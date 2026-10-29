# 工具插件开发

工具注册、参数定义和业务扩展均由本目录的插件提供。`builtin_tools.build_tool_registry` 保留为 Web/CLI 共用装配入口及旧安全 helper 的兼容导出，不再集中定义各工具 schema。插件是管理员安装的可信 Python 代码，不是安全沙箱。

## 已迁移的工具族

| 包 | 能力 | 可用范围 |
| --- | --- | --- |
| datetime | 日期与时区 | Web / CLI |
| files | 文本读写、用户文件归属 | Web / CLI |
| public_http | 公网 GET/HEAD，保留域名与私网访问检查 | Web / CLI |
| shell | 命令执行与原沙箱、审批策略 | CLI；Web 不注册 |
| skills | `skill_load` 控制桥接、按需 `skill_install` | Web / CLI，需要技能注册表 |
| attached | 显式连接的浏览器、应用回调 | 仅宿主实际提供回调时 |
| home_assistant | 白名单设备查询与控制 | 配置成功且存在允许实体时 |
| family_tasks | 日程、备忘、草稿及事项操作 | Web，需要家庭服务 |
| board | 留言板与便笺 | Web，需要留言板服务 |
| knowledge | 资料、个人记录与来源 | Web，需要知识库服务 |
| mcp | 受限 stdio 只读工具来源 | Web，需要 MCP 配置和用户授权 |

宿主只对代码库内已审核包设置默认启用和权限基线；这是宿主策略，不读取插件自己声明来授予权限。其他插件必须通过配置显式启用。需要的宿主服务缺失时不注册；`attached`、智能家居及 Skill 控制入口可以根据实际连接状态提供声明中的部分工具。

## 接入一个普通工具

1. 新建 `tool_plugins/<id>/plugin.json` 与 `plugin.py`，实现工厂 `create_plugin()`。
2. `tools(context)` 返回 `ToolDefinition`；在 `tool_metadata` 声明稳定工具名、分组及关键词。参数 schema 只维护在工具定义中。
3. 在本地 `config/tool-plugins.toml` 中配置 `[plugins.<id>] enabled = true` 和 `permissions = [...]`。可通过 `TOOL_PLUGINS_CONFIG` 或诊断命令的 `--config` 指定文件。
4. 在部署环境预装依赖，重启后端。普通扩展无须修改主入口、编排器、中央分组表或模型配置。

```json
{
  "id": "example", "version": "1.0.0", "api_version": 1,
  "entrypoint": "plugin.py:create_plugin", "runtimes": ["web", "cli"],
  "requires_services": [], "requested_permissions": [],
  "tool_metadata": {"example_double": {"group": "math", "keywords": ["翻倍", "double"]}},
  "aliases": {"example.double": "example_double"}
}
```

```python
from agent_runtime.models import ToolDefinition

class Plugin:
    def tools(self, context):
        return [ToolDefinition(
            name="example_double", description="Double an integer",
            input_schema={"type": "object", "properties": {"n": {"type": "integer"}},
                          "required": ["n"], "additionalProperties": False},
            handler=lambda args: {"value": args["n"] * 2}, idempotent=True)]

def create_plugin():
    return Plugin()
```

业务工具参数仍由 `tool_load` 按需提供，首轮只暴露加载入口。分类与关键词来自清单；不限制匹配数或任务内保留数，遵守 [工具加载约定](../docs/tool-loading.md)。Skill 的白名单只收窄工具权限，不启用插件或授予服务。

## 宿主依赖与授权

`ToolBindingContext` 由宿主创建：包含 Web/CLI 范围、身份访问器、执行上下文访问器和授权检查。每个插件只收到清单 `requires_services` 与 `optional_services` 声明的服务映射；外部插件还必须在启用配置中通过 `services = [...]` 获得管理员显式授权；新增宿主服务需要显式实现对应安全边界。

- 文件插件使用 `FileToolAccess`。先解码、规范化最终路径，再校验受保护目录和上传/生成文件归属；写入只在该用户目录，沿用文件授权记录与动态覆盖审批。
- HTTP 插件通过宿主的公网访问服务执行；保留私网、回环、DNS/Fake-IP 和重定向限制。Home Assistant 单独绑定，不借此放开公网工具访问内网。
- 工具执行和审批后继续均复核插件开关、权限、当前账号及会话访问权；不能仅从传给模型的工具列表推断执行授权。
- 模型参数不能决定当前 actor、session、branch 或文件授权。真实凭据不进入清单、schema、模型输入或诊断响应。
- `requires_services` 检查与只读映射是 API 约束，不是 Python 代码隔离；插件代码不可信时需采用后续隔离执行方案。

## 可选业务扩展接口

插件可实现 `extensions(context)`，返回每次运行独立创建的扩展对象；宿主按 `extension_order`（默认 0）和目录顺序固定调度。普通工具无需实现任何钩子。

| 方法 | 职责 |
| --- | --- |
| `system_messages()` | 增加本次选择等动态上下文 |
| `preserve_history(messages)` / `prepare_history(messages)` | 防止用压缩摘要保留失效证据，处理历史模型输入 |
| `filter_context(messages)` | 在请求前校验当前权限和资料版本，异常不能静默跳过 |
| `avoid_memory(messages)` | 禁止把有独立授权/生命周期的事实写入通用记忆 |
| `defer_output()` | 校验前缓冲模型文本；在验证通过后发送最终内容 |
| `finalize_answer(content, messages)` | 基于当前证据添加来源或替换无效回答 |
| `validate_answer(content, messages, retries)` | 返回 `(content, feedback)`；首个拒绝立即生效，后续钩子不能覆盖 |
| `normalize_response(content, calls)` | 抑制未执行工具前的提前保存回执 |
| `resource_events(result)` | 生成沿用现有协议的资源刷新事件 |

为保持旧回答校验语义，任务扩展顺序为 100、留言板为 200、知识为 300；通用历史保护优先执行。

宿主最多进行两次回答修正，仍不通过则失败关闭，不发布未校验的最终回答。钩子不自建模型循环，不绕过工具审批；涉及权限的服务读取仍使用授权执行上下文。动态提示和结果文案检查只使用宿主已准备的本次选择，不提前执行工具专属访问检查。

卡片由工具定义的 `card_kind` / `card_resource_types` 声明，通用 `CardPresenter` 仍只输出白名单引用字段；任意 HTML、脚本和回调不会进入卡片。全新卡片种类仍需前端适配器，不支持动态前端代码注入。

## 恢复、停用与兼容

`replay_policy` 与幂等重试分开：`cache` 表示可复用已完成调用结果，`revalidate` 表示需重新调用有权限与版本检查的 handler。文件读取、公网读取、设备状态、家庭业务和 MCP 使用后者；业务写操作沿用自身操作账本与幂等键防止重复副作用。未知是否完成的非幂等调用继续保留人工核对流程。

Run 保存 `plugin_snapshot`：版本、包内容、schema、配置摘要；MCP 额外保存来源配置摘要。恢复时不兼容或缺失插件会拒绝继续，需要恢复兼容配置后重试。旧 Run 缺少来源字段时保留兼容；P1 时间插件的空配置摘要保持不变。

停用只影响 Agent 工具入口，现有业务页面和 HTTP API 仍有各自的权限与生命周期。

停用或移除插件后，历史中需要重新授权的工具证据由宿主通用历史策略处理，不会因插件钩子消失而直接泄露给新模型请求，也不会写入通用记忆。历史界面与持久化树不被改写。执行中的线程仍不能依靠 Python 超时保证终止，进程隔离与完整热重载属于 P5。

## 诊断与 MCP

```bash
python3 scripts/tool_plugins.py list --runtime web
python3 scripts/tool_plugins.py validate --runtime cli
python3 scripts/tool_plugins.py validate --config /absolute/path/to/tool-plugins.toml
```

这些命令只校验清单和目录，不导入插件，不执行工具，不联系 MCP；不能据此宣称凭据或远端服务可用。返回状态区分发现、禁用、运行范围不符及清单错误，并显示上次绑定的安全错误码。

管理员可访问 `GET /api/runtime/plugins`；工具的实际可用清单仍通过 `GET /api/runtime/tools` 检查。诊断信息不包含凭据、用户请求或远端不可信描述。

外部 MCP 继续使用 [mcp.example.toml](../config/mcp.example.toml) 和 `MCP_CONFIG`：现有限制包括总开关、server/user/tool 白名单、只读工具、独立审批、参数验证、进程资源限制、审计及不可信数据封装。新服务配置不需要修改编排器；不把 MCP 扩展成通用写入授权。

安装文件和依赖后重启生效；配置撤权在执行层即时检查。插件热重载、市场分发及前端管理界面不在 P2–P4 范围。
