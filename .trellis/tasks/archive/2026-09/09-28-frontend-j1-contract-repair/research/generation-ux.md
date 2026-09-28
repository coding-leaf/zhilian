# Research: 出题范围与题目核对 UX

- Query: 核实单份资料知识点/知识树、生成与审核结果、题源详情的现行 API；判断“默认全资料所有知识点、允许调整”的前端可实现性；查明答案/解析默认展示决策，并收敛最多两个产品问题。
- Scope: internal（规划期源码与仓库产品文档研究；不重复缺陷审查，不修改业务代码）
- Date: 2026-09-28

## Findings

### 1. 结论摘要

1. **“当前资料版本的全部已抽取知识点默认选中，允许调整”可以只改前端实现**：读取知识树，递归收集真实节点 ID，向已有多考点生成接口显式提交。单资料接口不支持用空数组表示全选；也不能拿文件夹接口偷换资料范围。
2. **“所有知识点 + 固定 5 道题”不是当前后端语义**：每个选中知识点至少分配 1 道目标题；选中 K 个、请求 count=C，分配总数为 max(K,C)。这是源码和已有单测确认的行为，不是 UI 可以忽略的细节。请求 count 上限 20 不等于多考点返回总数上限 20。
3. **知识结构低可信与知识点为空必须分开**：低可信且存在真实节点时可继续出题并提示；空树无法合法发起单资料生成，不能临时编造“整份资料”知识点或传资料 ID 冒充知识点 ID。
4. **核对页可直接使用生成响应中的合格/待审核题和批次 ID**，不必另建生成任务轮询接口；重进时按 material_id + batch_id 查询同批题目。待审核题不得进入练习。
5. **答案/解析应可查看已有需求依据，但“默认展开还是折叠”仍未知**。历史核对页 PRD 只写“解析（可折叠）”；错题页“默认折叠”的决定不能套用到作答前的核对页。
6. **作答前的完整题源正文存在真实能力边界**：题目详情只给切片 ID/元数据；知识点切片列表可以匹配通常的直接关联来源，但生成服务也会使用未绑定的检索切片，不能保证该列表包含每道题的实际来源。不能承诺仅改前端就能补全所有预览题的精确正文。

### 2. Files found（现行代码与产品证据）

| 文件 | 用途 |
| --- | --- |
| backend/app/api/v1/__init__.py | 所有业务路由统一挂载 /api/v1。 |
| backend/app/api/v1/knowledge.py | 资料知识树、知识点详情、知识点切片、抽取重试入口。 |
| backend/app/schemas/knowledge.py | 递归 nodes/children、版本 ID、低可信标记、切片正文/页码。 |
| backend/app/services/knowledge.py | 最新版本选择、树装配、空候选拒绝、低可信降级。 |
| backend/app/api/v1/questions.py | 同步生成、题目详情、批次/审核状态分页、质检记录、人工更新。 |
| backend/app/schemas/question.py | 出题必填约束、题量/题型范围、qualified/pending 两类结果。 |
| backend/app/services/question.py | 多考点分配、原子事务、来源检索与切片元数据生成。 |
| backend/app/api/v1/materials.py | 资料详情提供 current_version_id、status、parse_status。 |
| backend/app/models/material.py | 小写就绪/处理中/失败/待重拍状态枚举。 |
| backend/app/api/v1/practices.py、backend/app/schemas/practice.py | 指定 question_ids 创建练习与练习详情中来源摘要 DTO。 |
| backend/app/services/practice.py | 仅使用 available 题目，练习详情按主来源切片 ID 补全文本。 |
| backend/tests/unit/services/test_question_multi_kp.py | “题数少于知识点数仍每点一题”的现有测试证据（本次未运行）。 |
| miniprogram/src/api/index.ts、miniprogram/src/stores/material.ts | 当前 API/store 接入位置；这里只定位承载点，不另列缺陷。 |
| miniprogram/src/subpackages/material/pages/course/index.vue | 当前资料详情/出题入口，可承载范围摘要与调整入口。 |
| miniprogram/src/subpackages/material/pages/questions/index.vue | 当前核对页，可承载批次结果、答案/解析及来源查看。 |
| docs/specs_extracted/智练自主学习平台_软件需求规格说明书_V2.0.md | FR-18 降级、FR-21 来源前置、FR-25 待审核隔离、FR-26 预览编辑等。 |
| .trellis/tasks/09-28-frontend-rebuild-j1-loop/prd.md | 本轮重建的核对页明确要求参考答案与解析可见能力。 |
| .trellis/tasks/archive/2026-09/09-27-question-gen-verify-list/prd.md | 历史题目核对列表要求参考答案、解析“可折叠”。 |
| docs/legacy_sdlc/ZL-136/spec.md | “默认折叠”仅针对练习后的错题卡片。 |

