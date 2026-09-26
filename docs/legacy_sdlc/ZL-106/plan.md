# Plan: 练习、答卷、掌握度与诊断报告数据模型 - 实施计划

- **关联 Spec**: ZL-106
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution

---

## 1. 变更文件清单 (Files that change)
* `backend/app/models/practice.py` (New - 6 大核心实体模型、枚举与纯函数辅助工具)
* `backend/app/models/__init__.py` (Modify - 统一导出练习域实体、枚举及纯函数)
* `backend/migrations/versions/0003_create_practice_tables.py` (New - Alembic 数据库迁移与对称回滚脚本)
* `backend/tests/unit/models/test_practice.py` (New - 实体字段约束、状态机、快照解耦与脱敏单测)
* `backend/tests/unit/models/test_practice_migrations.py` (New - Alembic 迁移升降级双向对称验证测试)
* `docs/sdlc/ZL-106/plan.md` (Modify - 实施计划工件)

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 测试先行 (Fail-repro First)
* **操作目标**: 编写练习域核心实体初始测试桩，定义实体导入与初始断言，在终端亲眼见证红灯（Fail）
* **涉及文件**: `backend/tests/unit/models/test_practice.py`
* **局部验证命令**: `cd backend && uv run pytest tests/unit/models/test_practice.py`
* **预期判据**: 因 `app.models.practice` 尚未实现，测试运行报错 `ModuleNotFoundError` 或 `ImportError`（红灯）

### Step 2: 核心实体模型与纯函数实现
* **操作目标**: 在 `backend/app/models/practice.py` 中实现 6 大核心实体模型（`Practice`, `AttemptItem`, `GradingRecord`, `MasteryRecord`, `DiagnosisReport`, `WrongRecord`）、相关枚举类及纯函数校验工具（`validate_question_snapshot`, `validate_practice_transition`）
* **涉及文件**: `backend/app/models/practice.py`, `backend/app/models/__init__.py`
* **局部验证命令**: `cd backend && uv run pytest tests/unit/models/test_practice.py`
* **预期判据**: 实体模型正常导入，表结构映射与纯函数测试变绿（绿灯）

### Step 3: Alembic 迁移脚本与双向对称实现
* **操作目标**: 实现 `0003_create_practice_tables.py`，完整支持 PostgreSQL 与 SQLite 方言自适应，实现 6 张表的 `upgrade()` 创建与 `downgrade()` 逆序清理
* **涉及文件**: `backend/migrations/versions/0003_create_practice_tables.py`
* **局部验证命令**: `cd backend && uv run pytest tests/unit/models/test_practice_migrations.py`
* **预期判据**: 数据库迁移双向执行 `upgrade()` -> `downgrade()` -> `upgrade()` 100% 成功

### Step 4: 完备覆盖与绝密脱敏验证
* **操作目标**: 完善 `test_practice.py` 覆盖两阶段答卷状态机、题目快照软解耦、幂等唯一索引、级联删除与 `__repr__` 绝密脱敏
* **涉及文件**: `backend/tests/unit/models/test_practice.py`
* **局部验证命令**: `cd backend && uv run pytest tests/unit/models/test_practice.py --cov=app/models/practice --cov-branch`
* **预期判据**: 单元测试全绿，`app/models/practice.py` 行覆盖率与分支覆盖率均达成高标准门禁

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd backend && uv run ruff format --check . && uv run ruff check .`
* **类型与契约安全校验**: `cd backend && uv run mypy app`
* **全量相关测试回归**: `cd backend && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80`
* **安全审计与分层校验**: `cd backend && bandit -r app -ll && python3 tooling/check_layers.py --root backend/app`
* **SDLC 门禁校验**: `python3 tooling/task_cli.py check ZL-106`

## 4. 实施偏差记录 (Deviations Log)
* 架构契约与 Spec 保持高度一致，无结构性偏差。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Approved
- **验证人 / 日期**: User / 2026-09-23 20:55
