"""Internal generation DTOs, prompt assembly, and quality-retry loop for QuestionService."""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.core.algorithms.question_quality import (
    CandidateQuestion,
    ExistingQuestionReference,
    QuestionQualityReport,
    filter_qualified_questions,
)
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.models.knowledge import KnowledgePoint
from app.models.material import Material
from app.models.question import Question, QuestionQualityCheck, QuestionType
from app.services._question_llm_schemas import (
    LLMGeneratedQuestionItem,
    LLMQuestionBatchOutput,
)


@dataclass(frozen=True)
class GenerateQuestionsOptions:
    """题目生成高级配置选项。"""

    question_types: Sequence[str] = (
        QuestionType.SINGLE_CHOICE.value,
        QuestionType.MULTIPLE_CHOICE.value,
        QuestionType.TRUE_FALSE.value,
        QuestionType.SHORT_ANSWER.value,
    )
    count: int = 5
    difficulty: int = 3
    max_retries: int = 2

    def __post_init__(self) -> None:
        """校验配置参数合法性。"""
        if self.count <= 0 or self.count > 20:
            raise ValueError("count 必须在 1 到 20 之间")
        if not (1 <= self.difficulty <= 5):
            raise ValueError("difficulty 必须在 1 到 5 之间")
        if self.max_retries < 0 or self.max_retries > 5:
            raise ValueError("max_retries 必须在 0 到 5 之间")
        if not self.question_types:
            raise ValueError("question_types 不能为空")
        valid_types = {item.value for item in QuestionType}
        invalid_types = [item for item in self.question_types if item not in valid_types]
        if invalid_types:
            raise ValueError(f"question_types 含非法题型: {', '.join(invalid_types)}")


@dataclass(frozen=True)
class QuestionGenerationResult:
    """出题服务执行结果传输对象。"""

    batch_id: str
    material_id: uuid.UUID
    version_id: uuid.UUID
    knowledge_point_id: uuid.UUID
    total_generated: int
    qualified_questions: Sequence[Question]
    pending_questions: Sequence[Question]
    quality_checks: Sequence[QuestionQualityCheck]
    retry_count: int


@dataclass(frozen=True)
class MultiKnowledgePointGenerationResult:
    """多考点出题聚合结果传输对象。"""

    batch_id: str
    material_id: uuid.UUID
    version_id: uuid.UUID
    knowledge_point_id: uuid.UUID
    knowledge_point_ids: Sequence[uuid.UUID]
    requested_count: int
    total_generated: int
    qualified_questions: Sequence[Question]
    pending_questions: Sequence[Question]
    quality_checks: Sequence[QuestionQualityCheck]
    retry_count: int


@dataclass(frozen=True)
class SnippetCandidate:
    """检索命中供出题使用的候选切片不可变对象。"""

    snippet_id: uuid.UUID
    content: str
    score: float
    chapter_title: str = ""


@dataclass(frozen=True)
class GenerationLoopOutcome:
    """出题与质检重抽循环聚合中间结果。"""

    qualified_questions: list[CandidateQuestion]
    last_unqualified_questions: list[CandidateQuestion]
    candidate_items_map: dict[str, LLMGeneratedQuestionItem]
    candidate_checks_map: dict[str, list[QuestionQualityCheck]]
    retry_count: int


def distribute_count(total: int, n: int) -> list[int]:
    """将总题量按考点数量均分，余数前置且每个考点至少 1 题。"""
    if total <= 0:
        raise ValueError("total 必须为正整数")
    if n <= 0:
        raise ValueError("n 必须为正整数")
    if total < n:
        return [1] * n
    base, remainder = divmod(total, n)
    return [base + 1 if idx < remainder else base for idx in range(n)]


