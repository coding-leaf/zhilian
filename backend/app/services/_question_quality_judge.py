"""Batched AI quality judge and targeted repair loop for flagged question candidates."""

import json
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.algorithms.question_quality import (
    CandidateQuestion,
    ExistingQuestionReference,
    QualityCheckType,
    QualitySeverity,
    QuestionQualityConfig,
    SingleQuestionQualityResult,
    evaluate_single_question,
)
from app.core.errors import LLMAuthError
from app.core.security import generate_user_ref
from app.integrations.embedding.protocol import EmbeddingProtocol
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.models.question import QuestionQualityCheck
from app.services._question_llm_schemas import LLMGeneratedQuestionItem

logger = logging.getLogger(__name__)

AI_JUDGE_CHECK_TYPE = "AI_JUDGE"


class LLMQuestionJudgeDecision(BaseModel):
    """单题 AI 质检裁决与定向修复结构。"""

    question_index: int = Field(ge=0, description="待裁决题目在批次中的索引")
    verdict: Literal["approve", "repair", "reject"] = Field(
        description="裁决结论: approve(仅允许 SOFT_FLAG) / repair(原地修复) / reject(淘汰)"
    )
    reason: str = Field(default="", description="简要中文裁决依据")
    repaired_question: LLMGeneratedQuestionItem | None = Field(
        default=None,
        description="当 verdict 为 repair 时提供修复后的完整题目",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_decision(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if isinstance(d.get("verdict"), str):
            d["verdict"] = d["verdict"].strip().lower()
        if d.get("reason") is None:
            d["reason"] = ""
        return d


class LLMQuestionJudgeBatchOutput(BaseModel):
    """批量 AI 质检裁决输出容器。"""

    decisions: list[LLMQuestionJudgeDecision] = Field(default_factory=list)


@dataclass(frozen=True)
class FlaggedCandidateEntry:
    """待 AI 裁决或修复的候选题上下文包装对象。"""

    candidate: CandidateQuestion
    precheck_result: SingleQuestionQualityResult
    llm_item: LLMGeneratedQuestionItem


@dataclass(frozen=True)
class JudgeBatchResult:
    """批量 AI 质检裁决与修复处理结果。"""

    approved_candidates: list[CandidateQuestion]
    approved_items_map: dict[str, LLMGeneratedQuestionItem]
    checks_map: dict[str, list[QuestionQualityCheck]]
    rejected_candidates: list[CandidateQuestion]
    rejected_reasons: list[str]


def _extract_reference_hints(precheck_result: SingleQuestionQualityResult) -> list[dict[str, str]]:
    """从预检诊断项中提取触发重复或冲突的参考题目摘要。"""
    hints: list[dict[str, str]] = []
    for item in precheck_result.check_items:
        matched_stem = item.metadata.get("matched_stem")
        if isinstance(matched_stem, str) and matched_stem:
            hints.append(
                {
                    "check_type": item.check_type.value,
                    "matched_stem": matched_stem,
                    "matched_answer": str(item.metadata.get("matched_answer", "")),
                }
            )
    return hints


def _build_judge_prompt(
    *,
    flagged_entries: Sequence[FlaggedCandidateEntry],
    kp_name: str,
    kp_description: str,
    context_text: str,
) -> list[LLMMessage]:
    """构造单次批量 AI 质检裁决与定向修复提示词。"""
    system_content = (
        "你是一名严谨的教育题库质检裁判与题目修复专家。请对照【参考资料切片】对预检标疑的题目"
        "逐题作出裁决并按需原地修复。\n"
        "【裁决规则】:\n"
        "1. approve：仅当 severity='soft_flag' 且题目事实忠于资料、数学/逻辑无误、与参考题"
        "考查角度明显不同（如设问极性相反或公式表达式导致词面重合率低）时允许放行；"
        "若 severity='hard_defect'，严禁使用 approve。\n"
        "2. repair：当题目存在可修复缺陷（如选项重复、答案键错误、表述歧义、或与已有题近似需"
        "改换考查角度）时，返回修复后的完整 repaired_question（包含 question_type, stem, "
        "options, answer, analysis, difficulty, grading_rubric, source_snippet_index）。\n"
        "3. reject：若题目严重脱离资料、存在不可挽回的逻辑错误或完全重复无法改写，选择 reject。\n"
        "4. 输出必须是包含 decisions 列表的 JSON 对象，覆盖每一道输入题目对应的 question_index。"
    )

    items_payload: list[dict[str, Any]] = []
    for idx, entry in enumerate(flagged_entries):
        cand = entry.candidate
        res = entry.precheck_result
        items_payload.append(
            {
                "question_index": idx,
                "severity": res.severity.value,
                "defect_type": res.unqualified_type.value if res.unqualified_type else "",
                "defect_reason": res.unqualified_reason or "",
                "question_type": cand.question_type,
                "stem": cand.stem,
                "options": list(cand.options),
                "answer": cand.answer,
                "analysis": cand.analysis,
                "source_snippet_index": entry.llm_item.source_snippet_index,
                "reference_matches": _extract_reference_hints(res),
            }
        )

    user_content = (
        f"【核心知识点】: {kp_name}\n"
        f"【知识点说明】: {kp_description or '依据参考资料切片考查'}\n\n"
        f"【参考资料切片正文】:\n{context_text}\n\n"
        f"【待裁决题目列表】:\n{json.dumps(items_payload, ensure_ascii=False)}"
    )
    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content=user_content),
    ]


