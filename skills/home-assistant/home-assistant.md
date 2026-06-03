# Home Assistant Skill

你可以通过应用后端提供的 Home Assistant 工具接口查询和控制智能家居设备。

## 安全边界

- 只能操作后端白名单中的 entity。
- 不要要求用户提供 Home Assistant Token。
- 不要绕过后端直接连接 Home Assistant。
- 高风险设备必须先让用户二次确认，确认后所有登录用户都可以控制。

## 白名单格式

后台白名单每行一个设备：

```text
switch.desk_lamp|书桌插座|low
switch.water_heater|热水器|risk=high
```

- `low`：低风险，命中明确指令后可直接控制。
- `high` / `risk=high`：高风险，首次请求只创建待确认操作，用户回复“确认”后才执行。
- 不写风险等级时默认 `low`。

## 可用工具

工具调用 HTTP 入口：

```text
POST /api/home-assistant/tools/call
```

请求体格式：

```json
{
  "name": "home_assistant.get_state",
  "arguments": {
    "entity_id": "switch.example"
  }
}
```

支持的工具名：

- `home_assistant.list_devices`
- `home_assistant.get_state`
- `home_assistant.turn_on`
- `home_assistant.turn_off`

## 参数说明

`home_assistant.list_devices`：

```json
{
  "include_states": false
}
```

`home_assistant.get_state`：

```json
{
  "entity_id": "switch.example"
}
```

`home_assistant.turn_on` / `home_assistant.turn_off`：

```json
{
  "entity_id": "switch.example",
  "confirmation_token": "optional-token"
}
```

高风险设备不要自行生成确认字段。没有确认时，先要求用户确认；用户确认后由后端执行待确认操作。

完成后用自然语言告诉用户操作结果。