def aggregate_snippet_context(
    snippets: Sequence[SnippetCandidate],
    max_chars: int = 2400,
) -> tuple[str, list[dict[str, Any]]]:
    """选取 Top 4 优质切片，截断在 2400 字符以内并提取溯源元数据。"""
    chosen = list(snippets[:4])
    context_parts: list[str] = []
    metadata_list: list[dict[str, Any]] = []
    current_length = 0

    for idx, snip in enumerate(chosen):
        title = snip.chapter_title if snip.chapter_title else f"片段 {idx + 1}"
        header = f"--- [切片 {idx}] (章节: {title}) ---\n"
        body = snip.content.strip()
        part = header + body + "\n\n"

        if current_length + len(part) > max_chars:
            remaining = max_chars - current_length - len(header) - 4
            if remaining > 20:
                truncated_body = body[:remaining] + "..."
                context_parts.append(header + truncated_body + "\n\n")
                metadata_list.append(
                    {
                        "snippet_id": str(snip.snippet_id),
                        "similarity": round(snip.score, 4),
                        "index": idx,
                    }
                )
            break

        context_parts.append(part)
        current_length += len(part)
        metadata_list.append(
            {
                "snippet_id": str(snip.snippet_id),
                "similarity": round(snip.score, 4),
                "index": idx,
            }
        )

    return "".join(context_parts).strip(), metadata_list


def build_generation_prompt(
    kp_name: str,
    kp_description: str,
    context_text: str,
    question_types: Sequence[str],
    count: int,
    difficulty: int,
    feedback: str | None = None,
) -> list[LLMMessage]:
    """构造大模型出题提示词上下文。"""
    system_content = (
        "你是一名资深教育命题专家。你的任务是严格依据所提供的资料切片内容，"
        "针对指定的核心知识点生成高质量的练习题目。\n"
        "【硬性命题铁律】:\n"
        "1. 事实完全忠于资料：题目的题干、选项与参考答案必须源自资料切片，绝不可编造概念；\n"
        "2. 题干长度：题干去空白字符数必须不少于 6 字符，表述必须清晰严谨，无任何歧义；\n"
        "3. 客观选择题规范：单选必须且仅有 1 个正确答案（如 'A'）；"
        "多选必须 >=3 个选项且正确答案数 >=2，"
        "多选答案必须为逗号分隔的纯字符串（如 'A,B,C' 或 'ABC'，严禁返回 JSON 数组）；\n"
        "4. 判断题规范：答案必须明确标注为字符串'正确'或'错误'（严禁返回布尔值）；\n"
        "5. 填空题规范：答案必须为纯字符串（若多空以分号分隔，如 '答案1; 答案2'，严禁返回数组）；\n"
        "6. 主观题评分细则：主观题必须提供 grading_rubric 对象"
        "（格式如 {'total_score': 5, 'points': [{'point': '...', 'score': 2}]}），"
        "要点分值总和严格等于 total_score；非主观题 grading_rubric 置为 null；\n"
        "7. 来源切片标注：每道题目必须标注 source_snippet_index (0~3)，指明主要依据的切片序号；\n"
        "8. 输出格式规范：必须输出包含 questions 列表的纯 JSON 对象，"
        '每题必须包含 question_type, stem, options([{"key": "A", "content": "..."}]), '
        "answer(纯字符串), analysis, difficulty, grading_rubric, source_snippet_index。"
    )

    user_parts = [
        f"【核心考查知识点】: {kp_name}",
        f"【知识点内涵阐述】: {kp_description if kp_description else '依据下述切片全面考查'}",
        f"【期望生成题型】: {', '.join(question_types)}",
        f"【期望出题数量】: {count} 道",
        f"【目标难度级别】: {difficulty} (1:基础 ~ 5:专家)",
        "\n【参考资料切片正文】:",
        context_text,
    ]
    if feedback:
        user_parts.append(
            f"\n【上一轮质检未通过反馈】:\n{feedback}\n"
            "请特别注意修正上述缺陷，严格避免重复、缺乏实词依据或答案冲突！"
        )
    user_parts.append("\n请输出符合契约的结构化题目列表。")

    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content="\n".join(user_parts)),
    ]


