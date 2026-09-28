# 跨层思维指南（backend ↔ miniprogram）

> **用途**：在动笔之前，先把数据在层与层之间的流动想清楚。
> **适用边界**：`backend/app/**`（FastAPI + SQLAlchemy + LangGraph）与本仓库小程序
> `miniprogram/src/**`（UniApp + Vue 3 + Pinia）。

---

## 问题所在

**大多数 bug 发生在层的交界处，而不是层内部。**

本项目最常见的跨层 bug：

- 后端返回格式 A，前端按格式 B 消费（字段名拼写、蛇形 vs 驼峰、`content` vs `text`）。
- 数据库存 X，Service 转成 Y，转换过程丢字段（可选字段变 `undefined`）。
- 同一份逻辑在 API 路由、Service、前端 adapter 各实现一遍，随后各自漂移。
- 长耗时任务的状态机（`parse_status`、练习交卷 `status`）在后端与前端取值集合不一致。

---

## 实现跨层功能之前

### 第 1 步：画出数据流

以「资料上传 → 解析 → 出题 → 练习 → 报告」为例，标出每一跳的格式：

```
上传文件
  → backend/app/api/v1/materials.py            （HTTP 请求体 / 校验）
  → backend/app/services/material.py           （领域对象、事务）
  → backend/app/models/material.py             （MaterialVersion.parse_status 落库）
  → backend/app/schemas/material.py            （响应模型，snake_case）
  → miniprogram/src/api/material.ts            （请求与原始响应）
  → miniprogram/src/api/adapters/*             （归一化边界）
  → miniprogram/src/stores/materialStore.ts    （状态）
  → 页面 / 组件                                （展示）
```

对每一跳追问：

- 此刻数据是什么格式（字段名、类型、可空性）？
- 可能出什么错（缺字段、类型不符、状态未识别）？
- 谁负责校验/归一化？

### 第 2 步：识别边界

| 边界 | 常见问题 |
| --- | --- |
| `backend/app/api/v1/*` ↔ `backend/app/schemas/*` | 响应字段漏配、HTTP 状态码不一致、可选字段缺省 |
| `backend/app/schemas/*` ↔ `miniprogram/src/api/*` | 序列化、日期格式、`snake_case` 字段名 |
| `miniprogram/src/api/adapters/*` ↔ `miniprogram/src/stores/*` | 归一化后的类型必须正好是 store 期望的形状 |
| `miniprogram/src/stores/*` ↔ 页面 / 组件 | props 形状变化、响应式引用被复制丢失 |
| `backend/app/services/*` ↔ `backend/app/repositories/*` | 提交边界（谁 commit）、`selectinload` 预加载、空值处理 |

### 第 3 步：钉死契约

对每条边界明确：

- 精确的输入格式是什么？
- 精确的输出格式是什么？
- 可能抛哪些错误（`backend/app/core/errors.py` 的异常类型 / 前端 `utils/error.ts` 的 `AppError`）？

---

## 常见跨层错误

### 错误 1：隐式格式假设

**坏**：假定日期字符串格式、假定字段一定存在，直接 `new Date(x)` 或做字符串截取。

**好**：在边界处显式转换，并在 `miniprogram/src/types/*` 里把可空性写清楚。

### 错误 2：校验散落在多层

**坏**：同一个校验在路由、Service、前端 store 各写一遍，语义逐渐分叉。

**好**：入口处校验一次（后端 `backend/app/schemas/*` 的 Pydantic 校验 + 路由层参数清洗），
其余层信任上层传入的值。

### 错误 3：抽象泄漏

**坏**：组件里直接知道数据库字段名或后端内部状态枚举。

**好**：每一层只知道它的邻居；前端页面只消费 `miniprogram/src/stores/*` 暴露的类型。

### 错误 4：每个消费方各自解析同一份 payload

**坏**：多处消费方各自把后端选项 `{ key, content }` 猜成前端的 `{ key, text }`：

```typescript
// 每个消费方都维护一份自己的“字段猜测”
const text =
  (option as { content?: string }).content ??
  (option as { text?: string }).text;
```

这看起来只是两行局部代码，但每个消费方都拥有了 payload 契约的一份私有定义；
下一次字段调整只会改到其中一处，其余静默读到 `undefined`。

**好**：在 adapter 边界解码一次，然后导出带类型的投影：

```typescript
import { adaptQuestionItem } from '../../api/adapters/question';

const question = adaptQuestionItem(raw);
```

