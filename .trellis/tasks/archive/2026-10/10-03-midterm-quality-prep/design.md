# 设计：中期质量检查准备包的结构与口径

> 任务：`10-03-midterm-quality-prep`
> 定位：说明四份产出**长什么样、内部如何组织、彼此如何引用**，以及准出标准、
> 角色映射、排期模型的定义方式。不重复 PRD 的需求条目。

## 1 交付物结构

```
中期质量检查/
├── README.md                  # 索引：用途、阅读顺序、与既有文档的关系
├── 中期质量计划.md             # R1 —— 范围 + 标准 + 角色 + 流程 + 风险
├── 评审清单.md                 # R2 —— 按 T0/T1/T2 的项目实例版检查清单
├── 单测计划.md                 # R3 —— 覆盖率口径 + 补测清单 + 抖动处置
├── 排期表.md                   # R4 —— 按主链路 8 节点的 M0–M4 里程碑
└── templates/
    ├── 单测用例模板.md          # R5.1
    ├── PR-MR模板.md            # R5.2
    ├── 评审检查清单模板.md      # R5.3（空白版，评审清单.md 是其填好版）
    └── 缺陷记录表模板.md        # R5.4
```

**引用方向（单向，避免环形重复）**：

```
中期质量计划 ──引用──> 评审清单 / 单测计划 / 排期表
评审清单     ──索引──> 缺陷记录表模板（台账入口）
单测计划     ──产出──> 单测用例模板 + PR-MR模板
排期表       ──引用──> 中期质量计划（准出标准）
README       ──索引──> 全部
```

各文档**不复制**对方正文，只写一句"详见《X》第 N 节"。理由：单一事实源，
避免四份文档里同一阈值出现四遍后开始互相漂移（本项目已发生三份文档测试规模数字互不一致）。

## 2 准出标准模型（三层 × 可判定）

「可判定」的定义：每条标准都能写成「命令 + 期望输出 + 判定人」。

| 层 | 何时执行 | 谁执行 | 失败后果 |
| --- | --- | --- | --- |
| **L1 硬门禁**（自动） | 每次 push / PR | CI（`verify.yml`） | 阻断合并 |
| **L2 增量门禁**（自动，本期新增） | 每个合入 `master` 的 PR | CI（本期待接线） | 阻断合并 |
| **L3 人工评审** | 里程碑收口 | Reviewer 为首 | 暂停交付（质量否决） |

### 2.1 L1 硬门禁（沿用现状，不新增）

| 检查 | 命令 | 判据 | 出处 |
| --- | --- | --- | --- |
| 后端格式/静态 | `task verify-backend` 前两段 | 无告警 | `Taskfile.yml` |
| 后端类型 | `uv run mypy app` | 严格模式 0 错 | 同上 |
| 后端架构契约 | `uv run lint-imports` | 5 条契约全过 | 同上 |
| 后端单测+覆盖率 | `uv run pytest tests --cov=app --cov-branch --cov-fail-under=80` | 全绿且 ≥80% | 同上 |
| 前端静态/类型 | `pnpm run lint && pnpm run type-check` | 0 错 | 同上 |
| 前端单测 | `pnpm run test:unit` | 全绿 | 同上 |

### 2.2 L2 增量门禁（本期定义、后续实施）

用户口径："新增代码覆盖率 ≥ 70%~80%，核心模块 ≥ 90%。" 落到可执行形态：

| 项 | 定义 |
| --- | --- |
| 口径 | **增量**（diff）覆盖率 = 本次改动的新增/修改行中被用例执行到的比例 |
| 后端工具 | `diff-cover`，输入 `coverage.xml`（`pytest --cov-report=xml`），基线 `origin/master` |
| 后端命令 | `uv run pytest tests --cov=app --cov-branch --cov-report=xml && uv run diff-cover coverage.xml --compare-branch=origin/master --fail-under=80` |
| 后端 T0 加严 | 对 `app/core/algorithms/`、`app/core/errors.py`、`app/core/security.py`、`app/api/deps/` 的改动单独跑一次 `--fail-under=90` |
| 前端工具 | **先接入** `@vitest/coverage-v8`（当前 `package.json` 无 coverage 依赖），用 `vitest run --coverage` |
| 前端命令 | `pnpm run test:unit -- --coverage`（`coverage.thresholds` 暂设 0 观察，观察一个里程碑后再设阈值） |
| 关系 | 增量门禁**叠加在**全量 80% 之上，不替换全量门禁（全量防倒退，增量防"新代码不测"） |

