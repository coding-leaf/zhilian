# Plan: 真实基础设施容器化编排与分层提供商注册中心 - 实施计划

- **关联 Spec**: ZL-139
- **实施执行人 / Agent**: Dev
- **当前状态**: In-Execution
- **Change Tier**: Tier 3 (Cross-Domain Rewiring)

---

## 1. 变更文件清单 (Files that change)

### 1.1 基础设施与配置层
* `deploy/docker-compose.yml` (New, 容器基础设施): 编排 PostgreSQL 16 (pgvector)、Redis 7 (Alpine)、MinIO 对象存储与 MinIO-Init 自动建桶服务，配置持久化数据卷与容器健康检查
* `backend/app/core/config.py` (New, 核心支持层 `app/core`): 实现基于 `pydantic-settings` 的 `AppSettings` 及 9 个强类型子配置模型，统一管理 `ZHILIAN_*` 环境变量，敏感凭据使用 `SecretStr` 脱敏，提供单例缓存 `get_settings()`
* `backend/pyproject.toml` (Modify, 依赖声明): 引入 `psycopg[binary]>=3.1.0` 生产驱动依赖，保障原生连接真实 PostgreSQL 16

### 1.2 双层注册中心与应用装配层
* `backend/app/integrations/container.py` (New, 外部适配层 `app/integrations`): 实现外部能力注册中心 `ProviderRegistry`，根据 `AppSettings` 组装并持有 7 块 Protocol 适配器，实现客户端优雅关闭。严格禁止反向导入 `app.services`
* `backend/app/container.py` (New, 应用顶级装配层 `app`): 实现应用装配容器 `AppContainer`，管理 SQLAlchemy 数据库引擎连接池与会话工厂，托管 `ProviderRegistry`，提供各领域服务工厂方法，封装 `startup()` 连接探测与 `shutdown()` 资源释放

### 1.3 应用运行时与依赖桥接层
* `backend/app/main.py` (Modify, 应用入口层 `app`): 移除模块顶层 SQLite 裸引擎与零散全局适配器，采用 FastAPI `lifespan` 异步上下文管理器全生命周期托管 `AppContainer`，将请求依赖绑定至容器工厂，将 `/health` 端点升级为多组件结构化健康就绪探测
* `backend/app/api/deps/*.py` (Modify/Review, 依赖注入层 `app/api/deps`): 保持既有 `get_*_service()` 与 `get_db_session()` 签名 100% 兼容，支持从 `request.app.state.container` 获取容器实例或无缝兼容 `dependency_overrides`

### 1.4 自动化测试与质量保障层
* `backend/tests/unit/core/test_config.py` (New, 核心配置单元测试): 覆盖默认配置加载、环境变量双下划线嵌套覆盖、SecretStr 脱敏与只读保护 (UT-CFG-01, UT-CFG-02)
* `backend/tests/unit/integrations/test_container.py` (New, 适配器注册中心单元测试): 覆盖 `ProviderRegistry` 各 Protocol 适配器生产、工厂分发契约与 `shutdown()` 优雅清理 (UT-REG-01, UT-REG-02)
* `backend/tests/unit/test_container.py` (New, 应用装配容器单元测试): 覆盖 `AppContainer` 启动连通性探测、数据库会话生命周期、领域服务依赖注入与容器销毁 (UT-CTR-01, UT-CTR-02)
* `backend/tests/unit/test_app_lifespan.py` (New, 生命周期单元测试): 覆盖应用 Lifespan 启动预热、`app.state.container` 挂载、`/health` 多状态探测与停机回收 (UT-LIFE-01)
* `backend/tests/integration/test_real_infrastructure.py` (New, 基础设施集成测试): 验证真实 PG16+pgvector、Redis 7 与 MinIO 连通性、Alembic 迁移幂等性与向量索引激活 (IT-PGV-01)
* `backend/tests/integration/test_p0_full_chain_e2e.py` (Verify, 全链路集成测试): 验证 8 步正向端到端全链路与 16 维越权矩阵在容器化重构后 100% 绿灯无回退

---

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Milestone 1: 容器编排与强类型配置中心

#### Step 1.1: 配置单元测试先行 (Fail-repro First)
- **目标**: 编写强类型配置中心针对默认加载、嵌套环境变量覆盖、敏感字段保护的单元测试用例
- **涉及文件**: `backend/tests/unit/core/test_config.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/core/test_config.py -v
  ```
- **预期判据 (红灯)**: 因 `app/core/config.py` 尚未创建，测试执行报错 `ModuleNotFoundError: No module named 'app.core.config'`

#### Step 1.2: 强类型配置中心实现 (Make it Green)
- **目标**: 实现 `AppSettings` 及其 9 大子配置类 (`DatabaseSettings`, `RedisSettings`, `StorageSettings`, `LLMSettings`, `OCRSettings`, `EmbeddingSettings`, `QueueSettings`, `IdempotencySettings`, `SearchSettings`)，配置 `ZHILIAN_` 前缀与 `__` 嵌套解析器
- **涉及文件**: `backend/app/core/config.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/core/test_config.py -v
  ```
