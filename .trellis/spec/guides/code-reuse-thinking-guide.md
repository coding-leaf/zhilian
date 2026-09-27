# 代码复用思维指南

> **用途**：动手写新代码之前先停一下——这段逻辑是不是已经存在？

---

## 问题所在

**重复代码是「不一致 bug」的头号来源。**

当你复制粘贴或重写既有逻辑时：

- bug 修复不会传播到副本；
- 行为随时间分叉；
- 代码库越来越难理解。

在本仓库，重复尤其容易出现在这几处：

- `miniprogram/src/utils/*`（`request.ts`、`storage.ts`、`error.ts` 等通用工具）；
- `miniprogram/src/**/composables/*`（如
  `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts`）;
- `miniprogram/src/stores/*`（`materialStore.ts`、`practiceStore.ts` 等）；
- `backend/app/core/algorithms/*`（`search.py`、`practice.py`、`grading.py` 等纯函数）。

---

## 编写新代码之前

### 第 1 步：先搜索

```bash
# 搜索相似函数名 / 符号（客户端已用 git，可直接搜索仓库）
git grep -n "functionName"
git grep -n "keyword"

# 也可以用带类型的检索工具（若环境提供）
# fast-glob / editor 全局搜索 "useMaterialPolling"
```

### 第 2 步：问自己这些问题

| 问题 | 若是…… |
| --- | --- |
| 是否已存在相似函数？ | 复用它，或在其上扩展 |
| 这个模式别处是否用过？ | 沿用既有模式 |
| 能否抽成共享工具？ | 放到正确的位置（`utils/`、`composables/`、`core/algorithms/`） |
| 我是不是在从另一个文件抄代码？ | **停下**——抽到共享处 |

---

## 常见重复模式

### 模式 1：复制粘贴函数

**坏**：把同一个文件大小/类型校验复制到另一个页面。

**好**：抽到 `miniprogram/src/utils/file.ts`，各处 import。

### 模式 2：相似组件

**坏**：新建一个与既有组件 80% 相似的组件。

**好**：用 props / 变体扩展既有组件（见 `docs/DESIGN.md` 的组件参数约定）。

### 模式 3：重复常量

**坏**：同一个常量（如分页大小、状态字符串）在多个文件各写一遍。

**好**：单一事实源，统一 import。前端类型放 `miniprogram/src/types/*`，
后端枚举放 `backend/app/models/*` 或 `backend/app/core/*`。

### 模式 4：重复的 payload 字段提取

**坏**：多个消费方各自把后端选项 `{ key, content }` 猜成 `{ key, text }`：

```typescript
// 每个消费方都维护自己的一份契约解释
const text =
  (option as { content?: string }).content ??
  (option as { text?: string }).text;
```

这即使只有两行，也已经是**重复的契约逻辑**：每个消费方都拥有了自己的
「什么算合法 payload」的定义。

**好**：把解码/type guard/投影放在数据所有者的旁边，其他地方复用：

```typescript
import { adaptQuestionItem } from '../../api/adapters/question';

const question = adaptQuestionItem(raw);
```

**规则**：同一份未类型化的 payload 字段被 2 处以上读取时，先抽出共享的
type guard / normalizer / adapter，再添加第 3 个读取方。本仓库的归一化边界在
`miniprogram/src/api/adapters/*`。

---

## 何时抽象

**该抽象**：

- 同一段代码出现 3 次及以上；
- 逻辑足够复杂、值得有单测（例如 `backend/app/core/algorithms/*`）；
- 可能有多人需要它。

**不该抽象**：

- 只用一次；
- 平凡的一行代码；
- 抽象本身比重复更复杂。

---

## 批量修改之后

当你对多个文件做了类似修改：

1. **复查**：是否覆盖了所有实例？
2. **搜索**：用 `git grep` 找出遗漏。
3. **考虑**：是否应该抽象？

### 用穷尽式的 reducer 结构

当状态由类 action 的取值派生（`action`、`kind`、`status`、`phase`）时，
优先用**一个 `switch` reducer** 掌管整张状态迁移表，而不是散落的 `if/else`。

```typescript
// 坏：每个 action 各写各的状态更新，难以审计
if (action === 'opened') { ... }
else if (action === 'comment') { ... }
else if (action === 'status') { ... }

// 好：一个 reducer 拥有整张迁移表
switch (action) {
  case 'opened':
    ...
    return;
  case 'comment':
    ...
    return;
  case 'status':
    ...
    return;
}
```

当状态是事实源（例如资料解析状态、练习会话状态）时，reducer 就是文档化的迁移模型；
展示代码和其他分支不应复制这套模型的一部分。

---

## 提交前检查清单

- [ ] 已搜索过相似的既有代码。
- [ ] 没有应当共享却被复制粘贴的逻辑。
- [ ] 没有在共享 adapter / normalizer 之外重复断言 payload 字段。
- [ ] 常量只有一处定义。
- [ ] 相似模式遵循同一结构。
- [ ] reducer / 状态迁移只存在于一个 reducer 或命令分发器中。

---

## 陷阱：Python if/elif/else 缺少穷尽检查

**问题**：Python 的 if/elif/else 没有编译期穷尽检查。当给一个 `Literal` 类型
新增取值时，既有的 if/elif/else 会静默落入 `else`，返回错误的默认值。

**症状**：新增的状态/类型只「工作了一半」——部分分支返回了默认值而非新值，且
不报错。

**示例**：

```python
# 坏：新增 "retake_required" 后落入 else，静默返回空/错误筛选
def resolve_status_filter(status: str) -> list[str]:
    if status == "parsing":
        return ["pending", "parsing"]
    elif status == "ready":
        return ["ready"]
    else:
        return []   # 新值被悄无声息地当成“不过滤”/“空列表”

# 好：为每个取值显式分支，新值必须被正视
def resolve_status_filter(status: str) -> list[str]:
    if status == "parsing":
        return ["pending", "parsing"]
    elif status == "ready":
        return ["ready"]
    elif status == "retake_required":
        return []   # 显式表达“诚实地返回空”，而非默认落空
    else:
        return [status]
```

**预防**：给 Python `Literal` 类型新增取值时，搜索**所有**以该类型分支的
if/elif/else 链并补上显式分支；不要把新取值的正确行为寄托在 `else` 上。

---

## 陷阱：两套机制产出同一份结果时的漂移

**问题**：当两条不同的代码路径必须产出同一份结果时（例如 HTTP API 与
`python -m app.cli` 都要驱动同一条业务链路），结构性变更只会经由自动/共享的那条
路径传播，手工维护的那条会静默漂移。

**症状**：HTTP 调用一切正常，但 CLI（或反过来）走错分支、漏掉步骤，或产生不一致结果。

**预防**：

- **首选**：消除不对称——让两条路径都调用同一处共享逻辑
  （例如都经 `AppContainer` 装配服务、都走同一 Service 方法 / 同一解析流水线）。
- **若不对称无法避免**：加回归测试，断言两条路径的输出一致。
- 迁移目录结构或重命名时，搜索**所有**引用旧结构的代码路径。

**本仓库真实案例**：后端 CLI（`python -m app.cli`）与 HTTP API 必须复用同一套
Service 与 `parse_material_pipeline`，禁止 CLI 绕开业务逻辑直连仓储——否则同一业务
在两条入口下会产生不同的状态与结果。

---

## 核心原则

30 分钟先把复用/边界想清楚，省下 3 小时排查不一致 bug。
