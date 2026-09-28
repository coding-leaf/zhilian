# 技术设计：题目响应补切片正文（source_snippet 装配）

## 1. 范围与触发

跨层契约变更：后端题目响应新增字段 → 前端 adapter 归一化 → 契约测试断言翻转。
触发项：响应模型新增字段（跨层 request/response 契约变化）。

## 2. 契约（Signatures & Contracts）

### 2.1 响应字段

```python
# backend/app/schemas/question.py::QuestionDetailResponse
source_snippet: SourceSnippetDTO | None = Field(
    default=None,
    description="主来源切片投影（章节/页码/正文）；无来源或切片缺失时为 null",
)
```

- 字段可空 + 默认 `None`：历史数据（`source_snippet_id` 为空）与切片已删除时仍可序列化。
- 形状与练习侧逐字一致（同一 Pydantic 类，非同名异构副本）。

### 2.2 装配入口

```python
# backend/app/services/source_snippets.py（新增，唯一装配实现）
def build_source_snippet_map(
    material_repo: MaterialRepository,
    snippet_ids: Iterable[uuid.UUID],
    user_id: uuid.UUID,
) -> dict[uuid.UUID, SourceSnippetDTO]: ...

# backend/app/services/question.py::QuestionService
def attach_source_snippets(
    self, items: Sequence[QuestionDetailResponse], user_id: uuid.UUID
) -> None: ...   # 就地补全 items[*].source_snippet
```

## 3. 设计决策

### 3.1 `SourceSnippetDTO` 移到资料域

**问题**：该 DTO 现定义在 `app/schemas/practice.py`，题目侧需要同一个类；跨域 import（question → practice）会让两个业务域相互耦合。

**决策**：移到 `app/schemas/material.py`（切片投影本属资料域），practice 侧 import 改为新位置。
依据：前端早已是单份模型（`miniprogram/src/types/index.ts::SourceSnippet`），后端对齐后两端都是「一个来源模型」。

### 3.2 装配实现只留一份

规范 `quality-guidelines.md:1248` 明确「原文装配只有一个实现」。现有实现在 `PracticeService._build_source_snippet_map` + 私有 `_resolve_snippet_page_index`（含 `page_index` 列 → `source_info` 元数据的回退）。

**决策**：抽出 `app/services/source_snippets.py::build_source_snippet_map`，`PracticeService` 改为委托（删除其私有回退方法），`QuestionService` 直接复用。禁止题目侧另写一份投影逻辑。

`MaterialRepository.list_snippets_by_ids(ids, user_id)` 保持不动（已批量 + 租户过滤）。

### 3.3 装配点覆盖四处

| 端点 | 装配 | 理由 |
| --- | --- | --- |
| `POST /questions/generate`（qualified + pending） | 是 | AC-1；核对页主路径 |
| `GET /questions/{id}` | 是 | AC-1 |
| `GET /questions` | 是 | 同一响应模型形状一致；该端点本就返回 stem/answer/analysis/rubric 全量字段，单条切片正文属同量级 |
| `PATCH/PUT /questions/{id}` | 是 | 更新后前端复用同一卡片渲染，来源不应消失 |

**取舍（AC-3 要求的明确说明）**：列表与更新路径各多一次按主键集合的批量 `IN` 查询（切片数为常数级、无 N+1），代价是响应体积增加一条切片正文。若后续实测列表体积成为问题，只需在 `list_questions` 路由去掉装配调用，契约字段保持可空，前端自动走空态。

### 3.4 依赖注入（实际无需改动）

原计划给 `QuestionService.__init__` 增加可选 `material_repo`；实施时发现该服务**早已**在构造函数里建好 `self.material_repo = MaterialRepository(session)`（`app/services/question.py`），故零改动，直接复用。`AppContainer.create_question_service` 亦无需改动。

### 3.6 实施中发现的额外缺陷：响应字段与 ORM 关系同名

原设计只考虑了「装配」，未预料 `Question` 上已存在 ORM 关系 `source_snippet`（`Mapped["MaterialSnippet | None"]`，指向实体）。响应模型字段与它同名后，`from_attributes` 会直接读该关系实体，导致：

- **投影错且静默**：实体无 `snippet_content` 属性（真名 `content`）→ 字段落空串；`page_index` 落默认 1；
- **每题一次惰性加载**：实测 `model_validate(question)` 触发 1 次 `material_snippets` 查询（列表 20 条即 20 次），使批量装配形同虚设（违反 AC-3）。

**处置**：ORM 关系改名 `primary_source_snippet`，把线格式名留给响应投影；并加回归用例「裸映射零查询」守住改名不被回退。该缺陷由新写的装配用例当场发现（装配前断言 `source_snippet is None` 失败）。

### 3.5 前端零改动

`adapters/question.ts` 已声明 `source_snippet?: SourceSnippet | null` 并映射 `source_quote: question.source_snippet?.snippet_content`；`QuestionPreviewCard.vue` 已有 `v-if="question.source_quote"` 来源框。本任务只把后端字段接通。

## 4. 验证与错误矩阵

| 条件 | 结果 |
| --- | --- |
| 题目有 `source_snippet_id` 且切片存在 | 返回完整 `source_snippet`（含 `snippet_content`）|
| `source_snippet_id` 为空（历史数据） | `source_snippet = null`，序列化正常 |
| 切片已被删除 / 不属于该租户 | `null`（`list_snippets_by_ids` 带 `user_id`，跨用户查不到 → 不泄漏）|
| 一次响应内多题引用同一切片 | 结果字典去重，仅一次查询 |

## 5. 兼容性与回滚

- 纯新增可空字段，旧客户端忽略即可；前端 adapter 早已按该字段读取。
- 回滚 = 去掉装配调用（字段留空即回到当前行为）；DTO 迁移是纯移动，无行为变化。

## 6. 需要同步的规范

- `quality-guidelines.md` §Scenario「Practice Source-Snippet Enrichment on Both Read Paths」→ 扩为题目侧同样装配，并指向新的唯一实现。
- 同文件 §Scenario「Contract Fixture Fidelity」→ 现文以「题目侧不含切片正文」为例（1274/1286/1287/1292/1299 行），本任务后该例失效，须改用其它真实差异举例，并翻转题目侧断言方向。
