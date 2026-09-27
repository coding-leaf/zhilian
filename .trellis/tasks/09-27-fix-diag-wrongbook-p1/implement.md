# 执行计划：DIAG 错题本 P1 修复

## 前置

- 任务：`09-27-fix-diag-wrongbook-p1`（父：`09-27-fullstack-bug-audit-and-fix`）。
- 权威契约见 `design.md` §2；证据见归档 `archive/2026-09/09-27-read-only-bug-audit/research/slice-DIAG.md`。

## 执行清单（有序）

### Step 1 — 失败回归（红）
- [ ] 1.1 仓库：`count_wrong_records` 过滤计数（含 is_mastered/knowledge_point_id）——先写断言/测试（当前方法不存在 → 红）。
- [ ] 1.2 服务/路由：`list_wrong_records` 返回真实 total（> 页大小）——断言 total 为全量而非 `len(items)`。
- [ ] 1.3 路由：`POST /wrong-records/{id}/master` body `{is_mastered:false}` → 响应 `is_mastered=false` 且 `mastered_at=null`；无 body → true。
- [ ] 1.4 Schema：`WrongRecordItemResponse.model_validate(ORM last_wrong_answer="C")` → `user_answer == "C"`。
- [ ] 1.5 练习：`source_type='wrong_record'` + `material_id=None` 创建成功（200）。
- [ ] 1.6 运行测试确认新增断言红。

### Step 2 — DIAG-003 真实总数
- [ ] 2.1 仓库 `count_wrong_records`。
- [ ] 2.2 服务 `list_wrong_records -> tuple[list, int]`（material 分支 total=len(filtered)）。
- [ ] 2.3 路由解包 total（兼容旧 list / WrongRecordListResponse）。
- [ ] 2.4 更新受影响服务/路由测试。

### Step 3 — DIAG-004 攻克切换
- [ ] 3.1 `MarkWrongRecordMasteredRequest`（可选 is_mastered）。
- [ ] 3.2 路由可选 body → target（缺省 True）。
- [ ] 3.3 服务/仓库 `is_mastered` 入参（False → mastered_at=None）；message 随状态。
- [ ] 3.4 测试转绿。

### Step 4 — DIAG-005 作答下发
- [ ] 4.1 `WrongRecordItemResponse.user_answer` + ORM 抽取映射 `last_wrong_answer`。
- [ ] 4.2 测试转绿。

### Step 5 — DIAG-006 继续练习
- [ ] 5.1 后端：source_type 白名单 + 枚举 + `material_id` 可选 + 服务解析 material。
- [ ] 5.2 前端：`wrong-book/index.vue` 无可用知识点时禁用继续练习。
- [ ] 5.3 测试转绿；旧路径零回归。

### Step 6 — 全门禁
- [ ] 6.1 后端：`uv run ruff format --check .` + `ruff check .` + `mypy app` + `lint-imports` + `pytest`。
- [ ] 6.2 前端：`pnpm run lint` + `pnpm run type-check` + `pnpm run test:unit`。
- [ ] 6.3 逐条关闭 BUG-DIAG-003/004/005/006。

## 验证命令

```bash
# 后端（workdir=backend）
uv run ruff format --check . && uv run ruff check . && uv run mypy app && uv run lint-imports && uv run pytest tests
# 前端（workdir=miniprogram）
pnpm run lint && pnpm run type-check && pnpm run test:unit
```

## 评审门禁

- Gate A：5 组回归断言先红后绿。
- Gate B：后端五项 + 前端三项全绿；派发 `trellis-check` 复核契约、兼容性与越权隔离。

## 回滚点

- `count_wrong_records`/tuple 返回、可选 material_id、source_type 扩展均可单独复位。
- `master` 缺省 True 保持旧行为。
