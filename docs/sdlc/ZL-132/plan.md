# Plan: 资料上传、状态轮询与分页重拍前端组件 - 实施计划

- **关联 Spec**: ZL-132
- **实施执行人 / Agent**: 专职 Builder 子代理分派实施
- **当前状态**: Approved
- **Change Tier**: Tier 2 (前端分包业务组件与交互流)

---

## 1. 变更文件清单 (Files that change)

### 1.1 新增文件 (New Files)
- `miniprogram/src/types/material.ts` (扩充上传与重拍接口 DTO 类型契约)
- `miniprogram/src/subpackages/material/utils/copywriting.ts` (面向用户的零度自然文案与重拍次数计算纯函数)
- `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts` (2s 智能轮询与自销毁定时器守护)
- `miniprogram/src/subpackages/material/components/MaterialCard.vue` (资料卡片、状态胶囊与删除交互)
- `miniprogram/src/subpackages/material/components/MaterialUpload.vue` (微信聊天/本地相册文件选择、大小格式校验与上传弹窗)
- `miniprogram/src/subpackages/material/components/RetakeDrawer.vue` (异常页高亮、剩余重拍次数展示、就地拍摄上传与熔断提示)
- `miniprogram/src/subpackages/material/pages/list/index.vue` (资料列表主页、下拉刷新、触底加载与上传触发)
- `miniprogram/src/subpackages/material/pages/detail/index.vue` (资料元数据详情、轮询监听、重拍抽屉触发与大纲入口)
- `miniprogram/tests/unit/utils/copywriting.spec.ts` (零度字典转换与纯函数单测)
- `miniprogram/tests/unit/composables/useMaterialPolling.spec.ts` (轮询器定时推进、状态切换停止与销毁清理单测)
- `miniprogram/tests/unit/components/MaterialCard.spec.ts` (资料卡片渲染与点击事件单测)
- `miniprogram/tests/unit/components/MaterialUpload.spec.ts` (上传弹窗选择来源、文件校验与接口调用单测)
- `miniprogram/tests/unit/components/RetakeDrawer.spec.ts` (重拍抽屉熔断判定、拍摄提交与文案呈现单测)
- `miniprogram/tests/unit/pages/materialList.spec.ts` (列表页加载、卡片交互与空状态单测)
- `miniprogram/tests/unit/pages/materialDetail.spec.ts` (详情页元数据、轮询集成与重拍触发单测)

### 1.2 修改文件 (Modified Files)
- `miniprogram/src/api/material.ts` (新增 `uploadMaterialFile` 与 `reshootMaterialPage` 接口封装)
- `miniprogram/src/pages.json` (配置 `subpackages/material` 分包内 `pages/list/index` 与 `pages/detail/index` 路由)
- `miniprogram/tests/unit/api/material.spec.ts` (补充上传与单页重拍接口调用的单元测试)

---

## 2. 4 支柱 Milestone 拆解与分步实施 (Order of Work)

为了确保各专职 Builder 子代理能够独立、并行且上下文隔离地完成研发，实施计划划分为 4 个高度解耦的 Milestone。

### Milestone 1: API 扩充、纯函数核与 Composable 轮询管理器 (Builder 1)
* **核心目标**:
  1. 在 `src/types/material.ts` 补充 `MaterialUploadResponse`, `MaterialReshootResponse` 契约；
  2. 在 `src/api/material.ts` 补充 `uploadMaterialFile` (支持幂等键与进度) 与 `reshootMaterialPage` 接口，并扩充 `tests/unit/api/material.spec.ts`；
  3. 实现纯函数 `src/subpackages/material/utils/copywriting.ts` (格式化 OCR 异常零度文案、剩余重拍次数计算 `Math.max(0, 3 - reshootCount)`、状态徽章映射)；
  4. 实现组合式函数 `src/subpackages/material/composables/useMaterialPolling.ts` (2000ms 定频轮询、最大 60s 超时保护、状态转为 ready/failed 自动停止、`onUnmounted` 强力清理定时器)；
  5. 编写针对纯函数与 Composable 的单元测试。
