# AGENTS.md - 全局工程协同协议与代码管理规范

本文件是常驻工程行为基准与中枢索引，启动时自动加载。终端实际运行结果与源码是唯一事实源。

---

## 1. 核心命令与物理闭环 (Commands & Verification)

- **工具链自测**：`uv run python -m unittest discover tests`（验证脚手架生命周期与统计工具）。
- **门禁合规检查**：`uv run python tooling/check_sdlc_integrity.py`（验证活跃任务工件完整性与防跳步约束）。
- **分层依赖校验**：`uv run python tooling/check_layers.py --root backend/app`（校验架构单向导入合法性）。
- **后端质量全量基线**（进入 `backend` 目录，优先使用 `uv run` 确保使用 Python 3.12 虚拟环境）：
  ```bash
  cd backend && \
  uv run ruff format --check . && \
  uv run ruff check . && \
  uv run mypy app && \
  uv run bandit -r app -ll && \
  uv run pip-audit --strict && \
  uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
  ```
  - `ruff format --check .`：严格检查行宽 100；
  - `ruff check .`：执行 Python 静态质量扫描（启用 E, F, I, N, UP, B, SIM, S, RUF, ASYNC 规则集）；
  - `mypy app`：开启类型严格模式（首批强制覆盖 `app/core`, `app/core/algorithms`, `app/services`，禁止未类型标注函数）；
  - `bandit -r app -ll`：高危安全隐患必须为 0，中危需专门登记并提供规避方案；
  - `pip-audit --strict`：依赖安全漏洞严格审计；
  - `pytest tests --cov=app --cov-branch --cov-fail-under=80`：全量单测、分支覆盖统计与全局覆盖率门禁。
- **前端质量基线**（进入 `miniprogram` 目录执行）：
  ```bash
  cd miniprogram && \
  pnpm run lint && \
  pnpm run type-check && \
  pnpm run test:unit
  ```
  - `pnpm run lint`：执行 ESLint + Prettier 静态扫描（强制行宽 100、单引号、尾随逗号、严禁隐式 `any`，**严格拦截单组件文件超过 300 行**）；
  - `pnpm run type-check`：执行 `vue-tsc --noEmit` 深度静态类型与模板属性检查。**AI 排错核心事实源**：AI Agent 在修改或新增前端代码后**必须**在终端执行该命令，直接根据输出的 `文件路径:行号:列号 - error TSxxxx: 错误信息` 精确定位并就地修复类型、未定义属性与契约不匹配，严禁带着类型报错流转工件；
  - `pnpm run test:unit`：执行 Vitest 脱机单元测试（验证拦截器、4-Store 状态流转与白名单隔离，毫秒级通过）；
  - `pnpm run build:mp-weixin`：小程序全量生产编译打包（验证构建产物完整、无缺少模块与语法破坏）。
- **本地提交前前置检查**（pre-commit）：
  ```bash
  pip install pre-commit && pre-commit install --install-hooks && pre-commit run --all-files
  ```
- **测试真实性与网络隔离红线**：
  - 单元测试单用例执行时间控制在毫秒级，后端全部单元测试必须在 30 秒内跑完；
  - 单元测试严格禁止真实联网，`conftest.py` 中配置网络阻断 Fixture，产生外部网络连接直接抛错中断；
  - 集成测试使用真实容器化依赖（PostgreSQL 16 + pgvector, Redis 7, MinIO）；外部 LLM 与 OCR 适配器在测试中一律替换为固定返回的假实现（Fake/Stub），严禁在自动化测试中消耗外部配额与网络。

---

## 2. 架构拓扑与分层依赖 (Architecture & Layered Boundaries)

- **智练后端五层单向架构矩阵**：
  - 依赖单向向下：`app/api/v1` (路由) $\rightarrow$ `app/services` (服务编排/事务) $\rightarrow$ `app/repositories` (数据仓储)；
  - 纯函数计算核：`app/core/algorithms` 独立于业务编排，只包含纯函数，输入输出均为原生数据结构；
  - 外部能力适配层：`app/integrations` 通过 Protocol 定义抽象接口，具体实现与供应商解耦；
  - 核心通用支持：`app/core`（配置、异常、安全、日志）可被各层导入，但自身严禁导入上层业务模块。
