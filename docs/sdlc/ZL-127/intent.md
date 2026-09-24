# Intent: 练习会话与判题自评 API 路由

- **任务编号**: ZL-127
- **提出人**: TechLead
- **创建时间**: 2026-09-24 20:53
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft

---

## 1. 问题与现状背景 (Problem)
在先前的阶段（ZL-122、ZL-123）中，系统已经完成了练习组卷与交卷调度服务（`PracticeService`）以及判题编排与自评/重判服务（`GradingService`）的底层领域编排与数据仓储实现，并通过了单测验证。
然而，当前 API 控制层（`app/api/v1`）尚未暴露针对练习会话（`practices`）与判题记录/自评重判（`grading`）的 HTTP RESTful 路由与 Pydantic v2 DTO 契约。小程序客户端无法通过网络请求发起练习组卷、暂存逐题作答草稿、执行交卷强幂等校验、查看练习详情、查询判题结果、提交主观题自评或发起异步重判。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **Pydantic v2 DTO 数据契约** (`app/schemas/practice.py` & `app/schemas/grading.py`):
   - 组卷创建请求（3 种组卷模式：`sequential`, `random`, `weak_points`，知识点范围，题量 1~50）；
   - 练习会话详情、题目快照（6 要素解耦脱敏）、逐题作答状态与分页列表响应；
   - 逐题作答草稿暂存请求（`question_id`, `user_answer`, `time_spent_seconds`）与响应；
   - 练习状态流转响应（暂停/恢复）；
   - 交卷请求与响应（支持 HTTP Header `Idempotency-Key` 强幂等防护，返回提交状态、是否未答确认阻断）；
   - 主观题用户自主评分请求（`attempt_item_id`, `score`, `feedback`）与响应；
   - 重新判题请求（`attempt_item_id`, `reason`）与响应；
   - 题目最新判题结果与历史判题记录响应（得分、评分渠道、评语、是否最终生效）。
2. **依赖注入容器** (`app/api/deps/practice.py` & `app/api/deps/grading.py`):
   - 提供 `get_practice_service` 与 `get_grading_service` 依赖，解耦数据库会话与外部队列/幂等/LLM 适配器注入。
3. **练习与判题 RESTful 路由** (`app/api/v1/practices.py` & `app/api/v1/grading.py`):
   - `POST /api/v1/practices`: 发起组卷创建练习；
   - `GET /api/v1/practices`: 练习历史会话列表（支持按状态过滤、分页）；
   - `GET /api/v1/practices/{id}`: 练习会话详情与作答题目快照；
   - `PUT /api/v1/practices/{id}/answers`: 逐题作答草稿实时暂存；
   - `POST /api/v1/practices/{id}/pause`: 练习会话暂停；
   - `POST /api/v1/practices/{id}/resume`: 练习会话恢复；
   - `POST /api/v1/practices/{id}/submit`: 提交交卷（强幂等锁拦截，24h快照回放，异步投递判题队列）；
   - `POST /api/v1/grading/self-evaluate`: 主观题自评打分覆盖；
   - `POST /api/v1/grading/regrade`: 用户申请异步重新判题；
   - `GET /api/v1/attempts/{attempt_item_id}/grading`: 查询题目判题明细与历史记录。
4. **统一汇聚与装配** (`app/api/v1/__init__.py`):
   - 挂载 `practices_router` 与 `grading_router` 至 `/api/v1`。
5. **门禁与安全质量保证**:
   - `check_layers.py` 自动化检测 0 违规，严禁在路由层导入 `app.repositories`，路由仅做 1 行委托至 Service；
   - 严格落实多租户隔离，全部端点通过 `Depends(get_current_user)` 获取当前用户 UUID，阻断越权访问；
   - 全套单元测试覆盖正常流转与异常错误码映射（如 40010、40011、40012、40013、40014、40015、20001 等），覆盖率 $\ge 90\%$。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 严格遵守 5 层单向架构，`app/api/v1` 严禁直接导入 `app.repositories` 或调用 ORM 原生事务；
  - 缩写白名单仅限 8 个：`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`；
  - 日志 8 要素结构化且严禁记录题干、选项、答案和用户作答原文；
  - 依赖注入统一使用 FastAPI `Depends`，便于单测替换 Fake/Stub；
  - 单元测试运行时间控制在毫秒级，严禁外部真实联网。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含前端小程序 UI 页面实现（由后续 ZL-134、ZL-135 承担）；
  - 不包含学情诊断报告与掌握度聚合 API（由后续 ZL-128 承担）；
  - 不修改底层的 `PracticeService`、`GradingService` 业务算法核心逻辑。
* **完成判定条件 (Definition of Done)**:
  - `python3 tooling/check_layers.py --root backend/app` 0 违规；
  - `ruff format --check .`、`ruff check .`、`mypy app`、`bandit -r app -ll` 全绿；
  - `backend/app/api/v1/practices.py` 与 `grading.py` 路由测试覆盖率 $\ge 90\%$；
  - 全量后端单测 100% 通过且无联网报错。

## 6. 未决疑问与待探讨点 (Open Questions)
- 判题相关路由是挂载在 `/api/v1/grading` 和 `/api/v1/attempts` 下，还是整合在 `/api/v1/practices` 下？
  - 方案确认：为保持领域职责清晰与 RESTful 规范，练习会话相关置于 `practices.py`（前缀 `/practices`），判题记录与自评/重评置于 `grading.py`（包含 `/grading/self-evaluate`、`/grading/regrade` 及 `/attempts/{attempt_item_id}/grading`）。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead / 2026-09-24 20:55
