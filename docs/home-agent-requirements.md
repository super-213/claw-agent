# 家庭 Agent 需求文档

## 1. 背景与目标

当前项目是一个部署在家庭环境中的本地 Agent，已经具备 Web UI、多会话、用户权限、文件级持久化、技能系统和后台看板能力。下一阶段需要让 Agent 从“聊天工具”升级为“家庭事务助理”，能够长期记住家庭信息、主动提醒用户，并围绕家庭日常形成可持续使用的工作流。

本需求重点覆盖：

- 记住冰箱、食品柜、药箱等家庭物品状态；
- 将家庭记忆以文件形式保存，便于本地部署、备份、迁移和审计；
- 支持提醒事件、周期任务和定时任务；
- 在网页端实现接近 App 的消息推送体验；
- 扩展更多适合家庭场景的主动服务能力。

## 2. 设计原则

- 本地优先：家庭数据默认保存在本机 `.data/` 目录，不依赖外部数据库。
- 文件可读：核心数据使用 JSON 文件保存，便于人工检查、备份和修复。
- 原子写入：所有数据写入使用临时文件 + `os.replace`，避免进程中断造成半写入文件。
- 多用户可控：结合现有账号体系，区分家庭成员、管理员、访客和共享权限。
- 主动但克制：提醒和推送必须由用户授权，支持免打扰、频率限制和关闭。
- 可追溯：Agent 对家庭记忆的新增、修改、删除要保留来源和时间。
- 可恢复：提醒任务重启后不能丢失，服务恢复时要能补偿处理未触达任务。

## 3. 用户角色

### 3.1 家庭管理员

通常是设备部署者或家庭主要管理者，权限包括：

- 管理家庭成员；
- 配置家庭数据保存目录；
- 查看和编辑所有家庭记忆；
- 管理所有提醒、推送订阅和任务；
- 设置家庭级免打扰时间、默认通知渠道、备份策略。

### 3.2 家庭成员

普通家庭用户，权限包括：

- 查看和维护自己有权限的家庭物品清单；
- 创建个人提醒和共享提醒；
- 订阅自己的浏览器推送；
- 接收家庭共享通知；
- 确认任务完成、延后提醒或关闭提醒。

### 3.3 访客或临时用户

可选角色。首版可以不实现，仅在权限模型中预留：

- 只允许查看被共享的信息；
- 不允许修改家庭记忆；
- 不允许管理通知订阅。

## 4. 核心场景

### 4.1 记住冰箱里有什么

用户可以通过自然语言告诉 Agent：

- “记一下，冰箱里有 6 个鸡蛋、半盒牛奶、两根黄瓜。”
- “牛奶明天过期，晚上提醒我喝掉。”
- “刚买了 1kg 牛肉，放冷冻层。”
- “鸡蛋吃完了，帮我从冰箱清单里删掉。”
- “冰箱里还有什么快过期？”

Agent 需要识别物品名称、数量、单位、位置、保质期、状态，并写入文件。

### 4.2 记住提醒事件

用户可以说：

- “明天早上 8 点提醒我带垃圾下楼。”
- “每周三晚上 9 点提醒我给花浇水。”
- “牛奶过期前一天提醒我。”
- “每个月 15 号提醒我交水电费。”

Agent 需要解析时间、重复规则、提醒对象、提醒渠道和提醒内容，写入任务文件，并由调度器按时触发。

### 4.3 主动发送消息

当提醒到期或家庭事件触发时，系统需要：

- 如果网页正在打开，优先通过页面内实时通知展示；
- 如果网页未打开但浏览器已授权推送，通过 Web Push 发送系统级通知；
- 如果推送失败，根据用户配置使用备用渠道，例如邮件、企业微信、钉钉、短信网关或仅记录待办；
- 在用户回到 Web UI 时展示未读提醒和历史通知。

### 4.4 家庭日常协作

家庭成员之间可以共享清单和任务：

- “谁下班路过超市，买一瓶酱油。”
- “这个周末提醒全家收拾客厅。”
- “妈妈的降压药还有 5 片，后天提醒补药。”

系统需要支持任务归属、共享范围、确认状态和完成记录。

## 5. 数据存储规划

### 5.1 目录结构

建议新增家庭数据目录：

```text
.data/
└── home/
    ├── household.json
    ├── inventory/
    │   ├── fridge.json
    │   ├── pantry.json
    │   ├── freezer.json
    │   └── medicine.json
    ├── reminders.json
    ├── schedules.json
    ├── push_subscriptions.json
    ├── notification_log.jsonl
    ├── activity_log.jsonl
    └── backups/
```

说明：

