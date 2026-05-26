# 登录、用户权限与协作会话需求文档

## 1. 目标

新增账号体系，支持：

- 登录、退出登录。
- 若系统中还没有管理员账号，则首次访问时先注册管理员账号。
- 管理员登录后才能新增、删除、修改、查询普通用户。
- 登录页用户名输入框支持下拉选择已注册用户名，便于快速登录。
- 一个管理员账号、多个普通用户账号。
- 普通用户默认只能看到和操作自己的会话。
- 用户可以把某个会话设置为协作会话，共享给所有用户或指定用户。
- 管理员可以管理用户，并查看每个用户的使用情况。

## 2. 角色

### 2.1 管理员

管理员角色为 `admin`，权限包括：

- 管理所有用户：新增、删除、修改、查询、禁用、重置密码、修改角色。
- 查看所有会话和所有用户使用统计。
- 查看任意用户的会话详情。
- 删除或管理任意会话。

### 2.2 普通用户

普通用户角色为 `user`，权限包括：

- 创建和管理自己的会话。
- 查看被共享给自己的会话。
- 设置自己拥有的会话共享范围。
- 不能查看其他人的私有会话。

## 3. 登录与账号初始化

页面建议新增 `/login`。

### 3.1 首次管理员初始化

如果系统中还没有管理员账号，访问登录页时应进入“初始化管理员”流程。

初始化管理员表单：

- 管理员用户名。
- 管理员密码。
- 确认密码。

初始化成功后：

- 创建第一个 `admin` 用户。
- 可自动登录并进入 `/`，或返回登录页。
- 初始化接口只允许在“系统中不存在任何管理员账号”时调用。

如果系统中已经存在管理员账号：

- 禁止再次通过初始化流程创建管理员。
- 返回 `409 admin_already_exists` 或跳转到正常登录页。

### 3.2 登录

登录表单：

- 用户名输入框。
- 密码输入框。
- 用户名输入框支持下拉已注册用户名。
- 登录成功后进入 `/`。

### 3.3 用户管理

普通用户不能自行注册。用户账号只能由管理员在后台创建、删除、修改和查询。

管理员创建用户表单：

- 用户名。
- 显示名称。
- 初始密码。
- 角色：`user` 或 `admin`。
- 状态：启用或禁用。

退出登录：

- 聊天页面侧边栏显示当前用户和退出按钮。

用户名下拉有安全取舍：如果这个服务只在内网或本机使用，可以直接从后端返回已注册用户名；如果会暴露到公网，建议只显示“本机最近登录过的用户名”，避免泄露用户列表。当前需求明确要“注册过的用户名”，可以做成配置项，例如 `AUTH_EXPOSE_USERNAMES=true`。

## 4. 数据模型

首版继续使用文件存储，不必引入数据库。

新增用户文件：

```json
.data/users.json
{
  "users": [
    {
      "id": "u_xxx",
      "username": "admin",
      "display_name": "管理员",
      "role": "admin",
      "password_hash": "...",
      "status": "active",
      "created_at": "...",
      "last_login_at": "..."
    }
  ]
}
```

会话 JSON 增加字段：

```json
{
  "id": "session_xxx",
  "owner_user_id": "u_001",
  "created_by": "u_001",
  "updated_by": "u_001",
  "sharing": {
    "scope": "private",
    "user_ids": [],
    "permission": "write"
  }
}
```

`sharing.scope` 支持：

- `private`：仅 owner 和 admin 可见。
- `all`：所有登录用户可见。
- `selected`：owner、admin、`user_ids` 中的用户可见。

首版建议共享权限统一为 `write`，即协作用户可继续发送消息、创建分支、切换分支。后续再加 `read` / `write` 两档权限。

## 5. 权限规则

### 5.1 会话列表

`GET /api/sessions`：

- admin：返回全部会话，可按用户筛选。
- user：返回自己拥有的会话 + 共享给自己的会话。

### 5.2 会话详情、聊天、分支、复制、删除

owner：

- 拥有完整权限。

admin：

- 拥有完整管理权限。

shared user：

- 可查看。
- 可发送消息和参与协作，前提是共享权限为 `write`。
- 不可删除原会话。
- 复制共享会话时，生成一份归自己所有的新会话。

非授权用户：

- 返回 `403 forbidden`。

### 5.3 删除会话

- owner 可删除自己的会话。
- admin 可删除任意会话。
- shared user 不可删除源会话。

## 6. 后端 API 草案

### 6.1 认证 API

```text
GET  /api/auth/usernames
GET  /api/auth/bootstrap-status
POST /api/auth/bootstrap-admin
POST /api/auth/login
POST /api/auth/logout
GET  /api/auth/me
```

说明：

