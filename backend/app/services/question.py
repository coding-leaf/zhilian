"""题目生成、质检过滤与来源溯源核心领域服务。

统领学习资料切片检索前置门禁、Top 4 切片上下文聚合、
大模型结构化多题型出题、题干 1024 维向量化、对接纯函数质检核过滤查重、
质检重抽反馈循环、事务持久化落库与 8 要素脱敏日志记录。
严格遵循 AGENTS.md 规范：
- app/services 是全系统唯一允许开启数据库事务的层；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)；
- 结构化脱敏日志 8 要素输出，严禁向日志记录题干、选项、答案与材料全文。
"""

import json
import logging
import threading
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.algorithms.question_quality import (
    ExistingQuestionReference,
    extract_keywords,
)
from app.core.errors import (
    FolderNotFoundError,
    KnowledgeNotFoundError,
    MaterialNotFoundError,
    MissingSourceSnippetError,
    QuestionGenerationJobNotFoundError,
    QuestionNotFoundError,
    SearchError,
)
from app.core.security import generate_user_ref
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.coach_graph import answer_with_course_evidence
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.protocol import QueueProtocol
from app.integrations.search.protocol import SearchProtocol
from app.models.knowledge import KnowledgePoint
from app.models.material import Material, MaterialStatus
from app.models.question import (
    AuditAction,
    Question,
    QuestionAuditLog,
    QuestionGenerationJob,
    QuestionGenerationJobStatus,
    QuestionQualityCheck,
    QuestionStatus,
)
from app.repositories.folder import FolderRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.repositories.question import QuestionRepository
from app.schemas.material import SourceSnippetDTO
from app.schemas.question import (
    AskCoachResponse,
    CoachSourceResponse,
    QuestionBatchSourceDTO,
    QuestionBatchSummaryResponse,
    QuestionDetailResponse,
    QuestionGenerateRequest,
    ScopedCoachResponse,
)
from app.services._question_generation import (
    GenerateQuestionsOptions as GenerateQuestionsOptions,
)
from app.services._question_generation import (
    GenerationLoopOutcome,
    KnowledgePointGenerationWorkSpec,
    build_existing_question_refs,
    build_question_entity,
    execute_concurrent_kp_generation,
    resolve_effective_version_id,
    run_question_generation_loop,
)
from app.services._question_generation import (
    MultiKnowledgePointGenerationResult as MultiKnowledgePointGenerationResult,
)
from app.services._question_generation import (
    QuestionGenerationResult as QuestionGenerationResult,
)
from app.services._question_generation import (
    SnippetCandidate as SnippetCandidate,
)
from app.services._question_generation import (
    aggregate_snippet_context as aggregate_snippet_context,
)
from app.services._question_generation import (
    build_generation_prompt as build_generation_prompt,
)
from app.services._question_generation import (
    convert_llm_items_to_candidates as convert_llm_items_to_candidates,
)
from app.services._question_generation import (
    distribute_count as distribute_count,
)
from app.services._question_llm_schemas import (
    LLMGeneratedQuestionItem as LLMGeneratedQuestionItem,
)
from app.services._question_llm_schemas import (
    LLMGradingPointItem as LLMGradingPointItem,
)
from app.services._question_llm_schemas import (
    LLMGradingRubric as LLMGradingRubric,
)
from app.services._question_llm_schemas import (
    LLMQuestionBatchOutput as LLMQuestionBatchOutput,
)
from app.services._question_llm_schemas import (
    LLMQuestionOptionItem as LLMQuestionOptionItem,
)
from app.services.source_snippets import build_source_snippet_map

logger = logging.getLogger(__name__)


def _is_in_memory_sqlite(session: Session) -> bool:
    """Return True when session is bound to an in-memory SQLite engine."""
    try:
        bind = session.get_bind()
    except Exception:
        return True
    url_str = str(getattr(bind, "url", "") or "")
    return ":memory:" in url_str


def _run_generation_job_in_background(
    session_factory: sessionmaker[Session],
    job_id: uuid.UUID,
    user_id: uuid.UUID,
    llm: LLMProtocol,
    embedding: EmbeddingProtocol,
    search_adapter: SearchProtocol | None,
) -> None:
    """Execute one QuestionGenerationJob inside a dedicated background Session."""
    try:
        with session_factory() as bg_session:
            bg_service = QuestionService(
                session=bg_session,
                llm=llm,
                embedding=embedding,
                search_adapter=search_adapter,
            )
            bg_service.run_generation_job(job_id=job_id, user_id=user_id)
    except Exception:
        logger.exception(
            "background question generation job failed: job_id=%s",
            job_id,
        )


# ==============================================================================
# QuestionService 服务主类实现
# ==============================================================================


