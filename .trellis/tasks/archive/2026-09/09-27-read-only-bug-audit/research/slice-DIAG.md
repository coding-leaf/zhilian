# Research: DIAG 切片（报告 / 诊断 / 错题本）只读 Bug 审计

- **Query**: 只读 bug 审计，切片 DIAG（报告/诊断/错题本），前后端同片核对
- **Scope**: mixed（backend service/api/repository/schema/algorithms + frontend api/store/pages/components/utils）
- **Date**: 2026-09-27
- **依据**: `prd.md`、`design.md` §3/§4/§8
- **约束**: 只读；除本文件（`research/`）外未改动任何文件

## 审阅范围（实际读取）

**后端**
- `backend/app/services/diagnosis.py`
- `backend/app/api/v1/diagnosis.py`
- `backend/app/repositories/diagnosis.py`
- `backend/app/schemas/diagnosis.py`
- `backend/app/core/algorithms/diagnosis.py`
- `backend/app/core/algorithms/mastery.py`
- 辅助核对：`backend/app/models/practice.py`、`backend/app/repositories/knowledge.py`、`backend/app/schemas/practice.py`、`backend/app/api/v1/practices.py`、`backend/app/schemas/practice.py:16-18`

**前端**
- `miniprogram/src/api/diagnosis.ts`
- `miniprogram/src/stores/reportStore.ts`
- `miniprogram/src/types/report.ts`
- `miniprogram/src/utils/recentLearning.ts`
- `miniprogram/src/subpackages/report/index.vue`
- `.../report/pages/detail/index.vue`、`.../report/pages/wrong-book/index.vue`
- `.../report/components/{ContinuePracticeBar,DiagnosisSummaryCard,WeakKnowledgeCard,WrongBookBatchBar,WrongRecordCard,WrongRecordFilterBar}.vue`
- `.../report/utils/{reportFormat,wrongBookFormat}.ts`
- 辅助核对：`miniprogram/src/utils/request.ts`、`types/common.ts`、`types/practice.ts`、`pages/index/index.vue`、`stores/practiceStore.ts`、`components/home/MasteryDashboardBar.vue`

---

## 功能性 Bug 清单

### BUG-DIAG-001
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-001 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `backend/app/schemas/diagnosis.py:188-199`；`miniprogram/src/types/report.ts:49`；`miniprogram/src/subpackages/report/pages/detail/index.vue:31-32,146-148`；`miniprogram/src/stores/reportStore.ts:59-61` |
| 现象 | 诊断报告字段名前后端不一致：后端下发 `weak_knowledge_points`，前端只读 `weak_points` → 报告详情的“薄弱知识点诊断卡片”永不渲染，`currentWeakPointIds` 恒为空数组。 |
| 证据/复现 | 后端响应模型 `DiagnosisReportResponse.weak_knowledge_points`（schemas/diagnosis.py:188），无 `weak_points` 别名。前端 `currentReport.weak_points`（detail/index.vue:31-32、147）与 `report?.weak_points`（reportStore.ts:59-60）。`utils/request.ts:288-296` 原样返回 `resData`，无字段重命名/转换层。 |
| 影响 | 报告页核心“薄弱点”板块不可见；由弱点到继续练习的入口数据丢失。 |
| 修复方向 | 前端统一改读 `weak_knowledge_points`，或后端在响应模型补 `weak_points` 别名。 |
| 证据强度 | 静态推理（跨层契约核对，非测试实跑） |

### BUG-DIAG-002
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-002 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `backend/app/schemas/diagnosis.py:172-212`（无 `overall_score`/`mastery_rate`）；`miniprogram/src/types/report.ts:41-43`；`miniprogram/src/subpackages/report/components/DiagnosisSummaryCard.vue:73-76`；`miniprogram/src/stores/reportStore.ts:38,42-54` |
| 现象 | 前端 `DiagnosisReport` 必填 `overall_score`、`mastery_rate`，后端响应均不提供 → “综合得分”恒显示 `0`；store 的 `overallMasteryRate` 恒 0、`masteryTier` 恒 `unlearned`。 |
| 证据/复现 | 后端仅有 `score_rate`（schemas/diagnosis.py:209）与 `mastery_before/after`，无 `overall_score`、无 `mastery_rate`。`DiagnosisSummaryCard.vue:74` `props.report.overall_score ?? 0`。`reportStore.ts:38` `mastery_rate ?? 0`。无响应转换层。 |
| 影响 | 报告页主分数展示错误；任何依赖 store `masteryTier`/`overallMasteryRate` 的面板失准。 |
| 修复方向 | 后端补 `overall_score`（可由 score_rate 或掌握度算法给出）与 `mastery_rate`，或前端改读 `score_rate`。 |
| 证据强度 | 静态推理（跨层契约核对） |

