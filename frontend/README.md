# ChatBI 前端

这是独立于 FastAPI 后端运行的原生 HTML/CSS/JavaScript 前端。

## 启动

在项目根目录执行：

```powershell
uv run python -m http.server 5173 --directory frontend
```

然后访问 <http://localhost:5173>。

后端默认地址配置在 `config.js`。如果后端部署到了其他地址，修改
`apiBaseUrl` 即可。
