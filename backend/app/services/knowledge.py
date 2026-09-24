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
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.algorithms.knowledge_quality import (
    CandidateKnowledgePoint,
    ChapterSnippetStat,
    ExtractionContext,
    verify_knowledge_points,
)
from app.core.algorithms.search import cosine_similarity
from app.core.errors import (
    KnowledgeExtractionRetryExceededError,
    MaterialInvalidError,
    MaterialNotFoundError,
)
from app.core.security import generate_user_ref
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.agent_graph import run_structured_agent_workflow
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


# ==============================================================================
# 结构化抽取 DTO 模型
# ==============================================================================


class ExtractedKnowledgeItem(BaseModel):
    """大模型抽取的单个知识点数据传输对象。"""

    temp_id: str = Field(description="临时标识符，用于建立父子层级关系，例如 kp_1")
    parent_temp_id: str | None = Field(
        default=None,
        description="父知识点临时标识符，根节点为 None",
    )
    name: str = Field(description="知识点名称，2~30 字符，严禁数字编号与占位词")
    description: str = Field(default="", description="知识点概念简述与核心考点")
    level: int = Field(default=1, ge=1, le=5, description="知识点层级深度 1~5")
    chapter_title: str = Field(default="", description="归属章节名称")
    source_snippet_indices: list[int] = Field(
        default_factory=list,
        description="来源片段序号列表",
    )


class KnowledgeExtractionOutput(BaseModel):
    """大模型批次知识点抽取输出容器 DTO。"""

    knowledge_points: list[ExtractedKnowledgeItem] = Field(default_factory=list)


# ==============================================================================
# 纯数据处理与拓扑构建辅助函数 (McCabe V(G) <= 8)
# ==============================================================================


def compute_chapter_stats(snippets: Sequence[MaterialSnippet]) -> list[ChapterSnippetStat]:
    """统计章节切片分布情况。

    Args:
        snippets: 切片序列。

    Returns:
        list[ChapterSnippetStat]: 各章节统计信息。
    """
    total = len(snippets)
    if total == 0:
        return []
    counts: dict[str, int] = {}
    for s in snippets:
        title = s.chapter_title.strip() if s.chapter_title else "默认章节"
        counts[title] = counts.get(title, 0) + 1
    return [
        ChapterSnippetStat(
            chapter_title=title,
            snippet_count=count,
            snippet_ratio=count / total,
        )
        for title, count in counts.items()
    ]


def deduplicate_candidate_points(
    items: Sequence[ExtractedKnowledgeItem],
    embeddings: Sequence[Sequence[float]],
    similarity_threshold: float = 0.92,
) -> list[ExtractedKnowledgeItem]:
    """对候选知识点执行基于向量相似度的语义去重并聚合来源切片。

    Args:
        items: 候选知识点列表。
        embeddings: 对应的定长语义向量列表。
        similarity_threshold: 余弦相似度合并阈值，默认 0.92。

    Returns:
        list[ExtractedKnowledgeItem]: 去重合并后的知识点列表。
    """
    n = len(items)
    if n <= 1:
        return list(items)

    merged_into: dict[int, int] = {}
    redirect_map: dict[str, str] = {}

    for i in range(n):
        if i in merged_into:
            continue
        for j in range(i + 1, n):
            if j in merged_into:
                continue
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim > similarity_threshold:
                merged_into[j] = i
                redirect_map[items[j].temp_id] = items[i].temp_id

    result: list[ExtractedKnowledgeItem] = []
    for i, item in enumerate(items):
        if i in merged_into:
            continue
        all_indices = set(item.source_snippet_indices)
        for j, target_i in merged_into.items():
            if target_i == i:
                all_indices.update(items[j].source_snippet_indices)

        p_ref = item.parent_temp_id
        if p_ref and p_ref in redirect_map:
            p_ref = redirect_map[p_ref]

        merged_item = ExtractedKnowledgeItem(
            temp_id=item.temp_id,
            parent_temp_id=p_ref,
            name=item.name,
            description=item.description,
            level=item.level,
            chapter_title=item.chapter_title,
            source_snippet_indices=sorted(all_indices),
        )
        result.append(merged_item)

    return result


