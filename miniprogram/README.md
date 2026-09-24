# 智练小程序客户端 (ZhiLian Miniprogram)

基于 **uni-app (Vue 3 + Vite 5 + TypeScript) + Wot Design Uni + Pinia** 构建的微信小程序客户端。

---

## 1. 核心质量门禁与排错命令 (Quality Gates & Diagnostics)

开发与提测过程中，所有前端改动必须在终端完整通过以下门禁（退出码为 0）：

```bash
# 1. 静态代码规范与行数扫描 (强制行宽 100、单组件 <= 300 行)
pnpm run lint

# 2. 深度静态类型与模板属性检查 (基于 vue-tsc，核心排错事实源)
pnpm run type-check

# 3. 前端自动化单元测试套件 (基于 Vitest，包含拦截器、Store 与白名单测试)
pnpm run test:unit

# 4. 全量编译构建 (验证产物完整性与打包无语法错误)
pnpm run build:mp-weixin
```

### AI Agent 排错与诊断指南 (Diagnostics for AI)
- **类型与语法排错**：运行 `pnpm run type-check`。终端会输出精确的 `文件路径:行号:列号 - error TSxxxx: 错误描述`。AI 必须以此为唯一事实源，直接根据行号定位并修复类型、未声明变量或未匹配契约。
- **规范与行数排错**：运行 `pnpm run lint`。若报告 `max-lines exceeded`，必须就地将单组件拆分为同名目录下的子组件。
- **本地开发预览**：运行 `pnpm run dev:mp-weixin`，在微信开发者工具中导入 `dist/dev/mp-weixin`。

---

## 2. 架构红线与编码约束

1. **单文件代码行数**：所有 `.vue`、`.ts` 文件必须 $\le 300$ 行；
2. **Pinia 4-Store 严格收敛**：
   - `useUserStore`：用户画像与登录态；
   - `useMaterialStore`：资料元数据与版本；
   - `usePracticeStore`：做题线性队列与作答草稿；
   - `useReportStore`：诊断报告与掌握度数据；
   - **铁律**：Store 内部严禁直接发网络请求，请求统一由 `src/api/` 承载。
3. **本地 Storage 存储白名单**：
   - 仅限 3 类 Key：`auth_tokens`、`practice_drafts`、`user_settings`；
   - 严禁将资料全文或题目全文存入 Storage。
4. **视觉与文案规范**：
   - 全局零表情包（严禁 Unicode Emoji）；
   - 主色 `#2563EB`、背景底色 `#F8FAFC`、四档掌握度颜色（精通紫 `#7C3AED`、良好绿 `#059669`、需巩固琥珀 `#B45309`、未学灰 `#64748B`）。
