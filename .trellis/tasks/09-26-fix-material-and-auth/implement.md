# Implementation Plan: 资料闭环、列表展示与鉴权修复

## 实施清单 (Action Checklist)

### 步骤 1: 健全用户 Store 鉴权状态水合与初始化
- [ ] 修改 `miniprogram/src/stores/userStore.ts`:
  - 增加 `hydrateProfile()` 动作，支持从后端 `/api/v1/users/me` 恢复用户信息；
  - 导出并完善状态机逻辑。
- [ ] 修改 `miniprogram/src/App.vue`:
  - 在 `onLaunch` 和 `onShow` 时触发 `userStore.hydrateProfile()`。
- [ ] 修改 `miniprogram/src/pages/auth/login.vue`:
  - 登录换取 Token 成功后立即触发水合，确保用户昵称与 ID 一致。

### 步骤 2: 修复资料列表展示、分页与跨页保活
- [ ] 改造 `miniprogram/src/subpackages/material/pages/list/index.vue`:
  - 将列表展示与全局 Store 分离，避免列表页重置冲刷掉全局资料列表；
  - 添加 `onShow` 自动拉取更新，解决进入列表白屏及返回资料丢失问题；
  - 修正 Tab 状态筛选过滤传参（全部不传 status，解析中包含 pending/parsing）；
  - 挂载轮询刷新：若当前列表存在 `parsing` / `pending` 状态项目，自动调度轻量退避轮询，解析成功后自动更新列表项。

### 步骤 3: 首页返回保活与多端协同优化
- [ ] 修改 `miniprogram/src/pages/index/index.vue`:
  - 在 `onShow` 阶段适时恢复/更新首页概览（`loadDashboardData(false)`），确保从子页面返回时掌握度与最近资料始终存在。

### 步骤 4: 自动化测试与质量门禁验证
- [ ] 补充/更新前端单测：
  - `miniprogram/tests/unit/stores/userStore.spec.ts`
  - `miniprogram/tests/unit/pages/materialList.spec.ts`
- [ ] 执行全套自动化质检：
  - 前端：`pnpm run lint` && `pnpm run type-check` && `pnpm run test:unit`
  - 后端：`uv run ruff check .` && `uv run mypy app` && `uv run pytest tests`