### 3. 真实 API 与必要字段（路径含完整前缀）

公共约定：前缀来自 backend/app/api/v1/__init__.py:15-24；以下接口均使用当前用户鉴权，Authorization: Bearer <access_token>，见 backend/app/api/deps/auth.py:25-36。成功响应直接是所列模型，不应凭空增加 data 包裹。业务错误体为 code/message/details，参数校验失败 HTTP 422、code=10001，见 backend/app/main.py:91-113。

| 场景 | 方法与路径 | 请求与响应中要消费的字段 | 代码证据 |
| --- | --- | --- | --- |
| 获取当前资料版本和就绪状态 | GET /api/v1/materials/{material_id} | 路径为真实资料 UUID；读取 id、title、current_version_id（可空）、status、parse_status、file_format。 | backend/app/api/v1/materials.py:356-403 |
| 获取一份资料的知识树/知识点集合 | GET /api/v1/materials/{material_id}/knowledge-tree?version_id=<UUID> | version_id 可省，但建议使用资料当前版本；返回 material_id、version_id、nodes[]；节点 id、material_id、version_id、parent_id、name、description、level、is_low_confidence、children[]。无分页，无独立“资料平铺知识点列表”接口，前端从树收集。 | backend/app/api/v1/knowledge.py:34-79；backend/app/schemas/knowledge.py:16-45 |
| 单知识点详情 | GET /api/v1/knowledge/{id} | 路径为知识点 UUID；返回归属资料/版本、名称/描述、层级、is_low_confidence 等。全选出题不必逐点请求。 | backend/app/api/v1/knowledge.py:82-107；backend/app/schemas/knowledge.py:48-63 |
| 单份资料出题 | POST /api/v1/questions/generate | JSON 必須 material_id + 非空 knowledge_point_ids，或兼容单个 knowledge_point_id；version_id 可选。count 默认5，1~20；difficulty 默认3，1~5；question_types 非空，J1 用 single_choice/multiple_choice/true_false/short_answer；max_retries 默认2，0~5。字段叫 question_types，不是 types。 | backend/app/schemas/question.py:18-84；backend/app/api/v1/questions.py:99-175 |
| 当次生成结果 | 上述 POST 返回 HTTP 200 | batch_id、material_id、version_id、knowledge_point_ids、total_generated、qualified_count、pending_count、retry_count、qualified_questions[]、pending_questions[]、quality_checks[]。它直接返回本批题目，不是 task_id；total_generated 是落库合格+待审核题总数，不是保证可练题数。 | backend/app/api/v1/questions.py:66-95；backend/app/schemas/question.py:132-163；backend/app/services/question.py:1057-1065 |
| 重进核对页/查询待审核题 | GET /api/v1/questions?material_id=<UUID>&batch_id=<batch>&review_status=available或pending_review&page=1&page_size=20 | batch_id、review_status 为可选过滤；本批核对必须保留 batch_id；返回 items[]、total、limit、offset。page>=1，page_size 1~100；状态也支持 status 别名，但 review_status 优先。可省 review_status 拉同批全部后分组。 | backend/app/api/v1/questions.py:245-313；backend/app/schemas/question.py:184-190 |
| 单题详情/参考答案/来源标识 | GET /api/v1/questions/{id} | 返回 id、material_id、version_id、knowledge_point_id、question_type、status、batch_id、stem、options[]（对象数组）、answer、analysis、difficulty、grading_rubric、source_snippet_id（可空）、source_snippet_ids[]。后两者不是正文。 | backend/app/api/v1/questions.py:179-207；backend/app/schemas/question.py:87-113 |
| 查看拦截原因 | 生成响应 quality_checks[]；重进时 GET /api/v1/materials/{material_id}/quality-checks | 响应 material_id、quality_checks[]；记录含 question_id、batch_id、check_type、is_passed、reason、check_metadata。后一个 API 是整份资料的记录，前端需按本批次/题目关联，不把其他批原因混进来。 | backend/app/api/v1/questions.py:433-463；backend/app/schemas/question.py:116-129,252-258 |
| 预览时取关联来源正文 | GET /api/v1/knowledge/{id}/snippets | 路径用题目的 knowledge_point_id；响应 knowledge_point_id、snippets[]；每项 id、material_id、version_id、page_index（1起）、snippet_index、chapter_title、content、char_length。用题目的真实 source_snippet_id/元数据 snippet_id 精确匹配，不能选列表第一条冒充。 | backend/app/api/v1/knowledge.py:110-138；backend/app/schemas/knowledge.py:66-129 |
| 已有练习的精确主来源摘要 | GET /api/v1/practices/{id} | items[].source_snippet / question_snapshot.source_snippet：id、chapter_title、page_index、snippet_content；可能为空。服务按快照 source_snippet_id 查询，不依赖知识点关联是否齐全。不是作答前的独立题源 API。 | backend/app/api/v1/practices.py:162-189；backend/app/services/practice.py:656-664,722-755；backend/app/schemas/practice.py:140-151,243-246,315-319 |
| 空树恢复的现成写接口（不自动触发） | POST /api/v1/materials/{material_id}/knowledge/extract | 可选 JSON {version_id}；同步返回 material_id、version_id、extracted_count、has_low_confidence、status。是重新抽取操作，不是读树时的免费副作用。成功后需重拉树并清理旧选择。 | backend/app/api/v1/knowledge.py:172-204；backend/app/schemas/knowledge.py:144-162；backend/app/services/knowledge.py:789-822 |

