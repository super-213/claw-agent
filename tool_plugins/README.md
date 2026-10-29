# 工具插件开发（P1）

插件是管理员安装的可信 Python 代码，不是沙箱。当前只默认启用 `datetime`；文件、HTTP、家庭业务与 MCP 仍沿用现有实现，后续分阶段迁移。

## 接入步骤

1. 在本目录建立 `<id>/plugin.json` 与 `plugin.py`。ID 使用小写字母、数字和下划线，且以字母开头。
2. 清单声明版本、API 版本（当前为 1）、入口、Web/CLI 范围、所需服务和请求权限。参考 [时间插件](datetime/plugin.json)。
3. 工厂 `create_plugin()` 返回实例；实例的 `tools(context)` 返回 `ToolDefinition` 列表。每个工具必须在 `tool_metadata` 中声明类别和可搜索关键词。`aliases` 可选。
4. 在 `config/tool-plugins.toml` 中显式设置 `[plugins.<id>] enabled = true` 与 `permissions = [...]`。也可用 `TOOL_PLUGINS_CONFIG` 指定配置文件。配置文件不提交，凭据不写清单或工具参数。
5. 安装所需依赖后重启后端。新增普通插件不修改主入口和中央注册列表。

```python
# tool_plugins/example/plugin.py
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

对应清单：

```json
{
  "id": "example", "version": "1.0.0", "api_version": 1,
  "entrypoint": "plugin.py:create_plugin", "runtimes": ["web", "cli"],
  "requires_services": [], "requested_permissions": [],
  "tool_metadata": {"example_double": {"group": "math", "keywords": ["翻倍", "double"]}}
}
```

`context` 是宿主创建的单次运行绑定上下文，包含 `runtime`、只读服务映射、`get_user()`、`get_execution_context()` 和宿主授权检查。P1 默认不向外部插件开放业务服务句柄；声明尚未提供的服务会导致该插件绑定失败。不能把模型传入的用户 ID 用作真实身份。Web 每次执行重新验证账号和会话权限；CLI 沿用本地操作者信任边界。插件不能以权限声明自动获得服务。

工具参数经既有校验和 Draft 2020-12 验证，后者补充 minimum/maximum 等限制；错误不会回显参数值。schema 还需适配所选模型的原生 function calling 支持范围，不能仅凭本地 schema 合法就宣称任意供应商兼容。

## 生命周期与诊断

- 发现阶段只读清单，不导入代码。禁用、运行范围不符、权限未授予、依赖缺失的插件不导入。
- 单个插件原子注册；ID/工具/别名冲突不覆盖现有定义；可选插件失败记录在 `PluginManager.errors`。P1 暂不提供管理界面。
- 目录禁止符号链接，入口不能越界；包内相对导入受支持。进程内代码仍然拥有 Python 进程能力，不能把这些检查当作不可信代码隔离。
- 代码/清单修改后需重启；Web 管理器固定启动时内容摘要，发现变更时拒绝绑定。
- 执行时检查启用状态、权限授予和宿主授权，撤销后既有绑定也不能继续调用。审批仍由原执行器负责。
- 插件来源、版本、代码摘要、schema 摘要、配置摘要写入 Run 的 `plugin_snapshot`，不发送给模型。旧 Run 缺少该字段时保持兼容；新 Run 恢复时插件缺失或不兼容会拒绝继续，需恢复原配置再重试。
- 使用 `tool_load` 发现工具；分类从元数据生成。新任务隔离、Skill 白名单、全部匹配结果及无自动淘汰约定见 [工具加载说明](../docs/tool-loading.md)。

验证示例见 [插件集成测试](../test/agent_runtime/test_plugins.py)，覆盖新增第二插件、真实 SDK 请求构建（模拟网络响应）、结果回传、流式事件路径与会话/Run 持久化。业务钩子迁移、更多宿主服务、MCP 来源统一与热重载仍在后续阶段。