def convert_llm_items_to_candidates(
    items: Sequence[LLMGeneratedQuestionItem],
    snippet_metadata: list[dict[str, Any]],
    aggregated_source_text: str,
    embeddings: Sequence[Sequence[float]] | None = None,
    start_seq: int = 0,
) -> tuple[list[CandidateQuestion], dict[str, LLMGeneratedQuestionItem]]:
    """将大模型生成的题目结构转化为纯函数质检核所需的 CandidateQuestion。"""
    candidates: list[CandidateQuestion] = []
    item_map: dict[str, LLMGeneratedQuestionItem] = {}

    for idx, it in enumerate(items):
        q_id = str(uuid.uuid4())
        item_map[q_id] = it

        snip_idx = it.source_snippet_index
        if 0 <= snip_idx < len(snippet_metadata):
            snip_id_str = snippet_metadata[snip_idx]["snippet_id"]
        elif snippet_metadata:
            snip_id_str = snippet_metadata[0]["snippet_id"]
        else:
            snip_id_str = ""

        opt_dicts = tuple(opt.model_dump() for opt in it.options)
        emb = tuple(embeddings[idx]) if embeddings and idx < len(embeddings) else None
        candidates.append(
            CandidateQuestion(
                question_id=q_id,
                stem=it.stem,
                question_type=it.question_type,
                answer=it.answer,
                options=opt_dicts,
                source_snippet_ids=(snip_id_str,) if snip_id_str else (),
                source_text=aggregated_source_text,
                embedding=emb,
                analysis=it.analysis,
                created_at_seq=start_seq + idx,
            )
        )
    return candidates, item_map


