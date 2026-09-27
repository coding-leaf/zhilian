# 跨层一致性核对矩阵（Stage C）

方法：逐切片核对「后端路由/请求/响应/错误码 ↔ 前端 `src/api/*` ↔ store/组件」的字段与语义一致性。
结论口径：✅ 一致 / ⚠️ 部分不一致（另有切片文件详述）/ ❌ 断言契约断裂。
证据：各切片 `slice-*.md`；`P0` 项已由主会话独立复核。

## AUTH（认证/登录/会话）

| 契约点 | 后端 | 前端 | 结论 |
|---|---|---|---|
| JWT 签名密钥来源 | `core/config.py` env_prefix=`ZHILIAN_`，`settings.secret_key` | — | ❌ `core/security.py:41` 读裸 `SECRET_KEY`，忽略 `ZHILIAN_SECRET_KEY` → `BUG-AUTH-001`（P0，已复核） |
| 登录请求 | `LoginRequest`（code/nickname/avatar_url） | `api/auth.ts`、`pages/auth/login.vue` 固定 `nickname:'学员用户'` | ⚠️ 语义错位 → `BUG-AUTH-002`（P1） |
| 登录失败语义 | 401 + code 20001（停用/注销/无效 code） | `utils/request.ts` 将 401/20001 一律当会话过期处理 | ❌ 错误归类 + 强制重定向 → `BUG-AUTH-003`（P1） |
| 用户画像更新 | users 路由仅 GET/DELETE `/me` | `api/user.ts` 调用 `PUT /users/me` | ❌ 405 → `BUG-AUTH-004`（P2） |
| token 存储同步 | — | refresh 后未同步 `userStore.tokens`（仅写 Storage） | ⚠️ `BUG-AUTH-005`（P2） |

**切片结论**：⚠️ 存在 1 个 P0 安全断裂（密钥来源）+ 2 个 P1 语义错位。

## MAT（素材/知识点树）

| 契约点 | 结论 |
|---|---|
| 上传/重拍 | ❌ 前端 `retakeMaterialPage` 用 JSON `request` 提交，后端要求 multipart `File+Form` → `BUG-MAT-002`（P1，真机必失败） |
| 秒传/内容哈希复用 | ❌ 复用他资料 `storage_key`，源资料硬删连带 purge → `BUG-MAT-001`（P1，数据完整性） |
| 重拍完成后续 | ❌ 仅重建切片置 READY，未重建知识树/清理旧知识点 → `BUG-MAT-003`（P1）；且后端无 `retake_required` 状态与不合格页查询接口，重拍链路整体不可达 → `BUG-MAT-004`（P1） |
| 知识树递归/选中级联 | ⚠️ 多处 P2（节点 key、级联、轮询清理） |
| 字段命名一致性 | ⚠️ 多项 P2 |

**切片结论**：⚠️ 重拍（retake）**全链路断裂**（002/003/004 三条 P1 互为因果），是 MAT 最高优先级。

## QGEN（题目生成/审核/编辑）

| 契约点 | 结论 |
|---|---|
| 选项字段 | ❌ 后端 `{key,content}` vs 前端 `{key,text}` → `BUG-QGEN-001`（P1）；与 PRAC-002 同根因 |
| 生成数量上限 | ❌ 前端 1~50 vs 后端 `count le=20` → `BUG-QGEN-002`（P2，>20 必 422） |
| 删除原因 | ⚠️ 前端 body vs 后端 Query → `BUG-QGEN-003`（P2，原因丢失） |
| 多考点生成原子性 | ❌ 逐考点各自 commit，中途失败遗留部分题目 → `BUG-QGEN-007`（P1） |

**切片结论**：⚠️ 选项渲染契约（001）与多考点原子性（007）为 P1。

## PRAC（练习作答/草稿/答案单）

| 契约点 | 结论 |
|---|---|
| 详情/创建响应题目字段 | ❌ 后端 `items`（`{question_snapshot}`）vs 前端 `res.data.questions` → `BUG-PRAC-001`（P0，已复核：会话题目恒空，主流程不可用） |
| 选项字段 | ❌ 后端 `{key,content}` vs 前端 `opt.text` → `BUG-PRAC-002`（P1，与 QGEN-001 同根因） |
| 交卷幂等键 | ❌ 每次重试重新生成，非幂等 → `BUG-PRAC-003`（P1） |
| 草稿写入 | ❌ 每次同步整写 `practice_drafts`，超 `MAX_STORAGE` 静默失败 → 数据丢失风险 → `BUG-PRAC-004`（P1） |
| 耗时字段 | ⚠️ 前端读 `res.data.time_elapsed_seconds`，`PracticeDetailResponse` 无此字段 → `BUG-PRAC-015`（P2） |
| 暂停/恢复端点 | ⚠️ 前端调用 `/pause`/`/resume`，后端无对应路由 → `BUG-PRAC-017`（P2） |

