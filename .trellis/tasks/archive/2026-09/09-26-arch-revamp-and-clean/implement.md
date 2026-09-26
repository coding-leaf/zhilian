# Implementation Plan: 架构全面重构与代码肃清优化 (implement.md)

## Ordered Checklist

- [ ] **Step 1: 工作区死代码与废弃临时文件清理**
  - 检查工程根目录，核实无残留临时测试文件或缓存。
  - 清查未跟踪或未被 gitignore 拦截的生成物。

- [ ] **Step 2: 前端自适应退避轮询与体验优化**
  - 改造 `miniprogram/src/subpackages/material/composables/useMaterialPolling.ts`：引入动态退避与最大时长保护，降低高频轮询消耗。
  - 更新对应的前端单元测试：`miniprogram/tests/unit/composables/useMaterialPolling.spec.ts`。

- [ ] **Step 3: 后端核心领域服务与向量检索性能精简**
  - 检查 `backend/app/integrations/search/hybrid.py` 与 `MaterialService`，精简多余的数据拼装与全表扫描隐患。
  - 保持现有契约完整，执行回归测试。

- [ ] **Step 4: 前端状态流与体验交互收敛**
  - 优化 `MaterialCard`、`detail/index.vue` 的状态渲染与轻量级反馈。
  - 确保页面重新渲染不产生多余计算开销。

- [ ] **Step 5: 全量门禁基线复核与规范固化**
  - 运行后端全量质检门禁：
    ```bash
    cd backend
    uv run ruff format --check .
    uv run ruff check .
    uv run mypy app
    uv run lint-imports
    uv run pytest tests
    ```
  - 运行前端全量质检门禁：
    ```bash
    cd miniprogram
    pnpm run lint
    pnpm run type-check
    pnpm run test:unit
    ```

## Rollback Points
- 各步骤依托 Git 原子提交与测试覆盖，任何一步测试未通过均可立即就地回退。
