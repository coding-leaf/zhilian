"""Thinking-model resilience, plain-text fallback, quick-prompt routing, and noise guard tests."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from app.core.errors import LLMResponseFormatError
from app.integrations.llm.agent_graph import repair_prompt_node, run_structured_agent_workflow
from app.integrations.llm.coach_graph import (
    CoachDraft,
    RewrittenQuery,
    classify_intent,
    is_short_noise,
    run_coach_graph,
)
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.llm.protocol import LLMMessage, LLMResponse, LLMUsage
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.protocol import SearchSnippetCandidate


class _DemoSchema(BaseModel):
    reply: str = Field(description="Concise reply")
    score: int = Field(description="Numeric score")


def _make_candidate(material_id: uuid.UUID, score: float = 0.82) -> SearchSnippetCandidate:
    return SearchSnippetCandidate(
        snippet_id=uuid.uuid4(),
        material_id=material_id,
        version_id=uuid.uuid4(),
        content="支持向量机通过最大化间隔超平面实现分类。",
        chapter_title="第 3 章 支持向量机",
        source_info={"page": 5},
        vector_score=score,
        final_score=0.02,
    )


def test_coach_thinking_model_token_budgets() -> None:
    material_id = uuid.uuid4()
    low_item = _make_candidate(material_id, score=0.1)
    search = FakeSearchAdapter()
    search.set_canned_candidates([low_item])

    reranker = MagicMock()
    reranker.rerank.return_value = [MagicMock(index=0, relevance_score=0.3)]

    llm = MagicMock()
    llm.generate_structured.side_effect = [
        (RewrittenQuery(query="SVM 最大间隔超平面"), MagicMock()),
        (CoachDraft(reply="依据资料...", citation_ids=[low_item.snippet_id]), MagicMock()),
    ]

    result = run_coach_graph(
        search=search,
        llm=llm,
        reranker=reranker,
        query="怎么理解间隔？",
        user_id=uuid.uuid4(),
        material_ids=(material_id,),
    )

    assert result.mode == "grounded"
    rewrite_call = llm.generate_structured.call_args_list[0].kwargs
    grounded_call = llm.generate_structured.call_args_list[1].kwargs
    assert rewrite_call["options"].max_tokens == 2048
    assert grounded_call["options"].max_tokens == 4096


def test_coach_overview_token_budget_and_plain_text_fallback() -> None:
    search = MagicMock()
    llm = MagicMock()
    llm.generate_structured.side_effect = LLMResponseFormatError("AI 输出格式暂时异常，请稍后重试")
    llm.generate.return_value = LLMResponse(
        content="本章核心考点包括：1. 间隔最大化；2. 核函数技巧。",
        usage=LLMUsage(),
        model="deepseek-flash",
    )

    result = run_coach_graph(
        search=search,
        llm=llm,
        query="总结这部分内容的关键适用条件",
        user_id=uuid.uuid4(),
        material_ids=(uuid.uuid4(),),
        overview_context="- 支持向量机：线性可分与核函数",
        suggested_topics=["间隔最大化", "核技巧"],
    )

    assert result.mode == "overview"
    assert "本章核心考点包括" in result.reply
    assert result.suggestions == ["讲讲「间隔最大化」", "讲讲「核技巧」"]
    assert llm.generate_structured.call_args.kwargs["options"].max_tokens == 4096
    assert llm.generate.call_count == 1
    assert llm.generate.call_args.kwargs["options"].max_tokens == 4096
    search.search.assert_not_called()


def test_coach_grounded_plain_text_fallback_preserves_citations() -> None:
    material_id = uuid.uuid4()
    item = _make_candidate(material_id, score=0.9)
    search = FakeSearchAdapter()
    search.set_canned_candidates([item])

    llm = MagicMock()
    llm.generate_structured.side_effect = LLMResponseFormatError("AI 输出格式暂时异常，请稍后重试")
    llm.generate.return_value = LLMResponse(
        content="核心结论：支持向量机通过最大化分类间隔提升泛化能力。",
        usage=LLMUsage(),
        model="deepseek-flash",
    )

    result = run_coach_graph(
        search=search,
        llm=llm,
        query="什么是支持向量机？",
        user_id=uuid.uuid4(),
        material_ids=(material_id,),
        suggested_topics=["核函数"],
    )

    assert result.mode == "grounded"
    assert "最大化分类间隔" in result.reply
    assert [c.snippet_id for c in result.cited] == [item.snippet_id]
    assert llm.generate.call_count == 1


@pytest.mark.parametrize(
    "prompt",
    [
        "总结这部分内容的关键适用条件",
        "关键适用条件有哪些",
        "适用条件是什么",
        "总结核心公式与推导思路",
        "概括本章要点",
        "有哪些易错点",
        "重难点是什么",
        "核心考点有哪些",
        "帮我梳理这份资料的核心框架",
        "知识框架是什么",
        "哪些核心公式和概念最容易混淆？",
        "用大白话解释这个考点",
        "这个考点有哪些易混边界条件？",
        "结合典型场景帮我加深理解",
    ],
)
def test_overview_pattern_covers_builtin_quick_prompts(prompt: str) -> None:
    assert classify_intent(prompt, has_overview=True) == "overview"


@pytest.mark.parametrize(
    "noise_query",
    ["111!", "???", "...", "123456", "aaa", "哈哈哈", "！！", "嗯嗯"],
)
def test_short_noise_guard_short_circuits_without_rag_or_llm(noise_query: str) -> None:
    assert is_short_noise(noise_query) is True
    assert classify_intent(noise_query, has_overview=True) == "noise"

    search = MagicMock()
    reranker = MagicMock()
    llm = MagicMock()

    result = run_coach_graph(
        search=search,
        llm=llm,
        reranker=reranker,
        query=noise_query,
        user_id=uuid.uuid4(),
        material_ids=(uuid.uuid4(),),
        suggested_topics=["拉格朗日对偶", "KKT 条件"],
    )

    assert result.mode == "chitchat"
    assert result.cited == []
    assert result.suggestions == ["讲讲「拉格朗日对偶」", "讲讲「KKT 条件」"]
    search.search.assert_not_called()
    reranker.rerank.assert_not_called()
    llm.generate_structured.assert_not_called()
    llm.generate.assert_not_called()


@pytest.mark.parametrize("valid_query", ["PCA", "SVM", "L1", "C++", "什么是过拟合", "第1章"])
def test_short_noise_guard_does_not_block_valid_short_terms(valid_query: str) -> None:
    assert is_short_noise(valid_query) is False


def test_agent_graph_repair_includes_schema_hints_and_sanitizes_error() -> None:
    state_update = repair_prompt_node(
        {
            "retry_count": 0,
            "messages": [LLMMessage(role="user", content="请给出回复")],
            "response_model": _DemoSchema,
            "raw_response": LLMResponse(content="{bad", usage=LLMUsage(), model="deepseek-flash"),
            "error_message": "Expecting property name enclosed in double quotes: line 1 column 2",
        }
    )
    repair_msg = state_update["messages"][-1].content
    assert "reply" in repair_msg
    assert "score" in repair_msg
    assert "Concise reply" in repair_msg

    fake_adapter = FakeLLMAdapter()
    fake_adapter.set_canned_response("请给出", "{invalid_json_forever")
    with pytest.raises(LLMResponseFormatError) as exc_info:
        run_structured_agent_workflow(
            adapter=fake_adapter,
            messages=[LLMMessage(role="user", content="请给出回复")],
            response_model=_DemoSchema,
        )

    msg = exc_info.value.message
    assert "AI 输出格式暂时异常" in msg
    assert "Expecting" not in msg
    assert "ValidationError" not in msg
    assert "invalid_json_forever" not in str(exc_info.value.details)