**切片结论**：❌ 存在 1 个 P0（题目字段名断裂）+ 1 个 P1 同根因（选项字段），主流程不可用。

## GRADE（评分/批改/自评/重批）

| 契约点 | 结论 |
|---|---|
| 重批终态 | ❌ 后端同步完成并写 `success`+新分，前端硬编码 `pending_regrade` 不回填 → `BUG-GRADE-001`（P1） |
| 待重判语义 | ❌ LLM 降级题 `score=0.0` 且逐题不返回判题状态，前端按分数判级显示"判错" → `BUG-GRADE-002`（P1） |
| 要点命中/遗漏 | ❌ 存于 `GradingRecord`，前端从 `question_snapshot` 读，后端从不注入 → 关键词胶囊不渲染 → `BUG-GRADE-003`（P2） |
| 报告 items 消费 | ⚠️ 前端用 `reportRes.data.items` vs `DiagnosisReportResponse` 字段 → `BUG-GRADE-005`（P2） |
| 自评可判题型 | ⚠️ 前端 `short_answer` vs 后端 `term_*` 枚举 → `BUG-GRADE-007`（P2） |
| 舍入 | ⚠️ 前端注释 half-up vs 后端 `round(raw/unit)*unit`（banker's） → `BUG-GRADE-009`（P2） |
| 自评 reason 长度 | ⚠️ 前端 `maxlength=200` vs 后端 `max_length=500` → `BUG-GRADE-013`（P2） |

**切片结论**：⚠️ 2 个 P1 均为"后端状态与前端展示/判级"错位；抽样 1 条（GRADE-015 空指针）经复核**撤销**。

## DIAG（报告/诊断/错题本）

| 契约点 | 结论 |
|---|---|
| 薄弱知识点字段 | ❌ 后端 `weak_knowledge_points` vs 前端 `weak_points`（无别名映射） → `BUG-DIAG-001`（P1，已复核） |
| 一键巩固入参 | ❌ 前端 `source_type='wrong_record'`（非法）+ 缺 `material_id` → 主 CTA 必 422 → `BUG-DIAG-006`（P1） |
| 取消攻克 | ❌ 后端 `master` 端点无请求体、恒置已掌握，前后端攻克状态不一致 → `BUG-DIAG-004`（P1） |
| 掌握度计算 | ⚠️ 多项 P2（除零/空数据/排序） |
| 报告格式化 | ⚠️ 多项 P2（百分比/日期越界） |

**切片结论**：⚠️ P1 数量最多（8 条），集中在报告字段映射与错题本 CTA/攻克状态。

## 跨切片同根因索引（去重提示）

| 根因 | 涉及条目 | 说明 |
|---|---|---|
| 选项字段 `content` vs `text` | `BUG-QGEN-001`、`BUG-PRAC-002` | 同一契约错位，修复应一端统一（建议后端加别名或前端归一） |
| 幂等键每次重生成 | `BUG-PRAC-003` + `SMELL-FE-UTIL-001` | 功能缺陷；另有 3 份 `generateIdempotencyKey` 实现属重构范畴 |
| 报告 JSON 字段名漂移 | `BUG-DIAG-001`、`BUG-GRADE-005` | 均为前端读取名与后端 schema 不符 |
| 前端调用不存在/不匹配的后端端点 | `BUG-AUTH-004`（PUT /users/me）、`BUG-PRAC-017`（/pause,/resume） | 新增端点或前端下线无效调用 |

## 矩阵总体判定

- 6 切片**全部**存在跨层不一致，**无一片完全通过**。
- 断裂最严重：**PRAC（P0）**、**AUTH（P0 安全）**、**MAT（重拍链路 P1×3）**、**DIAG（P1×8）**。
- 契约核对模式高度重复：**字段命名漂移**（content/text、items/questions、weak_*/weak_points）与**端点语义错位**（401 归类、重拍 multipart、非法 source_type）是两大主因。
