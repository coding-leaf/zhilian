# Plan: 学习资料、版本与知识片段存储模型 (含 pgvector) - 实施计划

- **关联 Spec**: ZL-104
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution

---

## 1. 变更文件清单 (Files that change)

### 依赖与工程配置 (Dependencies & Config)
* `backend/pyproject.toml` (Modify): 在项目运行时依赖中补充 `pgvector>=0.3.0`。
* `backend/uv.lock` (Modify): 同步锁定包含 `pgvector` 的全量依赖版本。
* `backend/alembic.ini` (New): 配置 Alembic 迁移配置文件，指定迁移脚本路径与日志配置。

### 生产源码文件 (Production Code)
* `backend/app/models/material.py` (New):
  - 定义枚举 `MaterialStatus`, `MaterialDocType`, `ParseStatus`, `SourceType`；
  - 实现向量字段类型兼容降级工厂函数 `get_vector_type(dimensions: int = 1024)`；
  - 声明式实体 `Material` (配置 `use_alter=True` 的 `current_version_id` 外键与软删除 `is_deleted`)；
  - 声明式实体 `MaterialVersion` (配置版本号递增、MinIO 对象键存储与 SHA-256 唯一约束)；
  - 声明式实体 `MaterialSnippet` (配置 1024 维向量字段、`(user_id, material_id, version_id)` 复合索引与 HNSW 索引)；
  - 声明式实体 `MaterialOCRPage` (配置页码唯一约束、乱码率/有效字数门禁字段与就地重拍计数)；
  - 绝密脱敏：所有模型实体的 `__repr__` 严禁输出 `content`（切片全文）与敏感存储凭据。
* `backend/app/models/__init__.py` (Modify): 导出 `Material`, `MaterialVersion`, `MaterialSnippet`, `MaterialOCRPage`, `MaterialStatus`, `MaterialDocType`, `ParseStatus`, `SourceType`。
* `backend/migrations/env.py` (New): 配置 Alembic 环境脚本，加载 `Base.metadata` 支持离线与在线 DDL 迁移。
* `backend/migrations/script.py.mako` (New): Alembic 迁移脚本代码生成模板。
* `backend/migrations/versions/0001_create_material_tables_and_vector.py` (New): 首版可逆 DDL 迁移脚本，包含 `CREATE EXTENSION IF NOT EXISTS vector;`、4 张表创建、复合与 HNSW 向量索引配置，及对称回滚降级逻辑。

### 自动化测试文件 (Tests & Verification)
* `backend/tests/unit/models/test_material.py` (New):
  - 4 个实体模型实例字段默认值与自定义赋值测试；
  - 多租户 `user_id` 继承与级联删除约束测试；
  - 关系双向联动与级联（`Material.versions`, `MaterialVersion.snippets`, `MaterialVersion.ocr_pages`）测试；
  - 软删除 `is_deleted` 与唯一约束测试；
  - 绝密日志脱敏红线测试（断言 `__repr__` 绝对不含 `content` 原文）；
  - `get_vector_type` 跨环境降级行为测试；
  - Alembic 迁移升级与降级可逆性闭环执行测试。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 测试先行 (Fail-repro First)
* **操作目标**: 编写 `backend/tests/unit/models/test_material.py` 初始测试桩，覆盖 4 个核心实体模型、枚举、脱敏与级联关系定义，并在终端亲眼见证测试变红（Fail）。
* **涉及文件**:
  - `backend/tests/unit/models/test_material.py`
* **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/models/test_material.py -v
  ```
* **预期判据**: 因 `app.models.material` 尚未创建，测试抛出 `ModuleNotFoundError` 或 `ImportError` 变红失败。

### Step 2: 依赖同步与核心实体模型落地 (Core Models & Vector Fallback)
* **操作目标**: 在 `backend/pyproject.toml` 中添加 `pgvector>=0.3.0` 并执行 `uv pip install -e ".[dev]" && uv lock`；创建 `backend/app/models/material.py` 完整实现 4 个实体、4 个枚举、`get_vector_type` 降级工厂与脱敏 `__repr__`；在 `backend/app/models/__init__.py` 中完成导出。
* **涉及文件**:
  - `backend/pyproject.toml`
  - `backend/uv.lock`
  - `backend/app/models/material.py`
  - `backend/app/models/__init__.py`
* **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/models/test_material.py -v
  ```
* **预期判据**: 实体字段、枚举类型、默认值、外键级联与安全脱敏测试全部通过（Pass 变绿）。

### Step 3: Alembic 迁移骨架与可逆迁移脚本落地 (Alembic Migrations)
* **操作目标**: 初始化并配置 `backend/alembic.ini`、`backend/migrations/env.py` 和 `backend/migrations/script.py.mako`；编写可逆迁移脚本 `backend/migrations/versions/0001_create_material_tables_and_vector.py`，完整覆盖 pgvector 扩展激活、4 张表创建、复合覆盖索引、HNSW 余弦距离索引与对称 `downgrade` 回滚。
* **涉及文件**:
  - `backend/alembic.ini`
  - `backend/migrations/env.py`
  - `backend/migrations/script.py.mako`
  - `backend/migrations/versions/0001_create_material_tables_and_vector.py`
* **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/models/test_material.py -k "test_migration" -v
  ```
* **预期判据**: 迁移测试脚本中的升级（upgrade）与降级（downgrade）完整闭环通过，表结构与约束能够干净创建与移除。

### Step 4: 全量模型与迁移集成测试回归 (Verification Loop)
* **操作目标**: 执行模型单元测试与迁移回归套件，确保毫秒级执行且零真实公网网络请求；执行覆盖率与类型检查。
* **涉及文件**:
  - `backend/tests/unit/models/test_material.py`
* **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/models/test_material.py --cov=app.models.material --cov-branch --cov-report=term-missing
  ```
* **预期判据**: 模型覆盖率达到 95% 以上，所有分支与脱敏断言 100% 绿灯。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `cd backend && uv run ruff check . && uv run ruff format --check .` 确保无代码异味、行宽不超过 100。
* **类型与契约安全校验**: `cd backend && uv run mypy app tests` 强制类型严格模式，零类型报错。
* **分层依赖检查**: `python3 tooling/check_layers.py --root backend/app` 验证 models 层严禁逆向导入 services 或 api。
* **全量测试与覆盖率门禁**: `cd backend && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80` 验证全局覆盖率门禁。
* **门禁完整性检查**: `python3 tooling/check_sdlc_integrity.py` 验证工件规范无残留占位符。
* **核验结果**: 所有命令退出码为 0，静态质量检查零错误零警告，测试套件毫秒级 100% 绿灯。

---

## 4. 实施偏差记录 (Deviations Log)
* 架构契约与数据模型实现完全遵从 `docs/sdlc/ZL-104/spec.md`。
* 在 `MaterialDocType` 枚举中对齐了规格书支持的输入格式（`PDF`, `DOCX`, `PPTX`, `MARKDOWN`, `TXT`, `IMAGE`），使格式校验与字段默认值更为严谨。
* 为支持单元测试在无 PostgreSQL/pgvector 真实容器依赖的纯内存环境下进行迁移逻辑可逆性校验，在迁移脚本与测试固件中提供了方言自适应处理，保证升级与对称降级逻辑的完整性。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: yezisama / 2026-09-23