* **涉及文件**:
  - `miniprogram/src/types/material.ts`
  - `miniprogram/src/api/material.ts`
  - `miniprogram/src/subpackages/material/utils/copywriting.ts`
  - `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts`
  - `miniprogram/tests/unit/api/material.spec.ts`
  - `miniprogram/tests/unit/utils/copywriting.spec.ts`
  - `miniprogram/tests/unit/composables/useMaterialPolling.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/api/material.spec.ts tests/unit/utils/copywriting.spec.ts tests/unit/composables/useMaterialPolling.spec.ts
  ```
* **预期判据**: 接口测试与 FakeTimer 轮询测试 100% 绿灯，轮询自销毁与熔断超时逻辑无泄漏。

---

### Milestone 2: 资料卡片与上传组件 (Builder 2)
* **核心目标**:
  1. 实现 `src/subpackages/material/components/MaterialCard.vue`：
     - 展示资料标题、格式图标、创建时间、当前状态胶囊（`wd-tag`）；
     - 点击卡片触发查看详情事件，更多按钮触发删除确认与回调；
     - 严格控制在 180 行以内，零 Emoji，深蓝/冷灰配色。
  2. 实现 `src/subpackages/material/components/MaterialUpload.vue`：
     - 提供导入弹窗（`wd-popup`），支持从微信会话选择文件 (`wx.chooseMessageFile`) 或本地相册/拍照 (`uni.chooseImage`)；
     - 实施上传前严格本地校验：仅限 PDF/DOCX/PNG/JPG，文件大小不超过 20MB；
     - 自动生成 UUIDv4 幂等键 (`Idempotency-Key`)，调用 `uploadMaterialFile` 并展示上传进度环；
     - 上传成功后调用 `materialStore.addMaterial` 同步内存，派发成功事件；
     - 严格控制在 240 行以内。
  3. 编写 `MaterialCard.spec.ts` 与 `MaterialUpload.spec.ts` 单元与交互测试。
* **涉及文件**:
  - `miniprogram/src/subpackages/material/components/MaterialCard.vue`
  - `miniprogram/src/subpackages/material/components/MaterialUpload.vue`
  - `miniprogram/tests/unit/components/MaterialCard.spec.ts`
  - `miniprogram/tests/unit/components/MaterialUpload.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/components/MaterialCard.spec.ts tests/unit/components/MaterialUpload.spec.ts
  ```
* **预期判据**: 组件挂载正常、事件正确 emit、非法格式/体积被拦截提示、Mock 上传与 Store 状态同步无误。

---

### Milestone 3: 单页重拍抽屉组件 (Builder 3)
* **核心目标**:
  1. 实现 `src/subpackages/material/components/RetakeDrawer.vue`：
     - 弹出抽屉展示 OCR 质检不合格页面清单与零度自然文案（如“第 4 页文字模糊，需重新拍摄”）；
     - 展示剩余重拍次数（初始 3 次，递减计算）；
     - 提供“就地重拍”按钮，唤起相机拍照 (`uni.chooseImage` with `camera`)；
     - 调用 `reshootMaterialPage` 提交单页更新，实时反馈该页重验结果；
     - **熔断保护**：当该页重拍已达 3 次（或后端返回 40002）时，自动禁用重拍按钮，并显示“该页重拍已达 3 次上限，文字仍不达标，建议重新上传更清晰的原文件”；
     - 严格控制在 220 行以内，遵循视觉与文案规范。
  2. 编写 `RetakeDrawer.spec.ts` 单元与交互测试（重点覆盖正常重拍流、次数耗尽熔断流与异常文案渲染）。
* **涉及文件**:
  - `miniprogram/src/subpackages/material/components/RetakeDrawer.vue`
  - `miniprogram/tests/unit/components/RetakeDrawer.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm vitest run tests/unit/components/RetakeDrawer.spec.ts
  ```