> 为什么不全量提到 90%：全量覆盖已被历史代码"摊薄"，一刀切提阈值会逼出为凑数而写的
> 无断言用例。增量口径直接对齐"新增代码必须有测试"这条真实意图。

### 2.3 L3 人工评审

- 打回线：T0 模块 **双人评审**且必须包含所有权人（`docs/团队分工.md` §4）。
- 闭环要求：缺陷台账（按 `缺陷记录表模板.md`）在里程碑收口时**无 open 项**，
  要么已修，要么写成显式决策（含理由、影响、下一步）——不允许"记了但没人管"。
- 质量否决：Reviewer 对「主链 P0 验收未过」或「阈值改动缺回归证据」可否决，只暂停交付、不改需求。

## 3 角色映射（用户五职能 → 四代号）

用户要求明确「开发 / 测试 / 评审人 / 记录员 / 项目与 QA 负责人」。此五者映射到
`docs/团队分工.md` 的四代号，一人多角，**不新增岗位**：

| 用户职能 | 承担代号 | 依据（`docs/团队分工.md`） |
| --- | --- | --- |
| 项目负责人 | **TechLead** | 需求口径维护、跨模块方案裁决（§2、§5） |
| QA 负责人 | **Reviewer** | 测试与质量判据、缺陷跟踪、质量否决权（§2、§5） |
| 开发 | **SecLead**（后端/算法/小程序）+ **TechLead**（需求/方案） | 代码所有权表（§4） |
| 测试 | **Reviewer**（用例与覆盖率门槛）+ **DevOpsLead**（CI 执行） | §4「`backend/tests/` 归 Reviewer」 |
| 评审人 | 按模块所有权指定（见《评审清单》每行"评审人"列） | §4 所有权矩阵 |
| 记录员 | **DevOpsLead** | §4「`docs/` 归 DevOpsLead」，工程文档与流程留痕 |

**RACI（用于里程碑收口）**：

| 活动 | R 执行 | A 批准 | C 咨询 | I 知会 |
| --- | --- | --- | --- | --- |
| 定义/调整准出标准 | Reviewer | Reviewer | TechLead、SecLead | DevOpsLead |
| T0 代码评审 | 所有权人 + 另一人 | 所有权人 | TechLead | Reviewer |
| 单测补测实施 | SecLead | Reviewer | TechLead | DevOpsLead |
| 覆盖率排除清单维护 | Reviewer | Reviewer | SecLead | TechLead |
| 里程碑收口验收 | Reviewer | Reviewer | TechLead | 全体代号 |
| 缺陷台账维护 | DevOpsLead（记录） | Reviewer（判定级别） | 相关所有权人 | TechLead |

## 4 评审范围分级（T0/T1/T2）

分级依据 = **churn Top20 ∩ 主链路 ∩ 编译器盲区**（推导过程见 `research/baseline-and-risk.md` §2–3）。

| 级别 | 后端 | 前端 | 评审强度 |
| --- | --- | --- | --- |
| T0 | `core/algorithms/`、`core/errors.py`、`core/security.py`、`api/deps/`、`services/{material,question,practice}.py`、`repositories/material.py`、`api/v1/{questions,materials,practices}.py` | `utils/request.ts`、`stores/{practice,material,diagnosis}.ts`、`api/adapters/*`、`pages/index/index.vue`、`subpackages/material/pages/questions/index.vue`、`subpackages/report/pages/detail/index.vue` | 双人评审 + 增量覆盖率 ≥90% |
| T1 | `schemas/*`、`repositories/*`（除 material）、`models/*` | `types/*`、`api/index.ts`、`api/material.ts`、`pages.json`、`pages/review/index.vue` | 单人评审 + 增量覆盖率 ≥80% |
| T2 | `cli/`、`integrations/*` 的 fake 实现 | `utils/materialState.ts` 等纯函数 | 抽检 + 增量覆盖率 ≥80% |