- `household.json`：家庭基础信息、成员、默认设置。
- `inventory/*.json`：按位置保存物品清单，冰箱信息必须落在 `inventory/fridge.json`。
- `reminders.json`：用户创建的提醒事件。
- `schedules.json`：系统可执行的周期任务和下一次运行时间。
- `push_subscriptions.json`：浏览器推送订阅信息。
- `notification_log.jsonl`：每次通知发送记录。
- `activity_log.jsonl`：家庭记忆变更审计日志。
- `backups/`：按日期保存快照。

### 5.2 冰箱清单数据模型

`inventory/fridge.json` 示例：

```json
{
  "version": 1,
  "updated_at": "2026-06-01T10:00:00+08:00",
  "items": [
    {
      "id": "inv_egg_001",
      "name": "鸡蛋",
      "normalized_name": "鸡蛋",
      "category": "蛋奶",
      "location": "fridge",
      "zone": "冷藏层",
      "quantity": 6,
      "unit": "个",
      "status": "available",
      "expires_at": "2026-06-10",
      "purchased_at": "2026-05-30",
      "opened_at": null,
      "source": {
        "type": "chat",
        "session_id": "session_xxx",
        "message_id": "node_xxx"
      },
      "confidence": 0.92,
      "tags": ["早餐", "易耗品"],
      "created_by": "u_001",
      "updated_by": "u_001",
      "created_at": "2026-06-01T10:00:00+08:00",
      "updated_at": "2026-06-01T10:00:00+08:00"
    }
  ]
}
```

字段要求：

- `id`：稳定唯一 ID，由系统生成。
- `name`：用户可读名称，保留用户表达。
- `normalized_name`：归一化名称，用于合并“鸡蛋”“蛋”“土鸡蛋”等近似项。
- `category`：食品分类，如蔬菜、水果、肉类、蛋奶、饮料、调料、熟食。
- `location`：固定为 `fridge`、`freezer`、`pantry`、`medicine` 等位置枚举。
- `zone`：更细位置，例如冷藏层、冷冻层、门架、抽屉。
- `quantity` 和 `unit`：数量和单位，数量未知时允许为 `null`。
- `status`：`available`、`low`、`used_up`、`expired`、`discarded`。
- `expires_at`：到期日期，不知道时为 `null`。
- `source`：记录来源，便于追溯。
- `confidence`：模型抽取置信度，低置信度变更需要用户确认。

### 5.3 提醒数据模型

`reminders.json` 示例：

```json
{
  "version": 1,
  "updated_at": "2026-06-01T10:00:00+08:00",
  "reminders": [
    {
      "id": "rem_001",
      "title": "喝掉快过期牛奶",
      "description": "牛奶将在 2026-06-02 过期",
      "timezone": "Asia/Shanghai",
      "trigger": {
        "type": "datetime",
        "run_at": "2026-06-01T20:00:00+08:00",
        "rrule": null
      },
      "recipients": ["u_001"],
      "channels": ["web_push", "in_app"],
      "status": "scheduled",
      "priority": "normal",
      "quiet_hours_policy": "delay",
      "related_object": {
        "type": "inventory_item",
        "id": "inv_milk_001"
      },
      "created_by": "u_001",
      "created_at": "2026-06-01T10:00:00+08:00",
      "updated_at": "2026-06-01T10:00:00+08:00",
      "last_sent_at": null,
      "next_run_at": "2026-06-01T20:00:00+08:00"
    }
  ]
}
```

提醒状态：

- `draft`：解析后等待用户确认。
- `scheduled`：已排程。
- `sent`：一次性提醒已发送。
- `snoozed`：用户已延后。
- `completed`：用户确认完成。
- `cancelled`：用户取消。
- `failed`：连续发送失败，需要用户或管理员处理。

### 5.4 推送订阅数据模型

`push_subscriptions.json` 示例：

```json
{
  "version": 1,
  "updated_at": "2026-06-01T10:00:00+08:00",
  "subscriptions": [
    {
      "id": "sub_001",
      "user_id": "u_001",
      "endpoint_hash": "sha256:...",
      "subscription": {
        "endpoint": "https://push.example/browser-token",
        "keys": {
          "p256dh": "...",
          "auth": "..."
        }
      },
      "user_agent": "Mozilla/5.0 ...",
      "device_name": "iPhone 主屏幕 Web App",
      "permission": "granted",
      "status": "active",
      "created_at": "2026-06-01T10:00:00+08:00",
      "last_seen_at": "2026-06-01T10:00:00+08:00",
      "last_success_at": null,
      "last_failure_at": null,
      "failure_count": 0
    }
  ]
}
```

订阅文件包含推送端点和密钥，必须视为敏感数据：

