# 实施计划：后端·文件夹范围出题与组卷

## 顺序清单

- [ ] 1. `migrations/versions/0006_practice_folder_scope.py`：`practices.material_id` 改 nullable + 加 `folder_id` + 索引；对称 `downgrade()`。
- [ ] 2. `app/models/practice.py`：`Practice.material_id` 可空、新增 `folder_id` + 索引。
- [ ] 3. `app/schemas/question.py`：`QuestionGenerateRequest` 加 `folder_id`、`material_id` 可空、加「至少一个」校验；`QuestionGenerateResponse` 三字段可选。
- [ ] 4. `app/schemas/practice.py`：`PracticeCreateRequest` 加 `folder_id`、放开 `knowledge_point_ids`；详情/摘要/创建响应 `material_id` 可空 + `folder_id`。
- [ ] 5. `app/repositories/question.py`：`list_questions` 加 `folder_id` 过滤；新增 `list_knowledge_points_for_folder`。
- [ ] 6. `app/repositories/practice.py`：创建/落库支持 `folder_id`。
- [ ] 7. `app/services/question.py`：`generate_questions_for_knowledge_points` 加 `defer_commit`；新增 `generate_questions_for_folder`（分组 + 单事务原子 + 归档过滤 + 归属校验）。
- [ ] 8. `app/services/practice.py`：`CreatePracticeOptions` 加 `folder_id`；folder 范围抽题与落库；`material_id` 可空路径。
- [ ] 9. `app/api/v1/questions.py`：generate 分流 folder；list 加 `folder_id`。
- [ ] 10. `app/api/v1/practices.py`：create 透传 `folder_id`。
- [ ] 11. 单测（见 design.md §8）+ 迁移对称测试。
- [ ] 12. 全工具链绿。

## 验证命令（`backend/`）

```
uv run ruff format --check .
uv run ruff check .
uv run mypy app
uv run lint-imports
uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
```

## 评审门禁

- [ ] 回归测试先红后绿。
- [ ] 单资料路径零回归（不传 folder_id 行为不变）。
- [ ] 全工具链绿。
- [ ] 归档一致性 + 跨资料单事务原子 写入 `.trellis/spec/backend/quality-guidelines.md`。

## 风险与回滚

- 原子性：跨组唯一 `commit()`；`defer_commit=True` 下逐组仅 `flush`。
- `material_id` 放开：全量回归读取点（练习列表/详情/报告/诊断）。
- 回滚：迁移 `0006` downgrade；folder 分流仅在传参时生效，不传即退回旧行为。