- **预期判据 (绿灯)**: UT-CFG-01 与 UT-CFG-02 全部通过，`SecretStr` 脱敏校验无误，用例 100% 绿灯

#### Step 1.3: 容器基础设施编排定义
- **目标**: 编写 `deploy/docker-compose.yml`，定义 PG16(pgvector)、Redis 7、MinIO 以及 `minio-init` 自动建桶服务，配置独立的健康检查与网络存储卷
- **涉及文件**: `deploy/docker-compose.yml`
- **局部验证命令**:
  ```bash
  docker compose -f deploy/docker-compose.yml config
  ```
- **预期判据**: Compose 文件语法校验通过，各服务拓扑、依赖顺序与网络端口声明正确

---

### Milestone 2: 双层注册中心机制 (ProviderRegistry 与 AppContainer)

#### Step 2.1: 注册中心与容器单测先行 (Fail-repro First)
- **目标**: 编写外部能力注册中心与应用装配容器的单元测试用例桩 (UT-REG-01, UT-REG-02, UT-CTR-01, UT-CTR-02)
- **涉及文件**: `backend/tests/unit/integrations/test_container.py`, `backend/tests/unit/test_container.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/integrations/test_container.py tests/unit/test_container.py -v
  ```
- **预期判据 (红灯)**: 因 `app/integrations/container.py` 与 `app/container.py` 尚未创建，测试导入失败

#### Step 2.2: 外部提供商注册中心实现 (Make it Green)
- **目标**: 实现 `ProviderRegistry`，根据 `AppSettings` 调用各工厂分发 Protocol 实现，实现 `shutdown()` 清理逻辑。严格遵循分层规范，禁止导入任何 `app.services`
- **涉及文件**: `backend/app/integrations/container.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/integrations/test_container.py -v && uv run python ../tooling/check_layers.py --root app
  ```
- **预期判据 (绿灯)**: `ProviderRegistry` 适配器按需加载成功，单测绿灯，架构分层扫描 0 违规

#### Step 2.3: 应用顶层装配容器实现 (Make it Green)
- **目标**: 实现 `AppContainer`，聚合数据库引擎与 Session 工厂，持有 `ProviderRegistry`，实现 `get_auth_service` 等 7 大领域服务工厂方法与 `startup()` / `shutdown()` 生命周期钩子
- **涉及文件**: `backend/app/container.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/test_container.py -v
  ```
- **预期判据 (绿灯)**: `AppContainer` 数据库会话正确生产与释放，各服务注入正确，容器生命周期测试全绿

---

### Milestone 3: 主入口 Lifespan 改造与依赖注入挂载

#### Step 3.1: 应用生命周期与健康检查单测先行 (Fail-repro First)
- **目标**: 编写测试覆盖 FastAPI `lifespan` 启动预热、`app.state.container` 挂载、`/health` 多组件状态输出以及停机钩子 (UT-LIFE-01)
- **涉及文件**: `backend/tests/unit/test_app_lifespan.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/test_app_lifespan.py -v
  ```
- **预期判据 (红灯)**: 因 `main.py` 仍为旧版模块顶层硬编码、未托管 `AppContainer`，测试执行断言失败

#### Step 3.2: 依赖注入层微调与适配
- **目标**: 审查并微调 `backend/app/api/deps/*.py`，使 `get_db_session` 与各 `get_*_service` 能无缝协同 `request.app.state.container` 与现存测试的 `app.dependency_overrides`
- **涉及文件**: `backend/app/api/deps/knowledge.py`, `backend/app/api/deps/material.py` 等依赖模块
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/api/ -k "test_material_router or test_auth_deps" -v
  ```
- **预期判据 (绿灯)**: 既有 API 依赖项单元测试完全不受影响，保持绿灯

#### Step 3.3: 应用主入口 Lifespan 重构与装配绑定 (Make it Green)
- **目标**: 改造 `backend/app/main.py`，彻底清除顶层 SQLite 与全局适配器实例化副作用；使用 `lifespan` 上下文管理器管理 `AppContainer` 的生命周期，绑定 `dependency_overrides` 桥接，升级 `/health` 多组件结构化就绪响应
- **涉及文件**: `backend/app/main.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/unit/test_app_lifespan.py tests/unit/api/ -v
  ```
- **预期判据 (绿灯)**: `test_app_lifespan.py` 全部通过，全量既有 API 路由单测 100% 绿灯无回归

---

### Milestone 4: 全量回归与真实基础设施连通性测试

#### Step 4.1: 基础设施集成测试编写与环境探测
- **目标**: 编写 `backend/tests/integration/test_real_infrastructure.py`，当本地检测到 PostgreSQL / Redis / MinIO 容器运行时执行物理连通、Alembic 迁移与 HNSW 向量索引创建 (IT-PGV-01)；在容器未启动时安全跳过以保证脱机开发流水线畅通
- **涉及文件**: `backend/tests/integration/test_real_infrastructure.py`, `backend/pyproject.toml`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/integration/test_real_infrastructure.py -v
  ```
