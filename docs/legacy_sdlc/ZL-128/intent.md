# Intent: 诊断报告与错题闭环 API 路由

- **任务编号**: ZL-128
- **提出人**: TechLead
- **创建时间**: 2026-09-24 21:51
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft

---

## 1. 问题与现状背景 (Problem)
在先前的阶段（ZL-124）中，系统已经完成了学情诊断报告生成、艾宾浩斯 30 天半衰期时间衰减掌握度聚合（`aggregate_mastery_scores`）与错题本联动更新服务（`DiagnosisService`），并通过了单元测试与物理隔离验证。
然而，当前 API 控制层（`app/api/v1`）尚未暴露针对学情诊断（`diagnosis`）、掌握度总览（`mastery`）与错题本闭环（`wrong-records`）的 HTTP RESTful 路由与 Pydantic v2 DTO 契约。小程序客户端无法在练习判题完成后请求生成诊断报告、无法查询掌握度四档徽章与薄弱退步分析、亦无法浏览错题本或将错题一键标记为已掌握消灭。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. **Pydantic v2 DTO 数据契约** (`app/schemas/diagnosis.py`):
   - 诊断报告响应（`DiagnosisReportResponse`：包含 `practice_id`、作答前后掌握度对比、知识点归因评估详情 `knowledge_evaluations`、根因分析 `root_causes`、自适应学习建议与总结）；
   - 用户全量掌握度概览（`UserMasteryOverviewResponse`：已掌握/学习中/薄弱知识点统计与掌握度列表）；
   - 单知识点掌握度详情（`KnowledgeMasteryResponse`：掌握度得分、四级档次 `level`、练习与正确次数、最后练习时间）；
   - 错题本列表与详情（`WrongRecordListResponse`, `WrongRecordItemResponse`：支持关联题目 6 要素快照与错因分类）；
   - 错题掌握标记响应（`MarkWrongRecordMasteredResponse`）。
2. **依赖注入容器** (`app/api/deps/diagnosis.py`):
   - 提供 `get_diagnosis_service` 依赖工厂，解耦数据库会话与底层服务。
3. **诊断与错题闭环 RESTful 路由** (`app/api/v1/diagnosis.py`):
   - `POST /api/v1/practices/{id}/diagnosis`: 触发生成指定练习的诊断报告（若练习处于未完成判题状态 `PARTIALLY_GRADED` 或 `IN_PROGRESS`，阻断并返回 400 状态码与业务错误码 `40016`）；
   - `GET /api/v1/practices/{id}/diagnosis`: 获取指定练习已生成的诊断报告；
   - `GET /api/v1/mastery`: 查询当前用户的全量知识点掌握度概览；
   - `GET /api/v1/mastery/{knowledge_point_id}`: 查询单个知识点的掌握度详情；
   - `GET /api/v1/wrong-records`: 错题本列表检索（支持按 `material_id`、`knowledge_point_id`、`error_type`、`is_mastered` 过滤与分页）；
   - `POST /api/v1/wrong-records/{id}/master`: 将错题标记为已消灭/已掌握。
4. **统一汇聚与装配** (`app/api/v1/__init__.py`):
   - 挂载 `diagnosis_router` 至 `/api/v1`。
5. **门禁与安全质量保证**:
   - `check_layers.py` 自动化检测 0 违规，严禁在路由层导入 `app.repositories`，路由仅做 1 行委托至 Service；
   - 严格落实多租户隔离，全部端点通过 `Depends(get_current_user)` 获取当前用户 UUID，阻断越权访问；
   - 全套单元测试覆盖正常流转与异常错误码映射（`PracticeNotGradedError` 400/40016, `DiagnosisReportNotFoundError` 404/40017, `PracticeNotFoundError` 404/40010, `WrongRecordNotFoundError` 404/40019 等），覆盖率 $\ge 90\%$。

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
  - 不包含前端小程序诊断组件实现（由后续 ZL-135、ZL-136 承担）；
  - 不修改底层的 `DiagnosisService` 计算与归因规则；
  - 不包含外部推送通知机制。
* **完成判定条件 (Definition of Done)**:
  - `python3 tooling/check_layers.py --root backend/app` 0 违规；
  - `ruff format --check .`、`ruff check .`、`mypy app`、`bandit -r app -ll` 全绿；
  - `backend/app/api/v1/diagnosis.py` 路由测试覆盖率 $\ge 90\%$；
  - 全量后端单测 100% 通过且无联网报错。

## 6. 未决疑问与待探讨点 (Open Questions)
- 诊断报告与错题本是在同一个路由文件 `diagnosis.py` 下承载还是拆分为多个文件？
  - 方案确认：为保持学情分析与错题消灭闭环内聚性，收敛在 `app/api/v1/diagnosis.py`，清晰组织 `/practices/{id}/diagnosis`、`/mastery`、`/wrong-records` 路径，避免文件过度碎片化。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: TechLead / 2026-09-24 21:53
