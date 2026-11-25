"""知识点抽取建树与质检重抽服务编排模块。

统领学习资料切片的大模型结构化抽取、向量语义去重、门禁质检验证、
重抽反馈循环、拓扑层级自愈及事务持久化落库。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 结构化脱敏日志 8 要素输出，严禁向日志记录切片文本或知识点原文。
"""

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.core.algorithms.document_denoising import (
    filter_and_rank_evidence_snippets,
    strip_display_watermark_lines,
)
from app.core.algorithms.knowledge_quality import (
    CandidateKnowledgePoint,
    ExtractionContext,
    verify_knowledge_points,
)
from app.core.algorithms.knowledge_tree import (
    ExtractedKnowledgeItem as ExtractedKnowledgeItem,
)
from app.core.algorithms.knowledge_tree import (
    KnowledgeExtractionOutput as KnowledgeExtractionOutput,
)
from app.core.algorithms.knowledge_tree import (
    build_structured_content,
    resolve_knowledge_hierarchy,
)
from app.core.algorithms.knowledge_tree import (
    compute_chapter_stats as compute_chapter_stats,
)
from app.core.algorithms.knowledge_tree import (
    deduplicate_candidate_points as deduplicate_candidate_points,
)
from app.core.algorithms.knowledge_tree import (
    normalize_extracted_temp_ids as normalize_extracted_temp_ids,
)
from app.core.errors import (
    KnowledgeExtractionRetryExceededError,
    KnowledgeNotFoundError,
    MaterialInvalidError,
    MaterialNotFoundError,
)
from app.core.security import generate_user_ref
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
)
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import MaterialSnippet, ParseStatus
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository

logger = logging.getLogger(__name__)


_DEFAULT_MAX_BATCH_SNIPPETS: int = 12
_RETRY_MAX_BATCH_SNIPPETS: int = 8
_DEFAULT_MAX_BATCH_CHARS: int = 6000


def _has_structured_fields(item: ExtractedKnowledgeItem) -> bool:
    """判断抽取条目是否提供了任何结构化复习卡片字段（兼容旧无结构化桩数据）。"""
    return bool(
        (item.core_summary or "").strip()
        or item.key_takeaways
        or item.key_formulas
        or item.boundary_notes
        or item.derivation_steps
        or item.common_mistakes
    )