- 不在日志中输出完整 endpoint；
- 后台看板只显示设备名、浏览器、状态和脱敏 ID；
- 用户退出登录时不自动删除订阅，必须提供“停用此设备通知”的入口；
- 当推送服务返回订阅失效时，将状态改为 `expired`。

## 6. 家庭记忆能力

### 6.1 自然语言写入

Agent 需要识别以下意图：

- 新增物品：`add_inventory_item`
- 更新数量：`update_inventory_quantity`
- 标记用完：`mark_inventory_used_up`
- 删除物品：`delete_inventory_item`
- 查询物品：`query_inventory`
- 查询快过期：`query_expiring_items`
- 创建到期提醒：`create_expiry_reminder`

低风险写入可以直接执行，例如“记一下冰箱里有 6 个鸡蛋”。高风险或不确定写入需要确认，例如：

- 数量变化过大；
- 删除多个物品；
- 模型无法确定物品名称或位置；
- 用户表达中同时包含多个可能的时间。

### 6.2 合并与冲突处理

新增物品时需要判断是否已有相同或相近物品：

- 同名、同位置、同保质期：默认合并数量。
- 同名、同位置、不同保质期：保留为两条批次。
- 同名、不同位置：分开保存。
- 用户明确说“替换为”时，覆盖旧数量。

冲突示例：

- 旧数据：鸡蛋 6 个。
- 用户说：“鸡蛋还剩 4 个。”
- 系统应更新为 4 个，而不是新增 4 个。

### 6.3 用户表达与库存记录不一致

当用户在对话中引用家庭物品数量，但该数量与文件记录不一致时，Agent 不能直接忽略记录，也不能直接覆盖记录。必须先把当前记录告诉用户，并询问用户是记错了、刚刚发生了变化，还是要更新库存。

典型场景：

```text
用户：我要用冰箱里的 4 个鸡蛋做面包，可以做什么类型的面包？
文件记录：冰箱里鸡蛋数量为 2 个。
```

Agent 应回复类似：

```text
我这里记录冰箱里现在只有 2 个鸡蛋，不是 4 个。
你是记错数量了，还是冰箱里实际已经有 4 个、需要我把库存更新成 4 个？
如果只用 2 个鸡蛋，我也可以先按 2 个鸡蛋推荐面包类型。
```

处理规则：

- 用户请求中“计划使用数量”大于库存记录时，进入澄清流程。
- 用户请求中“计划使用数量”等于或小于库存记录时，可以继续回答，并可在用户确认实际使用后扣减库存。
- 用户明确说“记录错了，现在有 4 个”时，更新库存并写入 `activity_log.jsonl`。
- 用户确认“我记错了，就按 2 个算”时，不更新库存，按当前记录继续回答。
- 用户说“我刚买了 2 个，还没告诉你”时，应按新增库存处理，合并后再继续回答。
- 不允许在未确认的情况下把 2 个直接改成 4 个。
- 回答中需要避免让用户误以为系统已经自动修正库存。

### 6.4 查询与回答

Agent 回答家庭记忆问题时，应优先读取文件中的结构化数据：

- “冰箱里有什么？”按类别和位置汇总。
- “今天该吃什么？”结合快过期、偏好、禁忌、菜谱建议。
- “要不要买牛奶？”结合库存数量、过期时间和家庭消耗习惯。

回答中需要明确数据时间，例如“根据 2026-06-01 10:00 的记录”。

## 7. 提醒与定时任务

### 7.1 调度器设计

首版建议实现一个本地文件驱动调度器，随 FastAPI 服务启动：

- 每 30 秒或 60 秒扫描 `reminders.json` 和 `schedules.json`；
- 找出 `next_run_at <= now` 且状态为 `scheduled` 的任务；
- 对任务加短期 lease，避免并发重复发送；
- 执行通知发送；
- 根据任务类型更新状态和下一次执行时间；
- 写入 `notification_log.jsonl`。

如果后续部署为多进程或多设备，需要升级为数据库锁或独立任务队列。首版家庭本地部署通常是单实例，文件驱动调度器更符合当前项目架构。

### 7.2 时间解析

需要支持：

- 绝对时间：“2026 年 6 月 2 日 8 点”；
- 相对时间：“明天早上 8 点”“半小时后”；
- 周期时间：“每周三晚上 9 点”“每月 15 号”；
- 条件时间：“牛奶过期前一天”“药只剩 3 片时”；
- 时区：默认使用服务配置时区，当前环境建议 `Asia/Shanghai`。

相对时间必须在写入文件时转换为明确时间，并保存原始表达：

```json
{
  "raw_text": "明天早上 8 点提醒我带垃圾下楼",
  "resolved_at": "2026-06-01T10:00:00+08:00",
  "run_at": "2026-06-02T08:00:00+08:00"
}
```

