# 前端静态资源缓存策略

## 当前策略

前端已迁移到 Vite + React + TypeScript，生产构建由 Vite 生成带内容哈希的静态资源，例如：

```text
dist/assets/index-B8y913Xo.css
dist/assets/index-BBbHnm30.js
```

文件内容变化时，哈希文件名会变化，浏览器会自动请求新资源，不再需要手动维护 `?v=` 版本号。

## 开发阶段

开发时使用 Vite dev server：

```bash
npm run web:dev
```

Vite 会通过模块热更新提供最新源码。后端 `web_app.py` 仍会给 API 以外的 HTML/CSS/JS 响应设置 no-cache 头，但 FastAPI 当前只提供后端 API，不托管 React 页面。

## 生产阶段

生产构建：

```bash
npm run web:build
```

构建产物位于 `web-react/dist/`。生产静态服务可以对 `dist/assets/*` 使用长期缓存，因为文件名已经包含内容哈希；`dist/index.html` 应保持 no-cache 或短缓存，确保能加载最新资源清单。