def _build_snippet_batches(
    snippets: Sequence[MaterialSnippet],
    max_batch_snippets: int,
    max_batch_chars: int = _DEFAULT_MAX_BATCH_CHARS,
) -> list[list[MaterialSnippet]]:
    """按切片条数与字符预算双限分批，并尽量贴合章节边界切分，避免单次输入过满。"""
    if not snippets:
        return []
    snippet_cap = max(1, max_batch_snippets)
    char_cap = max(1, max_batch_chars)
    soft_count_floor = max(1, snippet_cap // 2)
    soft_char_floor = int(char_cap * 0.6)

    batches: list[list[MaterialSnippet]] = []
    current: list[MaterialSnippet] = []
    current_chars = 0

    for snip in snippets:
        snip_len = max(snip.char_length or 0, len(snip.content or ""))
        if current:
            exceeds_count = len(current) >= snippet_cap
            exceeds_chars = current_chars + snip_len > char_cap
            chapter_changed = (snip.chapter_title or "").strip() != (
                current[-1].chapter_title or ""
            ).strip()
            near_budget = len(current) >= soft_count_floor or current_chars >= soft_char_floor
            if exceeds_count or exceeds_chars or (chapter_changed and near_budget):
                batches.append(current)
                current = []
                current_chars = 0
        current.append(snip)
        current_chars += snip_len

    if current:
        batches.append(current)
    return batches


def build_knowledge_hierarchy(
    items: Sequence[ExtractedKnowledgeItem],
    *,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    user_id: uuid.UUID,
    batch_id: str,
    is_low_confidence: bool = False,
) -> tuple[list[KnowledgePoint], dict[str, uuid.UUID]]:
    """将抽取的扁平节点解析并自愈为树形拓扑实体。

    处理孤儿节点自愈与环形依赖，限制层级深度在 1~5。

    Args:
        items: 候选知识点 DTO 列表。
        material_id: 归属资料标识。
        version_id: 归属版本标识。
        user_id: 租户用户标识。
        batch_id: 抽取批次标识。
        is_low_confidence: 是否标记为低可信度。

    Returns:
        tuple[list[KnowledgePoint], dict[str, uuid.UUID]]: (实体列表, temp_id 到实体 UUID 映射)。
    """
    nodes, temp_to_uuid = resolve_knowledge_hierarchy(items)
    result_points = [
        KnowledgePoint(
            id=node.id,
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            parent_id=node.parent_id,
            name=node.name,
            description=node.description,
            structured_content=node.structured_content,
            sort_order=node.sort_order,
            level=node.level,
            batch_id=batch_id,
            is_low_confidence=is_low_confidence,
        )
        for node in nodes
    ]
    return result_points, temp_to_uuid


# ==============================================================================
# 服务主类实现
# ==============================================================================


class KnowledgeService:
    """知识点领域核心编排服务。

    负责全流程调度切片分批、大模型结构化抽取、向量语义去重、门禁质检重抽熔断与拓扑落库。
    """

    def __init__(
        self,
        session: Session,
        llm: LLMProtocol,
        embedding: EmbeddingProtocol,
    ) -> None:
        """初始化知识点服务实例。

        Args:
            session: SQLAlchemy 数据库会话。
            llm: 大模型网关适配器。
            embedding: 向量化网关适配器。
        """
        self.session = session
        self.llm = llm
        self.embedding = embedding
        self.knowledge_repo = KnowledgeRepository(session)
        self.material_repo = MaterialRepository(session)

    def _build_batch_prompt(
        self,
        snippets: Sequence[MaterialSnippet],
        feedback: str | None = None,
        existing_outline: Sequence[dict[str, Any]] | None = None,
    ) -> list[LLMMessage]:
        """构建知识点抽取的大模型输入消息序列。

        Args:
            snippets: 当前批次的切片序列。
            feedback: 上一轮质检失败反馈（若有）。
            existing_outline: 前序批次已抽取的知识点骨架列表 ``{temp_id, name, level}``。

        Returns:
            list[LLMMessage]: 大模型上下文消息列表。
        """
        system_content = (
            "你是一个专业的考纲分析与知识图谱构建专家。"
            "请从所提供的切片内容中抽取关键知识点及其父子层级关系，"
            "生成可直接用于考前复习的结构化知识卡片。\n"
            "【抽取规范】\n"
            "1. 每个知识点必须有 2~30 字符规范名称，严禁数字编号前缀与占位词；\n"
            "2. **严禁**从目录页、章末小结页、课程介绍、教学目标、参考文献、致谢页抽取元结构知识点"
            "（如「本章知识小结梳理」「知识梳理」「重点回顾」「目录结构」）；"
            "若切片仅罗列章节标题或名词而无具体原理/定义/公式/步骤，必须忽略该切片；\n"
            "3. 正确标注父节点 temp_id，无父节点设为 null，层级深度 1~5 级；\n"
            "4. 记录来源片段序号 (source_snippet_indices)；\n"
            "5. 必须基于原文切片中的定义、推导与前后文，用清晰的教学复习语言填写结构化内容：\n"
            "   - core_summary：60~180 字符核心定义与直觉"
            "（讲清是什么+解决什么问题+核心意义，严禁重复标题或写「未展开」等废话）；\n"
            "   - key_takeaways：2~5 条完整复习陈述句"
            "（每条 15~80 字，包含主语与核心结论，可直接背诵，严禁只列 2~5 字裸名词）；\n"
            "   - key_formulas：关键公式（标准 `$...$` 或 `$$...$$` LaTeX）并说明关键符号含义"
            "（如 `$\\min \\frac{1}{2}\\|w\\|^2 + C\\sum \\xi_i$，$w$ 为法向量`，"
            "纯概念类可为 []）；\n"
            "   - derivation_steps：0~5 步推导或解题步骤"
            "（如「1. 构造拉格朗日函数 → 2. 求偏导置零」，纯概念类可为 []）；\n"
            "   - boundary_notes：前提假设、适用场景与相邻易混概念对比（无则 []）；\n"
            "   - common_mistakes：0~3 条高频易错点与纠偏（如「误区：…；正解：…」，无则 []）；\n"
            "   - **严禁捏造任何考试频次、重要度星级或'高频必考'等原文不存在的标签**；\n"
            "6. 输出严格符合 JSON Schema 规范。"
        )
        if feedback:
            system_content += f"\n\n【上一轮质检未通过反馈与整改要求】\n{feedback}"

        user_content_lines = []
        if existing_outline:
            outline_lines = [
                f"- temp_id={node['temp_id']} | name={node['name']} | level={node['level']}"
                for node in existing_outline
            ]
            user_content_lines.append(
                "【已抽取知识点骨架（若本批内容属于上述节点的下级分支，请直接引用对应 temp_id 作为 "
                "parent_temp_id，避免重复定义同名父节点）】\n" + "\n".join(outline_lines)
            )
        user_content_lines.append("请从以下切片内容中抽取知识点：")
        for s in snippets:
            ch_info = f" [章节: {s.chapter_title}]" if s.chapter_title else ""
            user_content_lines.append(f"片段 #{s.snippet_index}{ch_info}:\n{s.content}")

        return [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content="\n\n".join(user_content_lines)),
        ]

    def _extract_batch_points(
        self,
        snippets: Sequence[MaterialSnippet],
        feedback: str | None = None,
        existing_outline: Sequence[dict[str, Any]] | None = None,
    ) -> list[ExtractedKnowledgeItem]:
        """调用大模型抽取单批次切片的候选知识点。

        Args:
            snippets: 单批切片序列。
            feedback: 上一轮质检反馈。
            existing_outline: 前序批次已抽取知识点骨架。

        Returns:
            list[ExtractedKnowledgeItem]: 抽取的知识点项。
        """
        messages = self._build_batch_prompt(snippets, feedback, existing_outline=existing_outline)
        options = LLMOptions(temperature=0.3, max_tokens=4096, timeout=90.0)

        output, _ = self.llm.generate_structured(
            messages=messages,
            response_model=KnowledgeExtractionOutput,
            options=options,
        )
        return output.knowledge_points

    @staticmethod
    def _emit_progress(
        on_progress: Callable[[int, int, str], None] | None,
        completed: int,
        total: int,
        stage: str,
    ) -> None:
        if on_progress is None:
            return
        try:
            on_progress(completed, total, stage)
        except Exception:
            logger.warning("knowledge extraction progress callback failed", exc_info=True)

    def _validate_and_load_snippets(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        snippets: Sequence[MaterialSnippet] | None = None,
    ) -> list[MaterialSnippet]:
        """校验资料与版本归属并装载用于知识点抽取的切片列表。"""
        material = self.material_repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError(
                "请求的学习资料不存在或已被删除",
                details={"material_id": str(material_id)},
            )
        version = self.material_repo.get_version_by_id(version_id, user_id)
        if version is None:
            raise MaterialNotFoundError(
                "请求的资料版本不存在或已被删除",
                details={"version_id": str(version_id)},
            )
        resolved = (
            list(snippets)
            if snippets is not None
            else self.material_repo.get_snippets(version_id, user_id)
        )
        if not resolved:
            raise MaterialInvalidError(
                "学习资料切片为空，无法进行知识点抽取",
                details={"material_id": str(material_id), "version_id": str(version_id)},
            )
        if snippets is None:
            for snippet in resolved:
                # 预读后续纯内存计算所需属性并脱离会话，避免释放只读事务后触发懒加载
                _ = (
                    snippet.id,
                    snippet.snippet_index,
                    snippet.chapter_title,
                    snippet.content,
                    snippet.char_length,
                    snippet.source_info,
                )
                if snippet in self.session:
                    self.session.expunge(snippet)
        return resolved

    def _release_read_only_transaction(self) -> None:
        """在长耗时外部 LLM/Embedding I/O 之前释放只读事务，归还数据库连接池。"""
        if not self.session.new and not self.session.dirty and not self.session.deleted:
            self.session.rollback()

    def _run_extraction_with_retries(
        self,
        snippets: list[MaterialSnippet],
        batch_size: int,
        *,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> tuple[list[ExtractedKnowledgeItem], bool, int]:
        """执行分批抽取、向量语义去重与质量门禁重抽循环（最多 2 次重抽）。"""
        chapter_stats = compute_chapter_stats(snippets)
        total_effective_chars = sum(s.char_length for s in snippets)
        current_batch_size = batch_size
        prompt_feedback: str | None = None
        re_extract_count = 0
        is_low_confidence = False
        deduped_items: list[ExtractedKnowledgeItem] = []

        while re_extract_count <= 2:
            batches = _build_snippet_batches(
                snippets,
                max_batch_snippets=current_batch_size,
                max_batch_chars=_DEFAULT_MAX_BATCH_CHARS,
            )
            raw_extracted: list[ExtractedKnowledgeItem] = []
            outline_skeleton: list[dict[str, Any]] = []
            total_batches = len(batches)
            for batch_idx, batch in enumerate(batches):
                batch_items = self._extract_batch_points(
                    batch,
                    prompt_feedback,
                    existing_outline=outline_skeleton if batch_idx > 0 else None,
                )
                raw_extracted.extend(batch_items)
                for kp_item in batch_items:
                    outline_skeleton.append(
                        {
                            "temp_id": kp_item.temp_id,
                            "name": kp_item.name,
                            "level": kp_item.level,
                        }
                    )
                self._emit_progress(
                    on_progress,
                    batch_idx + 1,
                    total_batches,
                    ParseStatus.EXTRACTING_KNOWLEDGE.value,
                )

            if not raw_extracted:
                if re_extract_count >= 2:
                    break
                re_extract_count += 1
                current_batch_size = min(current_batch_size, _RETRY_MAX_BATCH_SNIPPETS)
                prompt_feedback = "上一轮未抽取到任何有效知识点，请降低粒度并认真分析片段正文内容。"
                continue

            self._emit_progress(on_progress, 1, 1, ParseStatus.AUDITING_KNOWLEDGE.value)
            embed_texts = [f"{it.name} {it.description}".strip() for it in raw_extracted]
            embeddings = self.embedding.embed_documents(embed_texts)
            deduped_items = deduplicate_candidate_points(
                raw_extracted,
                embeddings,
                similarity_threshold=0.92,
            )
            deduped_items = normalize_extracted_temp_ids(deduped_items)

            parent_temp_ids = {it.parent_temp_id for it in deduped_items if it.parent_temp_id}
            candidate_points = [
                CandidateKnowledgePoint(
                    name=it.name,
                    level=it.level,
                    chapter_title=it.chapter_title,
                    snippet_ids=tuple(str(idx) for idx in it.source_snippet_indices),
                    description=it.description,
                    structured_content=(
                        build_structured_content(it) if _has_structured_fields(it) else None
                    ),
                    is_leaf=(it.temp_id not in parent_temp_ids),
                )
                for it in deduped_items
            ]
            report = verify_knowledge_points(
                candidate_points,
                ExtractionContext(
                    total_snippets=len(snippets),
                    effective_chars=total_effective_chars,
                    chapter_stats=chapter_stats,
                    re_extract_count=re_extract_count,
                ),
            )
            if report.is_qualified:
                break
            if re_extract_count < 2:
                re_extract_count += 1
                current_batch_size = min(current_batch_size, _RETRY_MAX_BATCH_SNIPPETS)
                prompt_feedback = report.prompt_feedback
            else:
                is_low_confidence = True
                break

        return deduped_items, is_low_confidence, re_extract_count

    def extract_and_build_knowledge_tree(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        batch_size: int = _DEFAULT_MAX_BATCH_SNIPPETS,
        snippets: Sequence[MaterialSnippet] | None = None,
        replace_snippets: bool = False,
        defer_commit: bool = False,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> list[KnowledgePoint]:
        """端到端编排切片抽取、语义去重、门禁质检、熔断重抽与建树持久化。

        Args:
            material_id: 资料主键。
            version_id: 版本主键。
            user_id: 租户用户主键。
            batch_size: 默认批次切片大小，默认 40。
            snippets: 可选预切分切片列表（供流水线在未落库前先完成抽取，避免失败破坏旧数据）。
            replace_snippets: 为 True 时在抽取与质检全部通过后同一事务内替换旧切片。
            defer_commit: 为 True 时仅执行 flush，由调用方统一提交或回滚事务。
            on_progress: 可选进度回调函数 ``(completed, total, stage)``。

        Returns:
            list[KnowledgePoint]: 已持久化构建完成的知识点实体列表。

        Raises:
            MaterialNotFoundError: 资料或版本不存在、已删除或所属租户不匹配。
            MaterialInvalidError: 切片为空无法进行抽取。
            KnowledgeExtractionRetryExceededError: 重试耗尽且未生成任何候选知识点。
        """
        start_time = time.perf_counter()
        user_ref = generate_user_ref(user_id)

        resolved_snippets = self._validate_and_load_snippets(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
            snippets=snippets,
        )
        # 释放只读事务，禁止在长耗时 LLM + Embedding 网络调用期间占用数据库连接
        self._release_read_only_transaction()
        deduped_items, is_low_confidence, re_extract_count = self._run_extraction_with_retries(
            resolved_snippets,
            batch_size,
            on_progress=on_progress,
        )

        if not deduped_items:
            raise KnowledgeExtractionRetryExceededError(
                "知识点抽取重试次数耗尽且未生成任何候选知识点",
                details={
                    "material_id": str(material_id),
                    "version_id": str(version_id),
                    "re_extract_count": re_extract_count,
                },
            )

        # 拓扑解析与孤儿/环形自愈建树
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        points_to_save, temp_to_uuid = build_knowledge_hierarchy(
            deduped_items,
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
            batch_id=batch_id,
            is_low_confidence=is_low_confidence,
        )

        # 7. 数据库事务落库与关联建立（写入期过滤噪声切片并按相关性保留 Top 5）
        snippet_by_index = {s.snippet_index: s for s in resolved_snippets}
        relations_to_save: list[KnowledgePointSnippet] = []
        seen_relations: set[tuple[uuid.UUID, uuid.UUID]] = set()
        for it in deduped_items:
            kp_uuid = temp_to_uuid[it.temp_id]
            candidate_snips: list[MaterialSnippet] = []
            seen_cand_ids: set[uuid.UUID] = set()
            for s_idx in it.source_snippet_indices:
                snip = snippet_by_index.get(s_idx)
                if snip is not None and snip.id not in seen_cand_ids:
                    seen_cand_ids.add(snip.id)
                    candidate_snips.append(snip)
            selected_snips = filter_and_rank_evidence_snippets(
                candidate_snips,
                kp_name=it.name,
                kp_summary=it.core_summary or it.description,
                max_items=5,
            )
            for snip in selected_snips:
                relation_key = (kp_uuid, snip.id)
                if relation_key in seen_relations:
                    continue
                seen_relations.add(relation_key)
                relations_to_save.append(
                    KnowledgePointSnippet(
                        user_id=user_id,
                        knowledge_point_id=kp_uuid,
                        snippet_id=snip.id,
                    )
                )

        try:
            # 清理历史可能存在的残留数据并写入（仅在抽取与质检均成功后执行）
            self.knowledge_repo.delete_knowledge_points_by_version(material_id, version_id, user_id)
            if replace_snippets and snippets is not None:
                self.material_repo.delete_snippets_by_version(version_id, user_id)
                self.material_repo.create_snippets(resolved_snippets)
            saved_points = self.knowledge_repo.batch_create_knowledge_points(
                points_to_save, user_id
            )
            if relations_to_save:
                self.knowledge_repo.create_material_relations(relations_to_save, user_id)

            if not defer_commit:
                self.material_repo.update_version_status(
                    version_id=version_id,
                    user_id=user_id,
                    status=ParseStatus.READY.value,
                )
                self.session.commit()
        except Exception:
            self.session.rollback()
            if not defer_commit:
                try:
                    self.material_repo.update_version_status(
                        version_id=version_id,
                        user_id=user_id,
                        status=ParseStatus.FAILED.value,
                        error_message="知识点抽取入库异常",
                        failed_stage="extract_knowledge",
                    )
                    self.session.commit()
                except Exception:
                    self.session.rollback()
            raise

        # 8. 结构化脱敏日志 8 要素输出
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "knowledge tree extraction completed",
            extra={
                "user_ref": user_ref,
                "target_id": str(material_id),
                "duration_ms": duration_ms,
                "error_code": 0,
                "points_count": len(saved_points),
                "snippets_count": len(resolved_snippets),
                "is_low_confidence": is_low_confidence,
                "re_extract_count": re_extract_count,
            },
        )

        return saved_points

    def get_latest_version_id(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> uuid.UUID:
        """获取资料的最新版本主键标识。

        Args:
            material_id: 资料主键。
            user_id: 租户用户主键。

        Returns:
            uuid.UUID: 最新版本主键。

        Raises:
            MaterialNotFoundError: 资料不存在或版本为空。
        """
        material = self.material_repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError(
                "请求的学习资料不存在或已被删除",
                details={"material_id": str(material_id)},
            )
        versions = self.material_repo.list_versions_by_material(material_id, user_id)
        if not versions:
            raise MaterialNotFoundError(
                "请求的资料不存在可用版本",
                details={"material_id": str(material_id)},
            )
        return versions[0].id

    def get_knowledge_tree(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        user_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """获取结构化嵌套的树形拓扑结构。

        Args:
            material_id: 资料主键。
            version_id: 版本主键 (可选，缺省时自动选用最新版本)。
            user_id: 租户用户主键。

        Returns:
            list[dict[str, Any]]: 根节点及其子节点的树形嵌套列表。

        Raises:
            MaterialNotFoundError: 资料不存在或已被删除。
        """
        material = self.material_repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError(
                "请求的学习资料不存在或已被删除",
                details={"material_id": str(material_id)},
            )

        if version_id is None:
            versions = self.material_repo.list_versions_by_material(material_id, user_id)
            if not versions:
                raise MaterialNotFoundError(
                    "请求的资料不存在可用版本",
                    details={"material_id": str(material_id)},
                )
            target_version_id = versions[0].id
        else:
            target_version_id = version_id

        points = self.knowledge_repo.get_knowledge_points_by_version(
            material_id, target_version_id, user_id
        )

        node_map: dict[uuid.UUID, dict[str, Any]] = {}
        for p in points:
            node_map[p.id] = {
                "id": str(p.id),
                "material_id": str(p.material_id),
                "version_id": str(p.version_id),
                "parent_id": str(p.parent_id) if p.parent_id else None,
                "name": p.name,
                "description": p.description,
                "structured_content": p.structured_content,
                "sort_order": p.sort_order,
                "level": p.level,
                "is_low_confidence": p.is_low_confidence,
                "children": [],
            }

        roots: list[dict[str, Any]] = []
        for p in points:
            node = node_map[p.id]
            if p.parent_id and p.parent_id in node_map:
                node_map[p.parent_id]["children"].append(node)
            else:
                roots.append(node)

        return roots

    def get_knowledge_point_detail(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> KnowledgePoint:
        """获取单个知识点详情实体。

        Args:
            knowledge_point_id: 知识点主键。
            user_id: 租户用户标识。

        Returns:
            KnowledgePoint: 知识点实体。

        Raises:
            KnowledgeNotFoundError: 知识点不存在或所属租户不匹配。
        """
        point = self.knowledge_repo.get_by_id(knowledge_point_id, user_id)
        if point is None:
            raise KnowledgeNotFoundError(
                "请求的知识点不存在或已被删除",
                details={"knowledge_point_id": str(knowledge_point_id)},
            )
        return point

    def get_snippets_for_point(
        self,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[MaterialSnippet]:
        """反向溯源：通过知识点获取关联的所有来源切片列表。

        Args:
            knowledge_point_id: 知识点主键。
            user_id: 租户用户标识。

        Returns:
            list[MaterialSnippet]: 关联来源切片列表。

        Raises:
            KnowledgeNotFoundError: 知识点不存在或所属租户不匹配。
        """
        point = self.get_knowledge_point_detail(knowledge_point_id, user_id)
        snippets = self.knowledge_repo.get_snippets_for_point(knowledge_point_id, user_id)
        if not snippets:
            return []
        structured = point.structured_content if isinstance(point.structured_content, dict) else {}
        kp_summary = str(structured.get("core_summary") or point.description or "").strip()
        ranked = filter_and_rank_evidence_snippets(
            snippets,
            kp_name=point.name,
            kp_summary=kp_summary,
            max_items=5,
        )
        for snip in ranked:
            cleaned = strip_display_watermark_lines(snip.content or "")
            if cleaned != (snip.content or ""):
                _ = (
                    snip.id,
                    snip.material_id,
                    snip.version_id,
                    snip.snippet_index,
                    snip.chapter_title,
                    snip.source_info,
                    snip.char_length,
                )
                if snip in self.session:
                    self.session.expunge(snip)
                snip.content = cleaned
                snip.char_length = len(cleaned)
        return ranked

    def get_points_for_snippet(
        self,
        snippet_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[KnowledgePoint]:
        """正向溯源：通过切片获取关联的所有知识点列表。

        Args:
            snippet_id: 切片主键。
            user_id: 租户用户标识。

        Returns:
            list[KnowledgePoint]: 关联的知识点列表。
        """
        return self.knowledge_repo.get_points_for_snippet(snippet_id, user_id)

    def trigger_extraction(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        user_id: uuid.UUID,
    ) -> dict[str, Any]:
        """触发知识点抽取并返回抽取概要字典。

        Args:
            material_id: 资料主键。
            version_id: 版本主键 (可选，缺省取最新版本)。
            user_id: 租户用户主键。

        Returns:
            dict[str, Any]: 包含抽取结果统计的字典。
        """
        if version_id is None:
            resolved_version_id = self.get_latest_version_id(material_id, user_id)
        else:
            resolved_version_id = version_id

        saved_points = self.extract_and_build_knowledge_tree(
            material_id=material_id,
            version_id=resolved_version_id,
            user_id=user_id,
        )
        has_low_confidence = any(p.is_low_confidence for p in saved_points)
        return {
            "material_id": material_id,
            "version_id": resolved_version_id,
            "extracted_count": len(saved_points),
            "has_low_confidence": has_low_confidence,
            "status": "ready",
        }


__all__ = [
    "ExtractedKnowledgeItem",
    "KnowledgeExtractionOutput",
    "KnowledgeService",
    "build_knowledge_hierarchy",
    "compute_chapter_stats",
    "deduplicate_candidate_points",
    "normalize_extracted_temp_ids",
]