def _has_cycle(
    start_id: str,
    parent_map: dict[str, str | None],
) -> bool:
    """检测从指定节点向上追溯是否存在环。"""
    visited: set[str] = set()
    curr: str | None = start_id
    while curr is not None:
        if curr in visited:
            return True
        visited.add(curr)
        curr = parent_map.get(curr)
    return False


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
    temp_parents = {it.temp_id: it.parent_temp_id for it in items}
    temp_to_uuid = {it.temp_id: uuid.uuid4() for it in items}

    # 自愈环形依赖及丢失的父节点
    safe_parents: dict[str, str | None] = {}
    for it in items:
        p_id = it.parent_temp_id
        if p_id is None or p_id not in temp_to_uuid or _has_cycle(it.temp_id, temp_parents):
            safe_parents[it.temp_id] = None
        else:
            safe_parents[it.temp_id] = p_id

    def _calc_depth(tid: str) -> int:
        depth = 1
        curr = safe_parents.get(tid)
        while curr is not None and depth < 5:
            depth += 1
            curr = safe_parents.get(curr)
        return depth

    result_points: list[KnowledgePoint] = []
    for it in items:
        p_tid = safe_parents.get(it.temp_id)
        parent_uuid = temp_to_uuid[p_tid] if p_tid else None
        lvl = _calc_depth(it.temp_id)
        kp = KnowledgePoint(
            id=temp_to_uuid[it.temp_id],
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            parent_id=parent_uuid,
            name=it.name,
            description=it.description,
            level=lvl,
            batch_id=batch_id,
            is_low_confidence=is_low_confidence,
        )
        result_points.append(kp)

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
    ) -> list[LLMMessage]:
        """构建知识点抽取的大模型输入消息序列。

        Args:
            snippets: 当前批次的切片序列。
            feedback: 上一轮质检失败反馈（若有）。

        Returns:
            list[LLMMessage]: 大模型上下文消息列表。
        """
        system_content = (
            "你是一个专业的考纲分析与知识图谱构建专家。请从所提供的切片内容中抽取关键知识点及其父子层级关系。\n"
            "【抽取规范】\n"
            "1. 每个知识点必须有 2~30 字符规范名称，严禁数字编号前缀与占位词；\n"
            "2. 正确标注父节点 temp_id，无父节点设为 null，层级深度 1~5 级；\n"
            "3. 记录来源片段序号 (source_snippet_indices)；\n"
            "4. 输出严格符合 JSON Schema 规范。"
        )
        if feedback:
            system_content += f"\n\n【上一轮质检未通过反馈与整改要求】\n{feedback}"

        user_content_lines = ["请从以下切片内容中抽取知识点："]
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
    ) -> list[ExtractedKnowledgeItem]:
        """调用大模型抽取单批次切片的候选知识点。

        Args:
            snippets: 单批切片序列。
            feedback: 上一轮质检反馈。

        Returns:
            list[ExtractedKnowledgeItem]: 抽取的知识点项。
        """
        messages = self._build_batch_prompt(snippets, feedback)
        options = LLMOptions(temperature=0.3, timeout=60.0)

        try:
            output, _ = run_structured_agent_workflow(
                adapter=self.llm,
                messages=messages,
                response_model=KnowledgeExtractionOutput,
                options=options,
            )
            return output.knowledge_points
        except Exception:
            # 降级：直接尝试强类型反序列化
            output, _ = self.llm.generate_structured(
                messages=messages,
                response_model=KnowledgeExtractionOutput,
                options=options,
            )
            return output.knowledge_points

    def extract_and_build_knowledge_tree(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        batch_size: int = 40,
    ) -> list[KnowledgePoint]:
        """端到端编排切片抽取、语义去重、门禁质检、熔断重抽与建树持久化。

        Args:
            material_id: 资料主键。
            version_id: 版本主键。
            user_id: 租户用户主键。
            batch_size: 默认批次切片大小，默认 40。

        Returns:
            list[KnowledgePoint]: 已持久化构建完成的知识点实体列表。

        Raises:
            MaterialNotFoundError: 资料或版本不存在、已删除或所属租户不匹配。
            MaterialInvalidError: 切片为空无法进行抽取。
            KnowledgeExtractionRetryExceededError: 重试耗尽且未生成任何候选知识点。
        """
        start_time = time.perf_counter()
        user_ref = generate_user_ref(user_id)

        # 1. 资料与版本存在性及多租户归属校验
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

        # 2. 检索切片并校验
        snippets = self.material_repo.get_snippets(version_id, user_id)
        if not snippets:
            raise MaterialInvalidError(
                "学习资料切片为空，无法进行知识点抽取",
                details={"material_id": str(material_id), "version_id": str(version_id)},
            )

        chapter_stats = compute_chapter_stats(snippets)
        total_effective_chars = sum(s.char_length for s in snippets)

        # 3. 抽取与质检重抽循环 (最多 2 次重抽，共 3 轮尝试)
        current_batch_size = batch_size
        prompt_feedback: str | None = None
        re_extract_count = 0
        is_low_confidence = False
        deduped_items: list[ExtractedKnowledgeItem] = []

        while re_extract_count <= 2:
            # 切片分批
            batches = [
                snippets[i : i + current_batch_size]
                for i in range(0, len(snippets), current_batch_size)
            ]

            raw_extracted: list[ExtractedKnowledgeItem] = []
            for batch in batches:
                batch_points = self._extract_batch_points(batch, prompt_feedback)
                raw_extracted.extend(batch_points)

            # 若未抽取到任何知识点，直接准备重试或跳过
            if not raw_extracted:
                if re_extract_count < 2:
                    re_extract_count += 1
                    current_batch_size = 20
                    prompt_feedback = (
                        "上一轮未抽取到任何有效知识点，请降低粒度并认真分析片段正文内容。"
                    )
                    continue
                break

            # 4. 跨片段向量语义去重
            embed_texts = [f"{it.name} {it.description}".strip() for it in raw_extracted]
            embeddings = self.embedding.embed_documents(embed_texts)
            deduped_items = deduplicate_candidate_points(
                raw_extracted,
                embeddings,
                similarity_threshold=0.92,
            )

            # 5. 纯函数门禁质检
            candidate_points = [
                CandidateKnowledgePoint(
                    name=it.name,
                    level=it.level,
                    chapter_title=it.chapter_title,
                    snippet_ids=tuple(str(idx) for idx in it.source_snippet_indices),
                    description=it.description,
                )
                for it in deduped_items
            ]
            context = ExtractionContext(
                total_snippets=len(snippets),
                effective_chars=total_effective_chars,
                chapter_stats=chapter_stats,
                re_extract_count=re_extract_count,
            )
            report = verify_knowledge_points(candidate_points, context)

            if report.is_qualified:
                # 质检合格通过
                break

            # 质检未通过：重抽决策
            if re_extract_count < 2:
                re_extract_count += 1
                current_batch_size = 20  # 依据 FR-17 缩小批次以提高抽取准确度
                prompt_feedback = report.prompt_feedback
            else:
                # 重抽达 2 次超限熔断降级
                is_low_confidence = True
                break

        if not deduped_items:
            raise KnowledgeExtractionRetryExceededError(
                "知识点抽取重试次数耗尽且未生成任何候选知识点",
                details={
                    "material_id": str(material_id),
                    "version_id": str(version_id),
                    "re_extract_count": re_extract_count,
                },
            )

        # 6. 拓扑解析与孤儿/环形自愈建树
        batch_id = f"batch_{uuid.uuid4().hex[:8]}"
        points_to_save, temp_to_uuid = build_knowledge_hierarchy(
            deduped_items,
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
            batch_id=batch_id,
            is_low_confidence=is_low_confidence,
        )

        # 7. 数据库事务落库与关联建立
        snippet_index_map = {s.snippet_index: s.id for s in snippets}
        relations_to_save: list[KnowledgePointSnippet] = []
        for it in deduped_items:
            kp_uuid = temp_to_uuid[it.temp_id]
            for s_idx in it.source_snippet_indices:
                if s_idx in snippet_index_map:
                    relations_to_save.append(
                        KnowledgePointSnippet(
                            user_id=user_id,
                            knowledge_point_id=kp_uuid,
                            snippet_id=snippet_index_map[s_idx],
                        )
                    )

        try:
            # 清理历史可能存在的残留数据并写入
            self.knowledge_repo.delete_knowledge_points_by_version(material_id, version_id, user_id)
            saved_points = self.knowledge_repo.batch_create_knowledge_points(
                points_to_save, user_id
            )
            if relations_to_save:
                self.knowledge_repo.create_material_relations(relations_to_save, user_id)

            self.material_repo.update_version_status(
                version_id=version_id,
                user_id=user_id,
                status=ParseStatus.READY.value,
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
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
                "snippets_count": len(snippets),
                "is_low_confidence": is_low_confidence,
                "re_extract_count": re_extract_count,
            },
        )

        return saved_points

    def get_knowledge_tree(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """获取结构化嵌套的树形拓扑结构。

        Args:
            material_id: 资料主键。
            version_id: 版本主键。
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

        points = self.knowledge_repo.get_knowledge_points_by_version(
            material_id, version_id, user_id
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


__all__ = [
    "ExtractedKnowledgeItem",
    "KnowledgeExtractionOutput",
    "KnowledgeService",
    "build_knowledge_hierarchy",
    "compute_chapter_stats",
    "deduplicate_candidate_points",
]
