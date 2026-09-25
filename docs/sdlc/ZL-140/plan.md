# Plan: 资料异步解析闭环与PDF提取及知识树串联 - 实施计划

- **关联 Spec**: ZL-140
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution
- **Change Tier**: Tier 3 (Cross-Domain Rewiring)

---

## 1. 变更文件清单 (Files that change)

### 1.1 依赖声明层
* `backend/pyproject.toml` (Modify - 添加 `pypdf>=4.0.0` 依赖): 引入纯 Python PDF 解析库，消除系统编译级 C 库依赖，提供无外部网络环境下的原生文本提取支持。

### 1.2 核心服务与纯函数层
* `backend/app/services/material.py` (Modify - 实现 pypdf 原生抽取函数与解析流水线知识树自动调用逻辑):
  1. 重构纯函数 `extract_text_from_raw_content`，对 PDF 格式通过 `pypdf.PdfReader` 逐页提取正文、清洗空白段落并设置有效字符下限阈值（< 10 字符拦截并抛出 `MaterialInvalidError`）；
  2. 在 `parse_material_pipeline` 流水线中，切片与向量入库完成后，自动注入并调用 `KnowledgeService.extract_and_build_knowledge_tree` 完成知识树抽取与落库；
  3. 细化版本表状态流转（`parsing_doc` -> `extracting_knowledge` -> `embedding_generation` -> `ready`/`failed`），联动更新主表状态，并完善异常捕获与事务回滚。

### 1.3 外部接口与依赖注入层
* `backend/app/api/v1/materials.py` (Modify - upload 接口接入 BackgroundTasks，独立 Session 触发后台解析):
  1. 在 `upload_material` 路由参数中增加 `background_tasks: BackgroundTasks`；
  2. 实现后台任务触发函数 `run_parse_material_background`，通过 `request.app.state.container` 获取全新独立的数据库会话 (`with container.get_session() as session:`)，装配 `MaterialService` 与 `KnowledgeService` 驱动解析流水线，阻断请求级 Session 跨线程复用。

### 1.4 单元测试与质量保障层
* `backend/tests/unit/services/test_material_service.py` (Modify/Add - 单元测试):
  1. 补充 `extract_text_from_raw_content` PDF 解析单测（多页有效文本提取、换行规整、空白与扫描件阈值异常拦截）；
  2. 补充 `parse_material_pipeline` 串联知识树自动抽取测试，验证向量生成后顺利触发知识树落库与双表状态变更为 `ready`；
  3. 补充各阶段异常场景测试，验证 `failed_stage` 与 `error_message` 记录及事务原子回滚。
* `backend/tests/unit/api/test_material_router.py` (Modify/Add - 路由接口单测):
  1. 补充 `POST /api/v1/materials/upload` 路由成功触发 `BackgroundTasks` 的行为断言，验证立即返回 201 响应且注册后台任务；
  2. 验证异步执行体使用容器独立 Session，不会产生关闭状态的 Session 跨线程污染。

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 引入 pypdf 依赖与原生 PDF 文本抽取及门禁过滤 (M1)

#### Step 1.1: PDF 抽取与门禁单测先行 (Fail-repro First)
- **目标**: 针对 `extract_text_from_raw_content` 编写 PDF 提取多分支单元测试（包含多页标准 PDF 正文抽取、空白页/扫描件字符不足 10 个拦截抛出 `MaterialInvalidError`、非 PDF 降级处理）。
- **涉及文件**: `backend/tests/unit/services/test_material_service.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/services/test_material_service.py -k "test_extract_text_pdf" -v
  ```
- **预期判据 (红灯)**: 因尚未引入 `pypdf` 且原函数采用 utf-8 decode，测试断言失败或解析出非正文原始流指令。

#### Step 1.2: 引入 pypdf 依赖并实现原生提取纯函数 (Make it Green)
- **目标**: 
  1. 在 `backend/pyproject.toml` 的 `dependencies` 中添加 `"pypdf>=4.0.0"`；
  2. 在 `backend/app/services/material.py` 中重构 `extract_text_from_raw_content`，使用 `pypdf.PdfReader` 读取二进制流逐页提取文本并清洗，遇到损坏或有效字符 < 10 时显式抛出 `MaterialInvalidError`。