## 5 单测计划的设计要点

1. **覆盖率只从实时命令取**，文档里写命令不写死数字（C-5）。
2. **墙钟抖动（E-1）**：`backend/tests/unit/core/algorithms/` 的 4 处墙钟断言
   （200/50/20/100 ms）在全量并发下抖动。处置设计：
   - 准出**取证方式**：`pytest -p no:cacheprovider -o addopts=""` 单进程串行跑一遍作为
     覆盖率/通过率的取证运行；
   - 同时保留全量并发运行结果，抖动用例**计入缺陷台账（E-1）**，不作为准出阻断项；
   - **不放宽阈值**（`AGENTS.md` 定案）。
3. **变异验证**沿用 `docs/开发过程文档.md` §5.3 的纪律：关键改动做「故意破坏 → 确认失败 → 恢复」。
4. **前端补测方向**：优先把逻辑下移到纯函数/适配器（本项目既有先例：
   `reportView.ts`、`reviewView.ts`、`api/adapters/*`、`utils/materialState.ts`、`utils/draftQueue.ts`），
   再对纯函数补测——而不是引入组件挂载测试（当前无任何 `mount()` 用法的既有约定）。

## 6 排期模型

切片主轴 = 主链路 8 节点。理由：按节点切片，每个里程碑都能**端到端验收**
（比按文件分堆更容易暴露"单侧修好、链路仍断"的问题，P0-1 就是典型：只修前后端一侧用户依然卡死）。

| 里程碑 | 覆盖节点 | 主题 | 依赖 |
| --- | --- | --- | --- |
| **M0 基线化** | 全链路（只读盘点） | 重新基线化测试规模/覆盖率；确认评审范围与标准 | 无 |
| **M1 主链路前半** | 登录 → 工作台/课程 → 上传 → 解析 | 含 P0-1 解析卡死修复的质量保障 | M0 |
| **M2 主链路后半** | 出题核对 → 作答 → 判题 | 含 P0-2 思考模式、P1-3 出题反馈 | M1 |
| **M3 学习闭环** | 学情/题库/错题本 | 含 P1-4 统计口径、P1-5 覆盖率误导 | M2 |
| **M4 收口** | 全链路回归 | 准出标准全量判定 + 缺陷台账闭环 + 阶段收口会 | M0–M3 |

里程碑与既有任务的衔接：**不重复立项**，只把既有任务的验收项挂到对应里程碑下
（如 P0-1 挂 M1、P1-5 挂 M3），作为该里程碑的"必过验收项"。

## 7 风险与对策

| # | 风险 | 对策 |
| --- | --- | --- |
| R-1 | 前端无覆盖率工具 → "覆盖率准出"落不了地 | M0 先接入 `@vitest/coverage-v8`，观察一个里程碑再设阈值 |
| R-2 | 墙钟抖动导致"通过率 100%"无法稳定取证 | 串行取证 + 记入台账 + 不放宽阈值（§5.2） |
| R-3 | 覆盖率被排除清单抬高（E-2） | 排除项集中登记、逐项写理由，CI 校验未被扩大 |
| R-4 | 单账号 → 无法强制必需评审 | 评审作为组织层约定执行（`docs/团队分工.md` §6 已定案），不追求服务端强制 |
| R-5 | 文档数字再次漂移 | C-5「数字不手抄」+ M0 重新基线化 |
| R-6 | 范围蔓延到修缺陷 | Out of Scope 明确：只登记不实施，缺陷归各自任务 |
