# 前端完全重构与J1端到端切片闭环 (Design & Architecture)

## 1. 架构总览 (System Architecture)

```
┌────────────────────────────────────────────────────────┐
│                   Uni-app (Vue 3 + TS + Vite)          │
├────────────────────────────────────────────────────────┤
│ Presentation Layer (温润学术/纸质阅读风 + UnoCSS Tokens) │
│ - Pages: 3-Tab Main (index, review, profile)           │
│ - Subpackages: material, practice, report              │
│ - Components: Wot Design Uni + Custom Domain Cards     │
├────────────────────────────────────────────────────────┤
│ State & Machine Layer (Pinia + FSM + LocalStorage)     │
│ - useAuthStore: 微信登录鉴权与 Token 管理               │
│ - useMaterialStore: 资料上传、状态轮询与出题配置       │
│ - usePracticeMachine: 作答草稿持久化、中断恢复与交卷    │
│ - useDiagnosisStore: 诊断报告生成轮询与学情详情        │
├────────────────────────────────────────────────────────┤
│ Network & Service Layer (Type-Safe Uni Request)        │
│ - request: 拦截器、Token 刷新、网络重试、统一错误码处理 │
│ - api/v1: auth, material, question, practice, report   │
└────────────────────────────────────────────────────────┘
```

## 2. 视觉设计系统与 Design Tokens (Warm Academic)

### 色彩系统 (Color Palette)
- **纸张温润底色 (Page Canvas)**: `#F7F5F0` / `#FAF8F5`
- **卡片/容器白 (Surface)**: `#FFFFFF` (配合轻微温暖阴影 `0 2px 8px rgba(44, 39, 32, 0.04)` 与柔和边框 `#E7E5E4`)
- **正文墨黑 (Ink Black)**: `#1C1917` (Stone-900)
- **辅助说明 (Muted Slate)**: `#78716C` (Stone-500)
- **主交互/书卷靛 (Academic Indigo)**: `#2A4365` / `#1E3A8A`
- **强调/暖杏黄 (Warm Amber)**: `#D97706`
- **判题正确 (Correct Green)**: `#15803D`
- **判题错误 (Incorrect Crimson)**: `#B91C1C`

### 字体与版式 (Typography)
- 正文行高统一 1.6~1.8，题干与讲义段落适度留白；
- 标题采用加粗与紧凑字距，营造典雅书籍排印质感。

## 3. 页面路由与分包拓扑 (Routing & Package Topology)

```json
{
  "pages": [
    { "path": "pages/index/index", "style": { "navigationBarTitleText": "智练" } },
    { "path": "pages/review/index", "style": { "navigationBarTitleText": "学情" } },
    { "path": "pages/profile/index", "style": { "navigationBarTitleText": "我的" } },
    { "path": "pages/auth/login", "style": { "navigationBarTitleText": "快捷登录" } }
  ],
  "subPackages": [
    {
      "root": "subpackages/material",
      "pages": [
        { "path": "pages/upload/index", "style": { "navigationBarTitleText": "上传讲义资料" } },
        { "path": "pages/course/index", "style": { "navigationBarTitleText": "课程与资料详情" } },
        { "path": "pages/questions/index", "style": { "navigationBarTitleText": "核对出题结果" } }
      ]
    },
    {
      "root": "subpackages/practice",
      "pages": [
        { "path": "pages/session/index", "style": { "navigationBarTitleText": "练习作答", "disableScroll": true } }
      ]
    },
    {
      "root": "subpackages/report",
      "pages": [
        { "path": "pages/detail/index", "style": { "navigationBarTitleText": "学情诊断报告" } }
      ]
    }
  ]
}
```

## 4. 关键领域状态机设计 (FSMs)

### J1 核心练习会话状态机 (`usePracticeMachine`)
- **States**:
  - `IDLE`: 未进入练习
  - `LOADING`: 获取练习会话元数据与题目详情
  - `ACTIVE`: 用户交互作答中，每个选项切换自动执行 `saveDraftDebounced` (本地存储 + 后台同步 `PUT /answers`)
  - `SUBMITTING`: 提交中，展示防重复提交遮罩
  - `GENERATING_REPORT`: 触发并轮询报告生成状态 (`POST /practices/{id}/diagnosis` -> `GET /diagnosis`)
  - `COMPLETED`: 诊断生成完毕，安全跳转 `report/pages/detail/index`
  - `ERROR`: 异常状态，支持断点重试与“重新提交”

## 5. 接口契约对齐 (Backend API Contracts)
- 认证：`POST /api/v1/auth/login` (返回 `token`, `user`)
- 资料：`POST /api/v1/materials/upload`，`GET /api/v1/materials/{id}`
- 出题：`POST /api/v1/questions/generate`，`GET /api/v1/questions?material_id={id}`
- 练习：`POST /api/v1/practices`，`GET /api/v1/practices/{id}`，`PUT /api/v1/practices/{id}/answers`，`POST /api/v1/practices/{id}/submit`
- 诊断：`POST /api/v1/practices/{id}/diagnosis`，`GET /api/v1/practices/{id}/diagnosis`