### 7.3 重复规则

周期任务建议保存为两层：

- `rrule`：标准重复规则，便于后续兼容日历系统；
- `next_run_at`：下一次实际执行时间，便于调度器快速扫描。

示例：

```json
{
  "rrule": "FREQ=WEEKLY;BYDAY=WE;BYHOUR=21;BYMINUTE=0",
  "next_run_at": "2026-06-03T21:00:00+08:00"
}
```

### 7.4 任务操作

用户可以通过自然语言或 UI 操作：

- 查看今天提醒；
- 查看全部周期任务；
- 延后 10 分钟、1 小时、明天；
- 标记完成；
- 取消提醒；
- 修改提醒时间；
- 修改提醒对象；
- 暂停或恢复周期任务。

### 7.5 任务变更回执

Agent 解析提醒或定时任务并成功写入任务文件后，必须再次向用户展示本次具体做了什么，不能只回复“好的”“已完成”。

适用操作：

- 添加提醒或定时任务；
- 删除提醒或定时任务；
- 修改提醒时间、事件、频率、接收人或渠道；
- 暂停或恢复周期任务；
- 完成、取消或延后提醒。

回执必须包含：

- 操作类型：添加、删除、更改、暂停、恢复、完成、延后、取消；
- 任务名称或事件标题；
- 任务 ID 或可追踪的短标识；
- 触发时间或下一次执行时间；
- 事件内容；
- 频率；
- 重复规则；
- 提醒对象；
- 提醒渠道；
- 提醒内容；
- 当前状态；
- 是否受免打扰策略影响。

新增任务回执示例：

```text
已添加提醒任务：倒垃圾
- 时间：2026-06-02 08:00
- 事件：提醒你倒垃圾
- 频率：一次性
- 重复规则：不重复
- 提醒对象：你
- 提醒渠道：站内通知、浏览器推送
- 提醒内容：该倒垃圾了
- 状态：已排程
```

修改任务回执示例：

```text
已更改提醒任务：给花浇水
- 原时间：每周三 21:00
- 新时间：每周五 20:30
- 事件：提醒你给花浇水
- 频率：每周
- 重复规则：FREQ=WEEKLY;BYDAY=FR;BYHOUR=20;BYMINUTE=30
- 提醒对象：你
- 提醒渠道：站内通知、浏览器推送
- 状态：已排程
```

删除任务回执示例：

```text
已删除提醒任务：倒垃圾
- 原时间：2026-06-02 08:00
- 事件：提醒你倒垃圾
- 频率：一次性
- 提醒对象：你
- 提醒渠道：站内通知、浏览器推送
- 状态：已删除
```

如果用户的请求存在歧义，例如同名任务有多个，Agent 不能直接删除或修改，应先列出候选任务并让用户确认。

## 8. Web 推送方案

### 8.1 推荐方案

网页端要实现类似 App 的系统级通知，推荐采用 PWA + Web Push：

- 前端注册 Service Worker；
- 用户在明确操作中授权通知权限；
- 前端通过 `PushManager.subscribe()` 创建推送订阅；
- 后端保存订阅信息；
- 调度器触发提醒时，后端使用 VAPID 私钥向浏览器推送服务发送 Web Push；
- Service Worker 收到 push 事件后调用通知展示；
- 用户点击通知时打开对应会话、提醒或家庭任务页面。

依据官方资料：

- MDN 说明 Notifications API 在安全上下文中可用，适合在页面外展示系统级通知；
- MDN 说明 Service Worker 可在后台响应 push 消息；
- web.dev 的 Web Push 文档说明服务端通常使用 VAPID 识别应用服务器；
- Apple 文档说明 Safari/macOS 和 iOS 主屏幕 Web App 支持基于标准 Push API、Notifications API、Badging API 和 Service Worker 的 Web Push。

参考链接：

