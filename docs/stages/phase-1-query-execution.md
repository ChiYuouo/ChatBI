# 第一阶段：统一查询执行与安全边界

> 更新日期：2026-10-06。
> 当前状态：进行中；首组“执行入口”和第二组“预算、连接池与只读账户”已完成，业务口径及初始化任务仍待完善。
> 首组代码提交：`e89fd45`（统一查询执行入口并加强 SQL 权限校验）。
> 总体架构与路线见 [企业改造总规划](../enterprise-transformation-plan.md)，文档使用约定见 [文档目录](../README.md)。

本文件统一记录第一阶段的任务、实际改动、验证证据、限制与下一组工作。后续仍属于第一阶段的改动继续更新本文件；进入其他阶段时新建对应阶段文档，不在总规划中追加逐次实施记录。

## 阶段目标与验收范围

先复用当前 Python 主链路，把 SQL 生成与安全执行分开。

- 梳理 `UserContext`、`ChatBISystem`、`DatabaseClient` 和 `StepExecutor` 的实际调用，定义明确的执行上下文与独立结果对象。
- 所有单查询、流式查询、Agent 子步骤及修复重试进入同一执行器；分析路径缺少身份/授权时拒绝执行。
- 引入 AST 支持子集，处理只读、表/列、区域、OR、别名和查询作用域；不可靠的语法明确拒绝。
- 加入返回行数/字节、服务端执行时间和总预算，切换只读数据库账号，消除共享执行统计。
- 修正 Rewrite 与指标检索顺序，统一可修复错误与瞬时错误分类，权限拒绝不进入修复循环。
- 收敛业务口径，固定分析日期与可比较数据；修复索引初始化、构建数据排除和配置说明。

验收：普通查询和多步分析仍可执行；直接事实表、OR、别名、未授权表/字段及缺身份用例有明确结果；修复 SQL 再次校验；超限和超时可解释；只读账号不能写入。

## 首组任务：执行入口（已完成）

下面四项已在本组实施，具体证据与限制见后面的实施记录；Java 后端与检索治理仍按后续步骤接入。

| 顺序 | 具体任务 | 主要位置 | 验证重点 |
|---|---|---|---|
| 1 | 梳理身份传递，明确缺身份时的拒绝行为，区分公开健康接口与实际分析执行 | `core/security.py`、`api/dependencies.py`、`services/chatbi_service.py` | 分析请求不退回管理员，已登录请求和健康接口正常 |
| 2 | 建立独立执行结果，统一数据库入口，迁移共享 `last_query_info` 的读取 | `contracts/execution.py`、`execution/query_executor.py`、`infrastructure/database.py`、`services/chatbi_service.py` | 每次执行的 SQL、耗时和结果对应正确；现有前端契约保持兼容 |
| 3 | 加入 AST 检查及受限范围策略，修复直接事实表、OR 与别名问题 | `execution/` 与 `core/security.py` | 支持范围内查询正确，越权和不支持结构被拒绝 |
| 4 | 校验 Agent 重试也经过执行器，权限错误不再重复修复 | `analysis/agent_planner.py`、`analysis/analysis_service.py` | SQL 修复保留原意且重新校验，权限拒绝及时结束 |

只在上述安全入口可验证之后，继续补执行预算、业务数据、Java 接入和持久任务。每完成一组，在本阶段文档记录修改文件、验证结果、仍存在的限制和下一组任务；规划未完成的内容保持明确标识。

## 首组实施记录（2026-10-06）

本组完成执行入口的四项任务，并修正问题改写与指标检索顺序；不代表第一步全部验收完成。

| 已完成内容 | 修改位置 | 验证结果 |
|---|---|---|
| 分析缺身份即拒绝；公开健康/登录路径不授予演示管理员身份；默认角色改为 pending | `core/security.py`、`api/dependencies.py`、`api/routes.py`、两个业务服务 | 无身份、空身份、待授权和缺区域拒绝；现有登录与业务 API 回归通过 |
| 不可变执行身份快照、独立结果对象和统一执行器；兼容 execute 二元组接口也经过校验 | `contracts/execution.py`、`execution/query_executor.py`、`infrastructure/database.py`、`services/chatbi_service.py` | 同步/流式 SQL 与实际执行一致；双线程结果和统计独立，不再使用 last_query_info |
| MySQL AST 校验五表、列来源与函数；覆盖非相关子查询、CTE/UNION 各分支；普通星号展开 | `execution/sql_policy.py`、`core/security.py`、`pyproject.toml`、`uv.lock` | 别名/聚合/WHERE/ORDER BY 的敏感来源拒绝；系统表、写入、变量、危险函数和未支持结构在建连前拒绝 |
| 客户区域为授权事实源；每个客户/订单基础表在派生查询中限制范围；拒绝遮蔽业务表的 CTE | `execution/sql_policy.py` | SQLite 内存数据验证直接订单、OR、CTE、派生表、UNION、多区域和 LEFT JOIN 返回值；订单冗余 region 故意不一致也不能绕过 |
| 修复后的 SQL 再次校验；安全/权限/超时/未知错误结束，不重复尝试绕过；MySQL 权限错误优先分类 | `analysis/agent_planner.py`、`infrastructure/database.py` | 同步与流式修复从可执行 SQL 变成越权 SQL 时，第二次在建连前拒绝；1142 不再误分类为语法错误 |
| 先改写再检索；返回与保存受控执行后的 SQL；工作台成功后更新 SQL | `services/chatbi_service.py`、`frontend/src/App.tsx`、`tools/evaluator.py` | 指标检索收到改写后的完整问题；评测工具显式传入离线演示身份 |
| 测试与机器配置隔离 | `tests/conftest.py`、既有测试和新增 `tests/test_execution_pipeline.py` | 固定功能开关、临时账户/会话存储，不调用真实模型和业务数据库 |

