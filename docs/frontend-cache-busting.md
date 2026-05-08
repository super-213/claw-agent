# 前端静态资源缓存策略

## 问题

浏览器会缓存 CSS/JS 文件。修改前端代码后，用户刷新页面可能仍然加载旧版本。

## 解决方案

项目采用两层防缓存机制：

### 1. 服务端 no-cache 响应头（开发阶段）

`web_app.py` 中的 `@app.after_request` 钩子对所有 CSS、JS、HTML 响应设置：

```
Cache-Control: no-cache, no-store, must-revalidate
Pragma: no-cache
Expires: 0
```

开发阶段这一层就够了，浏览器每次都会向服务器请求最新文件。

### 2. 版本号 query string（生产 / 兜底）

`index.html` 中引用静态资源时带版本参数：

```html
<link rel="stylesheet" href="/styles.css?v=2">
<script type="module" src="/js/app.js?v=2"></script>
```

**规则：每次修改 CSS 或 JS 文件后，递增版本号。**

```html
<!-- 修改前 -->
<link rel="stylesheet" href="/styles.css?v=2">

<!-- 修改后 -->
<link rel="stylesheet" href="/styles.css?v=3">
```

这确保即使 no-cache 头被 CDN/代理忽略，浏览器也会因为 URL 变化而重新下载。

## 何时需要手动递增版本号

| 场景 | 是否需要递增 |
|------|-------------|
| 本地开发、直连 Flask | 不需要（no-cache 头已生效） |
| 部署到有缓存层的环境（Nginx、CDN） | 需要 |
| 用户反馈看到旧样式 | 递增后让用户硬刷新 |

## 注意事项

- 版本号只需要在 `index.html` 中维护，JS 模块之间的 `import` 不需要加版本号（浏览器会跟随入口文件的缓存策略）。
- 如果未来引入构建工具（Vite/Webpack），可改用内容哈希文件名（如 `styles.a3f2b1.css`）替代手动版本号。
- 生产环境部署时，可以移除 no-cache 头并改用长期缓存 + 哈希文件名策略以提升性能。
