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

## 主屏幕 Web App

012 改造增加了构建时注入资源清单的 `/sw.js`。Worker、HTML 和 Manifest 由 Nginx 设置 `no-cache`，哈希资源设置长期缓存。Worker 只预缓存公开应用外壳，API、聊天流及私人文件继续走网络。

新版本显示更新入口；草稿、上传、生成、业务写入或编辑弹层存在时阻止刷新，并要求关闭本站其他窗口。发布先复制全部依赖资源，再替换 HTML 和 Worker，保留旧哈希资源。具体发布、回滚和停用流程见 [PWA 部署说明](../deploy/PWA.md)。