- [MDN Notifications API](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API)
- [MDN Service Worker API](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API)
- [web.dev Web Push Protocol](https://web.dev/articles/push-notifications-web-push-protocol)
- [Apple: Sending web push notifications in web apps and browsers](https://developer.apple.com/documentation/UserNotifications/sending-web-push-notifications-in-web-apps-and-browsers)

### 8.2 浏览器与部署前提

必须满足：

- 生产环境使用 HTTPS；本地开发可使用 `localhost`；
- 前端提供 `manifest.webmanifest`；
- 前端提供 Service Worker 文件，例如 `/sw.js`；
- 用户主动点击按钮后再请求通知权限；
- 后端生成并保存 VAPID 公私钥；
- 通知订阅与当前登录用户绑定；
- iOS 用户需要将 Web App 添加到主屏幕后才能获得类似 App 的推送体验；
- 对不支持或未授权推送的设备，必须提供备用通知方式。

### 8.3 通知渠道优先级

建议按以下顺序发送：

1. `in_app`：用户当前打开网页时，通过 SSE/WebSocket 或前端轮询即时展示。
2. `web_push`：用户未打开网页时，通过浏览器推送服务展示系统通知。
3. `email`：已有邮件技能时可作为备用渠道。
4. `webhook`：企业微信、钉钉、Server 酱、IFTTT 等外部渠道。
5. `unread_center`：所有失败或被免打扰延迟的通知进入站内通知中心。

### 8.4 推送 API 草案

```text
GET    /api/push/vapid-public-key
GET    /api/push/subscriptions
POST   /api/push/subscriptions
PATCH  /api/push/subscriptions/{subscription_id}
DELETE /api/push/subscriptions/{subscription_id}
POST   /api/push/test
```

订阅请求：

```json
{
  "subscription": {
    "endpoint": "https://push.example/browser-token",
    "keys": {
      "p256dh": "...",
      "auth": "..."
    }
  },
  "device_name": "Chrome on MacBook",
  "user_agent": "Mozilla/5.0 ..."
}
```

测试推送：

```json
{
  "subscription_id": "sub_001",
  "title": "测试通知",
  "body": "家庭 Agent 推送已启用"
}
```

### 8.5 通知内容规范

通知必须短、明确、可点击：

```json
{
  "title": "牛奶明天过期",
  "body": "冰箱冷藏层的牛奶将在 2026-06-02 过期。",
  "url": "/reminders/rem_001",
  "tag": "rem_001",
  "requireInteraction": false
}
```

要求：

- 不在通知正文展示敏感内容，例如完整医疗信息；
- 同一提醒使用稳定 `tag`，避免重复刷屏；
- 支持点击后标记已读或跳转到详情；
- 支持通知动作：完成、延后、查看。

## 9. 后端 API 草案

### 9.1 家庭配置

```text
GET   /api/home/household
PATCH /api/home/household
GET   /api/home/activity-log
```

### 9.2 库存清单

```text
GET    /api/home/inventory
GET    /api/home/inventory/{location}
POST   /api/home/inventory/{location}/items
PATCH  /api/home/inventory/{location}/items/{item_id}
DELETE /api/home/inventory/{location}/items/{item_id}
POST   /api/home/inventory/{location}/items/{item_id}/consume
POST   /api/home/inventory/{location}/items/{item_id}/restore
GET    /api/home/inventory/expiring
```

查询参数：

- `location=fridge|freezer|pantry|medicine`
- `category=蛋奶`
- `expires_before=2026-06-05`
- `status=available`

### 9.3 提醒与任务

```text
GET    /api/home/reminders
POST   /api/home/reminders
GET    /api/home/reminders/{reminder_id}
PATCH  /api/home/reminders/{reminder_id}
DELETE /api/home/reminders/{reminder_id}
POST   /api/home/reminders/{reminder_id}/complete
POST   /api/home/reminders/{reminder_id}/snooze
POST   /api/home/reminders/{reminder_id}/cancel
GET    /api/home/schedules
POST   /api/home/schedules
PATCH  /api/home/schedules/{schedule_id}
DELETE /api/home/schedules/{schedule_id}
```

### 9.4 通知中心

```text
GET   /api/home/notifications
POST  /api/home/notifications/{notification_id}/read
POST  /api/home/notifications/read-all
```

### 9.5 任务统计 API

后台看板需要统计提醒和定时任务信息，建议新增：

```text
GET /api/dashboard/home/tasks/summary
GET /api/dashboard/home/tasks/timeseries
GET /api/dashboard/home/tasks
GET /api/dashboard/home/notifications/summary
```

统计口径：

- 总任务数；
- 一次性提醒数量；
- 周期任务数量；
- 已排程、已完成、已取消、已暂停、失败任务数量；
- 今日待执行任务数量；
- 未来 7 天待执行任务数量；
- 已逾期未发送任务数量；
- 按提醒对象统计任务数量；
- 按提醒渠道统计任务数量；
- 按频率统计任务数量，例如一次性、每天、每周、每月、自定义；
- 按创建来源统计任务数量，例如聊天、UI、系统自动生成；
- 近 7 天/30 天新增、修改、删除任务趋势；
- 通知发送成功率、失败率、失败原因 Top N；
- 平均延后次数；
- 任务完成率。

任务列表应支持筛选：

- `status=scheduled|completed|cancelled|paused|failed`
- `type=one_time|recurring`
- `recipient_user_id=u_001`
- `channel=web_push|in_app|email|webhook`
- `created_from=chat|ui|system`
- `next_run_before=2026-06-08T00:00:00+08:00`

## 10. 前端需求

### 10.1 家庭首页

建议新增 `/home` 或在现有聊天页增加家庭面板，展示：

- 今日提醒；
- 快过期物品；
- 冰箱概览；
- 购物清单；
- 最近家庭记忆变更；
- 推送授权状态。

### 10.2 冰箱清单页面

功能：

- 按位置、类别、到期时间筛选；
- 支持添加、编辑、删除、标记用完；
- 快过期物品高亮；
- 数量低于阈值时显示补货建议；
- 每条物品显示最近更新时间和来源；
- 支持从聊天中的 Agent 建议一键确认写入。

### 10.3 提醒页面

功能：

- 今日、未来 7 天、全部、已完成、已取消分组；
- 周期任务单独展示；
- 支持完成、延后、编辑、取消；
- 支持按成员筛选；
- 支持测试推送。

### 10.4 推送设置页面

功能：

- 显示当前浏览器推送权限；
- 一键启用通知；
- 发送测试通知；
- 管理已绑定设备；
- 设置免打扰时间；
- 设置默认渠道和备用渠道；
- 显示最近通知发送失败原因。

### 10.5 后台看板任务统计

现有后台看板需要增加家庭任务统计模块，展示：

- 任务总览 KPI：总任务、今日待执行、未来 7 天待执行、逾期未发送、失败任务；
- 状态分布：已排程、已完成、已取消、已暂停、失败；
- 类型分布：一次性提醒、周期任务、系统自动任务；
- 频率分布：一次性、每天、每周、每月、自定义；
- 渠道分布：站内通知、浏览器推送、邮件、Webhook；
- 接收人分布：每个家庭成员负责或接收的任务数量；
- 任务变更趋势：新增、修改、删除、暂停、恢复；
- 通知发送统计：成功率、失败率、失败原因；
- 最近任务操作日志：展示谁在何时添加、删除、更改了什么任务；
- 高风险提示：连续失败任务、推送订阅失效、逾期未发送任务。

任务统计应支持点击下钻到任务列表和任务详情。

## 11. Agent 对话集成

Agent 在聊天中需要具备工具化能力，而不是只生成文本建议。建议新增家庭工具层：

```text
home_inventory.read
home_inventory.add
home_inventory.update
home_inventory.delete
home_reminder.create
home_reminder.update
home_reminder.cancel
home_notification.send_test
home_schedule.list
```

对话流程：

1. 用户提出家庭请求。
2. Agent 抽取结构化意图。
3. 若信息完整且低风险，直接调用家庭工具写入文件。
4. 若信息不完整，追问缺失字段。
5. 若操作高风险，展示确认摘要。
6. 写入成功后，用自然语言反馈保存结果。

示例反馈：

```text
已记下：冰箱冷藏层有 6 个鸡蛋，预计 2026-06-10 到期。
我也可以在到期前一天提醒你。
```

## 12. 更好的功能点

### 12.1 过期与补货智能提醒

- 到期前 N 天提醒；
- 到期当天提醒；
- 过期后建议丢弃；
- 常用物品低库存提醒；
- 根据历史消耗速度预测补货时间。

### 12.2 自动购物清单

- 从低库存和快过期状态生成购物清单；
- 支持家庭成员认领购买；
- 支持“已买到”后自动加入库存；
- 支持按超市区域分类展示。

### 12.3 拍照识别入库

- 用户拍冰箱、购物小票、商品包装；
- Agent 识别物品并生成待确认清单；
- 用户确认后写入文件；
- 低置信度条目必须人工确认。

### 12.4 菜谱与饮食建议

- 优先推荐使用快过期食材；
- 结合家庭成员忌口、过敏、偏好；
- 输出可执行的晚餐建议；
- 一键把缺失食材加入购物清单。

### 12.5 药品与健康提醒

- 药品库存和有效期管理；
- 用药提醒；
- 补药提醒；
- 医疗信息默认更高隐私级别，通知正文避免暴露药名或病情。

### 12.6 家务轮值

- 垃圾、浇花、扫地、洗衣、缴费等周期任务；
- 支持家庭成员轮值；
- 支持跳过、换班、完成统计；
- 可在后台看板查看任务完成率。

### 12.7 家庭知识库

- 记录 Wi-Fi 密码、设备说明、维修电话、常用地址；
- 支持权限分级；
- 敏感内容加密或至少脱敏展示；
- 查询时优先引用文件中的结构化记录。

### 12.8 设备与物联网扩展

后续可接入：

- Home Assistant；
- 米家、Matter 或其他智能家居平台；
- 温湿度、门磁、摄像头、冰箱传感器；
- 通过传感器事件自动触发提醒。

首版不建议直接接入复杂 IoT，先把文件记忆、提醒和推送链路打通。

## 13. 安全与隐私

要求：

- 家庭数据默认只存本地；
- API 必须走现有登录态校验；
- 普通成员只能访问授权范围；
- 推送订阅、外部 webhook、邮箱配置视为敏感信息；
- 日志中不输出完整密钥、endpoint、个人隐私内容；
- 删除家庭成员时需要处理其个人提醒和设备订阅；
- 医疗、财务、证件类信息默认需要更严格确认。

建议：

- `.data/home` 支持导出和导入；
- 支持定期备份；
- 支持按文件查看最近修改历史；
- 后续增加本地加密存储选项。

## 14. 可靠性要求

- 服务重启后，提醒和周期任务不能丢失。
- 服务停机期间错过的提醒，启动后应根据策略处理：
  - 重要提醒：补发；
  - 普通提醒：进入通知中心并标记为错过；
  - 周期任务：计算下一次执行时间。
- 同一提醒不能重复发送多次，除非用户主动延后。
- 推送失败需要记录原因。
- 浏览器订阅失效后自动停用，不影响其他设备。
- 文件损坏时尽量从备份恢复，并在 UI 中提示管理员。

## 15. 配置项建议

新增环境变量：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOME_DATA_DIR` | `.data/home` | 家庭数据目录 |
| `HOME_TIMEZONE` | `Asia/Shanghai` | 家庭默认时区 |
| `HOME_SCHEDULER_INTERVAL_SECONDS` | `60` | 调度器扫描间隔 |
| `WEB_PUSH_VAPID_PUBLIC_KEY` | 无 | Web Push VAPID 公钥 |
| `WEB_PUSH_VAPID_PRIVATE_KEY` | 无 | Web Push VAPID 私钥 |
| `WEB_PUSH_SUBJECT` | `mailto:admin@example.com` | VAPID subject |
| `HOME_NOTIFICATION_QUIET_START` | `22:00` | 免打扰开始时间 |
| `HOME_NOTIFICATION_QUIET_END` | `07:00` | 免打扰结束时间 |
| `HOME_BACKUP_RETENTION_DAYS` | `30` | 家庭数据备份保留天数 |

## 16. 实施里程碑

### 16.1 M1：文件模型与冰箱清单

- 新增家庭数据目录；
- 实现 JSON 读写服务；
- 实现冰箱清单 API；
- 实现活动日志；
- Agent 支持“记住冰箱里有什么”和基础查询；
- 前端提供冰箱清单基础页面。

验收：

- 用户说“记一下冰箱里有 6 个鸡蛋”，系统写入 `inventory/fridge.json`；
- 用户刷新或重启服务后，仍能查询到鸡蛋；
- 删除和修改操作写入审计日志。

### 16.2 M2：提醒与本地调度器

- 实现 `reminders.json`；
- 实现提醒 API；
- 实现本地调度器；
- 实现站内通知中心；
- Agent 支持创建、查询、延后、完成提醒。

验收：

- 用户创建“明天 8 点提醒我”后，文件中保存明确时间；
- 到期后生成通知记录；
- 服务重启后提醒仍然存在；
- 已发送的一次性提醒不会重复发送。

### 16.3 M3：Web Push

- 增加 PWA manifest；
- 增加 Service Worker；
- 增加 VAPID 配置；
- 实现推送订阅 API；
- 实现测试推送；
- 调度器接入 Web Push 通知。

验收：

- 用户在浏览器启用通知后，订阅写入 `push_subscriptions.json`；
- 点击测试推送可以收到系统通知；
- 到期提醒可以在网页未打开时触发系统通知；
- 推送失败会写入 `notification_log.jsonl`。

### 16.4 M4：家庭协作与增强能力

- 支持提醒接收人；
- 支持家庭共享任务；
- 增加购物清单；
- 增加快过期和低库存提醒；
- 增加拍照识别待确认流程。

验收：

- 家庭管理员可以给多个成员创建共享提醒；
- 成员只能看到自己有权限的数据；
- 快过期物品可自动生成提醒或购物建议。

## 17. 验收用例

### 17.1 冰箱记忆

输入：

```text
记一下，冰箱冷藏层有 6 个鸡蛋，6 月 10 号过期。
```

期望：

- `inventory/fridge.json` 新增鸡蛋条目；
- 数量为 `6`，单位为 `个`；
- `expires_at` 为当前年份下的 `2026-06-10`，若年份不确定则使用当前年份并在回复中说明；
- Agent 回复保存结果。

### 17.2 库存更新

输入：

```text
鸡蛋还剩 4 个。
```

期望：

- 不新增第二条鸡蛋；
- 原鸡蛋数量更新为 `4`；
- `activity_log.jsonl` 记录一次更新。

### 17.3 用户说法与库存记录不一致

前置数据：

```json
{
  "name": "鸡蛋",
  "location": "fridge",
  "quantity": 2,
  "unit": "个"
}
```

输入：

```text
我要用冰箱里的 4 个鸡蛋做面包，可以做什么类型的面包？
```

期望：

- 系统读取 `inventory/fridge.json` 并发现鸡蛋记录只有 `2` 个；
- Agent 先明确告知“当前记录只有 2 个鸡蛋，不是 4 个”；
- Agent 询问用户是记错了、实际库存已变化需要更新，还是按 2 个鸡蛋继续推荐；
- 在用户确认前，不得把鸡蛋数量从 `2` 自动改成 `4`；
- 在用户确认前，不得直接给出基于 4 个鸡蛋的推荐作为最终答案；
- 若用户确认“实际有 4 个”，系统更新库存并记录审计日志；
- 若用户确认“按 2 个算”，系统不更新库存，并继续推荐适合 2 个鸡蛋的面包类型。

### 17.4 快过期查询

输入：

```text
冰箱里有什么快过期？
```

期望：

- 系统读取 `inventory/fridge.json`；
- 返回未来 3 天或用户配置窗口内到期物品；
- 回答中包含记录更新时间。

### 17.5 一次性提醒

输入：

```text
明天早上 8 点提醒我倒垃圾。
```

期望：

- `reminders.json` 新增提醒；
- `run_at` 被解析为明确 ISO 时间；
- `next_run_at` 与 `run_at` 一致；
- Agent 向用户展示添加任务回执，包含时间、事件、频率、重复规则、提醒对象、提醒渠道和提醒内容；
- 到期后发送通知并更新状态。

### 17.6 周期提醒

输入：

```text
每周三晚上 9 点提醒我给花浇水。
```

期望：

- `reminders.json` 保存 `rrule`；
- Agent 向用户展示添加任务回执，说明该任务为每周重复，并展示下一次执行时间；
- 调度器每次执行后计算下一次 `next_run_at`；
- 用户可以暂停、恢复、取消该任务。

### 17.7 任务修改与删除回执

前置数据：

```json
{
  "id": "rem_001",
  "title": "给花浇水",
  "next_run_at": "2026-06-03T21:00:00+08:00",
  "rrule": "FREQ=WEEKLY;BYDAY=WE;BYHOUR=21;BYMINUTE=0",
  "recipients": ["u_001"],
  "channels": ["in_app", "web_push"]
}
```

输入：

```text
把给花浇水改成每周五晚上 8 点半提醒。
```

期望：

- 系统更新 `reminders.json` 中对应任务；
- Agent 向用户展示更改任务回执；
- 回执包含原时间、新时间、事件、频率、重复规则、提醒对象、提醒渠道和当前状态；
- `activity_log.jsonl` 记录任务修改。

删除输入：

```text
删除给花浇水的提醒。
```

删除期望：

- 如果只有一个同名任务，系统删除或取消对应任务；
- Agent 向用户展示删除任务回执；
- 回执包含被删除任务的原时间、事件、频率、提醒对象、提醒渠道和最终状态；
- 如果存在多个同名任务，Agent 先列出候选项并要求用户确认，不直接删除。

### 17.8 后台看板任务统计

前置数据：

- 存在 3 个已排程提醒；
- 存在 2 个周期任务；
- 存在 1 个失败推送记录；

期望：

- 后台看板能展示任务总数、今日待执行、未来 7 天待执行、失败任务；
- 能按状态、频率、提醒对象和提醒渠道统计；
- 能展示任务新增、修改、删除趋势；
- 能展示通知成功率、失败率和失败原因；
- 点击统计项可以下钻到对应任务列表。

### 17.9 Web Push

操作：

1. 用户在设置页点击“启用通知”。
2. 浏览器弹出授权。
3. 用户允许通知。
4. 点击“发送测试通知”。

期望：

- Service Worker 注册成功；
- 订阅写入 `push_subscriptions.json`；
- 用户收到测试通知；
- 点击通知后打开 Web UI 对应页面。

## 18. 待确认问题

- 家庭 Agent 是否只支持单家庭，还是一个部署实例可以管理多个家庭？
- 是否需要引入购物清单作为 M1 功能，还是放到 M4？
- Web Push 失败后的备用渠道优先支持邮件、企业微信、钉钉还是短信？
- 家庭数据是否需要加密存储，还是先依赖本机权限？
- 是否允许 Agent 在无确认情况下删除物品，还是删除永远需要二次确认？
- 是否需要支持农历、节假日和工作日调休提醒？
- 是否需要移动端安装引导，特别是 iOS 添加到主屏幕流程？