- **涉及文件**: `backend/pyproject.toml`, `backend/app/services/material.py`
- **局部验证命令**:
  ```bash
  cd backend && uv sync && uv run pytest tests/unit/services/test_material_service.py -k "test_extract_text_pdf" -v
  ```
- **预期判据 (绿灯)**: PDF 解析与门禁拦截用例 100% 通过，段落切分干净规范。

---

### Milestone 2: 流水线自动串联知识树抽取与细粒度状态推进 (M2)

#### Step 2.1: 知识树自动抽取串联单测先行 (Fail-repro First)
- **目标**: 在资料服务单测中编写流水线自动构建知识树测试，验证切片向量入库后，流水线能够编排调用 `KnowledgeService.extract_and_build_knowledge_tree`，并将双表状态原子推进至 `ready`；测试模拟知识树抽取抛出异常，断言双表推进至 `failed` 且记录 `failed_stage="knowledge_extraction"`。
- **涉及文件**: `backend/tests/unit/services/test_material_service.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/services/test_material_service.py -k "test_parse_pipeline_knowledge_chaining" -v
  ```
- **预期判据 (红灯)**: 因现有流水线仅到向量持久化即终止且未调用知识树服务，测试用例断言未调用知识服务或版本状态未达预期而失败。

#### Step 2.2: 流水线串联 KnowledgeService 与多表状态机异常回滚 (Make it Green)
- **目标**: 
  1. 在 `backend/app/services/material.py` 的 `MaterialService` 中支持接收或注入 `KnowledgeService`（或提供流水线与知识树协同方法）；
  2. 在 `parse_material_pipeline` 中，完成切片向量存储后无缝拉起知识树生成流程；
  3. 细化阶段更新（`extracting_knowledge`、`embedding_generation`），并在 try-except 屏障中显式同时更新 `MaterialVersion` 与 `Material` 为 `failed` 并回滚事务。
- **涉及文件**: `backend/app/services/material.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/services/test_material_service.py -k "test_parse_pipeline_knowledge_chaining" -v
  ```
- **预期判据 (绿灯)**: 流水线全链路及异常回滚测试用例 100% 绿灯。

---

### Milestone 3: API 路由接入 BackgroundTasks 与独立 Session 异步调度 (M3)

#### Step 3.1: 异步后台任务路由单测先行 (Fail-repro First)
- **目标**: 在 `backend/tests/unit/api/test_material_router.py` 中编写 `upload_material` 接口触发异步后台任务的测试，验证上传成功后即刻返回 HTTP 201，且 `BackgroundTasks` 注册了后台任务，且后台任务执行期间使用的是全新 Session 而非请求生命周期 Session。
- **涉及文件**: `backend/tests/unit/api/test_material_router.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/api/test_material_router.py -k "test_upload_material_triggers_background_tasks" -v
  ```
- **预期判据 (红灯)**: 因接口尚未声明 `BackgroundTasks` 或未向其分派任务，测试断言失败。

#### Step 3.2: 路由层接入 BackgroundTasks 并通过 AppContainer 绑定独立 Session (Make it Green)
- **目标**: 
  1. 在 `backend/app/api/v1/materials.py` 的 `upload_material` 路由中增加 `background_tasks: BackgroundTasks` 参数；
  2. 声明后台执行函数 `run_parse_material_background(container, material_id, version_id, user_id)`，在后台函数中显式通过 `with container.get_session() as session:` 开启全新会话，通过容器工厂构建 `material_service` 与 `knowledge_service` 驱动全链路；
  3. 在 `upload_material` 返回前将该任务推入 `background_tasks.add_task(...)`。
- **涉及文件**: `backend/app/api/v1/materials.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/api/test_material_router.py -k "test_upload_material_triggers_background_tasks" -v
  ```