补充边界：已有 PUT /api/v1/questions/{id} 支持更新 stem/options/answer/analysis/difficulty/grading_rubric/status 及原因（backend/app/api/v1/questions.py:316-326；backend/app/schemas/question.py:193-208），但本修复的“核对”不必扩展成完整编辑器，更不能仅凭用户点“确认”就自动把 pending_review 改成 available。

### 4. “默认全资料所有知识点、允许调整”的最小实现约束

**建议的数据流（待用户确认产品含义，并非已批准实现）：**

资料详情 current_version_id → 同版本 knowledge-tree → 全量节点 ID 去重集合 → 默认全选/调整范围 → generate 显式传集合 → 直接展示 batch_id 下 qualified/pending → 以确认的 qualified IDs 创建练习。

- **只覆盖“当前资料版本已抽取的知识点”**，不能声称原文所有章节/所有隐含知识 100% 覆盖。树既含父节点也含子节点，每个节点都是实际知识点；“所有”应收集全部真实节点，不仅根节点或叶节点。折叠只影响显示，不影响全选集合。
- **固定版本**：不传 version_id 时知识服务选的是最新版本（backend/app/services/knowledge.py:665-674），未必等于用户当前激活版本。读树与出题显式传同一版本，节点归属也应一致。生成服务会将版本对齐到知识点归属（backend/app/services/question.py:791-804），这不是前端混用旧知识点的许可。
- **轻量 UI 足够**：在现有资料页展示“已选 K / 共 N 个知识点”与“调整范围”，需要时呈现带层级缩进的勾选列表、全选/清空；复用当前核对页，不恢复旧全量资料管理模块，不引入通用流程引擎。渲染树可以拍平成列表，但不能靠拍平掩盖缺失/非法的节点 ID。
- **题量的真实语义**：backend/app/services/question.py:397-418,1105-1137 对去重后的 K 点分配 max(C,K) 个目标题，再逐点生成。例如选8点请求5题，目标是8题；选30点请求20题，目标是30题。最终可练题还可能因质检减少，需同时显示计划目标、合格数、待审核数。单测 backend/tests/unit/services/test_question_multi_kp.py:111-118 已钉死每点至少1题。
- **不能静默缩范围**：若产品要固定5题、但仍声称考了全部8点，当前接口不满足。前端偷偷截前5个知识点，或对全部生成后只取5题，都改变“全覆盖”的含义。
- **大范围需限界**：多考点请求没有知识点个数上限，逐点同步出题可能很慢；不得据 count<=20 宣称最多20道、很快完成。练习 question_count 的显式契约是1~50（backend/app/schemas/practice.py:68-73）；全选可能超过此规模，J1 必须显式提示调整范围或另行规划拆批，不能静默截断，也不应依赖后置校验器自动回填题数时的边界绕过行为。
- **不要预检误拒绝**：知识点关联切片为空不必然不可出题，检索适配器还可补齐来源（backend/app/services/question.py:657-729）。无需逐节点额外请求切片来“认证可用”；由后端最终来源门禁判定。
- **一处不可用会使整批失败**：多个考点共一事务，任何考点无有效来源等异常都会回滚（backend/app/services/question.py:1082-1083,1120-1156）。不可宣称其余考点已成功生成，不自动跳过出错知识点；提示原因、保留用户选择并允许调整后再试。

