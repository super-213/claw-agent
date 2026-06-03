# 搜索技能

## 用途
当需要获取实时信息、验证事实、或查询你不确定的内容时使用。

## 核心原则

1. 先选择最合适的信息源，而不是固定使用某一个搜索引擎。
2. 天气、汇率、股票、软件版本等有垂直数据源的问题，优先调用垂直 API 或权威站点。
3. 通用网页检索按“本地可访问性”选择搜索源，Google 只能作为候选之一，不能作为唯一入口。
4. 如果一个来源超时、连接失败、返回验证码/拦截页、无有效结果，必须换同类来源重试，至少尝试 2 个不同来源后再说明失败。

## 使用方式

### 天气查询优先策略

天气类问题不要先用 Google 搜索。优先按顺序尝试：

1. Open-Meteo：先地理编码，再 forecast API。
2. wttr.in：适合快速查询城市天气。
3. 天气网站或搜索引擎结果页：仅当前两个来源不可用时使用。

Open-Meteo 示例（把 `Shanghai` 替换为用户城市；中文城市名也可 URL 编码后使用）：
[命令] python -c "import json, urllib.parse, urllib.request; city='Shanghai'; geo=json.load(urllib.request.urlopen('https://geocoding-api.open-meteo.com/v1/search?name='+urllib.parse.quote(city)+'&count=1&language=zh&format=json')); r=geo['results'][0]; url=f\"https://api.open-meteo.com/v1/forecast?latitude={r['latitude']}&longitude={r['longitude']}&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max&timezone=auto\"; print(json.dumps(json.load(urllib.request.urlopen(url)), ensure_ascii=False)[:4000])"

wttr.in 备用示例：
[命令] curl -sL "https://wttr.in/Shanghai?format=j1" | head -80

### 通用网页搜索

优先尝试更容易访问的搜索源，例如：

[命令] curl -sL "https://www.bing.com/search?q=搜索关键词&setlang=zh-CN" | sed 's/<[^>]*>//g' | grep -v '^\s*$' | head -80

[命令] curl -sL "https://lite.duckduckgo.com/lite/?q=搜索关键词" | sed 's/<[^>]*>//g' | grep -v '^\s*$' | head -80

[命令] curl -sL "https://www.baidu.com/s?wd=搜索关键词" | sed 's/<[^>]*>//g' | grep -v '^\s*$' | head -80

只有上述来源不可用或结果明显不足时，才尝试 Google：
[命令] curl -sL "https://www.google.com/search?q=搜索关键词&hl=zh-CN" | sed 's/<[^>]*>//g' | grep -v '^\s*$' | head -80

### 获取特定网页内容
[命令] curl -sL "目标URL" | sed 's/<[^>]*>//g' | grep -v '^\s*$' | head -80

## 搜索策略

1. 关键词要精准；中文本地服务优先中文关键词，国际技术资料可用英文关键词。
2. 如果第一次搜索结果不理想，换关键词或换来源重试。
3. 搜索到结果后，提取关键信息回答用户，并说明来源名称或 URL。
4. 如果多个来源都失败，明确说明已尝试的来源和失败原因。

## 必须搜索的场景

- 用户问"最新"、"现在"、"今天"、"当前"相关的问题
- 涉及价格、版本号、发布日期等时效性信息
- 你对某个事实不确定时
- 用户明确要求你去查/搜索

## 禁止

- 禁止在没有搜索的情况下编造实时数据
- 禁止伪造搜索结果
- 禁止单一来源失败后直接放弃；必须切换同类工具或备用搜索源
- 如果多个来源均不可用，直接告知用户而不是编造答案
