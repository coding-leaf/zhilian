# Intent: 资料管理与解析调度 API 路由

- **任务编号**: ZL-125
- **提出人**: Dev
- **创建时间**: 2026-09-24 19:08
- **初始 Change Tier**: Tier 2
- **当前状态**: In-Review

---

## 1. 问题与现状背景 (Problem)
智练平台底层已构建完备的资料领域编排服务 `MaterialService`（覆盖文件魔数校验、格式与大小限制、SHA-256 查重秒传、MinIO 隔离存储、纯函数知识切分、OCR 质量门禁与就地重拍熔断、以及多版本管理）。然而在系统外部接口层（`app/api/v1`），目前尚未提供对外暴露的 HTTP 路由控制器及对应 Pydantic 请求出入参 DTO 契约。客户端（微信小程序与管理端）无法进行学习资料上传、详情查看、状态轮询、列表检索、解析调度重试、版本切换、分页重拍替换及软/硬删除操作。必须提供高内聚、零业务越权、严格遵循五层单向架构规范的 API 路由模块。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
1. 在 `backend/app/schemas/material.py` 定义完备的 Pydantic v2 数据契约（DTO），包括资料上传、详情、分页列表、版本列表、版本切换、分页重拍、解析调度与删除确认的出入参结构，支持严格的数据类型、边界值校验与序列化支持。
2. 在 `backend/app/api/deps/material.py` 实现依赖注入工厂 `get_material_service`，配合 `app/api/deps/auth.py` 的租户安全凭证提取器 `get_current_user`，实现完全解耦的依赖装配。
3. 在 `backend/app/api/v1/materials.py` 实现全部 9 个核心 RESTful 路由（上传、详情、列表、解析调度、版本列表、版本切换、单页重拍、软删除、硬删除），路由函数严格限制为 1 行调用 Service，绝对不导入 `app.repositories`，不直接开启数据库事务。
4. 全面集成统一业务异常处理与脱敏结构化日志（8 要素），为后续微信小程序端（ZL-132）提供坚实的端侧接入支撑。

## 4. 波及工程分面 (Affected Architectural Layers)
- [ ] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [x] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - **架构分层铁律**：`backend/app/api/` 绝对严禁直接或间接导入 `app.repositories`，严禁直接操作数据库 Session 事务，违规由 `tooling/check_layers.py` 自动化拦截。
  - **多租户强隔离**：所有路由接口必须强制依赖 `get_current_user` 校验合法身份，并直接将当前用户的 `user.id` 传递给领域服务层，禁止接收外部传入的伪造 `user_id`。
  - **绝密日志脱敏红线**：日志仅记录操作摘要，严禁输出原文件内容、OCR 全文或敏感密钥，严格保障 8 要素结构化日志规范。
  - **命名与缩写规范**：缩写白名单仅限 8 个 (`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`)，严禁自造任何缩写。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不修改资料切分与 OCR 质检纯函数计算核算法规则；
  - 不修改持久化数据库表结构与 Alembic 迁移脚本；
  - 不涉及知识点树图谱与出题相关的下游 API；
  - 不涉及小程序前端 UI 组件渲染。
* **完成判定条件 (Definition of Done)**:
  - 9 个 RESTful 接口路由全部通过单元与集成测试（覆盖鉴权、正常流程、异常捕获与越权拦截）；
  - `tooling/check_layers.py --root backend/app` 架构分层校验 0 违规；
  - `tooling/check_sdlc_integrity.py` 检查通过；
  - 核心静态检查（`ruff check .`, `mypy app`）零警告，代码覆盖率达到门禁要求。

## 6. 未决疑问与待探讨点 (Open Questions)
- 重拍分页索引统一采用 1-based 页码 (`page_index >= 1`) 与底层的 `OCRPageInput.page_number` 对齐，在 Schema 层面通过 Field 校验严格限定。

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Passed
- **签批人 / 日期**: Dev / 2026-09-24