#### 空知识点与结构降级矩阵

| 情况 | 可以做什么 | 不能做什么 / 证据 |
| --- | --- | --- |
| 正在解析/抽取 | 显示处理状态，待就绪再读树；允许返回 | 不把暂时空树当最终无知识点；状态见 backend/app/models/material.py:34-54。 |
| 资料/版本 ready，但 nodes=[] | 禁用生成，明确“暂无可用知识点”，提供刷新、回资料处理入口；如本任务批准恢复按钮，可调用现成抽取接口后重新载入 | 不把 [] 解释为全选；schema 会拒绝。抽取最终零候选在 backend/app/services/knowledge.py:516-524 抛错。 |
| 用户主动清空选择 | 禁用生成，提示至少选择1个；提供全选 | 不默默替用户重新选中，更不能自动改成文件夹全范围。 |
| 节点正常、is_low_confidence=true | 保留真实 ID 继续允许出题，在范围区提示“知识结构可信度较低”，保持该信息供报告消费 | 不因低可信直接禁用，也不无依据显示该警告。产品 FR-18 与 backend/app/services/knowledge.py:506-535 一致。 |
| 层级只有一层/需要平铺显示，但真实节点有效 | 按实际节点显示勾选列表；层级退化和无节点是不同状态 | 不凭“一层”自己生成低可信标记；依据服务返回标记。树装配见 backend/app/services/knowledge.py:680-702。 |
| 结构缺字段/ID 非法/跨版本 | 显示加载/数据异常、允许重试；不要把不完整集合描述为全部 | 不用索引、名称、资料 ID 合成出题 ID，也不悄悄删除坏节点后声称全覆盖。 |
| 来源门禁失败 | 显示后端原因，保留范围，允许用户调整或处理资料 | 不切换“无资料常识生成”；backend/app/services/question.py:731-739。 |

### 5. 核对页、待审核题和题源的可实现 UX

**最小可核验结果页：**

- 接收本批生成响应，显示“可练 X 道 / 待审核 Y 道”，分区而不是混算为可答总数。待审核区展示失败 check_type/reason，只读即可满足本次核对研究范围；无合格题时禁用“开始作答”。这遵循 FR-25（SRS V2.0:300）。
- 保留 material_id + version_id + batch_id 等范围标识；页面重进按批次拉取分页结果。batch_id 缺失时不能用整份资料历史题冒充刚生成结果；只能明确这是历史题库视图，或引导重新进入正确批次。现有 GET /questions 不提供生成任务进度，也没有独立批次任务查询端点。
- 每题展示题型、题干、选项、知识点/来源查看入口；answer/analysis 的显隐等第7节问题2确认。不要为了“像测验”删掉历史明确要求的核对能力。
- “开始作答”使用 POST /api/v1/practices，最小体为 title、material_id、question_ids（确认的本批 available 题 ID）、question_count（与确认题数一致且在契约范围内）；可用 Idempotency-Key 防重复创建。见 backend/app/api/v1/practices.py:48-91；backend/app/schemas/practice.py:47-103,124-136。backend/app/services/practice.py:432-470 会筛选可用题并按数量截取，因此应核对服务返回的实际题集，不把失效/待审题混入确认列表。