- **预期判据 (绿灯)**: 路由测试顺利通过，验证了任务派发与独立 Session 上下文管理。

---

### Milestone 4: 全量回归与质量门禁核验 (M4)

#### Step 4.1: 全量相关单元测试回归
- **目标**: 集中执行资料服务与路由全部单元测试，确保无历史功能与边界回归。
- **涉及文件**: `backend/tests/unit/api/test_material_router.py`, `backend/tests/unit/services/test_material_service.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/api/test_material_router.py tests/unit/services/test_material_service.py -v
  ```
- **预期判据 (绿灯)**: 所有单测 100% 绿灯通过，无任何 warning 或异常。

#### Step 4.2: 架构分层单向依赖校验
- **目标**: 验证路由层、服务层、适配层与纯函数层导入合法性，杜绝跨层导入与反向依赖。
- **涉及命令**:
  ```bash
  uv run python tooling/check_layers.py --root backend/app
  ```
- **预期判据**: 架构分层校验输出 0 violations，严格符合规范。

#### Step 4.3: SDLC 工件完整性与防跳步核验
- **目标**: 验证阶段工件无残留占位符，符合生命周期约束。
- **涉及命令**:
  ```bash
  uv run python tooling/check_sdlc_integrity.py
  ```
- **预期判据**: 退出码为 0，门禁合规。

---

## 3. 风险评估与爆炸半径 (Risks & Blast Radius)

| 风险项 | 潜在破坏面 | 规避与隔离方案 |
| :--- | :--- | :--- |
| **1. Session 跨线程复用导致崩溃** | 若后台任务捕获了请求级的 `material_service`，当 HTTP 请求结束 Session 关闭后，后台任务执行 SQL 将抛出 `This session is closed` | 后台任务强制要求仅接收 `AppContainer` 实例，在异步任务函数体内部使用 `with container.get_session() as session:` 开启全新独立连接并派生服务 |
| **2. 扫描版 PDF 提取全空白触发死循环或静默失败** | 纯图片扫描版 PDF 抽取正文字符为 0，进入切片阶段抛出空内容异常导致任务直接失败 | 在 `extract_text_from_raw_content` 针对 PDF 设置有效字符数阈值（字符数 < 10 时直接阻断并抛出 `MaterialInvalidError`，精准指引用户上传图片格式走 OCR） |
| **3. 知识树抽取耗时与大事务超时** | LLM 知识抽取包含多次调用与质检重试，若与文档解析共用长事务，可能导致数据库连接被长期占用 | 文档切片向量持久化与知识树抽取持久化按阶段分别提交事务，避免持有单一长事务阻塞数据库连接池 |
| **4. 分层依赖违规破坏** | 路由层若为了获取会话或状态而跨层直接导入 `app.repositories` 将触发门禁打断 | 路由层仅通过 `AppContainer` 与 Service 层交互，严格禁止跨层直接调用 Repository |

---

## 4. 全局质量门禁核验 (Global Quality Gate)

* **SDLC 工件完整性校验**:
  ```bash
  uv run python tooling/check_sdlc_integrity.py
  ```
* **分层单向依赖校验**:
  ```bash
  uv run python tooling/check_layers.py --root backend/app
  ```
* **全量针对性测试执行**:
  ```bash
  cd backend && uv run pytest tests/unit/api/test_material_router.py tests/unit/services/test_material_service.py
  ```
* **代码风格扫描 (Ruff Format)**:
  ```bash
  cd backend && uv run ruff format --check .
  ```
* **代码静态质量检查 (Ruff Check)**:
  ```bash
  cd backend && uv run ruff check .
  ```
* **核验结果判据**: 全门禁 0 警告 0 报错，全量测试用例 100% 绿灯，退出码均为 0。

---

## 5. 实施偏差记录 (Deviations Log)

* 当前阶段尚无实施偏差，各项计划均严格对照 spec.md 技术契约执行。

---

## 6. 阶段准出签批 (Gate 3 Sign-off)

- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Approved
- **验证人 / 日期**: User / 2026-09-25 23:58