### BUG-DIAG-003
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-003 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | backend |
| 位置 | `backend/app/api/v1/diagnosis.py:145-147,323-325`；`miniprogram/src/stores/reportStore.ts:83-98`；`miniprogram/src/subpackages/report/pages/wrong-book/index.vue:177-186,266-269` |
| 现象 | 错题本列表接口 `total` 被赋值为“当前页条数”而非真实总数（`total = len(items)`）→ 前端 `wrongHasMore = wrongRecords.length < total` 在首页满页（20 条）时为 `false`，`onReachBottom` 永不再加载 → 错题本只能显示第一页。 |
| 证据/复现 | service `list_wrong_records` 返回 `list[WrongRecord]`（services/diagnosis.py:1087-1149）；api `total_count = getattr(records, "total", None)` 对 list 恒为 None，回退 `len(items)`（api/v1/diagnosis.py:323-325）。`reportStore.setWrongRecords` 用该 total 计算 `wrongHasMore`（reportStore.ts:86）。`wrong-book/index.vue:267` 仅在 `hasMore` 为真时翻页。 |
| 影响 | 错题超过一页时后续页永久不可见。 |
| 修复方向 | 仓储/服务返回 `(items, total)` 真实计数，或接口层单独 count。 |
| 证据强度 | 静态推理（后端源码 / 调用链核对） |

### BUG-DIAG-004
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-004 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `miniprogram/src/api/diagnosis.ts:92-105`；`backend/app/api/v1/diagnosis.py:337-372`；`backend/app/services/diagnosis.py:1151-1205`；`backend/app/repositories/diagnosis.py:432-466` |
| 现象 | “取消攻克”无效：前端 `toggleWrongRecordResolved(id, false)` 发送 body `{is_mastered:false}`，而后端 `/wrong-records/{id}/master` 无请求体参数，恒执行 `is_mastered=True`。 |
| 证据/复现 | 前端 api/diagnosis.ts:98-104 发送 `data:{is_mastered}`；后端路由签名仅 `id` + `current_user`（api/v1/diagnosis.py:343-346），service `mark_wrong_record_mastered` 无状态参数（services/diagnosis.py:1151-1176），repo 无条件置 True（repositories/diagnosis.py:463-464）。 |
| 影响 | 前端乐观更新为 false 且接口返回 code 0，前端保留 false；服务端实为 true，刷新后回弹，状态前后端不一致。 |
| 修复方向 | 后端 `master` 端点增加可选 `is_mastered` 入参并透传，或前端移除取反逻辑。 |
| 证据强度 | 静态推理（跨层契约核对） |

### BUG-DIAG-005
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-005 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `backend/app/schemas/diagnosis.py:360-380`；`miniprogram/src/subpackages/report/components/WrongRecordCard.vue:76-78,149-151` |
| 现象 | 错题记录响应体不含用户作答：`WrongRecordItemResponse` 无 `user_answer` / `last_wrong_answer` 字段，前端卡片读 `record.user_answer` → “您的作答”恒显示“未作答”。 |
| 证据/复现 | 后端 DTO 字段仅 id/question_id/practice_id/attempt_item_id/knowledge_point_id/error_type/is_mastered/wrong_count/error_count/question_snapshot/first_wrong_at/mastered_at/created_at/updated_at（schemas/diagnosis.py:360-380）。实体确有 `last_wrong_answer`（models/practice.py:831-836）但未映射下发。前端 `userAnswer`（WrongRecordCard.vue:149-151），模板 `formatAnswer(userAnswer) || '未作答'`（:77）。 |
| 影响 | 错题本无法显示用户原作答，复习比对功能失真。 |
| 修复方向 | 在 DTO 增加 `user_answer`（映射 `last_wrong_answer`）后再下发。 |
| 证据强度 | 静态推理（跨层契约核对） |

