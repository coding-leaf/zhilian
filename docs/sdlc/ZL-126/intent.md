# Intent: 知识点树与题目管理 API 路由

- **任务编号**: ZL-126
- **提出人**: Dev
- **创建时间**: 2026-09-24 20:02
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
智练系统前期已完成知识点抽取与质检服务（KnowledgeService）、题目生成与质检服务（QuestionService）、底层数据模型与仓储持久化层。
然而，系统对外接口层（app/api/v1/）目前仅挂载了资料管理路由（materials.py），缺乏知识点图谱拓扑查询、片段双向溯源、手动抽取触发、题目生成、多维题目检索、题目人工审核/编辑、题目修改审计追溯以及资料下质检拦截记录查询等 HTTP 接口，导致前端小程序与外部客户端无法通过合规的 RESTful API 消费上述核心能力。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. 完整落地 FR-14~FR-19 规定的知识点相关 API：
   - `GET /api/v1/materials/{material_id}/knowledge-tree`（支持 version_id 查询参数）：获取多层树形拓扑结构，标明节点层级、父子关联与低可信度标记；
   - `GET /api/v1/knowledge/{id}`：获取单个知识点详情；
   - `GET /api/v1/knowledge/{id}/snippets`：反向溯源，获取知识点关联的来源切片列表；
   - `GET /api/v1/knowledge/snippets/{snippet_id}/knowledge-points`：正向溯源，通过切片查询关联知识点列表；
   - `POST /api/v1/materials/{material_id}/knowledge/extract`：触发指定资料版本的知识点全量抽取与建树流程。
2. 完整落地 FR-20~FR-27 规定的题目相关 API：
   - `POST /api/v1/questions/generate`：触发大模型出题与质检，支持多题型、题数、难度，严格执行 40003 切片门禁；
   - `GET /api/v1/questions/{id}`：获取题目详情，包含 6 要素、来源切片溯源、难度与质检状态；
   - `GET /api/v1/questions`：多条件分页筛选题目（material_id, knowledge_point_id, question_type, difficulty, status）；
   - `PUT /api/v1/questions/{id}`：题目人工修改与审核，持久化不可变修改痕迹审计日志；
   - `DELETE /api/v1/questions/{id}`：软删除题目，解耦答卷并记录审计日志；
   - `GET /api/v1/questions/{id}/edit-logs`：查看题目修改审计痕迹日志；
   - `GET /api/v1/materials/{material_id}/quality-checks`：查看该资料下被质检拦截的题目记录与拦截原因。
3. 严格遵循五层单向架构与 AGENTS.md 编码红线，测试覆盖率达成门禁要求。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [x] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 路由层严格单向向下调用，严禁导入 `app.repositories`；
  - 路由层严禁直接访问数据库会话或开启事务；
  - 路由层严禁执行超过 1 行的业务判断逻辑；
  - 所有接口强制依赖 `get_current_user` 鉴权，严格携带 `user_id` 阻断水平越权；
  - 标识符一律英文，缩写白名单仅限 8 个（api, id, url, ocr, llm, db, config, env）；
  - 接口遵循统一 `AppError` 错误码（未登录 20001、越权 20002、缺切片 40003、资源不存在 40007/40009/40010）；
  - 满足 `tooling/check_layers.py` 静态检查，0 违规导入。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不修改现有数据库表结构或 Alembic 迁移脚本；
  - 不修改核心算法逻辑（如知识点质检核、题目质检核与判定核）；
  - 不包含练习创建与判题 API 路由（属于后续 ZL-129 与 ZL-130 范围）。
* **完成判定条件 (Definition of Done)**:
  - 编写 `app/schemas/knowledge.py` 与 `app/schemas/question.py` DTO 定义；
  - 编写 `app/api/deps/knowledge.py` 与 `app/api/deps/question.py` 依赖项；
  - 编写 `app/api/v1/knowledge.py` 与 `app/api/v1/questions.py` 路由模块并在 `app/api/v1/__init__.py` 挂载；
  - 在 `KnowledgeService` 与 `QuestionService` 中补齐路由所需的查询编排方法，确保全量调用经由 Service 层；
  - 编写配套单元测试 `test_knowledge_router.py` 与 `test_question_router.py`，覆盖正向、多租户越权隔离（404/20002）、未登录（401/20001）、参数缺失（422）等边界；
  - `python3 tooling/check_layers.py --root backend/app` 0 违规，`pytest tests/unit/api` 100% 通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 知识树与抽取路由的前缀划分：获取资料知识树与抽取属于资料层级操作，可挂载于 `/api/v1/materials/{material_id}/knowledge-tree` 与 `/api/v1/materials/{material_id}/knowledge/extract`（或在 materials router 中扩展，或通过 knowledge router 路由），推荐在 knowledge router 中以对应路径注册或统一挂载，保证路由职责清晰。
- 题目列表与资料下质检拦截记录的分页模式：采用 limit/offset 还是 page/page_size，统一对齐已有 `MaterialListResponse` 规范（limit/offset）。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [ ] 场景与问题已客观复现并达成共识
- [ ] 边界、非目标与约束清晰明确
- [ ] 初始 Change Tier 评定合理
- **准出结论**: Pending
- **签批人 / 日期**: [待人类签批] / 2026-09-24 20:02
