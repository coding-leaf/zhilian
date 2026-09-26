# Plan: 资料导入、多版本管理与解析调度服务 - 实施计划

- **关联 Spec**: ZL-119
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution

---

## 1. 变更文件清单 (Files that change)
* `backend/app/core/errors.py` (Modify - 扩充 40001~40004 统一业务异常与导出列表)
* `backend/app/repositories/material.py` (New - 实现 MaterialRepository，强制多租户 SQL 过滤)
* `backend/app/services/material.py` (New - 实现 MaterialService 与魔数校验、解析流水线编排、重拍熔断)
* `backend/tests/unit/core/test_errors.py` (Modify - 补充 40001~40004 异常类单测断言)
* `backend/tests/unit/repositories/test_material_repo.py` (New - 仓储层多租户隔离与 CRUD 单元测试)
* `backend/tests/unit/services/test_material_service.py` (New - 服务层魔数校验、解析流水线、重拍熔断、软硬删除集成编排单测)

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)
> **原则**：每个步骤必须配对明确的局部验证命令，步步红绿流转，禁止跳过单步验证直接写完提交。

### Step 1: 扩充统一业务异常体系 (Errors 40001~40004)
* **操作目标**: 在 `app/core/errors.py` 中扩充 `MaterialInvalidError (40001)`, `OCRReshootExceededError (40002)`, `MaterialParseError (40003)`, `MaterialNotFoundError (40004)`；并在 `test_errors.py` 中添加测试。
* **涉及文件**:
  - `backend/app/core/errors.py`
  - `backend/tests/unit/core/test_errors.py`
* **局部验证命令**:
  ```bash
  pytest backend/tests/unit/core/test_errors.py -v
  ```
* **预期判据**: 新增异常类的 `error_code`, `status_code`, `message`, `to_dict()` 校验全部通过，测试 100% 绿灯。

### Step 2: 仓储层测试先行与实现 (`MaterialRepository`)
* **操作目标**:
  1. 编写 `backend/tests/unit/repositories/test_material_repo.py`，覆盖 Material, Version, Snippet, OCRPage 的增删改查；
  2. 编写多租户越权负向测试（验证查询他人数据 100% 返回 None 或不漏出）；
  3. 实现 `backend/app/repositories/material.py`；
  4. 运行 AST 分层依赖校验，确保存储层 0 跨层导入。
* **涉及文件**:
  - `backend/tests/unit/repositories/test_material_repo.py` (New)
  - `backend/app/repositories/material.py` (New)
* **局部验证命令**:
  ```bash
  pytest backend/tests/unit/repositories/test_material_repo.py -v && \
  python3 tooling/check_layers.py --root backend/app
  ```
* **预期判据**: 仓储层全部单测通过，多租户隔离断言生效，分层依赖扫描 0 违规。

### Step 3: 服务编排层测试先行与实现 (`MaterialService`)
* **操作目标**:
  1. 编写 `backend/tests/unit/services/test_material_service.py`，配置 Memory 外设 Mock/Fake（Storage, OCR, Embedding, Queue, Idempotency）；
  2. 测试 `create_material`：魔数支持性校验（PDF/DOCX/PNG/TXT 合法，EXE/损坏二进制抛出 40001）、大小超限拦截、SHA-256 秒传复用检测、幂等锁拦截；
  3. 测试 `parse_material_pipeline`：编排 OCR 识别、质检不合格挂起、纯函数分块、批量嵌入向量生成并入库激活；
  4. 测试 `retry_ocr_pages`：重拍替换指定页、质检重新计算、重拍次数累加、超过 3 次抛出 `40002` 熔断拦截；
  5. 测试 `soft_delete_material` 与 `hard_delete_material`：验证软删除标记与物理级联删除 MinIO 对象；
  6. 实现 `backend/app/services/material.py`，严格遵循单向分层与脱敏日志规范。
* **涉及文件**:
  - `backend/tests/unit/services/test_material_service.py` (New)
  - `backend/app/services/material.py` (New)
* **局部验证命令**:
  ```bash
  pytest backend/tests/unit/services/test_material_service.py -v
  ```
* **预期判据**: 业务流水线测试、重拍熔断测试、多租户测试 100% 通过。

---

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**:
  ```bash
  cd backend && ruff format --check app tests && ruff check app tests
  ```
* **类型与契约安全校验**:
  ```bash
  cd backend && mypy app/repositories app/services app/core
  ```
* **分层依赖检查**:
  ```bash
  python3 tooling/check_layers.py --root backend/app
  ```
* **全量测试与覆盖率门禁**:
  ```bash
  cd backend && pytest tests --cov=app/repositories --cov=app/services --cov-branch --cov-fail-under=80
  ```
* **核验结果**: 全部门禁通过，零错误，服务层覆盖率 $\ge 85\%$，纯函数无被污染。

---

## 4. 实施偏差记录 (Deviations Log)
* [无偏差 / 严格对齐 spec.md 设计契约]

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: [待人类确认] / 2026-09-24 08:53
