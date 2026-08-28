# ChatBI 前端工作台 (React + Ant Design X)

基于 **React 19**、**Ant Design** 与 **@ant-design/x** 重构的现代智能数据分析（Text-to-SQL）工作台。

## ✨ 核心特性

- 🎯 **聚焦 SQL 与分析结果**：去繁就简，突出 SQL 语法高亮、生成耗时与交互式数据结果表格。
- ⚡ **SSE 流式实时渲染**：实时打字机动画展示生成的 SQL 语句并伴随光标闪烁。
- 📊 **交互式数据表格**：基于 Ant Design Table，支持列排序、分页、一键导出为 CSV。
- 💡 **快捷业务提问**：内置精选指标与常见问题推荐（Prompts），一键自动填入。
- 🛡️ **执行阶段透明化**：通过 ThoughtChain 直观呈现意图理解、SQL 编写、数据库执行全流程。
- 🩺 **系统健康监控**：顶部实时监测 FastAPI 后端及数据库连通状态。

## 🚀 启动与开发

### 1. 启动开发服务器

进入 `frontend` 目录：

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 <http://localhost:3000>。本地开发服务器已配置反向代理（Proxy），自动代理 `/api` 与 `/health` 到后端 `http://localhost:8000`。

### 2. 生产环境构建

```bash
npm run build
```

打包产物将输出在 `frontend/dist` 目录下。

### 3. 配置后端地址

可直接修改 `public/config.js`（或生产环境构建后的 `dist/config.js`）中的 `apiBaseUrl`：

```javascript
window.CHATBI_CONFIG = {
    apiBaseUrl: 'http://localhost:8000',
};
```