### BUG-DIAG-006
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-006 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `miniprogram/src/subpackages/report/pages/wrong-book/index.vue:73-84`；`miniprogram/src/subpackages/report/utils/wrongBookFormat.ts:236-255`；`miniprogram/src/api/diagnosis.ts:160-182`；`backend/app/schemas/practice.py:16-18,30-35,56-81` |
| 现象 | 错题本“一键巩固错题”请求必然校验失败：`ContinuePracticeBar` 传 `sourceType='wrong_record'`，而 `continuePractice` 将其作为 `source_type` 发出；后端 `VALID_PRACTICE_SOURCE_TYPES={"normal","weakness"}` 会 422。另：`material_id` 为后端必填，错题本页在未传 `materialId` 时置空导致缺失；`knowledge_point_ids` 有 `min_length=1`。 |
| 证据/复现 | wrong-book/index.vue:77 `:source-type="'wrong_record'"`；wrongBookFormat.ts:252 `source_type: params.sourceType ?? 'weakness'`；api/diagnosis.ts:176 `source_type: payload.source_type ?? 'weakness'`。后端 `source_type` 校验（schemas/practice.py:73-81）与合法集合（:18）→ `wrong_record` 非法。`material_id: uuid.UUID = Field(...)`（:30）必填；`knowledge_point_ids` `min_length=1`（:31-35）。 |
| 影响 | 错题本主 CTA 一键巩固练习直接 422 不可用（诊断报告页的薄弱点继续练习同样受 001/002 影响导致 `knowledge_point_ids` 为空）。 |
| 修复方向 | 对齐 `source_type` 枚举（新增 `wrong_record` 或前端映射为 `weakness`）；保证 `material_id`/`knowledge_point_ids` 有值或后端放宽。 |
| 证据强度 | 静态推理（跨层契约核对） |

### BUG-DIAG-007
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-007 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `miniprogram/src/api/diagnosis.ts:40-48`；`miniprogram/src/pages/index/index.vue:107`；`backend/app/api/v1/diagnosis.py:205-226`；`backend/app/services/diagnosis.py:903-929`；`backend/app/repositories/knowledge.py:148-170` |
| 现象 | 工作台调用 `fetchMasteryOverview()` 不传 `material_id` → 后端 `material_id=None` → `list_by_material_id(None)` 生成 `material_id IS NULL` 查询。而 `KnowledgePoint.material_id` 为 NOT NULL，结果恒空 → 掌握度全景恒为全 0。 |
| 证据/复现 | 前端无参调用（api/diagnosis.ts:40-47、pages/index/index.vue:107）。后端 `material_id` 为可选 Query，直接透传 service（api/v1/diagnosis.py:208、220-223，并带 `# type: ignore[arg-type]` 佐证 None）。仓储按 `material_id == material_id` 过滤（knowledge.py:162-170）。 |
| 影响 | 工作台“综合掌握度/四档分布”始终为 0/未学，主看板失效。 |
| 修复方向 | 后端支持 `material_id` 为空时的全量聚合，或前端必须传资料 ID。 |
| 证据强度 | 静态推理（后端源码核对） |

