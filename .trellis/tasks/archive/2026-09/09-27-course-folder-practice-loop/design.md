# 技术设计：课程文件夹与出题-答题闭环重构

> 本文件为父任务技术设计，锁定跨子任务契约。子任务可在各自 `design.md` 细化，但不得违背此处契约（除非回改本文件）。

## 1. 架构与边界

保持现有三层架构（router / service / repository）与「资料 + 版本」解析模型不变，**新增一层轻量分类实体**并把「出题范围」从「单资料」扩展到「文件夹」。

```
用户
 └─ 课程文件夹 (material_folders)         ← 新增单层分类容器
     └─ 学习资料 (materials.folder_id)      ← 新增可空外键，一份资料属一个课程
         └─ 版本 (material_versions)        ← 不变
             ├─ 知识片段 (material_snippets)
             └─ 知识点树 (knowledge_points)  ← 不变，仍按 (material, version)
                 └─ 题目 (questions)         ← 不变，仍绑定 (material, version, kp)
```

- **不合并知识树**（D2）：`knowledge_points` / `questions` 归属不变，跨资料「综合」只在**出题/组卷时的查询范围**上体现。
- **不引入解析批次实体**（D2/D6）：多批次上传 = 往文件夹多次加资料，各自独立解析。

## 2. 数据模型与迁移（migration 0005）

### 2.1 新增表 `material_folders`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| id | UUID | PK | UUIDv4 |
| user_id | UUID | FK users, NOT NULL, index | 租户归属 |
| name | String(100) | NOT NULL | 课程名称 |
| parent_id | UUID | FK self, NULL, 预留 | 未来嵌套；本期恒 NULL |
| sort_order | Integer | NOT NULL default 0 | 排序 |
| archived_at | timestamp | NULL, index | 归档时间；NULL=活跃。7 天反悔期清理基准 |
| created_at/updated_at | timestamp | 由 TimestampMixin | |

- 唯一约束：`UniqueConstraint(user_id, name)`。
- 继承 `TenantModelMixin` + `TimestampMixin`（与现有模型一致）。
- 归档为**软删除**：不改 `materials`，仅凭 `archived_at` 在列表/查询层隐藏该课程及其资料。

### 2.2 `materials` 增加 `folder_id`（可空 = 未分类）

- `folder_id UUID NULL`, FK → `material_folders.id`, `ON DELETE SET NULL`, index。
- **「未分类」= `folder_id IS NULL`**（前端虚拟分组，非真实课程；不可归档/重命名/删除）。
- 新增复合索引 `(user_id, folder_id, is_deleted)`。
- 上传未指定课程即落未分类；影响面：API 上传（`materials.py:198`）、CLI `material import`（`material.py:134`）、`smoke`（`smoke.py:245`）均可缺省 `folder_id`。

### 2.3 `practices` 扩展范围

- `folder_id UUID NULL`, FK → `material_folders.id`, `ON DELETE SET NULL`, index。
- `material_id` 由 NOT NULL 改为 **NULL**（文件夹范围组卷时无单一资料）。
- 新增索引 `(user_id, folder_id, status)`。

### 2.4 迁移与数据

- **D5：不做存量迁移**；迁移脚本仅做 DDL。上线前清空 `materials/knowledge_points/questions/practices/...` 测试数据。
- 迁移需 `upgrade()` + `downgrade()` 对称可回滚。

## 3. API 契约

### 3.1 课程文件夹 CRUD（新增 `app/api/v1/folders.py`）

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| POST | `/folders` | `{name}` | `FolderDetailResponse` |
| GET | `/folders` | `?include_archived=false` | `FolderListResponse`（含聚合计数 + `is_archived`） |
| GET | `/folders/{id}` | — | `FolderDetailResponse` |
| PATCH | `/folders/{id}` | `{name}` | `FolderDetailResponse` |
| DELETE | `/folders/{id}` | — | `{id, is_deleted, archived_at, purge_after, message}` |
| POST | `/folders/{id}/restore` | — | `FolderDetailResponse` |
| DELETE | `/folders/{id}/purge` | — | `{id, is_deleted, message}`（可选：立即物理清理） |

