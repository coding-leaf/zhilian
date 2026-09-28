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
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.algorithms.question_quality import (
    CandidateQuestion,
    ExistingQuestionReference,
    extract_keywords,
    filter_qualified_questions,
)
from app.core.errors import (
    FolderNotFoundError,
    KnowledgeNotFoundError,
    MaterialNotFoundError,
    MissingSourceSnippetError,
    QuestionNotFoundError,
    SearchError,
)
from app.core.security import generate_user_ref
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.agent_graph import run_structured_agent_workflow
from app.integrations.llm.coach_graph import answer_with_course_evidence
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
)
from app.integrations.search.protocol import SearchProtocol
from app.models.knowledge import KnowledgePoint
from app.models.material import MaterialStatus
from app.models.question import (
    AuditAction,
    Question,
    QuestionAuditLog,
    QuestionQualityCheck,
    QuestionStatus,
    QuestionType,
)
from app.repositories.folder import FolderRepository
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.repositories.question import QuestionRepository
from app.schemas.material import SourceSnippetDTO
from app.schemas.question import (
    AskCoachResponse,
    CoachSourceResponse,
    QuestionDetailResponse,
    ScopedCoachResponse,
)
from app.services.source_snippets import build_source_snippet_map

logger = logging.getLogger(__name__)

# ==============================================================================
# 题目生成配置与传输对象 (DTOs)
# ==============================================================================


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


# ==============================================================================
# 大模型结构化出题 Pydantic Schema
# ==============================================================================


class LLMQuestionOptionItem(BaseModel):
    """客观题选项条目。"""

    key: str = Field(description="选项标识，如 A, B, C, D")
    content: str = Field(description="选项文本内容")


class LLMGradingPointItem(BaseModel):
    """主观题采分要点条目。"""

    point: str = Field(description="采分要点阐述")
    score: int = Field(ge=1, description="本要点分值")

    @model_validator(mode="before")
    @classmethod
    def _normalize_point(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"point": data.strip() or "采分要点", "score": 1}
        if isinstance(data, dict):
            d = dict(data)
            if "point" not in d or not d["point"]:
                d["point"] = (
                    d.get("content")
                    or d.get("text")
                    or d.get("description")
                    or d.get("criterion")
                    or d.get("name")
                    or "采分要点"
                )
            raw_score = d.get("score")
            if raw_score is None:
                d["score"] = 1
            else:
                try:
                    score_val = int(float(raw_score))
                    d["score"] = max(1, score_val)
                except (ValueError, TypeError):
                    d["score"] = 1
            return d
        return data