### BUG-DIAG-008
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-008 |
| 级别 | P1 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `backend/app/core/algorithms/diagnosis.py:133-134,196,586-587`；`backend/app/services/diagnosis.py:695,713`；`miniprogram/src/subpackages/report/utils/reportFormat.ts:250-269`；`miniprogram/src/subpackages/report/components/WeakKnowledgeCard.vue:102-107` |
| 现象 | `score_delta` 语义相反：后端定义为 `previous_score - current_score`（退步为正，`:196`，docstring `:133`），前端 `formatScoreDelta` 以 `delta <= -0.05` 判退步、正数显示 `+N%` → 真正退步点不显示“退步”徽章，反而显示为提升。 |
| 证据/复现 | 算法 `score_delta = round(previous_score - current_score, 4)`，`is_regressed = score_delta >= threshold`（diagnosis.py:196-197）。service 原样写入 `"score_delta": item.score_delta`（services/diagnosis.py:695、713）。前端 `isRegressed = delta <= -0.05`（reportFormat.ts:262）、`prefix = percent > 0 ? '+' : ''`（:266）。WeakKnowledgeCard.vue:103-106 依赖该结果。 |
| 影响 | 退步预警（FR-51）前端呈现完全反向，用户看到正向增长。 |
| 修复方向 | 统一 delta 符号约定（建议“current - previous”，负数=退步）并同步两侧。 |
| 证据强度 | 静态推理（跨层语义核对） |

### BUG-DIAG-009
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-009 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `backend/app/schemas/diagnosis.py:282-352`；`backend/app/services/diagnosis.py:71-83`；`miniprogram/src/components/home/MasteryDashboardBar.vue:256-263` |
| 现象 | `UserMasteryOverviewResponse.mastered_count` 恒为 0：`_sync_fields` 的 `mastered_count<->proficient_count` 映射只在 `mode="before"` 且输入为 dict 时生效，而接口用 `model_validate(DTO对象)`（from_attributes），before 收到对象不进入分支；`after` 校验器未补该映射。`learning_count`（应对应 `basic_count`）同样恒 0。 |
| 证据/复现（实测） | `uv run python -c "...UserMasteryOverviewResponse.model_validate(UserMasteryOverviewDTO(proficient_count=2,...))"` 输出：`mastered_count= 0 proficient_count= 2 total_points= 5 overall_score= 0.8 learning_count= 0`。 |
| 影响 | 工作台“精通”档计数恒为 0（四档分布中精通段恒空）；`learning_count` 字段永不填充。 |
| 修复方向 | 在 `mode="after"` 校验器补齐 mastered/proficient（及 basic→learning）同步，或改为按属性解析。 |
| 证据强度 | 实测（已在 `backend/` 运行 venv 校验，只读） |

### BUG-DIAG-010
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-010 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `backend/app/api/v1/diagnosis.py:273,302-334`；`miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue:130-136,208-211`；`backend/app/models/practice.py:96-102` |
| 现象 | ① `error_type` 过滤在接口层“分页之后”用列表推导过滤（api/v1/diagnosis.py:316-317），导致该页可能被过滤为空、`total` 也失真；② 枚举取值不一致：前端筛选项 `incomplete`/`deviation`（WrongRecordFilterBar.vue:133-134），后端枚举为 `incomplete_expression`/`question_misreading`（models/practice.py:100-101），永不匹配；`getErrorTypeInfo` 同样只识别 `incomplete`/`deviation`（wrongBookFormat.ts:24-39）。 |
| 证据/复现 | 后端 service/repo 均无 `error_type` 下推（api/v1/diagnosis.py:302-312），仅事后过滤（:316-317）。枚举定义见 models/practice.py:96-102。 |
| 影响 | 错误类型筛选对 `incomplete/deviation` 恒无结果；分页+过滤组合下结果不完整、总数错误。 |
| 修复方向 | 枚举取值对齐；`error_type` 下推到仓储查询并参与 total 统计。 |
| 证据强度 | 静态推理（跨层契约核对） |