- **预期判据 (绿灯)**: 集成测试根据当前环境自动检测基础设施，测试通过或按预期跳过，无外部网络泄露

#### Step 4.2: P0 全链路端到端与越权矩阵回归
- **目标**: 回归运行 P0 端到端测试，确保从资料上传、切分、知识抽取、题目生成到判题诊断的完整 8 步正向流程与 16 维越权拦截 100% 兼容
- **涉及文件**: `backend/tests/integration/test_p0_full_chain_e2e.py`
- **局部验证命令**:
  ```bash
  cd backend && uv run pytest tests/integration/test_p0_full_chain_e2e.py -v
  ```
- **预期判据 (绿灯)**: 17 个全链路与多租户测试用例毫秒级通过，零断言修改，100% 保持绿灯

#### Step 4.3: 全局门禁严格扫描与架构校验
- **目标**: 执行代码格式化、类型静态分析、高危安全扫描、架构分层与 SDLC 工件合规核验
- **涉及命令**: 详见第 4 节 Quality Gate 命令列表
- **预期判据**: 全门禁 0 警告 0 报错，架构依赖违规数为 0，退出码均为 0

---

## 3. 风险评估与爆炸半径 (Risks & Blast Radius)

| 风险项 | 潜在破坏面 | 规避与隔离方案 |
| :--- | :--- | :--- |
| **1. 模块顶层副作用移除导致的测试未装配** | 部分直接 import `main.app` 的轻量测试若未触发 Lifespan，可能导致 `app.state.container` 未初始化 | 保持 `app.dependency_overrides` 最高优先级；在 `provide_*` 中做好 `getattr(request.app.state, "container", None)` 防御并抛出清晰指引 |
| **2. 分层架构反向依赖违规 (`check_layers.py`)** | `app/integrations` 若导入 `app.services` 或 `app/core` 导入业务服务将被门禁直接打断 | 严格执行双层隔离：`ProviderRegistry` 位于 `app/integrations/container.py` 仅持有 Protocol；`AppContainer` 位于 `app/container.py` 统筹服务装配 |
| **3. 网络阻断 Fixture 冲突** | `conftest.py` 禁止外部联网，若集成测试连接真实容器触发网络拦截 | `conftest.py` 原生放行 `127.0.0.1` 与 `localhost`，真实容器映射本地端口即可安全通信，无需破坏零公网外联红线 |
| **4. 强类型环境变量解析差异** | 生产与 CI 环境下多层嵌套环境变量（如 `ZHILIAN_STORAGE__ACCESS_KEY`）大小写或解析不匹配 | 采用 `pydantic-settings` 的 `env_nested_delimiter="__"`，在 `UT-CFG-02` 中建立完备的字典映射反序列化单元测试 |
| **5. 数据库驱动与向量扩展差异** | SQLite 内存测试不支持 PG 扩展，PG16 需要 `psycopg` 与 `vector` 扩展 | 单元测试环境沿用 SQLite + Fake 保持毫秒级自闭环；真实容器迁移脚本中严格执行 `CREATE EXTENSION IF NOT EXISTS vector` |

---

## 4. 全局质量门禁核验 (Global Quality Gate)

* **代码风格扫描 (Ruff Format)**:
  ```bash
  cd backend && uv run ruff format --check .
  ```
* **静态质量扫描 (Ruff Check)**:
  ```bash
  cd backend && uv run ruff check .
  ```
* **严格类型检查 (Mypy Strict)**:
  ```bash
  cd backend && uv run mypy app
  ```
* **高危安全漏洞审计 (Bandit)**:
  ```bash
  cd backend && uv run bandit -r app -ll
  ```
* **依赖安全漏洞审计 (Pip-audit)**:
  ```bash
  cd backend && uv run pip-audit --strict
  ```
* **架构分层单向依赖校验 (Layer Rules)**:
  ```bash
  uv run python tooling/check_layers.py --root backend/app
  ```
* **SDLC 工件完整性与防跳步门禁 (SDLC Integrity)**:
  ```bash
  uv run python tooling/check_sdlc_integrity.py
  ```
* **全量自动化测试与分支覆盖率门禁**:
  ```bash
  cd backend && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
  ```

---

## 5. 实施偏差记录 (Deviations Log)

- 暂无实施偏差。全量实施步骤严格对照 spec.md 架构契约推进。

---

## 6. 阶段准出签批 (Gate 3 Sign-off)

- [ ] 所有分步实施项与验证断言均已就地执行并通过
- [ ] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [ ] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Pending
- **验证人 / 日期**: 待后续验证完成后由人类签批 / 2026-09-25