def _resolve_snippet_ids(
    snippet_index: int,
    snippet_metadata: Sequence[dict[str, Any]],
) -> tuple[str, ...]:
    """根据切片序号解析来源切片标识元组。"""
    if 0 <= snippet_index < len(snippet_metadata):
        return (str(snippet_metadata[snippet_index]["snippet_id"]),)
    if snippet_metadata:
        return (str(snippet_metadata[0]["snippet_id"]),)
    return ()


def _build_repaired_candidate(
    *,
    original: CandidateQuestion,
    repaired_item: LLMGeneratedQuestionItem,
    context_text: str,
    snippet_metadata: Sequence[dict[str, Any]],
    embedding: EmbeddingProtocol,
) -> CandidateQuestion:
    """将修复后的 LLM 题目转为 CandidateQuestion 并重算语义向量。"""
    embed_text = (
        f"{repaired_item.stem} {' '.join(opt.content for opt in repaired_item.options)}".strip()
    )
    vectors = embedding.embed_documents([embed_text]) if embed_text else []
    emb_tuple = tuple(vectors[0]) if vectors else original.embedding
    return CandidateQuestion(
        question_id=original.question_id,
        stem=repaired_item.stem,
        question_type=repaired_item.question_type,
        answer=repaired_item.answer,
        options=tuple(opt.model_dump() for opt in repaired_item.options),
        source_snippet_ids=_resolve_snippet_ids(
            repaired_item.source_snippet_index, snippet_metadata
        ),
        source_text=context_text,
        embedding=emb_tuple,
        analysis=repaired_item.analysis,
        created_at_seq=original.created_at_seq,
    )


def _is_repaired_acceptable(recheck: SingleQuestionQualityResult) -> bool:
    """校验修复后题目是否已消除全部结构性、重复与冲突缺陷。"""
    if recheck.severity == QualitySeverity.PASS:
        return True
    if recheck.severity != QualitySeverity.SOFT_FLAG:
        return False
    return all(
        item.is_passed or item.check_type == QualityCheckType.NO_SOURCE
        for item in recheck.check_items
    )


def _build_quality_checks_for_accepted(
    *,
    user_id: uuid.UUID,
    batch_id: str,
    question_id: str,
    precheck_result: SingleQuestionQualityResult,
    verdict: str,
    reason: str,
    repaired: bool,
) -> list[QuestionQualityCheck]:
    """构造经 AI 裁决或修复通过后的质检明细审计记录。"""
    q_uuid = uuid.UUID(question_id)
    checks = [
        QuestionQualityCheck(
            user_id=user_id,
            question_id=q_uuid,
            batch_id=batch_id,
            check_type=item.check_type.value,
            is_passed=item.is_passed,
            reason=item.reason,
            similarity_score=item.similarity_score,
            check_metadata=item.metadata,
        )
        for item in precheck_result.check_items
    ]
    checks.append(
        QuestionQualityCheck(
            user_id=user_id,
            question_id=q_uuid,
            batch_id=batch_id,
            check_type=AI_JUDGE_CHECK_TYPE,
            is_passed=True,
            reason=reason or f"AI 质检裁决通过 ({verdict})",
            similarity_score=None,
            check_metadata={"verdict": verdict, "repaired": repaired},
        )
    )
    return checks


def _handle_single_decision(
    *,
    entry: FlaggedCandidateEntry,
    decision: LLMQuestionJudgeDecision | None,
    existing_refs: Sequence[ExistingQuestionReference],
    prior_qualified: Sequence[CandidateQuestion],
    accepted_so_far: Sequence[CandidateQuestion],
    context_text: str,
    snippet_metadata: Sequence[dict[str, Any]],
    config: QuestionQualityConfig,
    embedding: EmbeddingProtocol,
    user_id: uuid.UUID,
    batch_id: str,
) -> tuple[
    CandidateQuestion | None,
    LLMGeneratedQuestionItem | None,
    list[QuestionQualityCheck],
    str | None,
]:
    """处理单个题目的 AI 裁决并执行硬性安全降级校验。"""
    cand = entry.candidate
    pre_res = entry.precheck_result

    if decision is None or decision.verdict == "reject":
        reason = (decision.reason if decision else "") or pre_res.unqualified_reason or "质检淘汰"
        return None, None, [], f"题型[{cand.question_type}]已淘汰: {reason}"

    if decision.verdict == "approve":
        if pre_res.severity == QualitySeverity.HARD_DEFECT:
            reason = pre_res.unqualified_reason or "存在硬性结构/重复缺陷"
            return None, None, [], f"题型[{cand.question_type}]硬缺陷禁止直接放行: {reason}"
        checks = _build_quality_checks_for_accepted(
            user_id=user_id,
            batch_id=batch_id,
            question_id=cand.question_id,
            precheck_result=pre_res,
            verdict="approve",
            reason=decision.reason,
            repaired=False,
        )
        return cand, entry.llm_item, checks, None

    if decision.repaired_question is None:
        return None, None, [], f"题型[{cand.question_type}]修复结果缺失，已淘汰"

    repaired_cand = _build_repaired_candidate(
        original=cand,
        repaired_item=decision.repaired_question,
        context_text=context_text,
        snippet_metadata=snippet_metadata,
        embedding=embedding,
    )
    recheck, _ = evaluate_single_question(
        repaired_cand,
        existing_refs,
        [*prior_qualified, *accepted_so_far],
        config,
    )
    if not _is_repaired_acceptable(recheck):
        fail_reason = recheck.unqualified_reason or "修复后仍未通过结构校验"
        return None, None, [], f"题型[{cand.question_type}]修复后仍不合格: {fail_reason}"

    checks = _build_quality_checks_for_accepted(
        user_id=user_id,
        batch_id=batch_id,
        question_id=repaired_cand.question_id,
        precheck_result=recheck,
        verdict="repair",
        reason=decision.reason,
        repaired=True,
    )
    return repaired_cand, decision.repaired_question, checks, None


