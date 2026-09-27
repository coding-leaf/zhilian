# 执行计划：AUTH 切片 P0+P1 修复

## 前置

- 任务：`09-27-fix-auth-p0p1`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 依赖：无前置子任务。权威契约见 `design.md` §2。
- 证据：归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-AUTH.md`。

## 执行清单（有序）

### Step 1 — 建立失败回归（红）
- [ ] 1.1 后端：改 `tests/unit/core/test_security.py` 密钥用例为 Settings 契约；新增「仅 ZHILIAN_SECRET_KEY 生效」与「生产默认密钥 fail-fast」断言。
- [ ] 1.2 后端：新增登录「不传 nickname 时昵称保留」断言。
- [ ] 1.3 前端：新增「匿名端点 401 → 抛真实错误、不重定向、不清 token」断言。
- [ ] 1.4 运行后端/前端测试，确认新增断言**失败**（红）。

### Step 2 — AUTH-001 实现
- [ ] 2.1 `core/security.py`：`get_secret_key(*, secret_key=None)` 经 `get_settings().secret_key`；移除裸 `SECRET_KEY` 路径；清理重复默认密钥常量。
- [ ] 2.2 生产 fail-fast 校验接入启动路径（`main.py` lifespan 或 `container.py`）。
- [ ] 2.3 后端测试转绿。

### Step 3 — AUTH-003 实现（前端，先修主流程阻断）
- [ ] 3.1 `utils/request.ts`：匿名端点（`skipAuth`）401/20001 不走 `handle401Error`，直接抛真实 `AppError`；不重定向、不清 token。
- [ ] 3.2 前端测试转绿；确认非匿名 401 静默刷新回归不破。

### Step 4 — AUTH-002 实现
- [ ] 4.1 `pages/auth/login.vue`：`loginByWechat({ code })` 不再传 `nickname`/`avatar_url`。
- [ ] 4.2 后端 `services/auth.py`：画像更新仅非空触发，空值不覆盖既有昵称。
- [ ] 4.3 相关测试转绿。

### Step 5 — 全门禁
- [ ] 5.1 后端：`uv run ruff format --check .` + `ruff check .` + `mypy app` + `lint-imports` + `pytest`。
- [ ] 5.2 前端：`pnpm run lint` + `pnpm run type-check` + `pnpm run test:unit`。
- [ ] 5.3 逐条关闭 BUG-AUTH-001/002/003。

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests
# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- Gate A：4 条回归断言先红后绿。
- Gate B：后端五项 + 前端三项全绿；派发 `trellis-check` 复核鉴权语义与规范。

## 回滚点

- 密钥改动集中，可回退；若部署实际用裸 `SECRET_KEY` 须先确认迁移。
- 前端 401 分支为单点条件扩展。
