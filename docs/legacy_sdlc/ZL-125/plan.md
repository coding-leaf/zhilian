# Plan: 资料管理与解析调度 API 路由 - 实施计划

- **关联 Spec**: ZL-125
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution

---

## 1. 变更文件清单 (Files that change)

1. `backend/app/schemas/material.py` (New):
   - 定义全套 Pydantic v2 DTO 数据契约：`MaterialUploadResponse`, `MaterialDetailResponse`, `MaterialListItem`, `MaterialListResponse`, `MaterialParseRequest`, `MaterialParseResponse`, `MaterialVersionItem`, `MaterialVersionListResponse`, `MaterialReshootResponse`, `MaterialDeleteResponse`。
2. `backend/app/schemas/__init__.py` (New):
   - 统一导出资料相关的 Pydantic 模型。
3. `backend/app/api/deps/material.py` (New):
   - 实现 `get_material_service` 依赖项工厂函数，负责实例化并提供 `MaterialService`，支持单测中的 `dependency_overrides` 覆盖。
4. `backend/app/api/deps/__init__.py` (Modify):
   - 导出 `get_material_service`。
5. `backend/app/repositories/material.py` (Modify):
   - 在 `list_materials_by_user` 与 `list_materials` 中增加可选的 `keyword: str | None = None`（标题模糊匹配）与 `status: str | None = None` 过滤条件。
6. `backend/app/services/material.py` (Modify):
   - 补充 `list_material_versions(material_id, user_id)`、`switch_material_version(material_id, version_id, user_id)` 以及 `reshoot_material_page(material_id, user_id, page_number, image_bytes, version_id)` 等高阶编排方法，保证路由层 1 行直接调用，零业务逻辑堆砌。
7. `backend/app/api/v1/materials.py` (New):
   - 构建 FastAPI `APIRouter`，完整挂载 9 个 RESTful 端点，严格遵循分层规范，无任何 `app.repositories` 导入与原生事务操作。
8. `backend/app/api/v1/__init__.py` (New):
   - 导出 `materials_router`。
9. `backend/tests/unit/schemas/test_material_schema.py` (New):
   - Pydantic 模型白盒测试：覆盖字段校验、缺失字段拒绝、枚举限定与序列化断言。
10. `backend/tests/unit/api/test_material_router.py` (New):
    - 路由单元与集成测试：覆盖 9 大端点的正常执行流、401 未登录鉴权拦截、404 不存在/越权防穿透、400 校验与重拍熔断、软/硬删除级联验证。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: Pydantic 契约、依赖注入与上传脚手架 (Schemas, Deps & Upload Endpoint)

* **Step 1.1: Pydantic Schema 测试先行与数据契约实现**
  - 操作目标: 编写 `test_material_schema.py` 验证各 DTO 的入参出参约束；在 `app/schemas/material.py` 中实现全部 Pydantic 模型。
  - 涉及文件:
    - `backend/tests/unit/schemas/test_material_schema.py`
    - `backend/app/schemas/material.py`
    - `backend/app/schemas/__init__.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/schemas/test_material_schema.py -v
    ```
  - 预期判据: 全部 Schema 校验用例通过，非法格式和越界值均被正确拒绝。

* **Step 1.2: 服务层辅助能力与依赖注入工厂装配**
  - 操作目标: 在 `MaterialRepository` 扩充查询过滤参数；在 `MaterialService` 中实现版本枚举与切换等辅助方法；在 `app/api/deps/material.py` 实现 `get_material_service` 依赖项。
  - 涉及文件:
    - `backend/app/repositories/material.py`
    - `backend/app/services/material.py`
    - `backend/app/api/deps/material.py`
    - `backend/app/api/deps/__init__.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/services/test_material_service.py -v
    ```
  - 预期判据: 现有 Service 单测 100% 保持通过，新增方法行为正确。

* **Step 1.3: 路由脚手架与上传接口实现 (`POST /api/v1/materials/upload`)**
  - 操作目标: 初始化 `app/api/v1/materials.py`，实现上传接口端点与异常拦截；在 `tests/unit/api/test_material_router.py` 编写上传与鉴权测试。
  - 涉及文件:
    - `backend/app/api/v1/materials.py`
    - `backend/app/api/v1/__init__.py`
    - `backend/tests/unit/api/test_material_router.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/api/test_material_router.py -k "test_upload" -v
    ```
  - 预期判据: 上传文件能正确返回 201 Created 与对应 DTO，魔数不匹配时返回 400，未登录返回 401。