**题源查看务必区分能力层次：**

1. **题目详情的 source_snippet_ids 不是正文**：生成服务实际存 [{snippet_id, similarity, index}]，见 backend/app/services/question.py:439-466,963-980；不能直接渲染为讲义引用。
2. **作答前可做的匹配**：用户点“查看来源”时，用 knowledge_point_id 调知识点切片 API，按真实主来源 ID 精确匹配，显示 content、chapter_title、page_index；同一知识点可在页面内缓存，避免每题重复取相同列表。多来源应区分“主来源”和“生成上下文”，不能把所有检索片段都称为直接答案依据。
3. **不能保证覆盖的情况**：生成服务补充的未绑定切片（backend/app/services/question.py:725-729）可能不在知识点反查列表中；后者只读已有关系（backend/app/services/knowledge.py:737-755）。扫描现有 api/v1 未找到 GET /questions/{id}/source 或按切片 ID 取正文的独立 API。GET /knowledge/snippets/{snippet_id}/knowledge-points 只是查知识点，不是取正文。
4. **精确来源未匹配时**：明确“来源正文暂不可用”，保留返回的标识，不拿其他切片替代，不伪造页码/摘录；如果验收要求每题作答前都能查看精确原文，这属于后端能力缺口，需要主会话显式确认小范围补齐，不能隐瞒为前端已完成。
5. **练习创建后已有精确主来源**：GET /practices/{id} 会补全 source_snippet；不推荐为了核对题源就提前创建一次练习，此举会污染未开始/恢复入口。该接口亦未承诺全部多切片上下文正文或原始文档高亮/照片访问链接。

### 6. 答案/解析的产品文档调查结论

| 证据 | 可以得出的结论 | 不可外推的结论 |
| --- | --- | --- |
| SRS V2.0:289-301（FR-22、FR-26） | 题目应有答案与解析，用户要能预览核对/编辑 | 没写作答前默认展开还是默认折叠。 |
| .trellis/tasks/09-28-frontend-rebuild-j1-loop/prd.md:29-32 | 当前重建核对页要包含参考答案与解析，并能开始答题 | “包含”不能推导为首次进入自动展开。 |
| .trellis/tasks/archive/2026-09/09-27-question-gen-verify-list/prd.md:9-13 | 历史核对列表：题型、难度、题干、参考答案、解析（可折叠） | “可折叠”未定义初始状态，也未明确答案是否与解析一起折叠。 |
| docs/legacy_sdlc/ZL-136/spec.md:102-107 | 练习后错题卡片答案对比/解析明确默认折叠 | 是错题复习场景，不是出题质量核对场景。 |
| miniprogram/src/subpackages/material/pages/questions/index.vue:20-38 | 当前模板展示题干/选项/可选来源，没有答案/解析区域 | 当前缺展示不能当成用户已批准“禁止预览答案”。 |

结论：**默认状态未知，须问用户**。本次已检索 docs（含产品基线、DESIGN、legacy_sdlc）和 .trellis/tasks 的 Markdown 中“预览/核对/答案/解析/默认/折叠”相关证据。未发现能替当前核对页作默认状态决策的明确文档。

### 7. 最多两个必须由用户决定的产品分歧

以下是供主会话依次提问的问题，不是本研究代替用户拍板。

**问题1：默认范围与题量冲突时，优先全部知识点覆盖，还是严格固定题数？**

- 建议提问：“是否采用默认选中当前资料版本的全部已抽取知识点、允许调整，并在知识点多于题数时，明确提示至少每点1题、实际目标数随之增加（过大范围需先调整），而不是保证固定5题？”
- **推荐：默认全选、允许调整，覆盖优先并在生成前显示真实预计题量。** 复用现有接口，用户不必先理解复杂知识树；代价是资料较大时等待更长、题数可能高于输入目标，超过单次练习契约规模需调整范围。
- **另一选择：固定少量题优先。** 需用户明确选较小范围，或另定抽样规则，并承认这不是“所有知识点都覆盖”；若还要求全部 ID 传入、后端自己抽样固定题数，则现行接口语义需变更。不能偷偷替用户选前几个知识点。

