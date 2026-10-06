# 第一阶段：统一查询执行与安全边界

> 更新日期：2026-10-06。
> 当前状态：进行中；首组“执行入口”已完成，第一阶段尚未全部验收。
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

仍存在的限制：当前表/列清单是固定制造业五表，不是按源发布的 Schema；区域授权沿用现有用户模型，尚无租户与数据源归属校验。销售任意财务 SQL 继续禁止，收入聚合模板待接入。窗口函数、相关子查询、递归 CTE、RIGHT/FULL/CROSS JOIN 和未批准函数暂不支持。连接池并发计数、生命周期、无界 fetchall、SQL 服务端限时与统一总预算尚未整改，当前不能宣称完整生产级执行治理。

下一组继续第一步：补结果行数/字节与执行时间预算，完善连接池生命周期和并发控制，切换并验证只读 MySQL 账户；随后处理固定业务日期、可比较数据、口径与索引/容器初始化。完成这些后再验收第一步并接入 Java。
