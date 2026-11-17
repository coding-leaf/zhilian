# 题库区块进入页面不自动加载（P1-8）

## Goal

让「学情」页的「我的题目」在**进入页面时自动加载**，而不是恒显示「题库还是空的」；
并补上一条**能拦住此类接线缺陷**的回归测试——现有 16 个用例测的是组合式函数，
缺陷在组件与组合式函数之间，它们永远绿。

对应 `docs/后续待解决问题.md` 的 **P1-8**。

## 已查证的根因（非假设）

| 证据 | 内容 |
| --- | --- |
| 组件源码 | `miniprogram/src/pages/review/components/QuestionBankSection.vue` 中 `loadBatches` 只有 3 处 `@tap` 引用（刷新 / 两处重试）与 1 处解构，**无任何程序化调用点** |
| 组件源码 | 该组件**无任何生命周期钩子**（`onMounted` / `onShow` / `onActivated` / `watch` 全无） |
| 数据侧 | 接口 `/questions/batches` 实测 `HTTP 200`，返回 **2 个批次**（8 题与 13 题），`total=2` |
| 界面侧 | 该区块渲染的是**空态**（`batches.length === 0`）而非失败态（`loadError`），与「请求根本没发出」一致 |
| 测试侧 | `miniprogram/tests/questionBank.spec.ts` 16 个用例测的是 `useQuestionBank` 组合式函数；**全仓库无任何测试挂载过 Vue 组件** |

危害：空态文案写「题库还是空的。到资料详情页发起『智能出题』」，
已出过题的用户会被引导**再去出一次**。

## 既有模式（新代码须与之一致）

`miniprogram/src/pages/review/index.vue` 已确立的取数模式：

```ts
onMounted(async () => { await Promise.all([loadWrongs(), loadPractices()]) })
onPullDownRefresh(async () => { await Promise.all([loadWrongs(), loadPractices()]) })
```

即：**进入页面与下拉刷新走同一组 loader**，每个区块各有「刷新」按钮。
题库区块是三个区块里唯一缺席这个模式的。

## 需求

- R1 进入页面时题库区块自动加载（`onMounted`）。
- R2 下拉刷新同时刷新题库区块——否则修好 R1 后仍留着同一类缺口：
  用户下拉时错题与练习刷新了、题库没有。
- R3 新增**挂载组件**的接线测试，并做**变异验证**（去掉自动加载后该用例必须失败）。

## Acceptance Criteria

- [ ] AC-1 **端到端**：在开发者工具中进入「学情」页，「我的题目」显示**真实批次**
      （≥1 个批次、可见题数），而不是空态。以真机/开发者工具实测截图为证，**不以单测为准**。
- [ ] AC-2 下拉刷新后题库区块仍旧有数据（不因刷新而清空或报错）。
- [ ] AC-3 新增测试挂载 `QuestionBankSection.vue`，断言**挂载即请求** `/questions/batches`。
- [ ] AC-4 **变异验证**：临时移除自动加载后，AC-3 的用例**必须失败**；恢复后通过。
- [ ] AC-5 既有 16 个 `questionBank.spec.ts` 用例零回归。
- [ ] AC-6 `task verify` 退出码 0。
- [ ] AC-7 不引入新的测试依赖（`@vue/test-utils` 已在 devDependencies 中）。

## Out of Scope

- **不改空态文案**。文案在数据能加载后就不再误导；改写它属产品措辞，不混在本次修复里。
- 不动批次的展开、勾选、跨批次再练等既有行为。
- 不动 Maven 相关数据或后端。

## Notes

- 本条与 `docs/开发过程文档.md` 5.3 节是同一类错误：**被测单元正确 ≠ 接线正确**。
  故 AC-3 刻意选择「挂载组件」这一层——那是唯一能拦住接线的层次。

---

## 验收记录（2026-09-29）

| AC | 结果 | 取证 |
| --- | --- | --- |
| AC-1 端到端 | **通过** | 开发者工具实测截图：`05-question-bank.png` 显示两个真实批次（共 8 题 / 共 13 题），与接口返回一致，空态消失 |
| AC-2 下拉刷新 | 通过（代码路径） | `onPullDownRefresh` 已带上 `bankSection.value?.loadBatches()`；与既有两区块同批 |
| AC-3 挂载即请求的用例 | 通过 | 新增 `tests/questionBankSection.spec.ts`，挂载组件并断言请求 `/questions/batches` |
| AC-4 变异验证 | **通过** | 移除 `onMounted(loadBatches)` → 用例失败（`实际请求：[]`）；恢复 → 通过；文件无残留 |
| AC-5 既有用例零回归 | 通过 | 组合式函数 16 个用例仍全绿 |
| AC-6 `task verify` | 通过 | 退出码 0：后端 1416 用例 / mypy 135 文件 / 前端 126 用例 |
| AC-7 不新增依赖 | 通过 | `@vue/test-utils` 已在 devDependencies |

### 取证过程中的两个坑（已写入交付文档）

1. **微信小程序的 `SelectorQuery` 不跨自定义组件边界**。页面级 `page.$$('.bank-section')`
   恒返回 0——不是页面没渲染，是查不到。曾据此误判「修复无效」。组件内部的元素**只能靠截图**
   或 `getCurrentPages()` + `selectComponent`（且要求页面模板上给了 class/id）来断言。
2. **开发者工具不会自动加载重新构建的产物**。`reLaunch` 只重建页面，不重新加载 JS bundle；
   必须 `cli quit` 后重新 `cli auto`，否则模拟器一直跑旧代码——这也会让人误判修复无效。
3. **截图必须在数据加载完成后**。等 12 秒仍可能截到渲染中途，表现为「区块是空白卡片」，
   看起来像缺陷。最终以 15 秒 + 人工确认内容为准。

### 关于「批次行一开始没显示」

诊断期一度以为批次行未渲染（只看到动作卡）。加临时标记后确证 `batches.length === 2`，
批次行实际都在——之前是**截图时机**问题，不是渲染问题。标记已撤除，产物无残留。
