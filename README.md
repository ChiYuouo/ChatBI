# ChatBI 智能数据分析平台

ChatBI 是一个面向业务分析的自然语言数据查询项目。用户在工作台提问，系统结合数据库结构、指标定义与业务规则生成 SQL，展示查询过程和结果；对于“为什么下降”一类问题，还可以拆解分析步骤并生成归因报告。

## 技术栈

Python 3.12 · FastAPI · MySQL · SQLite · ChromaDB · OpenAI 兼容 API · React · TypeScript · Ant Design

## 核心能力

- **自然语言查询**：将业务问题转为 SQL，支持流式展示生成过程、结果表格和会话追问。
- **归因分析**：拆解复杂问题、执行多个子查询，并汇总分析结论。
- **业务知识检索**：按需检索 Schema、指标定义和示例，辅助 SQL 生成。
- **数据访问控制**：登录鉴权、SQL 结构与表/字段校验、角色权限和区域过滤；敏感字段在执行前拒绝访问。
- **Web 工作台**：集中管理会话、查看 SQL、查询结果与分析报告。

## 工作流程

```mermaid
flowchart LR
    A[业务问题] --> B[问题理解与知识检索]
    B --> C[SQL 生成]
    C --> D[安全与权限校验]
    D --> E[(MySQL 业务数据)]
    E --> F[结果表格 / 归因报告]
    F --> G[Web 工作台]
```

前端使用 React 和 TypeScript，后端由 FastAPI 提供 REST 与 SSE 接口。业务数据保存在 MySQL；账户和会话记录分别保存在独立的 SQLite 数据库中。


## 快速开始

需要 Docker Compose，以及一个兼容 OpenAI API 的模型服务。复制 `.env.example` 为 `.env`，填写模型配置、`MYSQL_ROOT_PASSWORD`（初始化管理账户）、`DB_PASSWORD`（分析只读账户）和 `JWT_SECRET`，保留 `DB_USER=chatbi_reader`，然后启动：

```bash
docker compose up -d --build
```