`miniprogram/src/api/adapters/question.ts` 是 `{ key, content }` → `{ key, text }` 的
**唯一**归一化入口；其他消费方必须复用它，而不是自行断言字段。

**规则**：同一份未类型化的跨层 payload，如果被 2 处以上读取，就先抽出共享的
type guard / normalizer / adapter，再添加第 3 个读取方。契约的归属地是数据的所有者
（后端 schema ↔ 前端 adapter），展示代码可以格式化字段，但不得重新定义契约。

### 错误 5：字段名漂移（本项目高发）

后端响应模型的字段名与前端类型/绑定发生漂移时，前端会静默渲染 `undefined`，
而两侧测试各自造 fixture，可能**同时通过**。

典型漂移：

- 列表字段 `items` vs `questions`；
- 选项文本 `content`（后端）vs `text`（前端）；
- 薄弱点 `weak_knowledge_points` vs `weak_points`。

因此每次新增/修改响应模型，都必须把后端字段名与前端
`miniprogram/src/types/*` 逐一比对。相关后端契约见
`.trellis/spec/backend/quality-guidelines.md` 的 scenario
「Backend↔Frontend Response Field-Name Contract Pinning」。

### 错误 6：派生状态自造第二游标

**坏**：派生状态不复用源标识（`id` / `version_id` / `seq`），另起一套游标，
导致回放与实时更新对不上。

**好**：派生状态始终指回源标识。例如资料状态以
`MaterialVersion.id` / `material.current_version_id` 为准，而不是前端自造序号。

---

## 跨层功能检查清单

实现前：

- [ ] 已画出完整数据流，标出每一跳的格式。
- [ ] 已识别全部层边界，并填入边界表。
- [ ] 已定义每条边界的输入/输出格式。
- [ ] 已决定校验发生在哪一层（通常是后端 schema + 路由参数清洗）。

实现后：

- [ ] 用边界用例验证（`null`、空数组、非法状态、超长文本）。
- [ ] 验证每条边界的错误处理（后端异常 → HTTP 状态码 → 前端提示）。
- [ ] 检查数据能完整往返（round-trip 不丢字段）。
- [ ] **逐一比对字段名**：把 `backend/app/schemas/*` 的响应模型与
      `miniprogram/src/types/index.ts`（`Wire*` 类型）及每个前端绑定对齐；
      名称漂移会静默渲染 `undefined`，且两侧测试可能同时通过。
      见 `.trellis/spec/backend/quality-guidelines.md` 的
      「Backend↔Frontend Response Field-Name Contract Pinning」。
- [ ] **核对字段存在性而非只有字段名**：契约 fixture 必须按**具体端点**的响应模型取材，
      不得跨端点搬运字段，更不得手工补一个服务端从不返回的字段——那样断言在生产恒不成立、
      测试却恒绿（假通过）。同一实体不同响应模型的字段可以不同：题目响应只有 `analysis`
      **没有** `explanation`，而练习快照 `QuestionSnapshotDTO` 两者都有。见「Contract Fixture Fidelity」。
- [ ] 检查消费方复用了共享的 adapter / 归一化投影，而不是在本地断言 payload 字段。
- [ ] 检查派生状态指回源标识（`id` / `version_id`），而不是自造第二游标。
- [ ] 长耗时任务的状态机取值，后端与前端保持一致（例如
      `parse_status`、练习交卷 `status` 的终态集合）。
- [ ] **需要"只派发一次"的动作，其状态跃迁走数据库条件更新而不是先读后写**：
      解析派发、判题重试这类「用户命令 → 改状态 → 入队」的路径，若用「先读状态、再判断、
      再写」，两个并发请求会凭同一次陈旧读双双通过校验、重复入队或重复执行。
      见 `MaterialRepository.try_transition_version_status` 与
      `PracticeRepository.try_transition_status`。
- [ ] **等待任务完成的前端轮询要问「谁写终态」**：若后台任务失败后没人回写业务状态，
      记录会永久停在"进行中"且用户无提示无恢复入口。派发链路必须有终态失败回写与主动重试入口。

---

## 何时编写端到端流程文档

出现以下情况时，为跨层链路单独写流程文档：

- 功能横跨 3 层以上（例如「上传 → 解析 → 出题 → 练习 → 报告」）。
- 数据格式复杂（嵌套结构、多状态聚合）。
- 该功能此前已经出过 bug。

流程文档至少写明：数据流图、每条边界的契约、错误矩阵、以及可 grep 的代码锚点。

---

**核心原则**：30 分钟把边界想清楚，省下 3 小时排查跨层 bug。