* **预期判据**: 抽屉按页高亮异常、剩余次数与熔断禁用逻辑 100% 验证通过。

---

### Milestone 4: 分包页面集成与全局门禁验收 (Builder 4)
* **核心目标**:
  1. 在 `src/pages.json` 中配置分包路由：
     - `subpackages/material/pages/list/index` (资料列表主页)
     - `subpackages/material/pages/detail/index` (资料详情与解析页)
  2. 实现 `src/subpackages/material/pages/list/index.vue`：
     - 列表展示、下拉刷新 (`onPullDownRefresh`)、触底加载下一页（每页 20 条，`onReachBottom`）；
     - 集成 `MaterialCard` 列表项，提供无数据时的空状态提示与导入引导；
     - 悬浮添加按钮（FAB）唤起 `MaterialUpload`；
     - 代码控制在 250 行以内。
  3. 实现 `src/subpackages/material/pages/detail/index.vue`：
     - 展示资料元数据（格式、大小、创建时间、当前状态胶囊）；
     - 挂载 `useMaterialPolling`：当资料处于 `pending` / `parsing` 时自动启动轮询，完成/失败自动终止，离开页面自动销毁；
     - 针对不合格切片/页面提供唤起 `RetakeDrawer` 的入口；
     - 提供进入知识点大纲（跳转 ZL-133 预留路由）的快捷入口；
     - 代码控制在 280 行以内。
  4. 编写页面级单元测试 `materialList.spec.ts` 与 `materialDetail.spec.ts`。
  5. 跑通全量前端静态质量门禁与测试回归。
* **涉及文件**:
  - `miniprogram/src/pages.json`
  - `miniprogram/src/subpackages/material/pages/list/index.vue`
  - `miniprogram/src/subpackages/material/pages/detail/index.vue`
  - `miniprogram/tests/unit/pages/materialList.spec.ts`
  - `miniprogram/tests/unit/pages/materialDetail.spec.ts`
* **局部验证命令**:
  ```bash
  cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
  ```
* **预期判据**: 全量 Lint 0 警告、类型推断 100% 通过、19 个测试套件及所有新增测试 100% 绿灯。

---

## 3. 架构与工程约束对齐 (Architectural & Engineering Gates)

1. **分包与文件尺寸红线**：
   - 所有页面与组件收敛在 `miniprogram/src/subpackages/material/`；
   - 任何单 `.vue` 或 `.ts` 文件行数强制 $\le 300$ 行。
2. **零度设计与视觉规范**：
   - 零 Unicode Emoji；深蓝主交互色 (`#2563EB`)、冷灰底色 (`#F8FAFC`)；
   - 文案严格对齐 `docs/DESIGN.md`，严禁直接展示底层算法参数（如“乱码率21%”）。
3. **防御性安全与内存防护**：
   - 资料全文与切片文本严禁存入 `uni.setStorageSync` 或 `storage.ts`；
   - 轮询器必须挂载生命周期并在组件卸载时调用 `clearInterval`，杜绝后台游离请求；
   - 上传携带 `Idempotency-Key`，重拍强制校验上限 $\le 3$。

---

## 4. 全局质量门禁核验 (Global Quality Gate)

```bash
cd miniprogram && \
pnpm run lint && \
pnpm run type-check && \
pnpm run test:unit
```
- **Lint 规范检查**: ESLint + Prettier 零报错；
- **类型严格性**: vue-tsc / mypy 零隐式 any 与类型错误；
- **测试回归**: 全部测试套件均处于通过状态，断言真实有效。

---

## 5. 实施偏差记录 (Deviations Log)
- 当前无架构设计与契约偏差。

---

## 6. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过规划评审
- [x] 4 支柱 Milestone 划分清晰，职责边界正交，无重叠耦合
- [x] 变更文件清单完备，严格遵循 <= 300 行与分包约束
- **验收结论**: Accepted
- **验证人 / 日期**: TechLead (人类授权模式) / 2026-09-25 02:10
