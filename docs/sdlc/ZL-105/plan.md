# Plan: 知识点与题目持久化数据模型及审计日志 - 实施计划

- **关联 Spec**: ZL-105
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution

---

## 1. 变更文件清单 (Files that change)
* `backend/app/models/knowledge.py` (New): 知识点实体 KnowledgePoint 与切片关联实体 KnowledgePointSnippet
* `backend/app/models/question.py` (New): 题目实体 Question、质检记录 QuestionQualityCheck、审计日志 QuestionAuditLog 及相关枚举、验证纯函数
* `backend/app/models/__init__.py` (Modify): 统一导出知识点、题目相关实体模型与枚举
* `backend/migrations/versions/0002_create_knowledge_and_question_tables.py` (New): 数据库 DDL 迁移脚本 (支持 PG/SQLite 方言与 HNSW 向量索引)
* `backend/tests/unit/models/test_knowledge.py` (New): 知识点树模型自引用、级联删除、片段映射、租户隔离与安全脱敏测试
* `backend/tests/unit/models/test_question.py` (New): 题目 7 大题型、6 要素、评分细则分值核算、质检、审计日志、软删除、__repr__脱敏及迁移升降级测试
* `docs/sdlc/ZL-105/plan.md` (Modify): 实施计划与步骤细化

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)
> **原则**：每个步骤必须配对明确的局部验证命令，步步红绿流转，禁止跳过单步验证直接写完提交。

### Step 1: 测试先行 (Fail-repro First)
* **操作目标**: 编写针对知识点树自引用、片段映射、题目 7 大题型、评分细则分值校验、审计日志及 Alembic 升降级的单元测试桩
* **涉及文件**: `backend/tests/unit/models/test_knowledge.py`, `backend/tests/unit/models/test_question.py`
* **局部验证命令**: `cd backend && uv run pytest tests/unit/models/test_knowledge.py tests/unit/models/test_question.py`
* **预期判据**: 确认因模型与迁移尚未实现，模块导入失败或测试运行变红（Fail）

### Step 2: 核心业务逻辑与实体模型实现
* **操作目标**: 实现 KnowledgePoint, KnowledgePointSnippet, Question, QuestionQualityCheck, QuestionAuditLog 实体模型，定义 QuestionType 等枚举，实现安全脱敏 __repr__ 与题目 payload 校验纯函数，在 models/__init__.py 中导出
* **涉及文件**: `backend/app/models/knowledge.py`, `backend/app/models/question.py`, `backend/app/models/__init__.py`
* **局部验证命令**: `cd backend && uv run pytest tests/unit/models/test_knowledge.py tests/unit/models/test_question.py -k "not test_migration"`
* **预期判据**: 知识点与题目模型单元测试全部通过，测试变绿（Pass）

### Step 3: 数据库迁移脚本实现与双向对称验证
* **操作目标**: 编写 Alembic 迁移脚本 0002_create_knowledge_and_question_tables.py，包含 PG/SQLite 方言兼容、HNSW 余弦向量索引创建及严格对称 downgrade 逻辑
* **涉及文件**: `backend/migrations/versions/0002_create_knowledge_and_question_tables.py`
* **局部验证命令**: `cd backend && uv run pytest tests/unit/models/test_question.py -k "test_migration"`
* **预期判据**: Alembic upgrade 与 downgrade 双向测试通过，表与索引创建回滚完全对称

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd backend && uv run ruff format --check . && uv run ruff check .`
* **类型与契约安全校验**: `cd backend && uv run mypy app && python3 tooling/check_layers.py --root backend/app`
* **全量相关测试回归**: `cd backend && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80`
* **核验结果**: 静态代码规范、类型检查与单向依赖校验 100% 通过，全量单测与覆盖率门禁达标

## 4. 实施偏差记录 (Deviations Log)
* 暂无架构与接口偏差，实现完全遵照 docs/sdlc/ZL-105/spec.md 技术契约执行

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Approved
- **验证人 / 日期**: User / 2026-09-23 20:30