打开 [Web 工作台](http://localhost:8300)；[API 文档](http://localhost:8000/docs)和[健康检查](http://localhost:8000/health)也可直接访问。Compose 首次启动时会导入 `docker/mysql/init/` 中的示例业务数据。若 8300 端口被占用，可在 `.env` 中设置 `FRONTEND_PORT`。

演示数据是**虚构样本**：保留原有 5 位客户、5 款产品、5 笔订单，同时追加 16 位客户、8 款产品、224 笔订单、170 条逐日汇率和 27 条费用记录。订单覆盖 2026 年 1—10 月（10 月仅截至 8 日），包含五个大区、三种币种和三种订单状态；费用、汇率与订单时间可对齐。数据用于演示趋势和归因，不代表真实企业业绩。固定样本不会自动随日期向后延伸，超过 2026 年 10 月后请优先使用明确的 2026 年时间范围提问。

已有 MySQL 数据卷不会重新执行初始化 SQL；如果此前已启动过项目，可在项目根目录运行以下命令，把同一套虚构样本**追加**到当前本地演示库：

```powershell
docker compose up -d mysql
uv run python -m chatbi.tools.demo_data --apply
```

该命令使用 `.env` 中的本地 MySQL 管理密码，先检查预留 ID 是否与已有数据冲突，再在事务中插入缺少的记录；重复执行不会重复插入。不要对外部业务库执行此命令。

演示时可先用管理员或财务账号提问：

- `2026 年 7 月至 9 月，每月已完成订单的人民币收入、销售成本和毛利是多少？`
- `2026 年 9 月，各大区和产品线的已完成订单数及人民币销售额是多少？`
- `2026 年 7 月至 9 月，简化经营利润为什么下降？`

当前产品成本是产品维度的现值，没有订单成本快照；可分析销售成本总额随销量和产品结构的变化，不能证明材料采购单价上涨。费用没有按产品线或大区分摊，不应计算这些维度的经营利润。

首次初始化会运行 `02-reader.sh`，为分析账户仅授予五张演示表的 SELECT 权限；后端使用 reader，管理密码不会传给后端。

启用 Schema Linking 或指标 RAG 时，`index-init` 会在后端启动前准备对应的表/字段/指标索引，首次会调用配置的 Embedding 服务。定义或 Embedding 模型/地址变化会触发重建；版本有效时跳过远程调用。索引保存到 `chatbi-index-data` 卷，镜像构建不需要本机 `chroma_db`。`index-init` 是一次性任务，成功后以退出码 0 结束是正常状态。检索全部关闭时不创建索引，也不调用 Embedding。

初始化失败时查看 `docker compose logs index-init`，修正配置后重新启动。也可以单独准备或检查索引：

```bash
docker compose run --rm --no-deps index-init
docker compose run --rm --no-deps index-init python -m chatbi.tools.init_indexes --status
```

`--all` 可准备全部三种索引；`--force` 强制重建并再次调用 Embedding。默认只处理当前启用功能需要的索引。不要通过删除 MySQL 数据卷来重建索引。

`/health` 检查数据库以及启用检索功能的索引，未就绪返回 503；`/live` 只检查 API 进程。健康轮询不建索引、不调用模型。前端会区分数据库异常、检索未就绪和服务离线。

已有 MySQL 数据卷不会重新执行初始化脚本。保留数据卷，将 `.env` 中的 `MYSQL_ROOT_PASSWORD` 设为该数据库原有的 root 密码，再配置 `DB_USER=chatbi_reader` 和新的分析密码，按顺序运行：

```bash
docker compose up -d mysql
docker compose exec mysql bash /docker-entrypoint-initdb.d/02-reader.sh
docker compose up -d --build backend frontend
```

脚本只创建/更新指定分析账户并重设其五表读取权限，不修改业务数据。不要通过删除数据卷来切换账户。接入自己管理的 MySQL 时，由数据库管理员创建并授权只读账户，再配置 `DB_USER`、`DB_PASSWORD`；这些初始化脚本仅用于 Compose 演示库。

也可以在本地分别运行前后端（需要 Python 3.12+、Node.js 和 MySQL）：

```bash
uv sync
uv run python -m chatbi.tools.init_indexes
uv run uvicorn api_service:app --reload
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

本地索引默认位于 `chroma_db`，可通过 `CHROMA_PERSIST_DIR` 指定其他目录；本地连接 Compose 的数据库使用 `DB_PORT=3307`。本地前端地址为 <http://localhost:3000>。前端 API 地址可在 `frontend/public/config.js` 中配置；Docker 部署使用同源反向代理。

### 账户授权

首次启动后，可运行账户初始化脚本，创建默认管理员（账号和密码均为 `admin`）：

```bash
# Docker Compose
docker compose exec backend python -m chatbi.tools.init_admin

# 本地运行
uv run python -m chatbi.tools.init_admin
```

脚本写入独立的 SQLite 账户库 `data/users.db`，密码以哈希形式保存；重复运行不会覆盖已有的 `admin` 账号。默认凭据仅用于本地演示，不应直接用于公开部署。

其他用户可以在登录页注册。新账号默认为 `pending`，需要管理员在 授权页面 授予 `admin`、`finance` 或 `sales` 角色后才能登录；`sales` 角色还需要设置 `region`。

### 当前查询执行范围

同步查询、流式查询和归因子步骤共用受控执行器。缺少用户身份时拒绝分析，健康检查仍可公开访问。返回的 SQL 和数据库耗时来自本次执行结果，不再读取共享的最近一次查询统计。

SQL 校验当前仅支持演示库的五张制造业表、明确的字段和常用分析函数；支持普通聚合、INNER/LEFT JOIN、非相关子查询、非递归 CTE 和 UNION。窗口函数、相关子查询、跨库、系统表、变量、写入语句和未批准函数会被拒绝。SQL 会规范化并展开普通 `*`，不能把解析成功等同于获得执行权限。

销售订单按客户的授权区域过滤，不依赖订单中冗余的区域值。销售暂不能通过任意 SQL 访问金额、成本和费用，别名或聚合也不能绕过；受审的区域收入指标模板仍待接入。安全/权限拒绝和查询超时不触发 SQL 修复重试。

当前执行限制由环境变量配置，查询、子步骤及修复重试共享预算：

| 配置 | 默认值 | 含义 |
|---|---:|---|
| `DB_MAX_RESULT_ROWS` | 1000 | 单条 SQL 最大返回行数 |
| `DB_MAX_RESULT_BYTES` | 1048576 | 单条 SQL 的列与结果行 UTF-8 JSON 大小上限 |
| `DB_SQL_TIMEOUT_MS` | 5000 | MySQL 单条 SELECT 服务端执行时间上限，毫秒 |
| `ANALYSIS_TIMEOUT_SECONDS` | 120 | 一次查询或整次多步分析的时间预算，秒 |
| `ANALYSIS_MAX_SQL_EXECUTIONS` | 20 | 整次分析的 SQL 尝试次数，失败与修复也计入 |
| `ANALYSIS_MAX_RESULT_BYTES` | 4194304 | 整次分析累计读取的结果大小上限 |
| `LLM_TIMEOUT_SECONDS` | 30 | 单次模型/向量 API 超时，且不超过剩余预算 |

超过行数或字节限制会明确失败，不返回截断数据作为成功结果。预算耗尽或结果超限会结束多步分析，不继续生成完整报告。连接池等待服从剩余预算，失效及未读完的连接会丢弃。SQL 会增加用于检测超限的 LIMIT，但不会扩大用户原本更小的 LIMIT。

人民币换算和简化经营利润由提示词与 `indicators_full.json` 约定；按当前需求，后端没有固定表/字段的汇率完整性预检查，业务方需维护汇率数据。

时间预算在阶段边界和受控网络调用中检查；本地同步计算及第三方库调用不能被 Python 立即强制中断，超时后的结果会被拒绝。结果字节统计不包含 SQL、格式化文本、报告和 SSE 外层封装。尚未完成租户/数据源授权、业务口径治理和持久取消协议。

后端离线回归使用 `uv run pytest -q`，测试会固定功能开关并使用临时账户/会话存储，不调用真实模型或业务数据库。

真实 MySQL 集成测试默认跳过。显式开启后，测试会自行创建、初始化并删除独立的 MySQL 8.4 容器，不读取 `.env` 的数据库凭据，也不连接现有业务库：

```powershell
$env:CHATBI_MYSQL_INTEGRATION = '1'
uv run pytest -q tests/test_mysql_execution_integration.py
```

独立 Compose 首次启动验收使用无本地索引、无本机账户/密钥的干净镜像，并创建自己的容器与数据卷；检索关闭且模型地址指向不可用地址，证明初始化不依赖远程模型。先构建测试镜像，再显式运行：

```powershell
docker build -f docker/backend/Dockerfile -t chatbi-backend:phase1-clean .
$env:CHATBI_COMPOSE_INTEGRATION = '1'
uv run pytest -q tests/test_bootstrap_integration.py
```

## Text-to-SQL 历史评测

2026-10-02 使用当时版本、当时的稀疏数据、50 道示例业务问题、已配置的模型服务与 MySQL 重新运行评测。评测将生成 SQL 和参考 SQL 分别执行，以结果是否等价作为主要指标。下列结果尚未基于扩充后的演示数据重新评测：

| 指标 | 结果 |
| --- | ---: |
| 执行结果正确 | 42 / 50（84.0%） |
| 简单问题 | 14 / 15（93.3%） |
| 中等问题 | 14 / 20（70.0%） |
| 复杂问题 | 14 / 15（93.3%） |
| SQL 执行失败 | 0 |
| 执行成功但结果不匹配 | 8 |

本次运行的[完整评测报告](reports/evaluation_report.md)包含逐题结果。评测命令为 `uv run python -m chatbi.tools.evaluator --report reports/evaluation_report.md`。这组历史数字反映当时示例数据与评测题集上的 SQL 生成表现，不作为本次第一阶段改动的准确率证明，不代表任意业务数据库上的准确率。


## 项目结构

```text
frontend/              React Web 工作台
src/chatbi/
├── analysis/           复杂问题拆解、执行计划与报告生成
├── api/                FastAPI 路由、鉴权与数据模型
├── core/               配置、安全策略与账户管理
├── contracts/          执行身份快照与独立查询结果
├── execution/          SQL 结构校验、范围限制与统一执行器
├── infrastructure/     数据库、大模型与会话存储
├── retrieval/          Schema 和指标检索
├── services/           查询与分析业务流程
├── text2sql/           问题处理、Prompt 与结果格式化
└── tools/              索引初始化、账户初始化和评测工具
tests/                 后端自动化测试
docker/                容器配置与示例数据初始化
```
