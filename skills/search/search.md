# 搜索技能

## 用途

当需要获取实时信息、验证事实或查询不确定内容时使用。本技能提供选源与查询策略；真正的网络访问必须通过运行时工具执行。

## 工具协议

- 调用 `http_request` 获取网络数据，不能用普通文本模拟网络请求。
- Home Assistant 是智能家居工具，不是通用天气或网页数据源。普通城市天气不要调用 Home Assistant。

## 核心原则

1. 选择最合适的信息源，不固定使用某一个搜索引擎。
2. 天气、汇率、股票、软件版本等有垂直数据源的问题，优先使用垂直 API 或权威站点。
3. 通用网页检索按本地可访问性选择搜索源；Google 只能作为候选之一。
4. 来源超时、失败、返回拦截页或无有效结果时，换同类来源重试；至少尝试两个不同来源后再说明失败。
5. 获取结果后说明来源名称或 URL，不伪造数据和链接。

## 天气查询

优先顺序：

1. Open-Meteo：先地理编码，再调用 forecast API。
2. wttr.in：适合快速查询城市当前天气。
3. 天气网站或搜索结果页：仅在前两个来源不可用时使用。

原生工具模式示例：

1. 调用 `http_request`：`{"url":"https://geocoding-api.open-meteo.com/v1/search?name=Shanghai&count=1&language=zh&format=json"}`
2. 从结果读取经纬度，再调用 `http_request` 请求 `https://api.open-meteo.com/v1/forecast?latitude=...&longitude=...&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto`
3. 根据成功返回的数据回答，并注明 Open-Meteo。

wttr.in 备用：调用 `http_request` 请求 `https://wttr.in/Shanghai?format=j1`。

## 通用网页搜索

使用 `http_request` 依次尝试可访问的搜索入口，例如：

- Bing：`https://www.bing.com/search?q=搜索关键词&setlang=zh-CN`
- DuckDuckGo Lite：`https://lite.duckduckgo.com/lite/?q=搜索关键词`
- 百度：`https://www.baidu.com/s?wd=搜索关键词`
- Google：仅在其他来源不可用或结果不足时尝试

请求特定网页时，直接将目标 HTTP(S) URL 传给 `http_request`。如果返回内容被截断，可适当提高 `max_chars`；不要改用 Shell 来绕过网络安全限制。

## 必须搜索的场景

- 用户询问“最新”“现在”“今天”“当前”等内容
- 涉及天气、价格、版本号、发布日期、人物近况等时效信息
- 对具体事实不确定
- 用户明确要求查询或搜索

## 失败处理

参数或权限错误先修正参数/工具选择，不要原样重试。网络或来源错误则切换备用来源。多个来源均不可用时，明确说明已尝试的来源和失败原因，不得编造答案。
