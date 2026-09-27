# 审计子任务技术设计：全量只读审计

## 1. 目标与边界

- **目标**：产出可被逐条引用、可复现、分级一致的 bug 总清单。
- **只读边界**：审计期间不改业务代码；仅在 `{TASK_DIR}/research/` 下写制品。
- **证据边界**：每条发现必须能由"可重跑命令"或"可跳转 `file:line`"支撑。

## 2. 目录与制品布局

```
{TASK_DIR}/                       # .trellis/tasks/09-27-read-only-bug-audit
  research/
    toolchain-baseline.md         # 8 项门禁命令的原始结果 + 环境受限标注
    bug-ledger.md                 # 功能性 bug 总清单（按切片分组，统一编号）
    code-smells.md                # 非功能性发现（重复造轮子/死代码/坏味道）
    cross-layer-matrix.md         # 6 切片 × 前后端契约核对结论
  design.md                       # 本文件
  implement.md                    # 执行清单
```

清单编号规范：`BUG-<切片>-<序号>`，如 `BUG-AUTH-003`；非功能性用 `SMELL-<切片>-<序号>`。

## 3. 垂直切片划分（前后端同片查）

| 切片码 | 范围 | 后端入口 | 前端入口 |
|---|---|---|---|
| AUTH | 认证/登录/会话 | `app/services/auth.py`、`app/api/*auth*`、`core/security.py` | `src/api/auth.ts`、`src/stores/user*.ts`、`pages/auth`、`pages/login` |
| MAT | 素材/知识点树 | `services/material.py`、`services/knowledge.py`、`core/algorithms/search.py` | `src/api/material.ts`、`stores/materialStore.ts`、`subpackages/material/**` |
| QGEN | 题目生成/审核/编辑 | `services/question.py`、`core/algorithms/question_quality.py` | `src/api/question.ts`、`subpackages/material/components/Question*`、`utils/questionGeneration.ts` |
| PRAC | 练习作答/草稿/答案单 | `services/practice.py` | `src/api/practice.ts`、`stores/practiceStore.ts`、`subpackages/practice/**` |
| GRADE | 评分/批改/自评/重批 | `services/grading.py` | `src/api/*grad*`、`subpackages/report/components/*Grade*`、`RegradeModal` |
| DIAG | 报告/诊断/错题本 | `services/diagnosis.py` | `src/api/diagnosis.ts`、`stores/reportStore.ts`、`subpackages/report/**`、`utils/wrongBookFormat.ts` |

跨切片横切关注点（在每片内检查，不单列切片）：错误处理、类型契约、鉴权、分页、幂等、时间/编码。

## 4. 严重级别定义（P0/P1/P2）

- **P0**：核心流程中断 / 数据错误或丢失 / 安全或越权 / 崩溃（未捕获异常导致 5xx 或白屏）。
- **P1**：功能性错误，存在绕行但正常路径下会出错（错误结果、状态不一致、接口契约不符）。
- **P2**：**仅客观可判定项**——空指针/越界、未处理的异常与 Promise 挂起、类型漏洞、前后端/存储契约不一致、状态未重置、边界值错误。
  - 明确排除：主观 UX/文案/布局偏好。
- **疑似（SR）**：真机/开发者工具专属渲染或交互问题，静态与组件测试无法确证；单列，不计入 P0/P1/P2。
- **环境受限（ENV）**：由缺依赖/解释器解析等环境因素导致的工具链失败；单列，不计为产品 bug。

## 5. 证据标准与判定流程

```
发现 → 定位(file:line) → 尝试复现
  ├─ 工具链命令可复现            → 定级 P0/P1/P2，附命令与输出
  ├─ 单测/组件测试可复现          → 定级，附最小复现（测试片段或挂载用例）
  ├─ 仅静态推理可支撑            → 定级 P2 或降级为疑似，注明推理链
  └─ 受环境/真机限制             → 标 ENV / SR
```

## 6. 工具链命令（基线采集）

后端（`backend/`，已确认 `backend/.venv` 存在）：
```
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run lint-imports
uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
```
前端（`miniprogram/`）：
```
pnpm run lint
pnpm run type-check
pnpm run test:unit
```
注：`go-task` 未安装，直接调用上述底层命令而非 `task verify`。

## 7. 环境与已知基线

- `uv 0.12.1`、`pnpm 12.4.1`、`backend/.venv` 存在。
- 集成测试以 in-memory fake 为主，`test_real_infrastructure.py` 含 `skipif` 守卫 → 无需真实 Postgres/Redis/LLM。
- 编辑器 LSP 报 `backend/tests/**` 中 `import pytest` 无法解析：属 LSP 解释器配置问题，**需复核 `uv run pytest` 实际结果**再判定，避免误报为 ENV 级 bug。
- 已排除的伪发现：`stores/{material,practice,report,user}.ts` 为 re-export shim；`pages/login/index.vue` 为跳转壳；非重复实现。

## 8. 清单条目契约（ledger schema）

`bug-ledger.md` 中每条按固定字段，便于后续逐条引用：

| 字段 | 说明 |
|---|---|
| ID | `BUG-<切片>-<序号>` |
| 级别 | P0 / P1 / P2 |
| 切片 | AUTH/MAT/QGEN/PRAC/GRADE/DIAG |
| 层 | backend / frontend / cross-layer |
| 位置 | `file:line`（可多行） |
| 现象 | 一句话描述 |
| 证据/复现 | 命令+输出 或 测试片段 或 推理链 |
| 影响 | 对功能/数据/安全的影响 |
| 修复方向 | 建议修法（不要求本阶段实现） |

## 9. 风险与权衡

- **风险：清单膨胀** → 以 P2 客观边界 + 疑似/环境单列控制规模。
- **风险：静态误报** → 每条须标注证据强度（实测 > 测试 > 推理）。
- **风险：前后端契约漏检** → 以 `cross-layer-matrix.md` 强制覆盖 6 切片。
- **权衡**：本阶段不做真机验证，渲染类结论强度上限为"疑似"。

## 10. 与后续修复任务的接口

- 清单是修复子任务的唯一输入契约；修复子任务按切片引用对应 `BUG-<切片>-*` 条目并逐条关闭。
- 非功能性 `SMELL-*` 不在本轮修复范围，另行立项。
