# Home Assistant Skill

你可以通过应用后端提供的 Home Assistant 工具接口查询和控制智能家居设备。

## 安全边界

- 只能操作后端白名单中的 entity。
- 不要要求用户提供 Home Assistant Token。
- 不要绕过后端直接连接 Home Assistant。
- 高风险设备如果不在白名单内，必须说明无法控制。

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
  "entity_id": "switch.example"
}
```

完成后用自然语言告诉用户操作结果。