class QuestionService:
    """题目领域核心编排服务。

    负责全流程调度切片检索前置门禁、Top 4 切片聚合、大模型结构化出题、
    题干语义向量化、纯函数质检核查重过滤、重抽反馈循环与原子事务落库。
    """

    def __init__(
        self,
        session: Session,
        llm: LLMProtocol,
        embedding: EmbeddingProtocol,
        search_adapter: SearchProtocol | None = None,
        queue: QueueProtocol | None = None,
        session_factory: sessionmaker[Session] | None = None,
    ) -> None:
        """初始化题目服务实例。

        Args:
            session: SQLAlchemy 数据库会话。
            llm: 大模型网关适配器。
            embedding: 向量化网关适配器。
            search_adapter: 可选的混合检索适配器。
            queue: 可选的异步任务队列适配器。
            session_factory: 可选的 SQLAlchemy 会话工厂（供内存队列后台线程执行）。
        """
        self.session = session
        self.llm = llm
        self.embedding = embedding
        self.search_adapter = search_adapter
        self.queue = queue
        self.session_factory = session_factory
        self.question_repo = QuestionRepository(session)
        self.knowledge_repo = KnowledgeRepository(session)
        self.material_repo = MaterialRepository(session)
        self.folder_repo = FolderRepository(session)

    def _retrieve_and_gate_snippets(
        self,
        *,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        knowledge_point_id: uuid.UUID,
        kp_name: str,
        kp_description: str,
    ) -> list[SnippetCandidate]:
        """检索先于生成门禁：获取知识点关联切片并校验相似度阈值。

        Args:
            user_id: 租户用户标识。
            material_id: 资料标识。
            version_id: 版本标识。
            knowledge_point_id: 知识点标识。
            kp_name: 知识点名称。
            kp_description: 知识点描述。

        Returns:
            list[SnippetCandidate]: 质检通过的候选切片列表。

        Raises:
            MissingSourceSnippetError: 切片为空或最高相似度 < 0.35 时抛出。
        """
        # 1. 优先获取知识点直接绑定的切片
        bound_snippets = self.knowledge_repo.get_snippets_for_point(knowledge_point_id, user_id)

        # 2. 若切片不足 4 个且提供了混合检索适配器，调用 search 检索补齐
        search_candidates: list[SnippetCandidate] = []
        if self.search_adapter is not None:
            try:
                search_res = self.search_adapter.search(
                    query=kp_name,
                    user_id=user_id,
                    material_id=material_id,
                    version_id=version_id,
                )
                for item in search_res.items:
                    # 门禁与提示词元数据均以「余弦相似度」为准（0-1）；
                    # final_score 是 RRF 融合排名分（量级约 1/(rrf_k+rank) ≈ 0.016），
                    # 不可用于 0.35 相似度阈值判定，否则真实检索命中也必被拒。
                    search_candidates.append(
                        SnippetCandidate(
                            snippet_id=item.snippet_id,
                            content=item.content,
                            score=item.vector_score,
                            chapter_title=item.chapter_title,
                        )
                    )
            except Exception as exc:
                logger.warning(
                    "search_adapter failed during question generation snippet retrieval",
                    extra={"error": str(exc)},
                )

        # 3. 整合切片与相似度分值
        search_map = {sc.snippet_id: sc for sc in search_candidates}
        candidates: list[SnippetCandidate] = []
        seen_ids: set[uuid.UUID] = set()

        kp_words = extract_keywords(f"{kp_name} {kp_description}".strip())

        for snippet in bound_snippets:
            if snippet.id in seen_ids:
                continue
            seen_ids.add(snippet.id)

            # 获取切片相似度分值
            score: float
            if snippet.source_info and (
                "similarity" in snippet.source_info or "score" in snippet.source_info
            ):
                score = float(
                    snippet.source_info.get("similarity") or snippet.source_info.get("score") or 0.0
                )
            elif snippet.id in search_map:
                score = search_map[snippet.id].score
            elif kp_words:
                hit_count = sum(1 for w in set(kp_words) if w in snippet.content)
                score = hit_count / len(set(kp_words))
            else:
                score = 1.0

            candidates.append(
                SnippetCandidate(
                    snippet_id=snippet.id,
                    content=snippet.content,
                    score=score,
                    chapter_title=snippet.chapter_title,
                )
            )

        # 补齐未绑定的检索切片
        for sc in search_candidates:
            if sc.snippet_id not in seen_ids and len(candidates) < 4:
                seen_ids.add(sc.snippet_id)
                candidates.append(sc)

        # 4. 门禁校验：切片为空或最高相似度 < 0.35 严格阻断
        max_score = max((c.score for c in candidates), default=0.0)
        if not candidates or max_score < 0.35:
            raise MissingSourceSnippetError(
                "检索不到与知识点匹配的有效资料片段，拒绝出题",
                details={
                    "knowledge_point_id": str(knowledge_point_id),
                    "candidate_count": len(candidates),
                    "max_similarity": max_score,
                },
            )

        return candidates

    def generate_questions(
        self,
        *,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        knowledge_point_id: uuid.UUID,
        options: GenerateQuestionsOptions | None = None,
        defer_commit: bool = False,
        batch_id: str | None = None,
    ) -> QuestionGenerationResult:
        """全流程编排：大模型结构化出题、向量化、门禁质检重抽与原子落库。

        Args:
            user_id: 租户用户主键。
            material_id: 学习资料主键。
            version_id: 可选的资料版本主键（若为空或不符将智能对齐）。
            knowledge_point_id: 知识点主键。
            options: 可选的生成控制选项。
            defer_commit: 为 True 时仅 flush 不提交，由外层调用方统一提交/回滚，
                用于多考点单事务原子编排；默认 False 保持单考点原行为。
            batch_id: 可选的显式批次标识；缺省时内部生成。上层编排传入同一
                batch_id 可让同一次生成的所有题目共享该批次。

        Returns:
            QuestionGenerationResult: 包含合格题、待处理题及质检记录的结果对象。

        Raises:
            MaterialNotFoundError: 资料或版本不存在或跨租户越权。
            KnowledgeNotFoundError: 知识点不存在或所属版本不匹配。
            MissingSourceSnippetError: 检索不到与知识点匹配的有效切片。
        """
        start_time = time.perf_counter()
        user_ref = generate_user_ref(user_id)
        effective_options = options if options is not None else GenerateQuestionsOptions()
        effective_batch_id = batch_id or f"batch_{uuid.uuid4().hex[:12]}"

        # 1. 知识点与版本归属及多租户校验
        material = self.material_repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")

        kp = self.knowledge_repo.get_by_id(knowledge_point_id, user_id)
        if kp is None or kp.material_id != material_id:
            raise KnowledgeNotFoundError("请求的知识点不存在或无权访问")

        effective_version_id = resolve_effective_version_id(material, kp, version_id)
        if effective_version_id is None:
            raise KnowledgeNotFoundError("请求的知识点不存在关联版本")

        # 2. 检索前置门禁校验与 Top 4 上下文聚合 (2400 字符上限)
        snippets = self._retrieve_and_gate_snippets(
            user_id=user_id,
            material_id=material_id,
            version_id=effective_version_id,
            knowledge_point_id=knowledge_point_id,
            kp_name=kp.name,
            kp_description=kp.description,
        )
        context_text, snippet_metadata = aggregate_snippet_context(snippets, max_chars=2400)

        # 3. 历史去重基准与出题质检重抽循环
        recent_questions = self.question_repo.list_recent_for_deduplication(
            material_id, user_id, limit=500
        )
        existing_refs = build_existing_question_refs(recent_questions)
        outcome = run_question_generation_loop(
            llm=self.llm,
            embedding=self.embedding,
            user_id=user_id,
            batch_id=effective_batch_id,
            kp_name=kp.name,
            kp_description=kp.description,
            context_text=context_text,
            snippet_metadata=snippet_metadata,
            existing_refs=existing_refs,
            options=effective_options,
        )

        # 4. 构造题目与质检实体 (合格品 + 残余待人工审核品)
        target_count = effective_options.count
        qualified_questions = [
            build_question_entity(
                cand,
                outcome.candidate_items_map[cand.question_id],
                user_id=user_id,
                material_id=material_id,
                version_id=effective_version_id,
                knowledge_point_id=knowledge_point_id,
                batch_id=effective_batch_id,
                status=QuestionStatus.AVAILABLE.value,
                snippet_metadata=snippet_metadata,
            )
            for cand in outcome.qualified_questions[:target_count]
        ]
        remaining_needed = target_count - len(qualified_questions)
        pending_questions = [
            build_question_entity(
                cand,
                outcome.candidate_items_map[cand.question_id],
                user_id=user_id,
                material_id=material_id,
                version_id=effective_version_id,
                knowledge_point_id=knowledge_point_id,
                batch_id=effective_batch_id,
                status=QuestionStatus.PENDING_REVIEW.value,
                snippet_metadata=snippet_metadata,
            )
            for cand in outcome.last_unqualified_questions[:remaining_needed]
        ]
        all_quality_checks = [
            check
            for q in qualified_questions + pending_questions
            for check in outcome.candidate_checks_map.get(str(q.id), ())
        ]
        retry_count = outcome.retry_count

        # 7. 原子数据库事务落库
        all_entities = qualified_questions + pending_questions
        try:
            with self.session.begin_nested():
                saved_questions = self.question_repo.batch_create_questions(all_entities, user_id)
                saved_checks = self.question_repo.batch_create_quality_checks(
                    all_quality_checks, user_id
                )
            if not defer_commit:
                self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        # 8. 结构化脱敏日志输出 (零泄露题干与切片原文)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "question generation completed",
            extra={
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "logger_name": __name__,
                "request_id": effective_batch_id,
                "user_ref": user_ref,
                "target_id": str(knowledge_point_id),
                "duration_ms": duration_ms,
                "error_code": 0,
                "total_generated": len(saved_questions),
                "qualified_count": len(qualified_questions),
                "pending_count": len(pending_questions),
                "checks_count": len(saved_checks),
                "retry_count": retry_count,
            },
        )

        return QuestionGenerationResult(
            batch_id=effective_batch_id,
            material_id=material_id,
            version_id=effective_version_id,
            knowledge_point_id=knowledge_point_id,
            total_generated=len(saved_questions),
            qualified_questions=qualified_questions,
            pending_questions=pending_questions,
            quality_checks=saved_checks,
            retry_count=retry_count,
        )

    def generate_questions_for_knowledge_points(
        self,
        *,
        user_id: uuid.UUID,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        knowledge_point_ids: Sequence[uuid.UUID],
        options: GenerateQuestionsOptions | None = None,
        defer_commit: bool = False,
        batch_id: str | None = None,
    ) -> MultiKnowledgePointGenerationResult:
        """多考点编排：按考点均分题量并逐个复用单考点流程后聚合结果。

        题量分配遵循「均分 + 余数前置 + 每考点至少 1 题」；任一考点生成失败时
        fail-fast 抛出既有异常，不做静默降级。

        Args:
            user_id: 租户用户主键。
            material_id: 学习资料主键。
            version_id: 可选的资料版本主键（若为空或不符将智能对齐）。
            knowledge_point_ids: 目标知识点主键序列（去重后保序）。
            options: 可选的生成控制选项，count 表示多考点总题量。
            defer_commit: 为 True 时不在本层提交/回滚，仅由外层统一提交，
                用于跨资料（课程文件夹）范围的单事务原子编排；默认 False 保持原行为。
            batch_id: 可选的显式批次标识；缺省时内部生成，并透传给每个考点，
                使多考点生成的题目共享同一批次。

        Returns:
            MultiKnowledgePointGenerationResult: 聚合后的多考点生成结果。

        Raises:
            ValueError: 当 knowledge_point_ids 为空时抛出。
            MaterialNotFoundError: 资料或版本不存在或跨租户越权。
            KnowledgeNotFoundError: 任一知识点不存在、越权或版本不匹配。
            MissingSourceSnippetError: 任一知识点检索不到与匹配的有效切片。
        """
        ordered_kp_ids = list(dict.fromkeys(knowledge_point_ids))
        if not ordered_kp_ids:
            raise ValueError("knowledge_point_ids 不能为空")

        effective_options = options if options is not None else GenerateQuestionsOptions()
        counts = distribute_count(effective_options.count, len(ordered_kp_ids))
        effective_batch_id = batch_id or f"batch_{uuid.uuid4().hex[:12]}"

        aggregated_qualified: list[Question] = []
        aggregated_pending: list[Question] = []
        aggregated_checks: list[QuestionQualityCheck] = []
        total_generated = 0
        total_retry = 0
        aligned_version_id: uuid.UUID | None = None

        # 单事务原子编排：当调用方未在实例上 monkeypatch generate_questions 时，
        # 先在调用线程单线程预取全部上下文与参考基准，再用受控 3 并发执行纯 LLM/Embedding 阶段，
        # 最后在调用线程统一构造与刷盘；任一环节失败则整批回滚。
        if "generate_questions" in self.__dict__:
            try:
                for kp_id, kp_count in zip(ordered_kp_ids, counts, strict=True):
                    per_kp_options = GenerateQuestionsOptions(
                        question_types=effective_options.question_types,
                        count=kp_count,
                        difficulty=effective_options.difficulty,
                        max_retries=effective_options.max_retries,
                    )
                    result = self.generate_questions(
                        user_id=user_id,
                        material_id=material_id,
                        version_id=version_id,
                        knowledge_point_id=kp_id,
                        options=per_kp_options,
                        defer_commit=True,
                        batch_id=effective_batch_id,
                    )
                    if aligned_version_id is None:
                        aligned_version_id = result.version_id
                    total_generated += result.total_generated
                    total_retry += result.retry_count
                    aggregated_qualified.extend(result.qualified_questions)
                    aggregated_pending.extend(result.pending_questions)
                    aggregated_checks.extend(result.quality_checks)

                if aligned_version_id is None:  # pragma: no cover - 非空列表保证首轮必赋值
                    raise KnowledgeNotFoundError("请求的知识点不存在关联版本")

                if not defer_commit:
                    self.session.commit()
            except Exception:
                if not defer_commit:
                    self.session.rollback()
                raise
        else:
            try:
                plan = [
                    (material_id, version_id, kp_id, kp_count)
                    for kp_id, kp_count in zip(ordered_kp_ids, counts, strict=True)
                ]
                specs = self._prepare_kp_work_specs(
                    user_id=user_id,
                    plan=plan,
                    base_options=effective_options,
                )
                outcomes = execute_concurrent_kp_generation(
                    specs,
                    llm=self.llm,
                    embedding=self.embedding,
                    user_id=user_id,
                    batch_id=effective_batch_id,
                    max_workers=3,
                )
                if outcomes:
                    aligned_version_id = outcomes[0][0].version_id
                if aligned_version_id is None:  # pragma: no cover - 非空列表保证首轮必赋值
                    raise KnowledgeNotFoundError("请求的知识点不存在关联版本")

                all_entities, all_checks, total_retry = self._materialize_kp_outcomes(
                    user_id=user_id,
                    batch_id=effective_batch_id,
                    outcomes=outcomes,
                )
                with self.session.begin_nested():
                    saved_questions = self.question_repo.batch_create_questions(
                        all_entities, user_id
                    )
                    saved_checks = self.question_repo.batch_create_quality_checks(
                        all_checks, user_id
                    )
                total_generated = len(saved_questions)
                aggregated_qualified = [
                    q for q in saved_questions if q.status == QuestionStatus.AVAILABLE.value
                ]
                aggregated_pending = [
                    q for q in saved_questions if q.status == QuestionStatus.PENDING_REVIEW.value
                ]
                aggregated_checks = saved_checks

                if not defer_commit:
                    self.session.commit()
            except Exception:
                if not defer_commit:
                    self.session.rollback()
                raise

        logger.info(
            "multi knowledge point question generation completed",
            extra={
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "logger_name": __name__,
                "request_id": effective_batch_id,
                "target_id": ",".join(str(kp) for kp in ordered_kp_ids),
                "knowledge_point_count": len(ordered_kp_ids),
                "requested_count": effective_options.count,
                "actual_total": total_generated,
                "retry_count": total_retry,
                "error_code": 0,
            },
        )

        return MultiKnowledgePointGenerationResult(
            batch_id=effective_batch_id,
            material_id=material_id,
            version_id=aligned_version_id,
            knowledge_point_id=ordered_kp_ids[0],
            knowledge_point_ids=tuple(ordered_kp_ids),
            requested_count=effective_options.count,
            total_generated=total_generated,
            qualified_questions=aggregated_qualified,
            pending_questions=aggregated_pending,
            quality_checks=aggregated_checks,
            retry_count=total_retry,
        )

    def generate_questions_for_folder(
        self,
        *,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
        knowledge_point_ids: Sequence[uuid.UUID] | None = None,
        options: GenerateQuestionsOptions | None = None,
    ) -> MultiKnowledgePointGenerationResult:
        """课程文件夹范围出题：跨资料分组均分题量后单事务原子落库。

        解析目标考点集（显式列表校验归属，缺省取文件夹全部 ready 资料考点），
        按 ``(material_id, version_id)`` 保序分组；题量先按组均分，再在组内按考点
        均分（均分 + 余数前置 + 每组至少 1 题）。全部资料组成功后仅提交一次，
        任一环节失败整批回滚，零遗留部分题目。

        Args:
            user_id: 租户用户主键。
            folder_id: 课程文件夹主键（必须归属当前用户且未归档）。
            knowledge_point_ids: 可选的显式考点列表；缺省取文件夹全部考点。
            options: 可选的生成控制选项，count 表示跨资料总题量。

        Returns:
            MultiKnowledgePointGenerationResult: 聚合后的跨资料生成结果。

        Raises:
            FolderNotFoundError: 课程文件夹不存在、已归档或越权。
            KnowledgeNotFoundError: 显式考点不属于该文件夹，或文件夹无可用考点。
            MaterialNotFoundError: 资料不存在或跨租户越权。
            MissingSourceSnippetError: 任一考点检索不到匹配的有效切片。
        """
        folder = self.folder_repo.get_by_id(folder_id, user_id, include_archived=False)
        if folder is None:
            raise FolderNotFoundError()

        resolved_points = self._resolve_folder_knowledge_points(
            user_id=user_id,
            folder_id=folder_id,
            knowledge_point_ids=knowledge_point_ids,
        )
        if not resolved_points:
            raise KnowledgeNotFoundError(
                "课程文件夹下没有可用的知识点",
                details={"folder_id": str(folder_id)},
            )

        effective_options = options if options is not None else GenerateQuestionsOptions()

        # 按 (material_id, version_id) 保序分组
        groups: dict[tuple[uuid.UUID, uuid.UUID], list[uuid.UUID]] = {}
        for point in resolved_points:
            groups.setdefault((point.material_id, point.version_id), []).append(point.id)

        ordered_kp_ids = list(dict.fromkeys(point.id for point in resolved_points))
        group_keys = list(groups.keys())
        group_counts = distribute_count(effective_options.count, len(group_keys))

        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        aggregated_qualified: list[Question] = []
        aggregated_pending: list[Question] = []
        aggregated_checks: list[QuestionQualityCheck] = []
        total_generated = 0
        total_retry = 0

        # 跨资料单事务原子编排：逐组仅 flush（defer_commit=True），
        # 全部成功一次性提交；任一资料组失败则整批回滚。
        try:
            for key, group_count in zip(group_keys, group_counts, strict=True):
                material_id, version_id = key
                per_group_options = GenerateQuestionsOptions(
                    question_types=effective_options.question_types,
                    count=group_count,
                    difficulty=effective_options.difficulty,
                    max_retries=effective_options.max_retries,
                )
                result = self.generate_questions_for_knowledge_points(
                    user_id=user_id,
                    material_id=material_id,
                    version_id=version_id,
                    knowledge_point_ids=groups[key],
                    options=per_group_options,
                    defer_commit=True,
                    batch_id=batch_id,
                )
                total_generated += result.total_generated
                total_retry += result.retry_count
                aggregated_qualified.extend(result.qualified_questions)
                aggregated_pending.extend(result.pending_questions)
                aggregated_checks.extend(result.quality_checks)

            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        first_material_id, first_version_id = group_keys[0]

        logger.info(
            "folder scope question generation completed",
            extra={
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "logger_name": __name__,
                "request_id": batch_id,
                "target_id": str(folder_id),
                "material_group_count": len(group_keys),
                "knowledge_point_count": len(ordered_kp_ids),
                "requested_count": effective_options.count,
                "actual_total": total_generated,
                "retry_count": total_retry,
                "error_code": 0,
            },
        )

        return MultiKnowledgePointGenerationResult(
            batch_id=batch_id,
            material_id=first_material_id,
            version_id=first_version_id,
            knowledge_point_id=ordered_kp_ids[0],
            knowledge_point_ids=tuple(ordered_kp_ids),
            requested_count=effective_options.count,
            total_generated=total_generated,
            qualified_questions=aggregated_qualified,
            pending_questions=aggregated_pending,
            quality_checks=aggregated_checks,
            retry_count=total_retry,
        )

    def _resolve_folder_knowledge_points(
        self,
        *,
        user_id: uuid.UUID,
        folder_id: uuid.UUID,
        knowledge_point_ids: Sequence[uuid.UUID] | None,
    ) -> list[KnowledgePoint]:
        """解析课程文件夹范围的目标考点集。

        显式提供 ``knowledge_point_ids`` 时逐个校验其归属资料属于该文件夹下未归档
        资料；缺省时取文件夹全部 ready 资料的全部知识点。

        Args:
            user_id: 租户用户主键。
            folder_id: 课程文件夹主键。
            knowledge_point_ids: 可选的显式考点列表。

        Returns:
            list[KnowledgePoint]: 去重后保序的目标知识点实体列表。

        Raises:
            KnowledgeNotFoundError: 显式考点不存在、越权或不属于该文件夹。
        """
        if not knowledge_point_ids:
            return self.question_repo.list_knowledge_points_for_folder(user_id, folder_id)

        allowed_material_ids = set(
            self.question_repo.list_material_ids_for_folder(user_id, folder_id)
        )
        resolved: list[KnowledgePoint] = []
        seen: set[uuid.UUID] = set()
        for kp_id in knowledge_point_ids:
            if kp_id in seen:
                continue
            seen.add(kp_id)
            point = self.knowledge_repo.get_knowledge_point_by_id(kp_id, user_id)
            if point is None or point.material_id not in allowed_material_ids:
                raise KnowledgeNotFoundError(
                    "请求的知识点不存在、越权或不属于该课程文件夹",
                    details={"knowledge_point_id": str(kp_id)},
                )
            resolved.append(point)
        return resolved

    def _prepare_kp_work_specs(
        self,
        *,
        user_id: uuid.UUID,
        plan: Sequence[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, int]],
        base_options: GenerateQuestionsOptions,
    ) -> list[KnowledgePointGenerationWorkSpec]:
        """在调用线程统一预检实体并构造纯值对象工作规范列表。"""
        material_cache: dict[uuid.UUID, Material] = {}
        refs_cache: dict[uuid.UUID, tuple[ExistingQuestionReference, ...]] = {}
        specs: list[KnowledgePointGenerationWorkSpec] = []

        for idx, (material_id, requested_version_id, kp_id, kp_count) in enumerate(plan):
            material = material_cache.get(material_id)
            if material is None:
                fetched_mat = self.material_repo.get_material_by_id(material_id, user_id)
                if fetched_mat is None:
                    raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
                material_cache[material_id] = fetched_mat
                material = fetched_mat

            kp = self.knowledge_repo.get_by_id(kp_id, user_id)
            if kp is None or kp.material_id != material_id:
                raise KnowledgeNotFoundError("请求的知识点不存在或无权访问")

            effective_version_id = resolve_effective_version_id(material, kp, requested_version_id)
            if effective_version_id is None:
                raise KnowledgeNotFoundError("请求的知识点不存在关联版本")

            snippets = self._retrieve_and_gate_snippets(
                user_id=user_id,
                material_id=material_id,
                version_id=effective_version_id,
                knowledge_point_id=kp_id,
                kp_name=kp.name,
                kp_description=kp.description,
            )
            context_text, snippet_metadata = aggregate_snippet_context(snippets, max_chars=2400)

            existing_refs = refs_cache.get(material_id)
            if existing_refs is None:
                recent_questions = self.question_repo.list_recent_for_deduplication(
                    material_id, user_id, limit=500
                )
                existing_refs = tuple(build_existing_question_refs(recent_questions))
                refs_cache[material_id] = existing_refs

            specs.append(
                KnowledgePointGenerationWorkSpec(
                    index=idx,
                    material_id=material_id,
                    version_id=effective_version_id,
                    knowledge_point_id=kp_id,
                    kp_name=kp.name,
                    kp_description=kp.description,
                    context_text=context_text,
                    snippet_metadata=tuple(snippet_metadata),
                    existing_refs=existing_refs,
                    options=GenerateQuestionsOptions(
                        question_types=base_options.question_types,
                        count=kp_count,
                        difficulty=base_options.difficulty,
                        max_retries=base_options.max_retries,
                    ),
                )
            )

        return specs

    @staticmethod
    def _materialize_kp_outcomes(
        *,
        user_id: uuid.UUID,
        batch_id: str,
        outcomes: Sequence[tuple[KnowledgePointGenerationWorkSpec, GenerationLoopOutcome]],
    ) -> tuple[list[Question], list[QuestionQualityCheck], int]:
        """在调用线程将并发生成结果映射为 Question 与质检 ORM 实体列表。"""
        all_entities: list[Question] = []
        all_checks: list[QuestionQualityCheck] = []
        total_retry = 0

        for spec, outcome in outcomes:
            target_count = spec.options.count
            snippet_meta_list = list(spec.snippet_metadata)
            qualified = [
                build_question_entity(
                    cand,
                    outcome.candidate_items_map[cand.question_id],
                    user_id=user_id,
                    material_id=spec.material_id,
                    version_id=spec.version_id,
                    knowledge_point_id=spec.knowledge_point_id,
                    batch_id=batch_id,
                    status=QuestionStatus.AVAILABLE.value,
                    snippet_metadata=snippet_meta_list,
                )
                for cand in outcome.qualified_questions[:target_count]
            ]
            remaining_needed = target_count - len(qualified)
            pending = [
                build_question_entity(
                    cand,
                    outcome.candidate_items_map[cand.question_id],
                    user_id=user_id,
                    material_id=spec.material_id,
                    version_id=spec.version_id,
                    knowledge_point_id=spec.knowledge_point_id,
                    batch_id=batch_id,
                    status=QuestionStatus.PENDING_REVIEW.value,
                    snippet_metadata=snippet_meta_list,
                )
                for cand in outcome.last_unqualified_questions[:remaining_needed]
            ]
            kp_entities = qualified + pending
            all_entities.extend(kp_entities)
            for q in kp_entities:
                all_checks.extend(outcome.candidate_checks_map.get(str(q.id), ()))
            total_retry += outcome.retry_count

        return all_entities, all_checks, total_retry

    def _resolve_generation_plan(
        self,
        *,
        user_id: uuid.UUID,
        payload: QuestionGenerateRequest,
    ) -> list[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, int]]:
        """解析单资料/文件夹范围的目标知识点出题配额计划。"""
        target_kp_ids = list(payload.knowledge_point_ids)
        if not target_kp_ids and payload.knowledge_point_id is not None:
            target_kp_ids = [payload.knowledge_point_id]

        if payload.folder_id is not None:
            folder = self.folder_repo.get_by_id(payload.folder_id, user_id, include_archived=False)
            if folder is None:
                raise FolderNotFoundError()
            resolved_points = self._resolve_folder_knowledge_points(
                user_id=user_id,
                folder_id=payload.folder_id,
                knowledge_point_ids=target_kp_ids or None,
            )
            if not resolved_points:
                raise KnowledgeNotFoundError(
                    "课程文件夹下没有可用的知识点",
                    details={"folder_id": str(payload.folder_id)},
                )
            groups: dict[tuple[uuid.UUID, uuid.UUID], list[KnowledgePoint]] = {}
            for pt in resolved_points:
                groups.setdefault((pt.material_id, pt.version_id), []).append(pt)
            group_keys = list(groups.keys())
            group_counts = distribute_count(payload.count, len(group_keys))
            plan: list[tuple[uuid.UUID, uuid.UUID | None, uuid.UUID, int]] = []
            for key, g_count in zip(group_keys, group_counts, strict=True):
                mat_id, ver_id = key
                kps_in_group = groups[key]
                kp_counts = distribute_count(g_count, len(kps_in_group))
                for kp, k_count in zip(kps_in_group, kp_counts, strict=True):
                    plan.append((mat_id, ver_id, kp.id, k_count))
            return plan

        material_id = payload.material_id
        if material_id is None:
            raise ValueError("material_id 必须指定")
        material = self.material_repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")

        ordered_kp_ids = list(dict.fromkeys(target_kp_ids))
        if not ordered_kp_ids:
            raise KnowledgeNotFoundError("未指定目标知识点")
        for kp_id in ordered_kp_ids:
            fetched_kp = self.knowledge_repo.get_by_id(kp_id, user_id)
            if fetched_kp is None or fetched_kp.material_id != material_id:
                raise KnowledgeNotFoundError("请求的知识点不存在或无权访问")

        kp_counts = distribute_count(payload.count, len(ordered_kp_ids))
        return [
            (material_id, payload.version_id, kp_id, k_count)
            for kp_id, k_count in zip(ordered_kp_ids, kp_counts, strict=True)
        ]

    def create_generation_job(
        self,
        *,
        user_id: uuid.UUID,
        payload: QuestionGenerateRequest,
    ) -> QuestionGenerationJob:
        """创建异步出题任务并入队调度。"""
        plan = self._resolve_generation_plan(user_id=user_id, payload=payload)
        job = QuestionGenerationJob(
            user_id=user_id,
            material_id=payload.material_id,
            folder_id=payload.folder_id,
            status=QuestionGenerationJobStatus.QUEUED.value,
            request_payload=payload.model_dump(mode="json"),
            total_kps=len(plan),
            completed_kps=0,
            generated_count=0,
            question_ids=[],
        )
        self.question_repo.create_generation_job(job, user_id)
        self.session.commit()
        self.session.refresh(job)

        if self.queue is not None:
            try:
                self.queue.enqueue(
                    task_name="generate_questions_job",
                    payload={"job_id": str(job.id), "user_id": str(user_id)},
                    user_id=str(user_id),
                    task_id=str(job.id),
                )
            except Exception as exc:
                job.status = QuestionGenerationJobStatus.FAILED.value
                job.error_message = f"任务入队失败: {str(exc)[:300]}"
                job.completed_at = datetime.now(UTC)
                self.session.commit()
                raise

            if (
                isinstance(self.queue, MemoryQueueAdapter)
                and not self.queue.has_handler("generate_questions_job")
                and self.session_factory is not None
                and not _is_in_memory_sqlite(self.session)
            ):
                thread = threading.Thread(
                    target=_run_generation_job_in_background,
                    args=(
                        self.session_factory,
                        job.id,
                        user_id,
                        self.llm,
                        self.embedding,
                        self.search_adapter,
                    ),
                    daemon=True,
                )
                thread.start()

        return job

    def list_generation_jobs(
        self,
        *,
        user_id: uuid.UUID,
        active_only: bool = False,
        material_id: uuid.UUID | None = None,
        folder_id: uuid.UUID | None = None,
    ) -> tuple[list[QuestionGenerationJob], int]:
        """查询当前用户的异步出题任务列表。"""
        return self.question_repo.list_generation_jobs(
            user_id=user_id,
            active_only=active_only,
            material_id=material_id,
            folder_id=folder_id,
        )

    def get_generation_job(
        self,
        *,
        user_id: uuid.UUID,
        job_id: uuid.UUID,
    ) -> QuestionGenerationJob:
        """查询单个异步出题任务详情，越权或不存在抛 404。"""
        job = self.question_repo.get_generation_job_by_id(job_id, user_id)
        if job is None:
            raise QuestionGenerationJobNotFoundError()
        return job

    def mark_generation_job_failed(
        self,
        *,
        user_id: uuid.UUID,
        job_id: uuid.UUID,
        error_message: str,
    ) -> QuestionGenerationJob | None:
        """幂等将非终态的异步出题任务标记为 failed。"""
        job = self.question_repo.get_generation_job_by_id(job_id, user_id)
        if job is None or job.status == QuestionGenerationJobStatus.COMPLETED.value:
            return job
        job.status = QuestionGenerationJobStatus.FAILED.value
        job.error_message = error_message[:500]
        if job.completed_at is None:
            job.completed_at = datetime.now(UTC)
        self.session.commit()
        return job

    def run_generation_job(
        self,
        *,
        job_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> QuestionGenerationJob:
        """执行异步出题队列任务：受控 3 并发跑纯 LLM 阶段并实时更新 KP 进度。"""
        job = self.question_repo.get_generation_job_by_id(job_id, user_id)
        if job is None:
            raise QuestionGenerationJobNotFoundError()
        if job.status == QuestionGenerationJobStatus.COMPLETED.value:
            return job

        job.status = QuestionGenerationJobStatus.RUNNING.value
        job.error_message = None
        job.completed_kps = 0
        self.session.commit()

        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        try:
            payload = QuestionGenerateRequest.model_validate(job.request_payload)
            base_options = GenerateQuestionsOptions(
                question_types=tuple(payload.question_types),
                count=payload.count,
                difficulty=payload.difficulty,
                max_retries=payload.max_retries,
            )
            plan = self._resolve_generation_plan(user_id=user_id, payload=payload)
            job.total_kps = len(plan)
            self.session.commit()

            specs = self._prepare_kp_work_specs(
                user_id=user_id,
                plan=plan,
                base_options=base_options,
            )

            def _on_kp_done(
                _spec: KnowledgePointGenerationWorkSpec,
                _outcome: GenerationLoopOutcome,
            ) -> None:
                job.completed_kps += 1
                self.session.commit()

            outcomes = execute_concurrent_kp_generation(
                specs,
                llm=self.llm,
                embedding=self.embedding,
                user_id=user_id,
                batch_id=batch_id,
                on_kp_done=_on_kp_done,
                max_workers=3,
            )
            all_entities, all_checks, _ = self._materialize_kp_outcomes(
                user_id=user_id,
                batch_id=batch_id,
                outcomes=outcomes,
            )
            with self.session.begin_nested():
                saved_questions = self.question_repo.batch_create_questions(all_entities, user_id)
                self.question_repo.batch_create_quality_checks(all_checks, user_id)

            job.status = QuestionGenerationJobStatus.COMPLETED.value
            job.batch_id = batch_id
            job.generated_count = len(saved_questions)
            job.question_ids = [str(q.id) for q in saved_questions]
            job.completed_kps = len(specs)
            job.completed_at = datetime.now(UTC)
            self.session.commit()
            self.session.refresh(job)
            return job
        except Exception as exc:
            self.session.rollback()
            refreshed = self.question_repo.get_generation_job_by_id(job_id, user_id)
            if (
                refreshed is not None
                and refreshed.status != QuestionGenerationJobStatus.COMPLETED.value
            ):
                refreshed.status = QuestionGenerationJobStatus.FAILED.value
                refreshed.error_message = str(exc)[:500]
                refreshed.completed_at = datetime.now(UTC)
                self.session.commit()
            raise

    def get_question(
        self,
        question_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> Question:
        """获取单个题目详情，严格租户隔离。

        Args:
            question_id: 题目主键。
            user_id: 租户用户主键。
            kwargs: 兼容命名参数传递。

        Returns:
            Question: 题目实体。

        Raises:
            QuestionNotFoundError: 题目不存在或越权访问。
        """
        resolved_question_id = question_id or kwargs.get("question_id")
        resolved_user_id = user_id or kwargs.get("user_id")
        if resolved_question_id is None or resolved_user_id is None:
            raise ValueError("question_id 与 user_id 必须指定")

        question = self.question_repo.get_question_by_id(resolved_question_id, resolved_user_id)
        if question is None:
            raise QuestionNotFoundError("请求的题目不存在或无权访问")
        return question

    def attach_source_snippets(
        self,
        items: Sequence[QuestionDetailResponse],
        user_id: uuid.UUID,
    ) -> None:
        """批量为题目响应装配主来源切片投影 (就地补全 ``source_snippet``)。

        出题、详情、列表与更新四条响应装配路径共用本方法；投影构造复用
        ``build_source_snippet_map``（与练习侧同一实现），一次 ``IN`` 查询完成装配，
        禁 N+1。切片缺失或不属于该租户时该题保持 ``None``，由前端渲染空态。

        Args:
            items: 待补全的题目响应 DTO 序列 (就地修改)。
            user_id: 租户用户标识。
        """
        snippet_ids: set[uuid.UUID] = set()
        for item in items:
            if item.source_snippet_id is not None:
                snippet_ids.add(item.source_snippet_id)
        if not snippet_ids:
            return

        snippet_map: dict[uuid.UUID, SourceSnippetDTO] = build_source_snippet_map(
            self.material_repo, snippet_ids, user_id
        )
        for item in items:
            if item.source_snippet_id is not None:
                item.source_snippet = snippet_map.get(item.source_snippet_id)

    def list_questions(
        self,
        user_id: uuid.UUID,
        material_id: uuid.UUID | None = None,
        knowledge_point_id: uuid.UUID | None = None,
        question_type: str | None = None,
        difficulty: int | None = None,
        review_status: str | None = None,
        page: int = 1,
        page_size: int = 20,
        *,
        status: str | None = None,
        folder_id: uuid.UUID | None = None,
        batch_id: str | None = None,
        unbatched: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        include_deleted: bool = False,
        **kwargs: Any,
    ) -> tuple[list[Question], int]:
        """多条件筛选分页查询题目列表及匹配总数。

        Args:
            user_id: 租户用户主键。
            material_id: 可选的学习资料标识过滤。
            knowledge_point_id: 可选的知识点标识过滤。
            question_type: 可选的题型过滤。
            difficulty: 可选的难度过滤。
            review_status: 可选的审核状态过滤 (review_status 优先于 status)。
            page: 当前页码，默认 1。
            page_size: 单页容量限制，默认 20。
            status: 兼容的状态过滤入参。
            folder_id: 可选的课程文件夹标识过滤（仅未归档课程资料）。
            batch_id: 可选的出题生成批次标识过滤。
            unbatched: 为 True 时只返回未分批（batch_id 为空）的历史题目。
            limit: 可选的单页数量限制（优先于 page_size）。
            offset: 可选的分页游标偏移量（优先于 page 计算）。
            include_deleted: 是否包含软删除记录，默认 False。
            kwargs: 兼容其他调用传参。

        Returns:
            tuple[list[Question], int]: (题目列表, 总条数)。
        """
        resolved_user_id = user_id or kwargs.get("user_id")
        if resolved_user_id is None:
            raise ValueError("user_id 必须指定")

        effective_status = (
            review_status if review_status is not None else (status or kwargs.get("status"))
        )
        calc_limit = limit if limit is not None else page_size
        calc_offset = offset if offset is not None else (max(page - 1, 0) * calc_limit)

        return self.question_repo.list_questions(
            user_id=resolved_user_id,
            material_id=material_id or kwargs.get("material_id"),
            folder_id=folder_id or kwargs.get("folder_id"),
            version_id=kwargs.get("version_id"),
            knowledge_point_id=knowledge_point_id or kwargs.get("knowledge_point_id"),
            question_type=question_type or kwargs.get("question_type"),
            difficulty=difficulty or kwargs.get("difficulty"),
            status=effective_status,
            batch_id=batch_id or kwargs.get("batch_id"),
            unbatched=unbatched or bool(kwargs.get("unbatched", False)),
            include_deleted=include_deleted or bool(kwargs.get("include_deleted", False)),
            limit=calc_limit,
            offset=calc_offset,
        )

    def list_question_batches(
        self,
        user_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[QuestionBatchSummaryResponse], int]:
        """按出题批次聚合分页查询批次摘要并装配来源。

        三次批量查询完成装配：本页批次聚合、批次总数、本页批次的来源资料。
        不对批次逐条补查来源 (N+1)。

        Args:
            user_id: 租户用户标识。
            page: 当前页码，从 1 开始，默认 1。
            page_size: 单页批次数量限制，默认 20。

        Returns:
            tuple[list[QuestionBatchSummaryResponse], int]: (本页批次摘要, 真实批次总数)。
        """
        resolved_page_size = max(1, page_size)
        offset = max(page - 1, 0) * resolved_page_size

        rows = self.question_repo.list_question_batches(
            user_id,
            limit=resolved_page_size,
            offset=offset,
        )
        total = self.question_repo.count_question_batches(user_id)
        sources_by_batch = self._group_batch_sources(
            user_id,
            [batch_id for batch_id, *_rest in rows],
        )

        items = [
            QuestionBatchSummaryResponse(
                batch_id=batch_id,
                question_count=question_count,
                available_count=available_count,
                pending_review_count=question_count - available_count,
                created_at=created_at,
                # 未分批组按「没有批次」渲染，不借它的资料拼一个假来源
                sources=sources_by_batch.get(batch_id, []) if batch_id is not None else [],
            )
            for batch_id, question_count, available_count, created_at in rows
        ]
        return items, total

    def _group_batch_sources(
        self,
        user_id: uuid.UUID,
        batch_ids: Sequence[str | None],
    ) -> dict[str, list[QuestionBatchSourceDTO]]:
        """一次查询批量装配本页批次的来源资料。

        Args:
            user_id: 租户用户标识。
            batch_ids: 本页批次标识 (可含 None，None 不参与来源查询)。

        Returns:
            dict[str, list[QuestionBatchSourceDTO]]: 批次标识 → 来源资料投影列表。
        """
        non_null_ids = [batch_id for batch_id in batch_ids if batch_id is not None]
        grouped: dict[str, list[QuestionBatchSourceDTO]] = {}
        for row in self.question_repo.list_batch_sources(user_id, non_null_ids):
            grouped.setdefault(row[0], []).append(
                QuestionBatchSourceDTO(
                    material_id=row[1],
                    material_title=row[2],
                    folder_id=row[3],
                    folder_name=row[4],
                )
            )
        return grouped

    def update_question(
        self,
        question_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        update_data: dict[str, Any] | None = None,
        edit_reason: str | None = None,
        *,
        updates: dict[str, Any] | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> Question:
        """修改题目并持久化不可变修改痕迹审计日志。

        Args:
            question_id: 题目主键。
            user_id: 租户用户主键。
            update_data: 变更字段映射字典。
            edit_reason: 用户编辑说明备注。
            updates: 变更字段字典 (兼容关键字参数)。
            reason: 编辑说明备注 (兼容关键字参数)。
            kwargs: 兼容其他参数。

        Returns:
            Question: 更新后的题目实体。

        Raises:
            QuestionNotFoundError: 题目不存在或越权。
        """
        resolved_question_id = question_id or kwargs.get("question_id")
        resolved_user_id = user_id or kwargs.get("user_id")
        resolved_updates = (
            update_data
            if update_data is not None
            else (updates if updates is not None else kwargs.get("updates"))
        )
        resolved_reason = (
            edit_reason
            if edit_reason is not None
            else (reason if reason is not None else kwargs.get("reason"))
        )

        if resolved_question_id is None or resolved_user_id is None:
            raise ValueError("question_id 与 user_id 必须指定")
        if resolved_updates is None:
            resolved_updates = {}

        existing = self.question_repo.get_question_by_id(resolved_question_id, resolved_user_id)
        if existing is None:
            raise QuestionNotFoundError("请求的题目不存在或无权访问")

        before_payload = {k: getattr(existing, k) for k in resolved_updates if hasattr(existing, k)}

        try:
            with self.session.begin_nested():
                updated = self.question_repo.update_question(
                    resolved_question_id, resolved_user_id, resolved_updates
                )
                if updated is None:
                    raise QuestionNotFoundError("请求的题目不存在或无权访问")

                after_payload = {
                    k: getattr(updated, k) for k in resolved_updates if hasattr(updated, k)
                }
                audit_log = QuestionAuditLog(
                    user_id=resolved_user_id,
                    question_id=resolved_question_id,
                    action=AuditAction.EDIT.value,
                    changed_fields=list(resolved_updates.keys()),
                    before_payload=before_payload,
                    after_payload=after_payload,
                    reason=resolved_reason,
                )
                self.question_repo.create_audit_log(audit_log, resolved_user_id)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return updated

    def delete_question(
        self,
        question_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        reason: str | None = None,
        **kwargs: Any,
    ) -> bool:
        """软删除单个题目并记录审计日志。

        Args:
            question_id: 题目主键。
            user_id: 租户用户主键。
            reason: 删除原因备注。
            kwargs: 兼容命名参数传递。

        Returns:
            bool: 软删除是否成功。

        Raises:
            QuestionNotFoundError: 题目不存在或越权。
        """
        resolved_question_id = question_id or kwargs.get("question_id")
        resolved_user_id = user_id or kwargs.get("user_id")
        resolved_reason = reason if reason is not None else kwargs.get("reason")

        if resolved_question_id is None or resolved_user_id is None:
            raise ValueError("question_id 与 user_id 必须指定")

        existing = self.question_repo.get_question_by_id(resolved_question_id, resolved_user_id)
        if existing is None:
            raise QuestionNotFoundError("请求的题目不存在或无权访问")

        try:
            with self.session.begin_nested():
                deleted = self.question_repo.soft_delete_question(
                    resolved_question_id, resolved_user_id
                )
                if not deleted:
                    raise QuestionNotFoundError("请求的题目不存在或无权访问")

                audit_log = QuestionAuditLog(
                    user_id=resolved_user_id,
                    question_id=resolved_question_id,
                    action=AuditAction.DELETE.value,
                    changed_fields=["is_deleted"],
                    before_payload={"is_deleted": False},
                    after_payload={"is_deleted": True},
                    reason=resolved_reason,
                )
                self.question_repo.create_audit_log(audit_log, resolved_user_id)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True

    def list_edit_logs(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[QuestionAuditLog]:
        """获取题目的修改痕迹审计日志列表，严格多租户校验。

        Args:
            question_id: 题目主键。
            user_id: 租户用户主键。

        Returns:
            list[QuestionAuditLog]: 审计日志列表。

        Raises:
            QuestionNotFoundError: 题目不存在或越权。
        """
        existing = self.question_repo.get_question_by_id(question_id, user_id)
        if existing is None:
            raise QuestionNotFoundError("请求的题目不存在或无权访问")
        return self.question_repo.list_audit_logs_by_question(question_id, user_id)

    list_audit_logs = list_edit_logs

    def list_quality_checks(
        self,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[QuestionQualityCheck]:
        """按资料获取所有题目的质检明细记录，严格多租户校验。

        Args:
            material_id: 学习资料主键。
            user_id: 租户用户主键。

        Returns:
            list[QuestionQualityCheck]: 质检明细记录列表。

        Raises:
            MaterialNotFoundError: 资料不存在或越权。
        """
        material = self.material_repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError("请求的学习资料不存在或已被删除")
        return self.question_repo.list_quality_checks_by_material(material_id, user_id)

    list_quality_checks_by_material = list_quality_checks

    def ask_coach(
        self,
        question_id: uuid.UUID,
        user_id: uuid.UUID,
        user_prompt: str,
        user_answer: str | None = None,
        grading_points: list[str] | None = None,
    ) -> AskCoachResponse:
        """AI 助教结合题目上下文、用户作答与采分点进行深度启发式答疑。

        Args:
            question_id: 题目主键 UUID。
            user_id: 租户用户主键。
            user_prompt: 学生追问内容。
            user_answer: 学生原始作答（可选）。
            grading_points: 相关采分点（可选）。

        Returns:
            AskCoachResponse: AI 助教答疑内容与延伸思考建议。

        Raises:
            QuestionNotFoundError: 题目不存在或越权。
        """
        question = self.question_repo.get_question_by_id(question_id, user_id)
        if question is None:
            raise QuestionNotFoundError("请求的题目不存在或无权访问")

        system_content = (
            "你是一位耐心的专业 AI 助教。请结合给出的题目题干、标准答案、解析与学生追问，"
            "为学生提供通俗生动、逻辑严密、循序渐进的答疑解析，引导学生掌握核心考点并给出延伸思考建议。"
        )
        context_parts = [
            f"【题干】\n{question.stem}",
            f"【题目类型】\n{question.question_type}",
            f"【标准答案】\n{question.answer}",
        ]
        if question.options:
            context_parts.append(f"【选项】\n{json.dumps(question.options, ensure_ascii=False)}")
        if question.analysis:
            context_parts.append(f"【解析】\n{question.analysis}")
        if user_answer:
            context_parts.append(f"【学生作答】\n{user_answer}")
        if grading_points:
            context_parts.append(f"【采分点/关键词】\n{', '.join(grading_points)}")
        context_parts.append(f"【学生追问】\n{user_prompt}")

        user_content = "\n\n".join(context_parts)
        messages = [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=user_content),
        ]
        options = LLMOptions(temperature=0.7)

        output, _ = self.llm.generate_structured(
            messages=messages,
            response_model=AskCoachResponse,
            options=options,
        )
        return output

    def ask_scoped_coach(
        self,
        *,
        user_id: uuid.UUID,
        user_prompt: str,
        folder_id: uuid.UUID | None = None,
        material_id: uuid.UUID | None = None,
        knowledge_point_id: uuid.UUID | None = None,
    ) -> ScopedCoachResponse:
        """Answer only from snippets in one authorized learning scope."""
        if self.search_adapter is None:
            raise SearchError("课程助教检索服务暂不可用")

        version_id: uuid.UUID | None = None
        material_versions: dict[uuid.UUID, uuid.UUID] = {}
        allowed_snippet_ids: frozenset[uuid.UUID] | None = None
        if folder_id is not None:
            folder = self.folder_repo.get_by_id(folder_id, user_id)
            if folder is None:
                raise FolderNotFoundError("课程不存在或无权访问")
            material_versions = self.question_repo.list_current_versions_for_folder(
                user_id, folder_id
            )
            material_ids = tuple(material_versions)
        elif material_id is not None:
            material = self.material_repo.get_material_by_id(
                material_id, user_id, exclude_archived_folder=True
            )
            if material is None:
                raise MaterialNotFoundError("学习资料不存在或无权访问")
            version_id = material.current_version_id
            is_ready = material.status == MaterialStatus.READY.value
            material_ids = (material.id,) if is_ready and version_id else ()
        elif knowledge_point_id is not None:
            point = self.knowledge_repo.get_by_id(knowledge_point_id, user_id)
            if point is None:
                raise KnowledgeNotFoundError("知识点不存在或无权访问")
            material = self.material_repo.get_material_by_id(
                point.material_id, user_id, exclude_archived_folder=True
            )
            if material is None or material.current_version_id != point.version_id:
                raise KnowledgeNotFoundError("知识点不存在或无权访问")
            material_ids = (material.id,) if material.status == MaterialStatus.READY.value else ()
            version_id = point.version_id
            allowed_snippet_ids = frozenset(
                snippet.id
                for snippet in self.knowledge_repo.get_snippets_for_point(point.id, user_id)
            )
            user_prompt = f"关于知识点「{point.name}」：{user_prompt}"
        else:
            raise ValueError("必须指定答疑范围")

        if not material_ids:
            return ScopedCoachResponse(reply="当前范围没有已解析完成的资料，暂时无法依据资料回答。")
        answer, cited = answer_with_course_evidence(
            search=self.search_adapter,
            llm=self.llm,
            query=user_prompt,
            user_id=user_id,
            material_ids=material_ids,
            version_id=version_id,
            material_versions=material_versions,
            allowed_snippet_ids=allowed_snippet_ids,
        )
        if answer is None:
            return ScopedCoachResponse(
                reply="未在当前资料中找到足够且可核实的依据，暂时无法可靠回答。"
            )
        return ScopedCoachResponse(
            reply=answer.reply,
            suggestions=answer.suggestions,
            sources=[
                CoachSourceResponse(
                    snippet_id=item.snippet_id,
                    material_id=item.material_id,
                    chapter_title=item.chapter_title,
                    excerpt=item.content[:320],
                    source_info=item.source_info,
                )
                for item in cited
            ],
        )