- `GET /api/auth/bootstrap-status`：返回是否已经存在管理员账号。
- `POST /api/auth/bootstrap-admin`：仅当不存在管理员账号时可用，用于创建第一个管理员。
- 不提供普通用户自助注册 API。

### 6.2 用户管理 API

```text
GET    /api/admin/users
POST   /api/admin/users
GET    /api/admin/users/{user_id}
PATCH  /api/admin/users/{user_id}
DELETE /api/admin/users/{user_id}
POST   /api/admin/users/{user_id}/reset-password
GET    /api/admin/users/{user_id}/usage
```

用户管理 API 仅管理员可访问。普通用户访问返回 `403 forbidden`。

### 6.3 会话共享 API

```text
GET   /api/sessions/{session_id}/share
PATCH /api/sessions/{session_id}/share
```

共享请求示例：

```json
{
  "scope": "selected",
  "user_ids": ["u_002", "u_003"],
  "permission": "write"
}
```

### 6.4 Dashboard 扩展

```text
GET /api/dashboard/summary?user_id=...
GET /api/dashboard/sessions?user_id=...
GET /api/dashboard/users
```

普通用户访问 dashboard 时，只能看到自己可见的统计；admin 可以看到全局和按用户维度统计。

## 7. 后端实现模块建议

新增模块：

- `services/user_store.py`
  - 用户创建、查询、密码校验、禁用用户、重置密码。
- `services/auth_service.py`
  - 登录、退出、首次管理员初始化、当前用户解析、密码 hash。
- `services/access_control.py`
  - `can_read_session(user, session)`
  - `can_write_session(user, session)`
  - `can_delete_session(user, session)`
  - `can_manage_users(user)`

改造模块：

- `services/conversation_store.py`
  - `create_session(..., owner_user_id)`
  - `list_sessions(user)` 或保留底层全量方法，另加权限过滤服务。
  - `clone_session(session_id, owner_user_id)`。
- `web_app.py`
  - 给所有会话、聊天、dashboard API 加当前用户校验。
  - 未登录访问 `/` 时重定向或返回登录页。
- `services/dashboard_metrics.py`
  - 支持传入可见会话集合，避免普通用户看到全局数据。

## 8. 前端改造

新增：

- `web/login.html`
- `web/js/auth.js`
- 登录/注册表单样式。
- 管理员用户管理页面或用户管理弹窗。

改造聊天页：

- 进入页面先请求 `/api/auth/me`。
- 未登录跳转 `/login`。
- 侧边栏显示当前用户名、角色、退出按钮。
- 会话菜单增加“共享设置”。
- 共享设置弹窗：
  - 私有。
  - 共享给所有人。
  - 共享给指定用户，多选用户列表。
- 会话列表上区分：
  - 我的会话。
  - 协作会话。
  - 管理员视角可按用户筛选。

改造后台看板：

- 普通用户：只显示自己的使用情况和共享可见会话。
- 管理员：增加用户使用排行、用户详情、用户新增、删除、修改、查询、禁用/启用入口。

## 9. 迁移策略

现有会话没有 `owner_user_id`，需要迁移：

- 首次启动时检查 `.data/users.json` 是否存在。
- 如果不存在管理员账号，则登录页进入初始化管理员流程。
- 可以选择支持环境变量自动创建默认管理员：
  - `ADMIN_USERNAME=admin`
  - `ADMIN_PASSWORD=...`
- 如果未配置环境变量，则必须由页面初始化第一个管理员。
- 旧会话统一归属默认管理员。
- 给旧会话补字段：
  - `owner_user_id = admin_user_id`
  - `sharing.scope = private`
  - `created_by = admin_user_id`

## 10. 测试验收

至少补这些测试：

- 未登录访问会话 API 返回 `401`。
- 系统无管理员时，可以初始化第一个管理员。
- 系统已有管理员时，不能再次调用初始化接口创建管理员。
- 普通用户不能自行注册账号。
- 只有管理员可以新增、删除、修改、查询用户。
- 普通用户只能看到自己的会话。
- 用户 A 不能读取用户 B 的私有会话。
- 用户 B 可以读取用户 A 共享给自己的会话。
- 共享给所有人后，所有普通用户可见。
- shared user 不能删除源会话。
- admin 可以查看所有会话和用户统计。
- 禁用用户后无法登录。
- 旧会话迁移后仍能正常打开、聊天、分支、复制。

## 11. 建议实施顺序

1. 先做用户存储、首次管理员初始化、登录退出、当前用户识别。
2. 再做管理员用户增删改查。
3. 再给会话加 `owner_user_id` 和权限过滤。
4. 再做共享会话。
5. 最后扩展管理员后台和用户使用统计。

这样改动风险最低，因为现有会话、分支、流式聊天逻辑可以尽量保持不动，只是在入口处加身份和权限判断。