验证记录：

- `uv run pytest -q`：204 项通过，12.23 秒；有一项既有 FastAPI/Starlette 测试客户端弃用警告。
- `frontend` 的 `npm run build`：TypeScript 与生产构建通过；有大体积资源包提示，本组未做前端分包优化。
- 50 条参考 SQL 的离线策略检查：49 条可通过，C12 使用窗口函数，当前明确拒绝；此检查不执行 SQL，也不是重新评测准确率。
- `git diff --check`：通过。未运行真实 MySQL、真实模型或浏览器端到端验收。

首组完成时的限制：当前表/列清单是固定制造业五表，不是按源发布的 Schema；区域授权沿用现有用户模型，尚无租户与数据源归属校验。销售任意财务 SQL 继续禁止，收入聚合模板待接入。窗口函数、相关子查询、递归 CTE、RIGHT/FULL/CROSS JOIN 和未批准函数暂不支持。当时连接池并发计数、生命周期、无界 fetchall、SQL 服务端限时与统一总预算尚未整改；这些执行资源问题已在第二组处理。

首组后的任务安排：先补预算、连接池和只读账户（第二组已落实），再处理固定业务日期、可比较数据、口径与索引/容器初始化。完成这些后再验收第一阶段并接入 Java。

## 第二组：预算、连接池与只读账户（2026-10-06）

本组仍属于第一阶段，与下方 Compose 启动修复一并提交；不代表第一阶段全部验收完成。

| 已完成内容 | 主要位置 | 关键行为 |
|---|---|---|
| 请求时间、SQL 尝试次数与累计结果字节预算 | `execution/budget.py`、`services/chatbi_service.py`、`analysis/agent_planner.py`、`analysis/analysis_service.py` | 普通查询、流式、多步及独立 Plan-and-Execute 入口共享截止时间；失败与修复不重置次数预算 |
| 单条 SQL 行数/字节限制、逐行获取与完整性 | `execution/query_executor.py`、`infrastructure/database.py`、`contracts/execution.py` | 自动 LIMIT 至最多上限加一行用于检测；保留更小的显式 LIMIT；SSCursor 逐行读取，超过任一限制直接失败，不返回截断成功结果 |
| MySQL 服务端限时、只读事务与网络超时 | `infrastructure/database.py` | 每次 SELECT 前由可信执行器设置 max_execution_time 和只读事务；socket 读取服从剩余时间；超时和未读完结果的连接销毁 |
| 有界、线程安全连接池和生命周期 | `infrastructure/database.py`、`bootstrap/runtime_factory.py`、`services/chatbi_service.py`、`api/app.py` | 创建前预留容量；失败释放名额；关闭唤醒等待者；晚归还连接销毁；按源复用运行时，应用关闭及分析流结束时释放资源 |
| 模型、向量调用与步骤事件预算 | `execution/budgeted_llm.py`、`infrastructure/llm_client.py`、三个检索模块、`analysis/agent_planner.py` | 调用超时不超过剩余预算，SDK 不再内部重试；SSE 预算上下文不跨 yield，线程内继承；步骤队列有界并可按截止时间结束等待 |
| 分析请求隔离及超限收尾 | `analysis/analysis_service.py` | 拆解器和报告生成器按请求复制，不重绑共享对象；时间/结果预算或 SQL 超时终止后不继续生成完整报告 |
| 演示只读账户及密码分离 | `docker/mysql/init/02-reader.sh`、`docker-compose.yml`、`.env.example`、`.gitattributes` | reader 仅获五张表 SELECT；管理密码不传给后端；支持旧演示卷显式授权，不删除数据；shell 固定 LF |
| API 错误、结果统计和日期序列化 | `api/routes.py`、`contracts/execution.py`、`services/chatbi_service.py` | 结果超限 413、总预算/查询超时 504、连接池等待超时 503；每次结果带大小、限时及完整标记；日期可序列化为 SSE |
| 配置与部署说明 | `README.md`、`.env.example`、`docker-compose.yml` | 预算可配置，前端默认端口统一为 8300；记录旧数据卷账户迁移及隔离集成测试入口 |

