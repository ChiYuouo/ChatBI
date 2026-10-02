# ChatBI Web 工作台

ChatBI 的 React + TypeScript 前端，提供登录注册、自然语言查询、归因分析、会话历史和结果展示。完整项目介绍与后端启动方式见[项目 README](../README.md)。

## 本地开发

先启动后端，再在本目录运行：

```bash
npm install
npm run dev
```

访问 <http://localhost:3000>。默认 API 地址在 `public/config.js` 中配置为 `http://localhost:8000`，可按部署环境修改。后端需将前端地址加入 `CORS_ALLOWED_ORIGINS`。

## 生产构建

```bash
npm run build
```

构建产物输出到 `dist/`。Docker Compose 部署使用 Nginx 托管静态文件，并通过同源代理访问后端。