- **后端禁止跨层与导入铁律**（由 `tooling/check_layers.py` 强力自动化校验）：
  - `app/api/v1`：只做解析请求、Pydantic 参数校验、调用 Service、响应转换。严禁直接访问数据库会话、调用外部服务或执行超过 1 行的业务判断，**严禁跨层导入 `app/repositories`**；
  - `app/services`：全系统**唯一允许开启数据库事务的层**，负责事务边界、多步骤编排与外部能力调度；
  - `app/repositories`：封装数据表查询与写入，**所有涉及用户数据的查询强制携带 `user_id` 条件**（阻断水平越权）；严禁导入 `fastapi` 与 `app/integrations`；
  - `app/core/algorithms`：纯函数计算核，**绝对禁止导入 `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3`** 等 Web 框架、ORM 或网络库，严禁导入 `app/services` 与 `app/repositories`；
  - `app/integrations`：严禁导入 `app/services`。**严禁在函数内部延迟导入或通过 `getattr` 动态取模块绕过架构分层检查**。
- **小程序架构与性能红线**：
  - 代码组织：严格按页面（`pages`）、业务组件（`components`）、组合式函数（`composables`）、状态（`stores`）、请求封装（`api`）五部分组织；
  - 组件规模：**单个组件文件代码行数超过 300 行时，必须在同一次改动中拆分**，拆分后的子组件集中置于同名目录下；
  - Pinia 状态树收敛：严格限定 4 个 Store（`materialStore` 资料、`practiceStore` 练习、`reportStore` 诊断报告、`userStore` 用户）；仅跨页面共享数据可进 Store；**Store 内严禁直接调用接口**，网络请求统一由 `src/api` 承载并由 Store 引用；
  - 本地存储（Storage）白名单：**仅允许持久化登录态、未提交作答草稿与用户偏好 3 类数据**，资料与题目全文绝对严禁进入本地 Storage；
  - 渲染与性能红线：数据更新必须合并后一次调用 `setData`，长列表每页 20 条且必须做窗口回收；页面滚动回调中仅允许更新视图层变量，严禁执行密集计算、数据格式化或接口请求；小程序主包体积必须控制在 2MB 以内，资料管理与报告页面放入分包；图片上传前在本地压缩至长边 1600 像素以内。

---

## 3. 核心计算核与测试覆盖率门槛 (Algorithms & Quality Gates)

- **5 块必测纯函数计算核清单**（任何一块新增分支必须在同一次改动中补充测试）：
  1. **资料分块算法**（`split_material_into_snippets`）：等价类划分与边界值测试（片段长度取 1、恰等于上限、上限加 1；重叠取 0 与上限；单段超长强制截断；孤立短段合并；空输入与全空白输入），**分支覆盖率 100%**；
  2. **知识点质检**（`verify_knowledge_points`）：决策表覆盖数量区间、层级深度、命名可读性、章节覆盖率 4 个条件的全部组合，**判定覆盖率 100%**；
  3. **题目质检**（`filter_qualified_questions`）：覆盖重复题、答案冲突、缺少来源、表述歧义 4 类异常，**条件组合覆盖**；
  4. **判题阈值与匹配**（`match_and_grade_answer`）：边界值测试相似度恰等于下阈值（离线判错）、恰等于上阈值（离线判对）、落在两阈值之间（转 AI 判题）；决策表覆盖 4 类转 AI 条件；成对测试否定词反转专项用例（仅否定词不同时得分方向严格相反），**条件组合覆盖**；
  5. **掌握度计算**（`aggregate_mastery_scores`）：加权正确率乘时间衰减因子（默认半衰期 30 天，离线判分权重 1.0、AI 判题 0.8、自评与重判 0.5；闲置 3/7/30/300 天衰减测试；无答题记录返回未学档次；0.40 与 0.70 临界档次判定），**分支覆盖率 100%**。
- **白盒复杂度上限（McCabe 环路复杂度 $V(G)$）**：
  - 资料分块主切分函数：$V(G) \le 12$；
  - 判题匹配决策函数：$V(G) \le 10$；
  - 掌握度衰减聚合函数：$V(G) \le 8$；
  - 超过上限必须进行函数拆分，严禁直接堆叠判断逻辑。