### BUG-DIAG-011
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-011 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue:121-128,182-184`；`backend/app/api/v1/diagnosis.py:268-280`；`backend/app/repositories/diagnosis.py:492-519` |
| 现象 | 前端题型筛选发送 `question_type`，后端错题列表端点未声明该 Query 参数、仓储也无该过滤 → FastAPI 静默忽略，筛选看似无效。 |
| 证据/复现 | 前端 emit `result.question_type`（WrongRecordFilterBar.vue:182-184）。后端端点参数仅 material_id/knowledge_point_id/error_type/is_mastered/status/page/page_size/offset/limit（api/v1/diagnosis.py:268-280）。仓储条件仅 is_mastered/knowledge_point_id（repositories/diagnosis.py:512-516）。 |
| 影响 | 题型筛选不生效（返回全部题型），用户筛选结果错误。 |
| 修复方向 | 后端增加 `question_type` 过滤（可按快照字段），或前端移除该筛选项。 |
| 证据强度 | 静态推理（跨层契约核对） |

### BUG-DIAG-012
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-012 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | backend |
| 位置 | `backend/app/services/diagnosis.py:1126-1141` |
| 现象 | 按 `material_id` 过滤错题时先 `limit=1000` 拉全量再内存切片；超过 1000 条即静默截断，且返回总量信息丢失（接口 `total=len(items)`）。 |
| 证据/复现 | `list_wrong_records(..., limit=1000, offset=0)` 后 `filtered[offset:offset+limit]`（services/diagnosis.py:1134-1141）。 |
| 影响 | 错题 >1000 时后段数据不可达；分页上限硬编码。 |
| 修复方向 | 下推到 SQL（join KnowledgePoint 过滤 material_id）并返回真实总数。 |
| 证据强度 | 静态推理（后端源码核对） |

### BUG-DIAG-013
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-013 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `miniprogram/src/api/diagnosis.ts:113-120`；`backend/app/schemas/diagnosis.py:448-455` |
| 现象 | 删除错题响应字段不一致：前端期待 `{removed: boolean}`，后端返回 `{id, success, message}`，消费 `res.data.removed` 恒为 undefined。 |
| 证据/复现 | 前端泛型 `ApiResponse<{id; removed; message}>`（api/diagnosis.ts:115-116）；后端 `DeleteWrongRecordResponse.success`（schemas/diagnosis.py:454）。当前代码库内 `deleteWrongRecord` 无调用点（grep 仅定义），属潜伏契约问题。 |
| 影响 | 一旦接入删除入口，成功判断将失效。 |
| 修复方向 | 前端改读 `success`，或后端对齐 `removed`。 |
| 证据强度 | 静态推理（跨层契约核对，当前无调用点） |

### BUG-DIAG-014
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-014 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | frontend |
| 位置 | `miniprogram/src/subpackages/report/pages/detail/index.vue:259-275` |
| 现象 | 报告详情页 `onMounted` 与 `onLoad` 均调用 `loadReportData`，无去重守卫 → 正常进入页面会重复请求诊断报告与练习详情。 |
| 证据/复现 | `onMounted`（:259-267）与 `onLoad`（:269-275）各自读取到 pid 后调用 `loadReportData`。 |
| 影响 | 首屏重复网络请求（2×），浪费带宽并可能触发竞态覆盖。 |
| 修复方向 | 以 `onLoad` 为唯一入口，`onMounted` 仅在无 query 时兜底。 |
| 证据强度 | 静态推理（前端源码核对） |

### BUG-DIAG-015
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-015 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | frontend |
| 位置 | `miniprogram/src/subpackages/report/components/WrongRecordFilterBar.vue:213-220`；`miniprogram/src/subpackages/report/pages/wrong-book/index.vue:9,204-212` |
| 现象 | 重置筛选时组件同时 `emit('reset')` 与 `emitChange()`（后者 emit `filter-change`）；页面 `@reset` 调 `handleResetFilters`（内部 loadData）与 `@filter-change` 调 `handleFilterChange`（又 loadData）→ 一次点击触发两次列表请求。 |
| 证据/复现 | WrongRecordFilterBar.vue:218-219 连续 emit `reset`、`filter-change`；wrong-book/index.vue:8-9 两监听器均发起 `loadData(1,true)`。 |
| 影响 | 重复请求；后发请求结果可能覆盖。 |
| 修复方向 | 二选一触发（保留 `filter-change`，移除 `reset` 的重复加载）。 |
| 证据强度 | 静态推理（前端源码核对） |

### BUG-DIAG-016
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-016 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | frontend |
| 位置 | `miniprogram/src/stores/reportStore.ts:57-62` |
| 现象 | `setReport` 仅在 `report?.weak_points` 为真时更新 `weakPoints`；当新报告无薄弱点（或字段缺失）时不重置，保留上一份报告的陈旧 `weakPoints`。 |
| 证据/复现 | `if (report?.weak_points) { weakPoints.value = [...] }`（reportStore.ts:59-61），无 else 清空分支；`clearReport` 未在报告页加载前调用。 |
| 影响 | 跨报告导航时展示过期薄弱点数据（状态未重置）。 |
| 修复方向 | 改为 `weakPoints.value = report?.weak_points ? [...report.weak_points] : []`。 |
| 证据强度 | 静态推理（前端源码核对） |

### BUG-DIAG-017
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-017 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | frontend |
| 位置 | `miniprogram/src/utils/recentLearning.ts:75-92`；`miniprogram/src/stores/practiceStore.ts:82-88,126-135`；`miniprogram/src/types/practice.ts:29-33` |
| 现象 | `extractLatestDraftPractice` 读取草稿的 `title` / `total_count|totalCount` / `material_id`，但 `practiceStore` 写入的 `AnswerDraft` 只有 `practice_id/answers/updated_at` → 这些字段恒缺，标题恒回落“专项练习”、总数恒 `max(10, answeredCount)`，无法反映真实练习。 |
| 证据/复现 | 草稿构造仅三字段（practiceStore.ts:83-87、127-131）；读取 `rawAny.title`、`rawAny.total_count`、`rawAny.material_id`（recentLearning.ts:75-89）；`AnswerDraft` 类型亦无这些字段（types/practice.ts:29-33）。 |
| 影响 | 工作台“最近学习/活跃练习”标题与题数进度恒失真。 |
| 修复方向 | 创建草稿时写入 `title/material_id/total_count`，或移除无效读取。 |
| 证据强度 | 静态推理（前后端/存储契约核对） |

### BUG-DIAG-018
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-018 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `miniprogram/src/api/diagnosis.ts:160-181`；`backend/app/api/v1/practices.py:48-93`；`backend/app/schemas/practice.py:21-63` |
| 现象 | 继续练习的幂等机制实际不生效：前端发 `X-Idempotency-Key` 头并把 `idempotency_key` 放进 body，但 `POST /practices` 无该 Header 依赖且请求模型无该字段（额外字段被忽略）→ 重复点击/重试会创建多份练习。 |
| 证据/复现 | 前端 headers/data（api/diagnosis.ts:163-180）；后端 create_practice 签名无 Header（api/v1/practices.py:54-58），`PracticeCreateRequest` 无 `idempotency_key`（schemas/practice.py:21-63）。注：交卷端点用的是 `Header(alias="Idempotency-Key")`（api/v1/practices.py:352），与前端 `X-Idempotency-Key` 也不一致。 |
| 影响 | 强化练习可被重复创建，产生重复练习会话。 |
| 修复方向 | 后端 create 端点接入统一幂等键（并对齐 Header 名）；前端对齐头名。 |
| 证据强度 | 静态推理（跨层契约核对） |

### BUG-DIAG-019
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-019 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | backend |
| 位置 | `backend/app/services/diagnosis.py:464-479,750-751`；`backend/app/models/practice.py:682-688,757-760` |
| 现象 | 报告生成的幂等为先查后插，无冲突捕获；并发/重放时 `diagnosis_reports.practice_id` 唯一约束将抛 `IntegrityError`，未转换为业务错误 → 可能 5xx。 |
| 证据/复现 | 先 `get_diagnosis_report_by_practice_id` 再 `create_diagnosis_report`+`commit`（services/diagnosis.py:465-479、750-751）；唯一约束 `UniqueConstraint("practice_id")`（models/practice.py:757-759）。无 `IntegrityError` 捕获分支。 |
| 影响 | 并发重复生成时接口 500，而非幂等返回。 |
| 修复方向 | 捕获唯一键冲突后回查返回既有报告。 |
| 证据强度 | 静态推理（后端源码核对） |

### BUG-DIAG-020
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-020 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | backend |
| 位置 | `backend/app/services/diagnosis.py:936,954-982,996` |
| 现象 | 掌握度全景的 `weak_knowledge_points` 按知识点遍历顺序（level asc、created asc）追加，未按掌握度升序排序；而算法层 `weak_points` 明确按 `(current_score, -score_delta)` 升序（core/algorithms/diagnosis.py:586）。两处“薄弱清单”排序约定不一致。 |
| 证据/复现 | `weak_points_summary.append(...)` 无排序（services/diagnosis.py:970、978）；返回 DTO 直接使用（:996）。 |
| 影响 | 全景薄弱点未按最弱优先，展示顺序与算法约定不符。 |
| 修复方向 | 统一按掌握度/降幅排序后再返回。 |
| 证据强度 | 静态推理（后端源码核对） |

### BUG-DIAG-021
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-021 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | cross-layer |
| 位置 | `miniprogram/src/types/report.ts:115-130`；`backend/app/schemas/diagnosis.py:265-305` |
| 现象 | 潜伏类型契约不一致：前端 `UserMasteryOverview.weak_points` 对应后端 `weak_knowledge_points`（无 `weak_points` alias 下发）；前端 `KnowledgeMasterySummary` 用 `current_score/tier/sample_count`，后端 `KnowledgeMasterySummaryResponse` 用 `mastery_score/level/practice_count/correct_count`。当前 DIAG 组件未消费这些字段，故为潜伏问题。 |
| 证据/复现 | 前端字段（types/report.ts:115-130）；后端字段（schemas/diagnosis.py:265-305）。 |
| 影响 | 后续接入掌握度明细/弱点点位面板时字段读取为空/失准。 |
| 修复方向 | 前后端字段命名统一或补别名。 |
| 证据强度 | 静态推理（跨层契约核对，潜在） |

### BUG-DIAG-022
| 字段 | 内容 |
|---|---|
| ID | BUG-DIAG-022 |
| 级别 | P2 |
| 切片 | DIAG |
| 层 | frontend |
| 位置 | `miniprogram/src/subpackages/report/pages/detail/index.vue:2-42` |
| 现象 | 报告详情页模板仅覆盖 `loading`/`error`/`currentReport` 三态，无“无 practiceId / 报告不存在”空态分支；当未传 pid 时 `loading=false` 且 `currentReport=null`，页面渲染空白无提示。 |
| 证据/复现 | `onMounted` 无 pid 时 `loading.value=false`（:264-266）；模板无对应 `v-else` 兜底（:24-42）。 |
| 影响 | 异常入口下白屏（无错误提示、无重试）。 |
| 修复方向 | 增加空态/未找到分支与引导。 |
| 证据强度 | 静态推理（前端源码核对） |

---

## 计数小结

| 层级 \ 级别 | P0 | P1 | P2 | 小计 |
|---|---|---|---|---|
| backend | 0 | 1 (003) | 5 (009*,012,019,020；含跨层项另计) | — |
| frontend | 0 | 0 | 5 (014,015,016,017,022) | — |
| cross-layer | 0 | 7 (001,002,004,005,006,007,008) | 5 (009,010,011,013,018,021) | — |
| **合计** | **0** | **8** | **14** | **22** |

> 层级计数中 `009` 为实测的跨层契约项，归入 cross-layer 明细；上方 backend 行列的“含跨层项另计”仅示意，精确以本表合计为准。

- P0：**0**
- P1：**8**（BUG-DIAG-001 … 008）
- P2：**14**（BUG-DIAG-009 … 022）
- 疑似(SR)：**0**（本切片未产生真机/开发者工具专属渲染结论）
- 环境受限(ENV)：**0**
- 非功能性（重复/死代码）：不在本文件（见 code-smells 分节）

**证据强度分布**：实测 1（BUG-DIAG-009，已运行 `backend/.venv` 校验）；测试复现 0；静态推理 21。

## 最严重 3 条

1. **BUG-DIAG-001** — 报告字段名前后端不一致（`weak_knowledge_points` vs `weak_points`），报告页薄弱知识点板块永不渲染、弱点评练入口数据为空。
2. **BUG-DIAG-006** — 错题本“一键巩固”使用非法 `source_type='wrong_record'` 且缺失必填 `material_id`，主 CTA 必然 422 不可用。
3. **BUG-DIAG-004** — “取消攻克”无效：后端 master 端点无请求体、恒置已掌握，导致前后端攻克状态不一致。
