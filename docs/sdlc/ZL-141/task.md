# Task ZL-141: 修复生题 404 与知识树子考点递归选择异常

- **任务编号**: ZL-141
- **评级**: Tier 2 (Bugfix & Feature Alignment)
- **提出人**: User
- **创建时间**: 2026-09-26 00:20
- **状态**: Completed (Reviewed: PASS)

---

## 1. 现状与根因依据 (Problem & Evidence)

1. **生题 404 Not Found 根因**:
   - `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue` 未向抽屉组件传递 `version-id`；
   - `QuestionConfigDrawer.vue:237` 将 `material_id` 误作为 `version_id` 发起 `POST /api/v1/questions/generate`；
   - 后端 `QuestionService.generate_questions` 校验 `kp.version_id != version_id`，版本不匹配，抛出 `KnowledgeNotFoundError`（HTTP 404）。
2. **知识树仅显示 6 点 / 无法级联选中 18 点根因**:
   - 数据库已落库 18 点（6 个一级父节点，12 个二级/三级子节点）；
   - `KnowledgeTreeNode.vue` 未显式 `import KnowledgeTreeNode from './KnowledgeTreeNode.vue'`，微信小程序原生编译器未解析递归组件声明，导致子节点渲染受阻；
   - `materialStore.toggleKnowledgeSelection` 仅翻转单节点，缺少对子树所有子节点的级联选中/反选联动。

---

## 2. 变更实施方案 (Implementation Plan)

### 前端修复 (miniprogram)
1. `miniprogram/src/subpackages/material/pages/knowledge-tree/index.vue`:
   - 记录接口返回的 `currentVersionId`；
   - 挂载 `<QuestionConfigDrawer>` 时传递 `:version-id="currentVersionId"`；
2. `miniprogram/src/subpackages/material/components/QuestionConfigDrawer.vue`:
   - 移除 `props.versionId || props.materialId` 的错误兜底，当 `versionId` 缺失时由后端智能解析或通过 store 补全；
3. `miniprogram/src/subpackages/material/components/KnowledgeTreeNode.vue`:
   - 显式 `import KnowledgeTreeNode from './KnowledgeTreeNode.vue'`；
   - 优化选择交互：点击复选框时触发级联选择（通过树工具递归收集该节点下所有子孙节点 ID）；
4. `miniprogram/src/subpackages/material/utils/tree.ts` & `materialStore.ts`:
   - 提供 `collectSubtreeIds(node)` 与级联批量选中/取消功能。

### 后端加固 (backend)
1. `backend/app/services/question.py` & `backend/app/api/v1/questions.py`:
   - 在 `generate_questions` 中支持当 `version_id` 为空、或与 `material_id` 相同（前端传错）时，自动根据知识点的实际所属版本 `kp.version_id` 或资料的 `material.current_version_id` 自动修正，提升容错性。

---

## 3. 验证命令与判据 (Verification)

1. 前端类型检查与单元测试:
   - `cd miniprogram && pnpm run type-check && pnpm run test:unit`
2. 后端单元测试:
   - `cd backend && uv run pytest tests/unit/api/test_question_router.py tests/unit/services/test_question_service.py`
3. 真实生题接口调用测试（退出码 0，返回生成的题目列表）。