执行预算的默认值见 [README](../../README.md#当前查询执行范围)。这些值来自可信服务配置，不接受模型或请求体修改。当前 SQL 只支持既有五表，业务授权动态配置仍按后续数据源治理阶段建设。

### 验证记录

- 全量验证：`CHATBI_MYSQL_INTEGRATION=1 uv run pytest -q`，241 项通过，22.39 秒，其中 9 项为真实 MySQL 集成测试；一项既有 FastAPI/Starlette 测试客户端弃用警告。
- MySQL 测试使用独立 `mysql:8.4` 容器，创建并验证 reader 账户（密码包含单引号和反斜杠）；直接绕开应用安全层，确认 INSERT/UPDATE/DELETE/CREATE 和 mysql.user 访问由数据库拒绝。
- 耗时聚合查询确实返回 MySQL 错误码 3024；超时与结果超限均销毁当前连接，下一次正常查询重新建立干净连接。区域查询返回欧洲 3 笔、财务查询 5 笔，与演示数据一致。
- 离线测试覆盖同一截止时间和重试次数、UTF-8 字节/行数超限、超限不返回成功结果、报告终止、SQL 超时 HTTP 映射、模型流关闭、SSE 跨线程预算上下文、连接池并发预留/创建失败/关闭唤醒/迟到连接及请求结束清理。
- `docker compose --env-file .env.example config --quiet` 和 `git diff --check` 均通过；测试容器已删除，没有留下测试卷或变更现有数据库。
- 本组没有修改前端源码，未重复前端构建；没有调用真实模型，也没有完成整套 Compose 的干净构建、索引初始化或浏览器端到端验收。

### 当前限制与下一组

- 时间预算属于阶段边界检查加网络超时；本地同步计算、第三方库调用和正在执行的操作不能由 Python 立即强制取消。执行结果在预算过期后不会被接受，已有 SQL 受服务端限时约束；完整取消协议仍属于后续持久任务建设。
- 字节统计针对列和结果行的 UTF-8 JSON 表示，包含行字段名，不包含 SQL、格式化文本、报告和 SSE 外层封装；单行读取仍有驱动协议包开销，不是进程内存的硬配额。
- 本组只切换配置与演示初始化方案，并在独立 MySQL 验证；没有读取或修改本机 `.env`，没有改现有业务数据库账户、凭据或数据。已有演示卷需按 README 显式切换。
- 固定五表/角色策略、租户与数据源授权、按源发布的元数据和指标仍未实现；不把本组结果宣传成任意企业数据库的完整治理。
- 下一组继续第一阶段：固定分析日期、补可比较业务数据、收敛经营利润/换汇/成本/单位口径；处理索引初始化、干净构建、账户/会话数据排除及健康就绪。随后再验收第一阶段。

实现依据：MySQL 的 SELECT 服务端限时范围参见 [max_execution_time 官方文档](https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html#sysvar_max_execution_time)；逐行读取与关闭时排空结果的行为参见 [PyMySQL SSCursor 文档](https://pymysql.readthedocs.io/en/latest/modules/cursors.html#pymysql.cursors.SSCursor)。

## 追加修复与验证：本机 Compose 启动（2026-10-06）

用户启动 Compose 失败后，定位到 Windows 保留端口包含 8000 和 8300，导致容器无法绑定宿主机端口。增加 `BACKEND_PORT` 配置，并只将本机 `.env` 的端口映射改为后端 18000、前端 18300；其他环境配置保持不变。

随后确认后端已配置为 `chatbi_reader`，但现有演示库中尚无该账户。显式运行 `02-reader.sh` 创建并授权只读账户，业务表数据未修改。原后端镜像创建于 10 月 2 日，已通过 `docker compose up -d --build` 重建为当前工作区代码。

补充 `pymysql[rsa]` 依赖，支持 MySQL 8 完整认证；依据见 [PyMySQL 安装说明](https://pymysql.readthedocs.io/en/latest/user/installation.html)。`.dockerignore` 增加本地账户/会话 SQLite 与环境文件排除，避免构建时复制这些文件。

验证结果：

- 当前工作区前后端镜像构建及容器启动成功，MySQL 与后端为 healthy。
- `http://localhost:18300`、`http://localhost:18000/health` 和前端代理的 `/backend/health` 均返回 200，两处健康检查的 `database_connected` 均为 true。
- 重设 reader 凭据后，新后端进程再次认证成功；真实受控查询返回 5 笔订单，并带 5000 毫秒 SQL 时间限制。
- 新后端镜像的 `/app/data` 不含本地账户或会话数据库；MySQL 隔离集成测试重新运行，9 项通过，9.53 秒。
- 本次验证使用已有本地 Chroma 索引，不代表无索引的干净检出已可构建；没有调用真实模型，也未完成浏览器查询端到端验收。