`FolderDetailResponse` 字段：`id, name, is_archived, archived_at, purge_after, material_count, ready_material_count, knowledge_point_count, question_count, last_practice_at, created_at, updated_at`。

- `DELETE /folders/{id}`：**归档**（写 `archived_at=now`），列表默认隐藏；其下资料随课程在查询层隐藏；`purge_after = archived_at + 7 天`。**不再回退到未分类、不物理删除**。
- `POST /folders/{id}/restore`：清空 `archived_at`，课程与资料恢复可见。
- **逾期清理**：采用**惰性清理**——任何列表/详情查询时，对 `archived_at < now - 7d` 的课程执行物理级联删除（复用 `hard_delete_material`）。无需常驻调度器。

### 3.2 资料归属（扩展现有 `/materials`）

- `POST /materials/upload` 新增**可选** Form 参数 `folder_id`（校验归属当前用户；缺省 = 未分类）。
- `GET /materials` 新增可选 Query `folder_id`；`folder_id` 缺省返回全部，`folder_id=__none__` 返回未分类（契约在 C1 定稿）。
- 响应 `MaterialListItem` / `MaterialDetailResponse` 新增 `folder_id`（可空）。
- 全局快捷上传（控制台 `QuickUploadBar`）**不再阻断**：未选课程即落未分类。

### 3.3 跨资料综合出题（扩展现有 `/questions/generate`）

- `QuestionGenerateRequest` 新增可选 `folder_id`；当提供 `folder_id`：
  - `material_id` 可缺省；`knowledge_point_ids` 可跨该文件夹下多份 ready 资料的考点。
  - service 将所选考点按 `(material_id, version_id)` 分组，逐组调用既有 `generate_questions` 逻辑，题量按考点均分（复用 `distribute_count` 思路）。
  - 若未提供 `knowledge_point_ids`，则以该文件夹下所有 ready 资料的全部知识点为范围。
- 每道题仍归属其来源 `(material_id, version_id, knowledge_point_id)`，溯源不丢。
- `GET /questions` 新增可选 `folder_id`（经 `materials.folder_id` join 过滤）。

### 3.4 文件夹范围组卷（扩展现有 `POST /practices`）

- `PracticeCreateRequest` 新增可选 `folder_id`；提供时 `material_id` 可缺省。
- service 抽题范围：`folder_id` → 该文件夹所有 ready 资料的可用题目（可叠加 `knowledge_point_ids` / `question_types` / `difficulty` / `count` / `mode`）。
- `PracticeDetailResponse` 增加 `folder_id`（可选）。

### 3.5 移动资料（未分类 ↔ 课程、课程间）

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| PATCH | `/materials/{id}/folder` | `{folder_id: UUID \| null}` | `MaterialDetailResponse` |

- `folder_id=null` → 移回未分类；非空 → 校验目标课程归属当前用户且未归档。
- 批量移动可在 C3 前端循环调用，或后续加 `POST /materials/move-batch`（本期不必）。

## 4. 前端信息架构

### 4.1 页面/路由变更

| 变更 | 路径 | 说明 |
|---|---|---|
| 改 | `pages/index/index`（控制台） | 移除 `MasteryDashboardBar` 总分卡；首屏改为课程列表入口（含「未分类」）+ 快捷上传 + 最近学习 |
| 新增 | `subpackages/material/pages/course/index` | 课程详情：课程内资料列表 + 上传（归属本课程）+ 出题/题目入口 + **移动资料** |
| 改 | `subpackages/material/pages/list/index` | 支持按课程过滤；承载「未分类」资料列表与「移动到课程」操作 |
| 改 | `subpackages/material/pages/questions/index` | 支持 `folder_id` 范围 + 「开始答题」按钮 |
| 新增 | 已归档列表/恢复（可并入控制台或课程页） | 展示归档课程、剩余反悔时间、恢复/立即清理 |
| 复用 | `subpackages/practice/pages/session/index` | 答题页（无需改结构），由「开始答题」经 `createPractice` 进入 |