---

### Milestone 2: 完整端点实现与综合路由测试 (Complete Router Endpoints & Tests)

* **Step 2.1: 详情与列表检索端点实现 (`GET /materials/{id}`, `GET /materials`)**
  - 操作目标: 实现资料详情查询与支持分页、搜索词及状态过滤的资料列表查询端点；补充多租户越权阻断测试。
  - 涉及文件:
    - `backend/app/api/v1/materials.py`
    - `backend/tests/unit/api/test_material_router.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/api/test_material_router.py -k "test_get_or_list" -v
    ```
  - 预期判据: 详情正确返回版本总数，列表分页准确；跨租户查询返回 404，不泄露其他用户资源。

* **Step 2.2: 解析调度、版本列表与版本切换端点实现**
  - 操作目标: 实现 `POST /materials/{id}/parse`、`GET /materials/{id}/versions` 及 `POST /materials/{id}/versions/{version_id}/switch` 端点。
  - 涉及文件:
    - `backend/app/api/v1/materials.py`
    - `backend/tests/unit/api/test_material_router.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/api/test_material_router.py -k "test_version_or_parse" -v
    ```
  - 预期判据: 解析任务调度正常，版本列表按倒序排列，版本切换后详情同步更新。

* **Step 2.3: 单页重拍与软/硬删除端点实现**
  - 操作目标: 实现 `POST /materials/{id}/reshoot`、`DELETE /materials/{id}`（软删除）及 `DELETE /materials/{id}/hard`（物理级联清理）；编写超过 3 次重拍熔断异常拦截测试。
  - 涉及文件:
    - `backend/app/api/v1/materials.py`
    - `backend/tests/unit/api/test_material_router.py`
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/api/test_material_router.py -k "test_reshoot_or_delete" -v
    ```
  - 预期判据: 重拍达到 3 次时准确返回 40002 错误码，软删除置 is_deleted 为 True，硬删除级联清理完成。

---

### Milestone 3: 架构依赖校验与全局质量门禁 (Architecture & Quality Gate)

* **Step 3.1: 架构单向依赖合规核验**
  - 操作目标: 执行 `tooling/check_layers.py` 严格扫描 AST，确保 `app/api/v1/materials.py` 及相关模块绝对未导入 `app.repositories`。
  - 局部验证命令:
    ```bash
    python3 tooling/check_layers.py --root backend/app
    ```
  - 预期判据: 输出 `恭喜！未发现任何跨层架构违规导入。`，退出码为 0。

* **Step 3.2: 全量测试与覆盖率回归**
  - 操作目标: 运行后端全量测试套件，检查路由与 Schema 模块覆盖率。
  - 局部验证命令:
    ```bash
    cd backend && pytest tests/unit/api/test_material_router.py tests/unit/schemas/test_material_schema.py --cov=app/api/v1/materials --cov=app/schemas/material --cov-report=term-missing
    ```
  - 预期判据: 路由与 Schema 模块覆盖率达到 90% 以上，全用例 100% 绿灯。

---

## 3. 全局质量门禁核验 (Global Quality Gate)

* **代码风格与静态检查**:
  ```bash
  cd backend && ruff format --check . && ruff check .
  ```
  预期结果: 行宽 100，零 lint 错误，无拼写与缩写违规。
* **类型与契约安全校验**:
  ```bash
  cd backend && mypy app
  ```
  预期结果: 类型严格模式通过，零类型不安全告警。
* **全量相关测试回归**:
  ```bash
  cd backend && pytest tests/unit/api/ tests/unit/schemas/ tests/unit/services/test_material_service.py -v
  ```
  预期结果: 相关单元与集成测试用例 100% 绿灯通过。

---

## 4. 实施偏差记录 (Deviations Log)

* 无偏差：严格按照 Spec 契约设计执行，在 Service 层新增的轻量委托方法均属既定规划范围内。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: In-Execution
- **验证人 / 日期**: Dev / 2026-09-24