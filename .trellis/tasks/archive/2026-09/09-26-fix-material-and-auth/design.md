# Design: 资料生命周期、列表状态管理与鉴权链路设计

## 1. 架构定位与边界 (Architectural Boundaries)
本设计面向小程序前端核心体验层，涵盖：
1. **状态层 (Stores)**:
   - `useUserStore`: 增强鉴权状态机，增加 `hydrateProfile()` 异步动作；
   - `useMaterialStore`: 明确职责分工，分离 `recentMaterials`（首页概览用）与 `pagedMaterials`（列表页分页/筛选用），或保持标准缓存机制并由页面驱动生命周期。
2. **页面交互层 (Pages & Composables)**:
   - `subpackages/material/pages/list/index.vue`: 引入 `onShow` 联动、Tab 过滤映射修正、挂载列表级轮询保活；
   - `pages/index/index.vue`: 增强 `onShow` 刷新机制与未登录保护；
   - `pages/auth/login.vue`: 登录成功后直接水合服务端真实 Profile。

---

## 2. 状态与数据流契约 (State & Data Flow)

### 2.1 用户鉴权状态流水线 (Auth Hydration Pipeline)
```
[App.vue onLaunch / onShow]
           │
           ▼
 userStore.initFromStorage() ──► 恢复 auth_tokens
           │
     (有 token?)
     ├── 是 ──► 调用 fetchUserProfile() ──► userStore.setUserProfile(profile)
     │                                           │ (401失效时)
     │                                           ▼
     │                                      清除tokens，保持未登录态
     └── 否 ──► 保持未登录态
```

### 2.2 资料列表与首页隔离流动契约 (Material Store Separation)
为了避免“列表页更新 20 条把首页冲掉，或者首页加载 5 条把列表页切掉”的副作用：
- 在 `materialStore` 中保持 `materials` 作为全局统一缓存；
- 列表页 `list/index.vue` 维护自己的局部展示列表 `listData = ref<MaterialItem[]>([])` 与局部 `total`，更新时同时通过 `materialStore.addMaterial(item)` 同步给全局缓存，防止单页重置导致跨页数据丢失；
- 页面返回首页时，首页的 `onShow` 会检查或静默拉取首页专属的最近 5 条概览，并与 `activePractice` 正确合成，确保数据绝对不丢失。

### 2.3 状态筛选映射表 (Status Filter Mapping)
| Tab Key | Tab Label | 前端传参 status | 后端匹配 |
| :--- | :--- | :--- | :--- |
| `all` | 全部 | `undefined` (不传) | 返回所有非删除资料 |
| `parsing` | 解析中 | `parsing` | 包含 `pending` 和 `parsing` |
| `retake` | 待重拍 | `retake_required` | 匹配 `retake_required` |
| `ready` | 已完成 | `ready` | 包含 `ready` 和 `completed` |

---

## 3. 容错与回退机制 (Rollout & Resilience)
1. **网络超时容错**：在网络不畅或 401 刷新时，静默捕获异常并给用户友好提示，绝不因一次请求失败清空已有缓存数组。
2. **单测安全网覆盖**：
   - 增加 `miniprogram/tests/unit/stores/userStore.spec.ts` 鉴权水合测试用例；
   - 补充 `miniprogram/tests/unit/pages/materialList.spec.ts` 列表页状态持久化测试。