- 课程列表项展示：名称、资料数、ready 数、考点数、题目数、最近练习时间、进入按钮；「未分类」为固定首项（仅当存在无归属资料）。
- 归档课程不在主列表显示；单独「已归档」入口展示并可恢复。
- 新增 course store 或扩展 `materialStore`（遵循前端「Store 不发请求，请求走 `src/api/`」铁律）。

### 4.2 出题→答题闭环（修复 R7）

```
课程详情 → 出题配置（跨资料选考点）→ POST /questions/generate(folder_id)
        → 题目列表(folder_id) → [开始答题] → POST /practices(folder_id, kp, count, mode)
        → navigateTo /subpackages/practice/pages/session/index?id=...
        → 作答 → 交卷 → 判题（客观秒判 / 主观 LLM / 降级自评）→ 报告
```

- `createPractice`（`src/api/practice.ts:25`）由此接入，消除死代码。

### 4.3 判题分流（D3，界面统一）

- 不新增答题节奏/模式；沿用现有 `GradingChannel` 与 `pending_regrade` 三态。
- 前端交卷后按 `grading_status` 展示：客观题即显分；主观题 `pending`/`pending_regrade` 显示处理中，LLM 判毕回填。

## 5. 兼容性与权衡

- **向后兼容**：`folder_id` 可空；现有单资料出题/组卷调用不传 `folder_id` 时行为不变。
- **权衡 A（出题分组）**：跨资料生成按 `(material, version)` 分组逐组生成，而非合并切片统一生成——牺牲少量「跨资料融合出题」质量，换取知识树/溯源/重建逻辑零改动（D2 的代价，明确接受）。
- **权衡 B（删课程）**：采用**软删除 + 归档 + 7 天惰性清理**，非破坏性；代价是查询层需处处过滤 `archived_at`，且需惰性清理逻辑。
- **权衡 C（未分类）**：`folder_id` 可空 + 前端虚拟「未分类」；上传不阻断。代价是需在查询层用 `IS NULL` 表达未分类，且出题/组卷范围需明确是否含未分类资料（默认不含，须先归位）。

## 6. 回滚与运维

- 迁移 0005 的 `downgrade()` 对称回滚（drop 表/列/索引）。
- 因数据已清空（D5），无数据迁移回滚风险。
- 前端为增量页面改动，出问题可回退对应页面而不影响后端（后端字段可空、向后兼容）。
- 归档/惰性清理为纯后端逻辑，可独立回退（去掉清理调用即退回「永久归档不删」）。
- 非功能性：不做重复实现/重构，沿用现有工具函数（如 `distribute_count`、`generate_questions_for_knowledge_points`、`hard_delete_material`）。

## 7. 子任务契约边界（供子任务 design.md 细化）

- **C1** 交付：表/列/迁移（`material_folders` 含 `archived_at`）+ `/folders` CRUD + 归档/恢复/惰性清理 + `/materials` 归属（可空 folder_id）/过滤 + `PATCH /materials/{id}/folder` 移动 + schemas/repository/service/router 全套 + 单测。
- **C2** 交付：`/questions/generate` folder 范围（未分类资料默认不含，需先归位）+ `/questions` folder 过滤 + `/practices` folder 范围 + `Practice.material_id` 可空联动 + 单测。依赖 C1。
- **C3** 交付：控制台课程列表（含未分类/已归档入口）+ 课程详情页 + 文件夹 CRUD UI + 上传归属 + 移动资料 UI + 归档/恢复 UI + 去总分卡 + 前端 store/api/types + 单测。依赖 C1。
- **C4** 交付：课程内出题入口 + 题目列表答题按钮 + `createPractice` 接线 + 跳转答题 + 判题分流展示 + 单测 + 真机 E2E。依赖 C2、C3。