- **覆盖率硬性门槛**：
  - `backend/app/core/algorithms/`：**行覆盖率 $\ge 95\%$，分支覆盖率 $\ge 90\%$**；
  - `backend/app/core/security.py`：**行覆盖率 $\ge 95\%$**；
  - `backend/app/services/`：**行覆盖率 $\ge 85\%$**；
  - 全局后端：**行覆盖率 $\ge 80\%$，分支覆盖率 $\ge 70\%$**；
  - 纯函数计算核严禁使用 Mock 替身打桩内部调用；
  - 行内跳过标注（`# pragma: no cover`）单个文件不得超过 3 处，且必须明确注明不可达防御分支原因。

---

## 4. 编码规范、命名与日志安全 (Coding, Naming & Security)

- **命名规范与全英文要求**：
  - 标识符一律使用英文，**严禁使用拼音或中文命名**（测试数据变量名同样受限）；
  - **缩写白名单仅限 8 个**：`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`，严禁自造任何缩写（如 usr, mgr, tmp, cnt 等）；
  - 命名格式矩阵：Python 模块/函数 `snake_case`；类/接口 `PascalCase`；常量 `UPPER_SNAKE_CASE`；私有成员 `_prefix`；DB 表 `snake_case` 复数；DB 字段 `snake_case`（布尔加 `is_` 前缀）；前端组件目录及文件大驼峰；组合式函数 `useXxx`；Pinia `useXxxStore`；任务编号 `ZL-xxx`；缺陷编号 `BUG-xxx`。
- **注释与文档字符串**：
  - 采用 Google 风格中文 Docstring（包含职责说明、Args、Returns、Raises，纯函数补充前置条件与失败返回约定）；
  - **算法中的每一个阈值常量必须显式注明注释依据**（决策基线条目、实验数据或接口限制）；
  - **严禁废弃注释代码**，历史版本由 Git 记录，过期或废弃代码一律直接删除。
- **统一业务异常体系（AppError）**：
  - 统一继承业务异常基类 `AppError`（携带错误码、HTTP 状态码与面向用户的提示文案）；
  - 五位数字错误码分类矩阵：
    - `10xxx`：参数校验与请求格式问题（如 10001）；
    - `20xxx`：鉴权与权限越权问题（如 20001 未登录、20002 无权访问）；
    - `30xxx`：外部能力与网络问题（如 30001 OCR 失败、30002 LLM 超时）；
    - `40xxx`：算法与质量门禁阻断（如 40001 资料不达标、40002 知识点质检失败）；
    - `50xxx`：内部系统与数据库问题（如 50001 数据库写入失败）；
  - 严禁在路由层用 `try...except` 吞掉全部异常并返回字符串，新增错误码必须先在规范登记。
- **结构化日志 8 要素与绝密脱敏红线**：
  - 每条日志必须输出结构化 8 要素：时间（`timestamp`）、级别（`level`）、日志名（`logger_name`）、请求标识（`request_id`）、用户引用（`user_ref`，仅保留用户 ID 不可逆摘要前 8 位）、业务对象标识（`target_id`）、耗时（`duration_ms`）、错误码（`error_code`）；
  - **绝密脱敏红线（严禁记录入日志）**：
    1. 学习资料全文；
    2. 题目与参考答案全文；
    3. 用户作答原文；
    4. 访问令牌（Access/Refresh Token）与第三方 API Key；
    5. 用户手机号与明文用户标识；
    6. 数据库连接密码与服务口令；
  - 文本排查统一使用字符长度、片段数量、匹配相似度、判分来源等量化字段，日志输出前必须经过脱敏函数。

---

## 5. Git 协作、分支模型与提交约定 (Git Flow, Commits & CODEOWNERS)

- **精简版 Git Flow 机制**：
  - 长期分支：`main`（唯一可发布产物，打 vX.Y.Z 标签，禁止直接推送）、`develop`（集成开发分支，禁止直接推送）；
  - 短期分支：`feature/ZL-xxx-desc`（存活不超过 5 工作日）、`release/vX.Y.Z`（发布冻结与回归验证，只接受缺陷修复）、`hotfix/ZL-xxx-desc`（线上紧急修复，从 main 标签切出）；
  - 合并策略：
    - `feature/*` $\rightarrow$ `develop`：强制采用 **Squash and Merge**（压缩合并，提交信息保留任务编号）；
    - `release/*` / `hotfix/*` $\rightarrow$ `main` & `develop`：强制采用 **Merge Commit**（普通合并，保留完整审计路径）。