**问题2：进入核对页时，答案/解析默认展开，还是默认折叠、点开才看？**

- **推荐：默认折叠但提供明显的“查看答案与解析”，来源正文同样按需查看。** 兼顾已有核对能力与随后作答不被动提前看到答案，不另建测验/学习双模式；代价是逐题深度核对需要多一次点击，主动看过答案后的练习也不能称为盲测。
- **另一选择：默认展开。** 更利于立即审核生成质量、符合“先核对再练”的学习式流程；代价是作答前已经见过答案/解析，不能再把后续得分当未经提示的自测表现。
- 这两种都可只改前端；后端本就返回 answer/analysis。是否默认展示不是技术问题，不能用现有字段存在与否代替产品决定。

### 8. Code patterns 与后续小范围验证建议

- 契约只在 API 边界适配一次：knowledge-tree 的 nodes/children，题目分页 items，生成的 qualified/pending，均保留真实 UUID 与 batch_id；页面不再猜测第二种结构。依据 .trellis/spec/guides/cross-layer-thinking-guide.md:48-62,87-98。
- 核对数据与显示控制分离：答案/解析的展开状态不修改题目对象或审核状态；visibleRows 的折叠不改变全量 selectedIds。只需局部状态和纯数据转换，无须新建统一状态机框架。
- 后续实现阶段应有针对性用例：空树/低可信树/父子全量去重/切换版本/全清空；K>C 时题数提示；合格与待审核混合及全待审核；重进按批次分页；来源精确匹配失败；确认题集与创建练习实际题集一致。**本次未执行这些测试，也未运行完整门禁。**

### 9. Related specs / External references

- .trellis/workflow.md：规划先行与研究持久化；本次未启动实现。
- .trellis/tasks/09-28-frontend-j1-contract-repair/prd.md：AC1“选择范围出题并正确核对返回题目”，以及范围/答案显隐待决策项。
- .trellis/spec/frontend/index.md:31-36：J1 从资料到核对再到练习的边界。
- .trellis/spec/frontend/type-safety.md:46-56,85-92：原始响应与领域类型隔离、禁止自造漂移字段；其中部分旧文件路径在重建后已非现状，只采纳契约原则，不声称旧 adapter/树组件仍存在。
- .trellis/spec/guides/cross-layer-thinking-guide.md:40-62,87-98：标明边界与单一契约转换位置。
- 产品版本：仓库内《软件需求规格说明书 V2.0》（正式基线 2026-09-21，文件:15）及本任务/关联任务 PRD；不把历史全量功能自动纳入 J1。
- External references：无。本题研究的是本仓库现行实现与已有产品决定，未引用外部时效性事实、未联网、不引入外部库或行业默认 UX 替用户作决定。

## Caveats / Not Found

- 仅源码/文档研究，未调用真实账号 API、LLM、数据库或微信客户端；不声称 E2E 可用或质量门禁通过。
- “全选可实现”不等于保证每点最终生成合格题、不等于全资料原文绝对覆盖，也不等于固定输入题数；多考点失败会整批回滚。
- 无独立生成任务进度/恢复查询接口；POST 超时不能直接认定服务端没有生成，也不能无提示自动重发。正常拿到 batch_id 后的分页恢复是现成能力；未拿到批次响应时的精确恢复不在本报告承诺内。
- 作答前每道题的精确来源正文并非现有 API 全面覆盖；若 AC1 的“核对”包含这项强保证，需主会话明确后端补齐边界，不能以其他知识点片段伪装来源。
- SRS FR-27 写1~50题，但当前生成请求 schema 实际1~20，多考点总量又可能超过20；本研究以现行代码为调用契约，矛盾须在规划中如实说明，不据产品旧文档直接发 count=50。
- 核对页答案/解析的初始展开状态仍无明确已批准决定；上述推荐不构成替用户选择。
- 本次只新建 research/generation-ux.md；未覆盖他人文件，未修改业务代码、PRD、规范或任务状态，未执行 git 操作或完整门禁。
