# Intent: 资料分块算法实现

- **任务编号**: ZL-107
- **提出人**: Dev
- **创建时间**: 2026-09-23 18:49
- **初始 Change Tier**: Tier 2
- **当前状态**: Draft / In-Review / Accepted

---

## 1. 问题与现状背景 (Problem)
在智练自主学习平台流水线中，学习资料（原生文档解析文本与纸质拍照 OCR 识别文本）是后续知识点抽取与建树、题目生成与来源溯源的关键基石。
当前系统尚未实现用于将解析后段落切分为可检索知识片段的纯函数计算核。缺少健壮的资料切分算法会导致长文本超出 LLM 上下文窗口、知识点提取不均、向量检索粒度过粗、跨片段语义断裂以及题目溯源缺失。
根据需求规格说明书 FR-07、非功能性需求 NFR-22 以及概要设计第 6.1 节与第 7.1 节，资料切分逻辑必须封装为脱离数据库、网络与 Web 框架的独立纯函数计算核，并具备严谨的边界处理、降级机制与 100% 分支覆盖率。

## 2. 变更性质分类 (Change Archetype - 单选)
- [ ] 局部结构精简 (Local Cleanup - 仅限模块内部冗余消除，不改数据流向与全局装配)
- [x] 单模块特性演进 (Single-Module Feature - 单一模块业务增量或修复)
- [ ] 跨领域架构重构 (Cross-Domain Rewiring - 触及应用全局装配、生命周期或跨域流向，必须升 Tier 3)

## 3. 期望达成效果 (Proposed Outcome)
在 `backend/app/core/algorithms/` 模块下实现资料分块纯函数计算核 `split_material_into_snippets` 及轻量数据模型，达成以下效果：
1. **标准化切分能力**：接收段落序列（`paragraphs: list[str]`）、片段上限（`max_chars: int = 800`）、重叠量（`overlap_chars: int = 120`，约 15%）、可选标题层级标记与来源映射；输出结构化知识片段列表（含起止字符偏移、所属章节标题、来源标记、资料类型标记与顺序号）。
2. **多层级切分与降级决策**：
   - 连续短段累加合并（不超过 800 字符，换行符分隔）；
   - 超长段落优先按句末标点（。！？.!?）分句累加切分；句末标点缺失时降级查找逗号、分号或顿号；仍无合适标点时按窗口硬切；
   - 相邻片段保留 120 字符重叠，且重叠起点对齐至最近句子起始位置；
   - 遇到标题标记强制开启新片段并将标题作为后续片段的章节归属（标题自身不作为独立片段）；
   - 字符数小于上限 1/10（<80 字符）的孤立短段自动向后合并，末尾段向前合并；
   - 单段超过上限 10 倍时按固定窗口硬切并在窗口内二次标点微调；
   - 重叠量大于等于片段上限时优雅退化为无重叠切分并记录参数告警，不抛出非预期崩溃；
   - 单份资料达到 3000 个片段上限时安全截断并返回截断元数据与原始总量，调用方标记部分处理；
   - 输入包含不可见 Unicode 或控制字符时预清洗并记录字符数变化。
3. **性能与质量达标**：
   - 20 万字符吞吐切分耗时 $\le 2\text{s}$（循环内禁止字符串拼接累加，使用高效内存操作）；
   - 主切分函数环路复杂度 $V(G) \le 12$；
   - 达到 100% 分支覆盖率与等价类/边界值全覆盖（涵盖长度为 1、上限、上限+1、重叠 0 与上限、孤立短段、空输入/全空白等）。

## 4. 波及工程分面 (Affected Architectural Layers)
- [x] 核心领域与计算逻辑 (Domain & Core Business Logic)
- [ ] 外部接口与协议入口 (Public Ingress & Controllers & Protocols)
- [ ] 数据持久化与状态存储 (Database & Storage & Schemas)
- [ ] 全局装配与应用入口 (Bootstrap & Lifecycle & Service Wiring)

## 5. 边界与硬性约束 (Constraints & Boundaries)
* **硬性技术制约**:
  - 纯函数无外部 I/O 与副作用：绝对禁止导入 `fastapi`、`sqlalchemy`、`httpx`、`redis`、`boto3`，严禁导入 `app/services` 与 `app/repositories`，输入输出均为原生数据结构或不可变领域模型；
  - 架构分层防线：严格位于 `backend/app/core/algorithms/`，通过 `tooling/check_layers.py` 严格校验；
  - 白盒复杂度红线：主切分函数环路复杂度 $V(G) \le 12$，复杂判定逻辑必须前置拆解子函数；
  - 测试与覆盖率红线：分支覆盖率强制 100%，行覆盖率 $\ge 95\%$；测试运行在毫秒级且严禁真实联网；禁止使用 Mock 替身打桩内部逻辑；
  - 命名与代码规范：全英文标识符，严格遵守 8 个缩写白名单（`api`, `id`, `url`, `ocr`, `llm`, `db`, `config`, `env`），Google 风格中文 Docstring，阈值常量显式注明依据；
  - 性能红线：20 万字样本切分耗时 $\le 2\text{s}$，循环内避免低效字符串拼接累加。
* **明确非目标 (Non-Goals / Out-of-Scope)**:
  - 不包含 PDF/Word/TXT 原生解析器或 OCR 服务调用（由 `backend/app/integrations/` 负责）；
  - 不包含向量嵌入计算（Embedding）及 pgvector 数据库入库持久化（由 `backend/app/services/` 编排）；
  - 不包含大模型出题与知识点抽取工作流（由后续 ZL-109 等特性负责）；
  - 不包含对外暴露的 HTTP API 端点（仅通过纯函数供服务层调用）。
* **完成判定条件 (Definition of Done)**:
  - 资料分块算法函数与数据模型在 `backend/app/core/algorithms/` 完整定义；
  - 单元测试覆盖全部等价类与边界值用例（长度为 1、等于上限、上限加 1；重叠 0 与上限；单段超长截断；孤立短段合并；空输入与全空白输入），分支覆盖率达到 100%；
  - 静态检查全绿：`ruff format --check`、`ruff check`、`mypy app`、`bandit -r app -ll` 全部通过；
  - 架构依赖合规：`python3 tooling/check_layers.py --root backend/app` 0 违规；
  - 门禁合规检查：`python3 tooling/check_sdlc_integrity.py` 校验通过。

## 6. 未决疑问与待探讨点 (Open Questions)
- 疑问 1：截断（超过 3000 片段）发生时，数据结构的承载方式选择：采用专门的包装对象（如 `ChunkingResult` 携带 `snippets: list[Snippet]`、`is_truncated: bool`、`total_count: int`），还是保持 `list[Snippet]` 返回并在元数据或自定义属性中标记？
  - **决策结果**：经用户决策确认，采用专门的包装对象（`ChunkingResult`）承载切分结果、截断状态与元数据，并在 `spec.md` 中严格冻结其类型定义。
- 疑问 2：针对代码块或多行表格等特殊段落，当前阶段按统一段落文本处理，后续服务层在调用切分前是否需传入特殊段落保护标记，以防止表格行被中断？

---

## 7. 阶段准出签批 (Gate 1 Sign-off)
- [x] 场景与问题已客观复现并达成共识
- [x] 边界、非目标与约束清晰明确
- [x] 初始 Change Tier 评定合理
- **准出结论**: Accepted
- **签批人 / 日期**: yezisama / 2026-09-23