- **提交三段式规范（Commit Message Specification）**：
  - 格式规范：
    ```text
    <type>(<scope>): <subject>

    <body>

    Refs: ZL-xxx
    Fixes: BUG-xxx
    ```
  - Type 白名单：`feat`, `fix`, `refactor`, `test`, `docs`, `chore`, `perf`, `ci`, `revert`；
  - Scope 白名单：`api`, `services`, `algorithms`, `integrations`, `models`, `miniprogram`, `deploy`, `ci`, `docs`；
  - 标题约束：不超过 50 字符，祈使语气动词开头，末尾不加句号；
  - 正文约束：说明为什么修改，每行不超过 72 字符；
  - 关联行约束：统一以 `Refs: ZL-xxx` 关联任务卡片，修复缺陷补写 `Fixes: BUG-xxx`。
- **代码所有权与高风险 MR 双人签批要求（CODEOWNERS）**：
  - 算法核心（`backend/app/core/algorithms/`）：所有权人【TechLead、SecLead】，必须双人评审通过（须含TechLead），修改默认阈值必须附测试用例与依据；
  - 鉴权与安全（`backend/app/core/security.py`, `backend/app/api/deps/`, `backend/app/repositories/`）：所有权人【SecLead、TechLead】，必须双人评审通过，必须附越权负向测试用例；
  - 部署与运维（`deploy/`, `.github/workflows/`, `backend/Dockerfile`, `backend/migrations/`）：所有权人【DevOpsLead、SecLead】，必须双人评审通过，必须附回滚方案与迁移降级验证；
  - 高风险 MR 判定（命中以下 7 项任一：跨 2 个以上模块、改动对外 API 契约、改动 DB 结构或向量索引、触碰鉴权/数据隔离、引入/升级核心第三方依赖、改动难以回滚/需人工修复、影响全量用户主链）：必须由 2 名成员（含对应 CODEOWNER）批准，且必须附可执行回滚方案。

---

## 6. 核心红线 (Must-Not)

- **严禁擅自破坏公共契约**：严禁在方案获确认前擅自修改公共 API 契约、数据库 Schema 或核心持久化格式。
- **严禁并发泄漏与竞态**：并发路径必须具备严格的互斥与生命周期管理，严禁资源泄漏或死锁。
- **严禁泄露敏感凭证与隐私**：严禁将真实公网 IP、生产域名、Token、私钥或敏感密码写入代码、配置或日志。
- **严禁静默吞错**：严禁忽略或静默压制未处理的异常返回值。
- **严禁过度抽象（KISS 原则）**：严禁单实现 interface、空转包装类与各类无痛点工厂。
- **严禁主会话越俎代庖（禁止直通改代码）**：主会话定位为【纯调度指挥官】，严禁在 Tier 2 / Tier 3 任务中直接调用 edit/write 工具编写业务代码，必须通过 `task` 委派专职子代理。

---

## 7. 典型错误防御 (Things AI Gets Wrong)

- **伪造测试**：自称测试已通过但未在终端实际执行，或通过削弱断言/注入 skip 掩盖失败。
- **巨石任务**：面对复杂诉求试图立项“大爆炸重构”，必须主动提醒人类按领域拆解为原子任务。
- **幻觉签批**：误以为自己可代替人类在工件中勾选签批；Sign-off 必须由人类专属签批。
- **单会话直通懒惰**：自恃掌握工具而违规跳过子代理；凡 Tier 2 / Tier 3 任务必须严格委派 planner、builder 和 reviewer 分阶段执行。
- **前端盲目猜错与跳步**：修改前端代码后未在终端运行 `pnpm run type-check` 和 `pnpm run lint`，脱离终端真实编译报错凭空猜错或掩盖类型隐患；必须以 `vue-tsc` 与 ESLint 输出的具体行号及错误描述为唯一事实源就地修复。

---

## 8. 协同与能力索引 (Collaboration & Skills)

- **特性与架构变更**：加载 `sdlc-workflow` 技能，通过 `python3 tooling/task_cli.py` 驱动工件推进。凡 Tier 2 / Tier 3 任务，**必须强制通过 `task` 工具委派 `planner` / `builder` / `reviewer`**，严禁主会话单会话直通越权实施。
- **缺陷排查与修复**：加载 `bug-fix` 技能，遵循 Fail-repro First（失败测试先行）。
- **代码审查与把关**：由 `reviewer` 子代理对照根目录 `REVIEW.md` 执行 3-Pass 审计（正确性与边界、安全与用户隔离、与计划一致性），单次审查次要建议上限不超过 5 条。
