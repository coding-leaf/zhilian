---
name: sdlc-workflow
description: 引导 AI-Native SDLC 各阶段工件（intent.md / spec.md / plan.md）流转、7 维风险动态扫描与停止/升级判断。在创建新任务、设计技术契约、制定实施方案或任务升降级时激活。
---

# SDLC Workflow Orchestration (工件流转与门禁编排)

> **核心范式 (Playbook 契约)**：代码编写已不再是工程瓶颈；瓶颈已转移至构建前（Plan/Design）与构建后（Test/Review/Deploy）。每个阶段以“向版本控制提交工件”为准出，下一阶段以此工件为输入展开；线上异常与运维监控突破控制限时，自动回流为新 `intent.md` 闭环。

## 1. 任务工件目录与分级决策
工件统一归档于：`docs/sdlc/<task-id>/`（小写中划线格式）。

### 7 维动态风险扫描
1. **Affected Files**：改动文件数量与跨模块广度
2. **Public API**：对外接口契约（入参、出参、错误码）变动
3. **Data Schema**：数据库表结构、配置 Schema 或持久化状态迁移
4. **Auth & Security**：租户权限、鉴权逻辑与敏感密钥
5. **Dependencies**：第三方外部依赖引入
6. **Rollback Difficulty**：状态变更可逆性与回滚代价
7. **Blast Radius**：核心进程崩溃爆炸半径

### 分级准则与 Tier 3 强制升级触发器
- **Tier 1 (Trivial / Fast Track)**：局部低风险、可逆、无对外契约/数据迁移/鉴权变动（改动 <= 2 个文件，如特定 Bug 修复、局部样式调整、完善现有单元测试）。**直通敏捷流**：无需前置 intent/spec/plan 工件与 task_cli 注册，直接遵循 Fail-repro First 测试先行闭环完成。
- **Tier 2 (Normal)**：单模块特性或局部优化（执行完整的 intent → spec → plan 工件流转）。
- **Tier 3 (High-risk)**：高危变更，强制方案评审与人类签批。**命中以下任一条件必须升为 Tier 3**：
  1. 跨越 >= 2 个独立顶级子系统/业务模块；
  2. 触及顶层引导装配 (Bootstrap) 或进程生命周期退出机制；
  3. 预计涉及文件数 >= 5 个；
  4. 影响核心服务可用性与进程启动的高爆炸半径；
  5. 不可逆状态或无平滑降级的数据迁移。

### 核心纪律红线
- **单一关注点与正交互斥律**：严禁将局部精简与全局装配重排混杂在同一任务中。
- **人类独占签批 (Anti-Self-Signoff)**：工件底部的 `Gate Sign-off` 是**人类专属权限**，AI 严禁勾选 `[x]` 或自行批准。
- **防巨无霸任务 (Anti-Monolith)**：拒绝大爆炸重构，主动引导拆解为单一关注点的原子任务小步快跑。

---

## 2. 7 阶段全生命周期流转与子代理绑定 (Playbook 闭环)

| 阶段 | 负责角色 | 核心动作与输入输出 | 交付工件 | 准出条件 |
| :--- | :--- | :--- | :--- | :--- |
| **Stage 0: Ingest** | 主会话 / 工具 | 摄取长篇需求与规范，基线化工程规则，生成任务矩阵大表与对齐单 | `ROADMAP.md` / `ALIGNMENT` | Leader 签署确认 P0 范围 |
| **Stage 1: Plan** | 主会话 | 提炼痛点、目标、约束与未决问题，严禁主会话提前深挖代码或测试 | `intent.md` | 人类确认 Intent |
| **Stage 2: Design** | `planner` (强制) | 只读分析调用链、评估 7 维风险并起草技术契约，标注 Flagged Concerns | `spec.md` | 人类签批 Spec |
| **Stage 3: Build** | `planner` + `builder` | `planner` 按 4 支柱拆解方案；`builder` 依据 Plan 单遍落地 | `plan.md` | 各步骤就地验证通过 |
| **Stage 4: Test** | `builder` / 环境 | 运行闭环反馈循环 (Feedback Loop)，测试先行，必须退出码 0 | - | 真实测试 100% 全绿 |
| **Stage 5: Review** | `reviewer` (强制) | 对照 `spec.md` 与根目录 `REVIEW.md` 执行 3-Pass 审计，输出结论 | - | 人类终审并归档 |
| **Stage 6: Maintain**| 运维/监控/主会话 | 生产告警或控制限突破（Breached control band）自动回流为新 `intent.md` | 新 `intent.md` | 触发新一轮闭环 |

### 子代理派发标准 3 要素 (Prompt 极简规范)
主会话通过 `task` 派发子代理时，无需注入冗长模板，直接传递 3 要素：
1. **上下文定位**：明确任务 ID 与读写工件路径（如 `docs/sdlc/<task-id>/spec.md`）；
2. **目标与依据**：明确本轮目标、依据文档（如 `依据 intent.md 设计接口并评估风险`）；
3. **返回与红线约束**：限定变更范围、只读/修改权限、强制物理测试命令与返回摘要行数限制。

---

## 3. 风险升级与停止/继续条件 (Stop & Escalate)

- **触发停止并报请人类确认**：需求目标改变、范围实质扩大、公共 API 契约改变、数据模型变动、安全鉴权边界变动、关键设计决策改变。
- **自主继续执行**：内部文件位置/命名微调、局部算法路径优化、实现顺序调整（更新 `plan.md` 后继续推进）。

---

## 4. CLI 命令速查 (tooling/task_cli.py)

```bash
# 1. 任务查看
python3 tooling/task_cli.py list                 # 列出所有活跃任务
python3 tooling/task_cli.py show <task-id>        # 查看任务卡片与工件快照

# 2. 任务创建 (默认 Tier 2，自动释放 intent.md)
python3 tooling/task_cli.py create <task-id> --title "<简明标题>" [--tier 2] [--owner "Dev"]

# 3. 推进阶段与状态变更 (自动按需释放/恢复对应阶段工件)
python3 tooling/task_cli.py update <task-id> --stage Design --next "委托 planner 起草 spec.md"
python3 tooling/task_cli.py update <task-id> --stage Build  --next "委托 planner 起草 plan.md"
python3 tooling/task_cli.py update <task-id> --stage Plan   # 回退重做(自动将超前工件备份为.bak解除自锁)
python3 tooling/task_cli.py update <task-id> --status blocked --blocked "<卡点原因>"

# 4. 门禁与完整性检查 (自动扫描模板占位符与防跳步逆向校验)
python3 tooling/task_cli.py check [<task-id>]

# 5. 归档与注销
python3 tooling/task_cli.py archive <task-id> --outcome "<交付摘要>" --commit "<SHA/PR>" --verify "<测试结果>"
python3 tooling/task_cli.py delete <task-id> [--force]
```