class LLMGradingRubric(BaseModel):
    """主观题评分细则。"""

    total_score: int = Field(ge=1, description="主观题总分")
    points: list[LLMGradingPointItem] = Field(
        default_factory=list,
        description="采分要点列表",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_rubric(cls, data: Any) -> Any:
        if isinstance(data, list):
            points = data
            total = 0
            for p in points:
                if isinstance(p, dict):
                    try:
                        total += max(1, int(float(p.get("score", 1))))
                    except (ValueError, TypeError):
                        total += 1
                elif isinstance(p, LLMGradingPointItem):
                    total += p.score
                elif isinstance(p, str):
                    total += 1
            return {
                "total_score": max(1, total),
                "points": points,
            }
        if isinstance(data, str):
            s = data.strip()
            if not s or s.lower() in ("none", "null", "无", "{}"):
                return {"total_score": 5, "points": []}
            return {
                "total_score": 5,
                "points": [{"point": s, "score": 5}],
            }
        if isinstance(data, dict):
            d = dict(data)
            if "points" not in d:
                for alt_key in ("rubric", "items", "criteria", "points_list"):
                    if alt_key in d and isinstance(d[alt_key], list):
                        d["points"] = d[alt_key]
                        break
            points = d.get("points") or []
            if not isinstance(points, list):
                points = [points] if points else []
                d["points"] = points

            raw_total = d.get("total_score")
            total_score_val = 0
            if raw_total is not None:
                try:
                    total_score_val = int(float(raw_total))
                except (ValueError, TypeError):
                    total_score_val = 0

            if total_score_val < 1:
                computed = 0
                for p in points:
                    if isinstance(p, dict):
                        try:
                            computed += max(1, int(float(p.get("score", 1))))
                        except (ValueError, TypeError):
                            computed += 1
                    elif isinstance(p, LLMGradingPointItem):
                        computed += p.score
                    elif isinstance(p, str):
                        computed += 1
                total_score_val = max(1, computed) if computed > 0 else 5

            d["total_score"] = total_score_val
            return d
        return data


class LLMGeneratedQuestionItem(BaseModel):
    """大模型抽取的单道题目数据结构。"""

    question_type: str = Field(description="题型枚举")
    stem: str = Field(description="题干内容，至少 6 字符")
    options: list[LLMQuestionOptionItem] = Field(
        default_factory=list,
        description="客观题选项列表",
    )
    answer: str = Field(description="参考答案或标准答案")
    analysis: str = Field(default="", description="题目解析")
    difficulty: int = Field(default=3, ge=1, le=5, description="题目难度系数")
    grading_rubric: LLMGradingRubric | None = Field(
        default=None,
        description="主观题评分细则",
    )
    source_snippet_index: int = Field(
        default=0,
        description="主要依据的切片序号 (0~3)",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_item(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        # 兼容 question / title 映射至 stem
        if ("stem" not in d or not d["stem"]) and ("question" in d or "title" in d):
            d["stem"] = d.get("question") or d.get("title")

        # 兼容 options 为字符串列表 ["...", "..."] 或字典不规范形式
        raw_options = d.get("options")
        if isinstance(raw_options, list):
            normalized_opts: list[dict[str, Any]] = []
            for idx, opt in enumerate(raw_options):
                if isinstance(opt, str):
                    key = chr(ord("A") + idx)
                    if len(opt) > 2 and opt[0].isalpha() and opt[1] in (".", "、", ":", " "):
                        key = opt[0].upper()
                        opt_content = opt[2:].strip()
                    else:
                        opt_content = opt
                    normalized_opts.append({"key": key, "content": opt_content})
                elif isinstance(opt, dict):
                    opt_dict = dict(opt)
                    if "content" not in opt_dict and "text" in opt_dict:
                        opt_dict["content"] = opt_dict["text"]
                    if "key" not in opt_dict:
                        opt_dict["key"] = chr(ord("A") + idx)
                    normalized_opts.append(opt_dict)
                else:
                    normalized_opts.append(opt)
            d["options"] = normalized_opts

        # 兼容 difficulty_level / target_difficulty
        if "difficulty" not in d:
            if "target_difficulty" in d:
                d["difficulty"] = d["target_difficulty"]
            elif "difficulty_level" in d:
                d["difficulty"] = d["difficulty_level"]

        # 兼容与规范化 answer（list/tuple 转字符串、bool 转正确/错误、数值转 str）
        raw_answer = d.get("answer")
        if raw_answer is None:
            raw_answer = (
                d.get("correct_answer") if "correct_answer" in d else d.get("standard_answer")
            )

        if raw_answer is None:
            d["answer"] = "A"
        elif isinstance(raw_answer, bool):
            d["answer"] = "正确" if raw_answer else "错误"
        elif isinstance(raw_answer, (list, tuple)):
            items = [str(x).strip() for x in raw_answer if x is not None and str(x).strip()]
            if all(len(x) == 1 and x.isalpha() for x in items):
                d["answer"] = ",".join(x.upper() for x in items)
            else:
                d["answer"] = "; ".join(items) if len(items) > 1 else (items[0] if items else "")
        elif isinstance(raw_answer, (int, float)):
            d["answer"] = str(raw_answer)
        elif isinstance(raw_answer, str):
            d["answer"] = raw_answer.strip()
        else:
            d["answer"] = str(raw_answer).strip()

        # 兼容与清洗 grading_rubric（空/无效清洗为 None）
        raw_rubric = d.get("grading_rubric")
        if raw_rubric is not None:
            if isinstance(raw_rubric, str):
                cleaned_rubric_str = raw_rubric.strip()
                if not cleaned_rubric_str or cleaned_rubric_str.lower() in (
                    "none",
                    "null",
                    "无",
                    "{}",
                ):
                    d["grading_rubric"] = None
                else:
                    d["grading_rubric"] = cleaned_rubric_str
            elif isinstance(raw_rubric, (list, tuple)):
                if not raw_rubric:
                    d["grading_rubric"] = None
                else:
                    d["grading_rubric"] = list(raw_rubric)
            elif isinstance(raw_rubric, dict):
                if not raw_rubric:
                    d["grading_rubric"] = None
                else:
                    d["grading_rubric"] = raw_rubric

        return d


class LLMQuestionBatchOutput(BaseModel):
    """大模型批次出题输出容器 DTO。"""

    questions: list[LLMGeneratedQuestionItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_batch(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"questions": data}
        if isinstance(data, dict) and "questions" not in data and "items" in data:
            data["questions"] = data["items"]
        return data


# ==============================================================================
# 纯数据处理与上下文组装辅助函数 (McCabe V(G) <= 8)
# ==============================================================================


def distribute_count(total: int, n: int) -> list[int]:
    """将总题量按考点数量均分，余数前置且每个考点至少 1 题。

    Args:
        total: 期望生成的总题量（正整数）。
        n: 考点数量（正整数）。

    Returns:
        list[int]: 与考点一一对应的题量分配列表，长度等于 n 且每项 >= 1。
            当 total < n 时退化为每个考点各 1 题（实际总数 = n）。

    Raises:
        ValueError: 当 total 或 n 非正整数时抛出。
    """
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
    """选取 Top 4 优质切片，截断在 2400 字符以内并提取溯源元数据。

    Args:
        snippets: 候选切片序列。
        max_chars: 上下文字符数上限，默认 2400 字符。

    Returns:
        tuple[str, list[dict[str, Any]]]: (聚合文本, 切片元数据清单)。
    """
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

    aggregated_text = "".join(context_parts).strip()
    return aggregated_text, metadata_list


def build_generation_prompt(
    kp_name: str,
    kp_description: str,
    context_text: str,
    question_types: Sequence[str],
    count: int,
    difficulty: int,
    feedback: str | None = None,
) -> list[LLMMessage]:
    """构造大模型出题提示词上下文。

    Args:
        kp_name: 知识点名称。
        kp_description: 知识点描述。
        context_text: 聚合切片上下文。
        question_types: 目标题型列表。
        count: 生成题目数量。
        difficulty: 题目目标难度 (1~5)。
        feedback: 质检未通过历史反馈信息。

    Returns:
        list[LLMMessage]: 组装完毕的提示词消息序列。
    """
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
            f"\n【上一轮质检未通过反馈】:\n{feedback}\n请特别注意修正上述缺陷，严格避免重复、缺乏实词依据或答案冲突！"
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
    """将大模型生成的题目结构转化为纯函数质检核所需的 CandidateQuestion。

    Args:
        items: 大模型结构化题目对象序列。
        snippet_metadata: 切片溯源元数据列表。
        aggregated_source_text: 聚合切片原文。
        embeddings: 题干语义向量列表（若有）。
        start_seq: 批次序列号起始游标。

    Returns:
        tuple[list[CandidateQuestion], dict[str, LLMGeneratedQuestionItem]]:
            (待质检候选题目列表, question_id 到原始条目映射字典)。
    """
    candidates: list[CandidateQuestion] = []
    item_map: dict[str, LLMGeneratedQuestionItem] = {}

    for idx, it in enumerate(items):
        q_id = str(uuid.uuid4())
        item_map[q_id] = it

        # 匹配来源切片标识
        snip_idx = it.source_snippet_index
        if 0 <= snip_idx < len(snippet_metadata):
            snip_id_str = snippet_metadata[snip_idx]["snippet_id"]
        elif snippet_metadata:
            snip_id_str = snippet_metadata[0]["snippet_id"]
        else:
            snip_id_str = ""

        opt_dicts = tuple(opt.model_dump() for opt in it.options)
        emb = tuple(embeddings[idx]) if embeddings and idx < len(embeddings) else None

        candidate = CandidateQuestion(
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
        candidates.append(candidate)

    return candidates, item_map


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
    ) -> None:
        """初始化题目服务实例。

        Args:
            session: SQLAlchemy 数据库会话。
            llm: 大模型网关适配器。
            embedding: 向量化网关适配器。
            search_adapter: 可选的混合检索适配器。
        """
        self.session = session
        self.llm = llm
        self.embedding = embedding
        self.search_adapter = search_adapter
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

        # 智能版本回退与容错：
        # 如果客户端传入的 version_id 为空，或者客户端误传了 version_id == material_id，
        # 或者传入的 version_id 与知识点所属的 kp.version_id 不符但知识点确实属于该 material_id，
        # 自动将 effective_version_id 对齐为 kp.version_id（或 material.current_version_id）
        effective_version_id = version_id
        if (
            effective_version_id is None
            or effective_version_id == material_id
            or effective_version_id != kp.version_id
        ):
            fallback_version_id = kp.version_id or getattr(material, "current_version_id", None)
            if fallback_version_id is None:
                raise KnowledgeNotFoundError("请求的知识点不存在关联版本")
            effective_version_id = fallback_version_id

        # 2. 检索前置门禁校验
        snippets = self._retrieve_and_gate_snippets(
            user_id=user_id,
            material_id=material_id,
            version_id=effective_version_id,
            knowledge_point_id=knowledge_point_id,
            kp_name=kp.name,
            kp_description=kp.description,
        )

        # 3. 上下文聚合: Top 4 切片，截断在 2400 字符内
        context_text, snippet_metadata = aggregate_snippet_context(snippets, max_chars=2400)

        # 4. 获取历史已有题目比对基准 (滑动窗口 500 道)
        recent_questions = self.question_repo.list_recent_for_deduplication(
            material_id, user_id, limit=500
        )
        existing_refs = [
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

        # 5. 抽取与质检重抽循环 (最多 2 次重抽)
        target_count = effective_options.count
        retry_count = 0
        prompt_feedback: str | None = None

        candidate_items_map: dict[str, LLMGeneratedQuestionItem] = {}
        candidate_questions_map: dict[str, CandidateQuestion] = {}
        candidate_checks_map: dict[str, list[QuestionQualityCheck]] = {}

        qualified_questions_list: list[CandidateQuestion] = []
        last_unqualified_questions: list[CandidateQuestion] = []

        while retry_count <= effective_options.max_retries:
            needed_count = target_count - len(qualified_questions_list)
            if needed_count <= 0:
                break

            # 构造提示词
            messages = build_generation_prompt(
                kp_name=kp.name,
                kp_description=kp.description,
                context_text=context_text,
                question_types=effective_options.question_types,
                count=needed_count,
                difficulty=effective_options.difficulty,
                feedback=prompt_feedback,
            )

            # 调用大模型结构化出题
            output, _ = run_structured_agent_workflow(
                messages=messages,
                response_model=LLMQuestionBatchOutput,
                adapter=self.llm,
                options=LLMOptions(temperature=0.3),
            )
            generated_items = output.questions if output else []
            if not generated_items:
                if retry_count < effective_options.max_retries:
                    retry_count += 1
                    prompt_feedback = "上一轮未生成任何题目，请严格依据资料切片输出题目。"
                    continue
                break

            # 向量化题干
            embed_texts = [
                f"{q.stem} {' '.join(str(opt.content) for opt in q.options)}".strip()
                for q in generated_items
            ]
            embeddings: list[list[float]] = []
            if embed_texts:
                embeddings = self.embedding.embed_documents(embed_texts)

            # 转换为 CandidateQuestion
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

            # 纯函数质检: 校验包含已有合格题目与当前新生成题目
            current_eval_candidates = qualified_questions_list + attempt_candidates
            report = filter_qualified_questions(
                candidates=current_eval_candidates,
                existing_questions=existing_refs,
            )

            # 收集每个题目的质检明细记录
            for res in report.results:
                checks_for_q: list[QuestionQualityCheck] = []
                for check_item in res.check_items:
                    checks_for_q.append(
                        QuestionQualityCheck(
                            user_id=user_id,
                            question_id=uuid.UUID(res.question_id),
                            batch_id=effective_batch_id,
                            check_type=check_item.check_type.value,
                            is_passed=check_item.is_passed,
                            reason=check_item.reason,
                            similarity_score=check_item.similarity_score,
                            check_metadata=check_item.metadata,
                        )
                    )
                candidate_checks_map[res.question_id] = checks_for_q

            # 更新合格题目与残余未通过题目
            qualified_questions_list = list(report.qualified_questions)
            last_unqualified_questions = list(report.unqualified_questions)

            # 判定重抽与反馈
            if len(qualified_questions_list) >= target_count:
                break

            if retry_count < effective_options.max_retries and last_unqualified_questions:
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
            else:
                break

        # 6. 构造题目主实体
        qualified_questions: list[Question] = []
        pending_questions: list[Question] = []
        all_quality_checks: list[QuestionQualityCheck] = []

        # 合格题目入库归档
        for cand in qualified_questions_list[:target_count]:
            llm_item = candidate_items_map[cand.question_id]
            source_snip_id = (
                uuid.UUID(cand.source_snippet_ids[0]) if cand.source_snippet_ids else None
            )
            rubric_dict: dict[str, Any] = {}
            if llm_item.grading_rubric is not None:
                rubric_dict = llm_item.grading_rubric.model_dump()

            q_entity = Question(
                id=uuid.UUID(cand.question_id),
                user_id=user_id,
                material_id=material_id,
                version_id=effective_version_id,
                knowledge_point_id=knowledge_point_id,
                source_snippet_id=source_snip_id,
                question_type=cand.question_type,
                status=QuestionStatus.AVAILABLE.value,
                is_deleted=False,
                batch_id=effective_batch_id,
                stem=cand.stem,
                options=list(cand.options),
                answer=cand.answer,
                analysis=cand.analysis,
                difficulty=llm_item.difficulty,
                grading_rubric=rubric_dict,
                source_snippet_ids=snippet_metadata,
                embedding=list(cand.embedding) if cand.embedding is not None else None,
            )
            qualified_questions.append(q_entity)
            if cand.question_id in candidate_checks_map:
                all_quality_checks.extend(candidate_checks_map[cand.question_id])

        # 残余不合格题目作为 pending_review 归档入待处理区
        remaining_needed = target_count - len(qualified_questions)
        for cand in last_unqualified_questions[:remaining_needed]:
            llm_item = candidate_items_map[cand.question_id]
            source_snip_id = (
                uuid.UUID(cand.source_snippet_ids[0]) if cand.source_snippet_ids else None
            )
            rubric_dict = {}
            if llm_item.grading_rubric is not None:
                rubric_dict = llm_item.grading_rubric.model_dump()

            q_entity = Question(
                id=uuid.UUID(cand.question_id),
                user_id=user_id,
                material_id=material_id,
                version_id=effective_version_id,
                knowledge_point_id=knowledge_point_id,
                source_snippet_id=source_snip_id,
                question_type=cand.question_type,
                status=QuestionStatus.PENDING_REVIEW.value,
                is_deleted=False,
                batch_id=effective_batch_id,
                stem=cand.stem,
                options=list(cand.options),
                answer=cand.answer,
                analysis=cand.analysis,
                difficulty=llm_item.difficulty,
                grading_rubric=rubric_dict,
                source_snippet_ids=snippet_metadata,
                embedding=list(cand.embedding) if cand.embedding is not None else None,
            )
            pending_questions.append(q_entity)
            if cand.question_id in candidate_checks_map:
                all_quality_checks.extend(candidate_checks_map[cand.question_id])

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

        # 单事务原子编排：所有考点在同一事务内仅 flush（defer_commit=True），
        # 全部成功后一次性提交；任一考点失败则整批回滚，不遗留部分题目。
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

            # 全部考点成功：单次提交，保证多考点批次原子落库。
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

    get_question_detail = get_question

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
            include_deleted=include_deleted or bool(kwargs.get("include_deleted", False)),
            limit=calc_limit,
            offset=calc_offset,
        )

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