def resolve_effective_version_id(
    material: Material,
    kp: KnowledgePoint,
    requested_version_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """结合资料激活版本与知识点所属版本解析最终出题版本。"""
    if (
        requested_version_id is None
        or requested_version_id == material.id
        or requested_version_id != kp.version_id
    ):
        return kp.version_id or getattr(material, "current_version_id", None)
    return requested_version_id


def build_existing_question_refs(
    recent_questions: Sequence[Question],
) -> list[ExistingQuestionReference]:
    """将近期已持久化题目转换至纯函数查重引用集合。"""
    return [
        ExistingQuestionReference(
            question_id=str(rq.id),
            stem=rq.stem,
            question_type=rq.question_type,
            answer=rq.answer,
            options=tuple(rq.options) if rq.options else (),
            embedding=tuple(rq.embedding) if rq.embedding else None,
        )
        for rq in recent_questions
    ]


def collect_quality_checks_by_question(
    report: QuestionQualityReport,
    *,
    user_id: uuid.UUID,
    batch_id: str,
) -> dict[str, list[QuestionQualityCheck]]:
    """将质检核评估报告按题目主键整理为待持久化质检明细映射。"""
    checks_map: dict[str, list[QuestionQualityCheck]] = {}
    for res in report.results:
        checks_map[res.question_id] = [
            QuestionQualityCheck(
                user_id=user_id,
                question_id=uuid.UUID(res.question_id),
                batch_id=batch_id,
                check_type=check_item.check_type.value,
                is_passed=check_item.is_passed,
                reason=check_item.reason,
                similarity_score=check_item.similarity_score,
                check_metadata=check_item.metadata,
            )
            for check_item in res.check_items
        ]
    return checks_map


def run_question_generation_loop(
    *,
    llm: LLMProtocol,
    embedding: EmbeddingProtocol,
    user_id: uuid.UUID,
    batch_id: str,
    kp_name: str,
    kp_description: str,
    context_text: str,
    snippet_metadata: list[dict[str, Any]],
    existing_refs: Sequence[ExistingQuestionReference],
    options: GenerateQuestionsOptions,
) -> GenerationLoopOutcome:
    """执行大模型结构化出题、向量化、纯函数质检与失败反馈重抽循环。"""
    target_count = options.count
    retry_count = 0
    prompt_feedback: str | None = None
    candidate_items_map: dict[str, LLMGeneratedQuestionItem] = {}
    candidate_questions_map: dict[str, CandidateQuestion] = {}
    candidate_checks_map: dict[str, list[QuestionQualityCheck]] = {}
    qualified_questions_list: list[CandidateQuestion] = []
    last_unqualified_questions: list[CandidateQuestion] = []

    while retry_count <= options.max_retries:
        needed_count = target_count - len(qualified_questions_list)
        if needed_count <= 0:
            break

        messages = build_generation_prompt(
            kp_name=kp_name,
            kp_description=kp_description,
            context_text=context_text,
            question_types=options.question_types,
            count=needed_count,
            difficulty=options.difficulty,
            feedback=prompt_feedback,
        )
        output, _ = llm.generate_structured(
            messages=messages,
            response_model=LLMQuestionBatchOutput,
            options=LLMOptions(temperature=0.3),
        )
        generated_items = output.questions if output else []
        if not generated_items:
            if retry_count >= options.max_retries:
                break
            retry_count += 1
            prompt_feedback = "上一轮未生成任何题目，请严格依据资料切片输出题目。"
            continue

        embed_texts = [
            f"{q.stem} {' '.join(str(opt.content) for opt in q.options)}".strip()
            for q in generated_items
        ]
        embeddings = embedding.embed_documents(embed_texts) if embed_texts else []
        attempt_candidates, item_map = convert_llm_items_to_candidates(
            generated_items,
            snippet_metadata=snippet_metadata,
            aggregated_source_text=context_text,
            embeddings=embeddings,
            start_seq=len(candidate_questions_map),
        )
        candidate_items_map.update(item_map)
        for cand in attempt_candidates:
            candidate_questions_map[cand.question_id] = cand

        report = filter_qualified_questions(
            candidates=qualified_questions_list + attempt_candidates,
            existing_questions=existing_refs,
        )
        candidate_checks_map.update(
            collect_quality_checks_by_question(report, user_id=user_id, batch_id=batch_id)
        )
        qualified_questions_list = list(report.qualified_questions)
        last_unqualified_questions = list(report.unqualified_questions)

        if len(qualified_questions_list) >= target_count:
            break
        if retry_count >= options.max_retries or not last_unqualified_questions:
            break
        retry_count += 1
        unqualified_reasons = [
            (
                f"题型[{candidate_questions_map[res.question_id].question_type}]"
                f"未通过原因: {res.unqualified_reason}"
            )
            for res in report.results
            if not res.is_qualified
            and res.unqualified_reason
            and res.question_id in candidate_questions_map
        ]
        prompt_feedback = "；".join(unqualified_reasons[:3])

    return GenerationLoopOutcome(
        qualified_questions=qualified_questions_list,
        last_unqualified_questions=last_unqualified_questions,
        candidate_items_map=candidate_items_map,
        candidate_checks_map=candidate_checks_map,
        retry_count=retry_count,
    )


def build_question_entity(
    cand: CandidateQuestion,
    llm_item: LLMGeneratedQuestionItem,
    *,
    user_id: uuid.UUID,
    material_id: uuid.UUID,
    version_id: uuid.UUID,
    knowledge_point_id: uuid.UUID,
    batch_id: str,
    status: str,
    snippet_metadata: list[dict[str, Any]],
) -> Question:
    """将质检候选条目统一构造为可持久化的 Question ORM 实体。"""
    source_snip_id = uuid.UUID(cand.source_snippet_ids[0]) if cand.source_snippet_ids else None
    rubric_dict: dict[str, Any] = (
        llm_item.grading_rubric.model_dump() if llm_item.grading_rubric is not None else {}
    )
    return Question(
        id=uuid.UUID(cand.question_id),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        knowledge_point_id=knowledge_point_id,
        source_snippet_id=source_snip_id,
        question_type=cand.question_type,
        status=status,
        is_deleted=False,
        batch_id=batch_id,
        stem=cand.stem,
        options=list(cand.options),
        answer=cand.answer,
        analysis=cand.analysis,
        difficulty=llm_item.difficulty,
        grading_rubric=rubric_dict,
        source_snippet_ids=snippet_metadata,
        embedding=list(cand.embedding) if cand.embedding is not None else None,
    )


__all__ = [
    "GenerateQuestionsOptions",
    "GenerationLoopOutcome",
    "MultiKnowledgePointGenerationResult",
    "QuestionGenerationResult",
    "SnippetCandidate",
    "aggregate_snippet_context",
    "build_existing_question_refs",
    "build_generation_prompt",
    "build_question_entity",
    "convert_llm_items_to_candidates",
    "distribute_count",
    "resolve_effective_version_id",
    "run_question_generation_loop",
]