def judge_and_repair_candidates(
    *,
    llm: LLMProtocol,
    embedding: EmbeddingProtocol,
    flagged_entries: Sequence[FlaggedCandidateEntry],
    existing_refs: Sequence[ExistingQuestionReference],
    prior_qualified: Sequence[CandidateQuestion],
    kp_name: str,
    kp_description: str,
    context_text: str,
    snippet_metadata: Sequence[dict[str, Any]],
    config: QuestionQualityConfig,
    user_id: uuid.UUID,
    batch_id: str,
) -> JudgeBatchResult:
    """对同批次非 PASS 候选题合并发起 1 次批量 AI 质检裁决与定向修复。"""
    if not flagged_entries:
        return JudgeBatchResult(
            approved_candidates=[],
            approved_items_map={},
            checks_map={},
            rejected_candidates=[],
            rejected_reasons=[],
        )

    messages = _build_judge_prompt(
        flagged_entries=flagged_entries,
        kp_name=kp_name,
        kp_description=kp_description,
        context_text=context_text,
    )
    decisions_by_idx: dict[int, LLMQuestionJudgeDecision] = {}
    try:
        output, _ = llm.generate_structured(
            messages=messages,
            response_model=LLMQuestionJudgeBatchOutput,
            options=LLMOptions(temperature=0.1, max_tokens=4096),
        )
        if output is not None:
            for item in output.decisions:
                decisions_by_idx.setdefault(item.question_index, item)
    except LLMAuthError:
        raise
    except Exception as exc:
        logger.warning(
            "ai quality judge failed; conservatively rejecting flagged candidates",
            extra={
                "request_id": batch_id,
                "user_ref": generate_user_ref(user_id),
                "flagged_count": len(flagged_entries),
                "error_type": type(exc).__name__,
            },
        )

    approved_candidates: list[CandidateQuestion] = []
    approved_items_map: dict[str, LLMGeneratedQuestionItem] = {}
    checks_map: dict[str, list[QuestionQualityCheck]] = {}
    rejected_candidates: list[CandidateQuestion] = []
    rejected_reasons: list[str] = []

    for idx, entry in enumerate(flagged_entries):
        accepted_cand, accepted_item, checks, reject_reason = _handle_single_decision(
            entry=entry,
            decision=decisions_by_idx.get(idx),
            existing_refs=existing_refs,
            prior_qualified=prior_qualified,
            accepted_so_far=approved_candidates,
            context_text=context_text,
            snippet_metadata=snippet_metadata,
            config=config,
            embedding=embedding,
            user_id=user_id,
            batch_id=batch_id,
        )
        if accepted_cand is not None and accepted_item is not None:
            approved_candidates.append(accepted_cand)
            approved_items_map[accepted_cand.question_id] = accepted_item
            checks_map[accepted_cand.question_id] = checks
        else:
            rejected_candidates.append(entry.candidate)
            if reject_reason:
                rejected_reasons.append(reject_reason)

    logger.info(
        "ai quality judge batch finished",
        extra={
            "request_id": batch_id,
            "user_ref": generate_user_ref(user_id),
            "flagged_count": len(flagged_entries),
            "accepted_count": len(approved_candidates),
            "rejected_count": len(rejected_candidates),
        },
    )
    return JudgeBatchResult(
        approved_candidates=approved_candidates,
        approved_items_map=approved_items_map,
        checks_map=checks_map,
        rejected_candidates=rejected_candidates,
        rejected_reasons=rejected_reasons,
    )


__all__ = [
    "AI_JUDGE_CHECK_TYPE",
    "FlaggedCandidateEntry",
    "JudgeBatchResult",
    "LLMQuestionJudgeBatchOutput",
    "LLMQuestionJudgeDecision",
    "judge_and_repair_candidates",
]
