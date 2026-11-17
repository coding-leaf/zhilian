"""Adaptive + Corrective RAG 课程助教图的离线测试（路由 / 精排门禁 / 改写 / 引用校验 / 记忆）。"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.integrations.llm import coach_graph as cg
from app.integrations.llm.coach_graph import (
    CoachDraft,
    CoachGraphConfig,
    CoachOverviewDraft,
    RewrittenQuery,
    answer_with_course_evidence,
    classify_chitchat,
    classify_intent,
    run_coach_graph,
    verify_citations,
)
from app.integrations.llm.coach_memory import CoachTurn
from app.integrations.llm.protocol import LLMMessage
from app.integrations.rerank.fake import FakeRerankAdapter
from app.integrations.rerank.protocol import RerankItem
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.protocol import (
    NeighborSearchProtocol,
    SearchOptions,
    SearchResult,
    SearchSnippetCandidate,
)

MATERIAL = uuid.uuid4()
VERSION = uuid.uuid4()
USER = uuid.uuid4()


def cand(
    content: str = "资料中的一段真实内容。",
    *,
    index: int | None = None,
    vector: float = 0.8,
    bm25: float = 0.0,
    final: float = 0.02,
    page: int | None = None,
    material: uuid.UUID = MATERIAL,
    version: uuid.UUID = VERSION,
) -> SearchSnippetCandidate:
    return SearchSnippetCandidate(
        snippet_id=uuid.uuid4(),
        material_id=material,
        version_id=version,
        content=content,
        chapter_title="第一章",
        source_info={} if page is None else {"page_number": page},
        vector_score=vector,
        bm25_score=bm25,
        final_score=final,
        snippet_index=index,
    )


def pool_of(*contents: str) -> list[SearchSnippetCandidate]:
    """按融合分降序的候选池（池顺序 == 传入顺序）。"""
    return [cand(c, final=0.05 - i * 0.001, vector=0.9 - i * 0.01) for i, c in enumerate(contents)]


@dataclass
class LLMCall:
    name: str
    messages: list[LLMMessage]
    options: Any


class ScriptedLLM:
    """按 response_model 分发的脚本化 LLM 替身；值可为实例、可调用或待抛异常。"""

    def __init__(
        self,
        *,
        draft: Any = None,
        overview: Any = None,
        rewrite: Any = None,
    ) -> None:
        self.handlers = {
            "CoachDraft": draft,
            "CoachOverviewDraft": overview,
            "RewrittenQuery": rewrite,
        }
        self.calls: list[LLMCall] = []

    def generate_structured(
        self, messages: list[LLMMessage], response_model: type, options: Any = None
    ) -> tuple[Any, Any]:
        name = response_model.__name__
        self.calls.append(LLMCall(name, list(messages), options))
        handler = self.handlers[name]
        if handler is None:
            raise AssertionError(f"unexpected LLM call: {name}")
        value = handler(messages) if callable(handler) else handler
        if isinstance(value, Exception):
            raise value
        return value, MagicMock()

    def names(self) -> list[str]:
        return [c.name for c in self.calls]


class ScriptedSearch:
    """按调用序返回预置候选的检索替身（超出则复用最后一组）。"""

    def __init__(self, *batches: Sequence[SearchSnippetCandidate]) -> None:
        self.batches = [list(b) for b in batches] or [[]]
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        user_id: uuid.UUID,
        material_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        options: SearchOptions | None = None,
    ) -> SearchResult:
        self.calls.append(
            {
                "query": query,
                "user_id": user_id,
                "material_id": material_id,
                "version_id": version_id,
                "options": options,
            }
        )
        batch = self.batches[min(len(self.calls) - 1, len(self.batches) - 1)]
        return SearchResult(query=query, items=batch, total_candidates=len(batch))


class NeighborSearch(ScriptedSearch):
    def __init__(
        self,
        *batches: Sequence[SearchSnippetCandidate],
        neighbors: Sequence[SearchSnippetCandidate] = (),
        error: Exception | None = None,
    ) -> None:
        super().__init__(*batches)
        self.neighbors = list(neighbors)
        self.error = error
        self.neighbor_calls: list[dict[str, Any]] = []

    def fetch_neighbor_snippets(
        self,
        candidates: Sequence[SearchSnippetCandidate],
        *,
        user_id: uuid.UUID,
        window: int = 1,
    ) -> list[SearchSnippetCandidate]:
        self.neighbor_calls.append(
            {"candidates": list(candidates), "user_id": user_id, "window": window}
        )
        if self.error is not None:
            raise self.error
        return list(self.neighbors)


class ScriptedRerank:
    """按调用序给出池内（输入顺序）得分；超出则复用最后一组。"""

    def __init__(self, *score_batches: Sequence[float]) -> None:
        self.score_batches = [list(b) for b in score_batches]
        self.calls: list[dict[str, Any]] = []

    def rerank(
        self, query: str, documents: Sequence[str], *, top_n: int | None = None
    ) -> list[RerankItem]:
        self.calls.append({"query": query, "documents": list(documents), "top_n": top_n})
        scores = self.score_batches[min(len(self.calls) - 1, len(self.score_batches) - 1)]
        items = [RerankItem(index=i, relevance_score=s) for i, s in enumerate(scores)]
        items.sort(key=lambda it: (-it.relevance_score, it.index))
        return items[:top_n] if top_n is not None else items


def cite(*items: SearchSnippetCandidate) -> Callable[[list[LLMMessage]], CoachDraft]:
    ids = [i.snippet_id for i in items]
    return lambda _messages: CoachDraft(
        reply="有据回答", suggestions=["再问一个"], citation_ids=ids
    )


def run(
    search: Any,
    llm: Any,
    query: str = "什么是主成分分析？",
    **kwargs: Any,
) -> cg.CoachGraphResult:
    kwargs.setdefault("user_id", USER)
    kwargs.setdefault("material_ids", (MATERIAL,))
    return run_coach_graph(search=search, llm=llm, query=query, **kwargs)


def user_prompt(llm: ScriptedLLM, name: str = "CoachDraft") -> str:
    call = next(c for c in reversed(llm.calls) if c.name == name)
    return str(call.messages[1].content)


# ---------------------------------------------------------------------------
# 意图路由
# ---------------------------------------------------------------------------


class TestIntentRouting:
    @pytest.mark.parametrize(
        ("query", "kind"),
        [
            ("你好呀", "greeting"),
            ("您好", "greeting"),
            ("hello", "greeting"),
            ("谢谢", "thanks"),
            ("谢谢老师！", None),
            ("你是谁", "identity"),
            ("你是谁呀？", "identity"),
            ("再见", "bye"),
            ("拜拜~", "bye"),
            ("你好，谢谢", "greeting"),
        ],
    )
    def test_chitchat_kinds(self, query: str, kind: str | None) -> None:
        assert classify_chitchat(query) == kind

    @pytest.mark.parametrize(
        "query",
        ["你好，请解释PCA", "hi there what is SVD", "谢谢，那特征值怎么求", "", "   ", "你好" * 20],
    )
    def test_substantive_or_empty_is_not_chitchat(self, query: str) -> None:
        assert classify_chitchat(query) is None

    @pytest.mark.parametrize(
        ("query", "has_overview", "expected"),
        [
            ("你好呀", True, "chitchat"),
            ("你好呀", False, "chitchat"),
            ("帮我梳理本章重点", True, "overview"),
            ("帮我梳理本章重点", False, "detail_qa"),
            ("这份资料的知识体系是什么", True, "overview"),
            ("考点有哪些", True, "overview"),
            ("总结一下本章", True, "overview"),
            ("什么是主成分分析", True, "detail_qa"),
            ("请推导特征值公式", True, "detail_qa"),
        ],
    )
    def test_classify_intent_matrix(self, query: str, has_overview: bool, expected: str) -> None:
        assert classify_intent(query, has_overview=has_overview) == expected


def test_overview_pattern_summarize_this_chapter() -> None:
    assert classify_intent("总结一下这一章", has_overview=True) == "overview"


# ---------------------------------------------------------------------------
# 寒暄 / 概览：零检索 / 受控 LLM
# ---------------------------------------------------------------------------


class TestChitchatAndOverview:
    def test_chitchat_makes_zero_search_and_llm_calls(self) -> None:
        search = MagicMock()
        llm = MagicMock()
        result = run(
            search, llm, "你好呀", suggested_topics=["主成分分析", "特征值", "协方差", "多余"]
        )
        assert result.mode == "chitchat"
        assert result.cited == []
        assert result.suggestions == [
            "讲讲「主成分分析」",
            "讲讲「特征值」",
            "讲讲「协方差」",
        ]
        search.search.assert_not_called()
        llm.generate_structured.assert_not_called()

    def test_chitchat_defaults_without_topics(self) -> None:
        result = run(MagicMock(), MagicMock(), "谢谢")
        assert result.mode == "chitchat"
        assert result.suggestions == ["帮我梳理本章重点", "解释一个核心概念", "举个例子帮我理解"]

    def test_chitchat_uses_intent_text_not_prefixed_query(self) -> None:
        """KP 范围会给 query 加前缀，寒暄判定必须基于原始 intent_text。"""
        result = run(
            MagicMock(),
            MagicMock(),
            "关于知识点「PCA」：你好呀",
            intent_text="你好呀",
        )
        assert result.mode == "chitchat"

    def test_overview_uses_context_and_skips_search(self) -> None:
        search = MagicMock()
        llm = ScriptedLLM(
            overview=CoachOverviewDraft(reply="总览", suggestions=["a", "b", "c", "d"])
        )
        result = run(
            search,
            llm,
            "帮我梳理本章重点",
            overview_context="- 主成分分析：降维方法",
            scope_title="机器学习",
        )
        assert result.mode == "overview"
        assert result.reply == "总览"
        assert result.suggestions == ["a", "b", "c"]
        assert result.cited == []
        search.search.assert_not_called()
        assert llm.names() == ["CoachOverviewDraft"]
        assert "- 主成分分析：降维方法" in user_prompt(llm, "CoachOverviewDraft")

    def test_overview_pattern_without_context_goes_to_detail_qa(self) -> None:
        item = cand()
        search = ScriptedSearch([item])
        llm = ScriptedLLM(draft=cite(item))
        result = run(search, llm, "帮我梳理本章重点", overview_context=None)
        assert result.mode == "grounded"
        assert len(search.calls) == 1


# ---------------------------------------------------------------------------
# detail_qa：精排门禁
# ---------------------------------------------------------------------------


class TestDetailQaWithReranker:
    def test_happy_path_scores_and_min_score_filtering(self) -> None:
        a, b, c = pool_of("甲内容", "乙内容", "丙内容")
        search = ScriptedSearch([a, b, c])
        reranker = ScriptedRerank([0.7, 0.3, 0.1])
        llm = ScriptedLLM(draft=cite(a))

        result = run(search, llm, reranker=reranker)

        assert result.mode == "grounded"
        assert result.top_score == pytest.approx(0.7)
        assert result.rewritten is False
        assert [x.snippet_id for x in result.cited] == [a.snippet_id]
        assert llm.names() == ["CoachDraft"]
        assert reranker.calls[0]["documents"] == ["甲内容", "乙内容", "丙内容"]
        assert reranker.calls[0]["top_n"] == 6
        prompt = user_prompt(llm)
        assert str(a.snippet_id) in prompt and str(b.snippet_id) in prompt
        assert str(c.snippet_id) not in prompt  # 0.1 < min_score(0.25)

    def test_search_options_use_config_and_scope(self) -> None:
        item = cand()
        search = ScriptedSearch([item])
        run(
            search,
            ScriptedLLM(draft=cite(item)),
            reranker=ScriptedRerank([0.9]),
            config=CoachGraphConfig(retrieve_top_k=10, vector_top_k=25),
            version_id=VERSION,
        )
        call = search.calls[0]
        assert call["options"].top_k == 10
        assert call["options"].vector_top_k == 25
        assert call["options"].allowed_snippet_ids is None
        assert call["material_id"] == MATERIAL and call["version_id"] == VERSION
        assert call["user_id"] == USER

    def test_reranker_error_degrades_to_fused_order(self) -> None:
        item = cand()
        reranker = MagicMock()
        reranker.rerank.side_effect = RuntimeError("boom")
        result = run(ScriptedSearch([item]), ScriptedLLM(draft=cite(item)), reranker=reranker)
        assert result.mode == "grounded"
        assert result.top_score is None

    def test_works_with_fake_rerank_adapter(self) -> None:
        relevant = cand("主成分分析 降维 方法")
        other = cand("完全无关的内容", final=0.01)
        llm = ScriptedLLM(draft=cite(relevant))
        result = run(
            ScriptedSearch([other, relevant]),
            llm,
            "主成分分析 降维",
            reranker=FakeRerankAdapter(),
        )
        assert result.mode == "grounded"
        assert result.top_score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Corrective：改写 / 回退 / 诚实兜底
# ---------------------------------------------------------------------------


class TestCorrectiveRewrite:
    def test_low_score_rewrites_exactly_once_then_generates(self) -> None:
        item = cand()
        search = ScriptedSearch([item])
        reranker = ScriptedRerank([0.3], [0.9])  # 0.3 < rewrite_threshold(0.45)
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="PCA 降维 原理"), draft=cite(item))

        result = run(search, llm, reranker=reranker)

        assert llm.names() == ["RewrittenQuery", "CoachDraft"]
        assert [c["query"] for c in search.calls] == ["什么是主成分分析？", "PCA 降维 原理"]
        assert result.mode == "grounded"
        assert result.rewritten is True
        assert result.top_score == pytest.approx(0.9)

    def test_rewrite_prompt_contains_scope_and_history(self) -> None:
        item = cand()
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="改写"), draft=cite(item))
        run(
            ScriptedSearch([item]),
            llm,
            reranker=ScriptedRerank([0.3], [0.9]),
            scope_title="机器学习导论",
            history=[CoachTurn("什么是PCA", "一种降维方法")],
        )
        prompt = user_prompt(llm, "RewrittenQuery")
        assert "机器学习导论" in prompt
        assert "什么是PCA" in prompt

    def test_worse_rewrite_falls_back_to_first_attempt_evidence(self) -> None:
        first = cand("首轮证据")
        second = cand("改写后证据")
        search = ScriptedSearch([first], [second])
        reranker = ScriptedRerank([0.4], [0.3])  # 改写后更差
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="改写"), draft=cite(first))

        result = run(search, llm, reranker=reranker)

        assert result.mode == "grounded"
        assert result.top_score == pytest.approx(0.4)
        assert [c.snippet_id for c in result.cited] == [first.snippet_id]
        prompt = user_prompt(llm)
        assert str(first.snippet_id) in prompt
        assert str(second.snippet_id) not in prompt
        assert llm.names() == ["RewrittenQuery", "CoachDraft"]

    def test_still_below_min_score_gives_honest_fallback(self) -> None:
        item = cand()
        search = ScriptedSearch([item])
        reranker = ScriptedRerank([0.1])  # < min_score，改写前后都过滤为空
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="改写"))

        result = run(search, llm, reranker=reranker, suggested_topics=["特征值", "协方差"])

        assert result.mode == "fallback"
        assert result.cited == []
        assert result.rewritten is True
        assert result.top_score == pytest.approx(0.1)
        assert result.suggestions == ["讲讲「特征值」", "讲讲「协方差」"]
        assert llm.names() == ["RewrittenQuery"]  # 没有 generate 调用
        assert len(search.calls) == 2

    def test_empty_candidates_rewrite_once_then_fallback(self) -> None:
        search = ScriptedSearch([])
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="更精确的查询"))
        result = run(search, llm)
        assert result.mode == "fallback"
        assert result.rewritten is True
        assert result.top_score is None
        assert llm.names() == ["RewrittenQuery"]
        assert [c["query"] for c in search.calls] == ["什么是主成分分析？", "更精确的查询"]

    def test_rewrite_llm_error_uses_deterministic_fallback_query(self) -> None:
        search = ScriptedSearch([])
        llm = ScriptedLLM(rewrite=RuntimeError("llm down"))
        result = run(search, llm, scope_title="机器学习")
        assert result.mode == "fallback"
        assert search.calls[1]["query"] == "机器学习 什么是主成分分析？"

    def test_blank_rewrite_uses_fallback_query(self) -> None:
        search = ScriptedSearch([])
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="   "))
        run(search, llm, scope_title="课程")
        assert search.calls[1]["query"] == "课程 什么是主成分分析？"

    def test_no_reranker_applies_vector_gate_then_rewrites(self) -> None:
        weak = cand(vector=0.1, bm25=0.0)
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="改写"))
        result = run(ScriptedSearch([weak]), llm)
        assert result.mode == "fallback"
        assert llm.names() == ["RewrittenQuery"]

    def test_no_reranker_keyword_hit_bypasses_vector_gate(self) -> None:
        keyword_hit = cand(vector=0.1, bm25=3.2)
        llm = ScriptedLLM(draft=cite(keyword_hit))
        result = run(ScriptedSearch([keyword_hit]), llm)
        assert result.mode == "grounded"
        assert llm.names() == ["CoachDraft"]


# ---------------------------------------------------------------------------
# 确定性引用校验
# ---------------------------------------------------------------------------


class TestVerifyCitations:
    def test_drops_hallucinated_and_dedupes_in_order(self) -> None:
        a, b = pool_of("a", "b")
        draft = CoachDraft(
            reply="r", citation_ids=[b.snippet_id, uuid.uuid4(), a.snippet_id, b.snippet_id]
        )
        checked = verify_citations(draft, [a, b])
        assert checked.citation_ids == [b.snippet_id, a.snippet_id]
        assert checked.reply == "r"

    def test_all_invalid_backfills_top_two(self) -> None:
        a, b, c = pool_of("a", "b", "c")
        draft = CoachDraft(reply="r", citation_ids=[uuid.uuid4()])
        assert verify_citations(draft, [a, b, c]).citation_ids == [a.snippet_id, b.snippet_id]
        assert verify_citations(draft, [a, b, c], backfill=1).citation_ids == [a.snippet_id]

    def test_no_candidates_yields_empty(self) -> None:
        draft = CoachDraft(reply="r", citation_ids=[uuid.uuid4()])
        assert verify_citations(draft, []).citation_ids == []

    def test_graph_backfills_without_second_llm_call(self) -> None:
        a, b, c = pool_of("a", "b", "c")
        llm = ScriptedLLM(draft=CoachDraft(reply="编造引用", citation_ids=[uuid.uuid4()]))
        result = run(ScriptedSearch([a, b, c]), llm)
        assert llm.names() == ["CoachDraft"]  # 无返工
        assert result.mode == "grounded"
        assert [x.snippet_id for x in result.cited] == [a.snippet_id, b.snippet_id]

    def test_graph_drops_foreign_ids_but_keeps_valid(self) -> None:
        a, b = pool_of("a", "b")
        llm = ScriptedLLM(draft=CoachDraft(reply="r", citation_ids=[uuid.uuid4(), b.snippet_id]))
        result = run(ScriptedSearch([a, b]), llm)
        assert [x.snippet_id for x in result.cited] == [b.snippet_id]


# ---------------------------------------------------------------------------
# 多轮历史
# ---------------------------------------------------------------------------


class TestHistory:
    def test_history_capped_to_six_turns_in_prompt(self) -> None:
        item = cand()
        llm = ScriptedLLM(draft=cite(item))
        history = [CoachTurn(f"问{i}", f"答{i}") for i in range(8)]
        run(ScriptedSearch([item]), llm, history=history)
        prompt = user_prompt(llm)
        assert "此前对话" in prompt
        for i in (2, 3, 4, 5, 6, 7):
            assert f"问{i}" in prompt
        assert "问0" not in prompt and "问1" not in prompt

    def test_no_history_has_no_history_block(self) -> None:
        item = cand()
        llm = ScriptedLLM(draft=cite(item))
        run(ScriptedSearch([item]), llm)
        assert "此前对话" not in user_prompt(llm)

    def test_short_followup_query_is_augmented_with_previous_user_turn(self) -> None:
        item = cand()
        search = ScriptedSearch([item])
        run(
            search,
            ScriptedLLM(draft=cite(item)),
            "那为什么呢",
            history=[CoachTurn("什么是主成分分析", "一种降维方法")],
        )
        assert search.calls[0]["query"] == "什么是主成分分析 那为什么呢"

    def test_long_query_not_augmented_and_no_history_not_augmented(self) -> None:
        item = cand()
        long_query = "请详细解释一下主成分分析为什么需要对数据做中心化处理"
        search = ScriptedSearch([item])
        run(
            search,
            ScriptedLLM(draft=cite(item)),
            long_query,
            history=[CoachTurn("什么是主成分分析", "一种降维方法")],
        )
        assert search.calls[0]["query"] == long_query
        search2 = ScriptedSearch([item])
        run(search2, ScriptedLLM(draft=cite(item)), "那为什么呢")
        assert search2.calls[0]["query"] == "那为什么呢"

    def test_overview_prompt_includes_history(self) -> None:
        llm = ScriptedLLM(overview=CoachOverviewDraft(reply="总览"))
        run(
            MagicMock(),
            llm,
            "帮我梳理本章重点",
            overview_context="- 知识点",
            history=[CoachTurn("前一个问题", "前一个回答")],
        )
        assert "前一个问题" in user_prompt(llm, "CoachOverviewDraft")


# ---------------------------------------------------------------------------
# 范围白名单下推
# ---------------------------------------------------------------------------


class TestAllowedSnippetIds:
    def test_pushed_down_as_sorted_tuple(self) -> None:
        item = cand()
        ids = frozenset({uuid.uuid4(), item.snippet_id, uuid.uuid4()})
        search = ScriptedSearch([item])
        run(search, ScriptedLLM(draft=cite(item)), allowed_snippet_ids=ids)
        pushed = search.calls[0]["options"].allowed_snippet_ids
        assert pushed == tuple(sorted(ids, key=str))

    def test_empty_whitelist_never_searches(self) -> None:
        search = MagicMock()
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="改写"))
        result = run(search, llm, allowed_snippet_ids=frozenset())
        assert result.mode == "fallback"
        search.search.assert_not_called()

    def test_results_outside_whitelist_are_discarded(self) -> None:
        allowed_item = cand("允许的")
        leaked = cand("越权泄露")
        llm = ScriptedLLM(draft=cite(allowed_item, leaked))
        search = ScriptedSearch([leaked, allowed_item])
        result = run(search, llm, allowed_snippet_ids=frozenset({allowed_item.snippet_id}))
        assert [x.snippet_id for x in result.cited] == [allowed_item.snippet_id]
        assert str(leaked.snippet_id) not in user_prompt(llm)

    def test_foreign_material_and_stale_version_discarded(self) -> None:
        good = cand("好")
        foreign = cand("他人资料", material=uuid.uuid4())
        stale = cand("旧版本", version=uuid.uuid4())
        llm = ScriptedLLM(draft=cite(good))
        result = run(
            ScriptedSearch([foreign, stale, good]),
            llm,
            material_versions={MATERIAL: VERSION},
        )
        assert [x.snippet_id for x in result.cited] == [good.snippet_id]
        prompt = user_prompt(llm)
        assert str(foreign.snippet_id) not in prompt and str(stale.snippet_id) not in prompt

    def test_multi_material_pool_dedupes_by_best_score(self) -> None:
        other_material = uuid.uuid4()
        other_version = uuid.uuid4()
        mine = cand("本资料", final=0.03)
        theirs = cand("另一资料", material=other_material, version=other_version, final=0.04)

        class PerMaterial(ScriptedSearch):
            def search(
                self,
                query: str,
                user_id: uuid.UUID,
                material_id: Any = None,
                version_id: Any = None,
                options: Any = None,
            ) -> SearchResult:
                self.calls.append({"material_id": material_id, "query": query})
                items = [mine, theirs]  # 每个资料都返回两条，按 material 过滤保留各自
                return SearchResult(query=query, items=items)

        search = PerMaterial()
        llm = ScriptedLLM(draft=cite(mine, theirs))
        result = run(search, llm, material_ids=(MATERIAL, other_material))
        assert {c["material_id"] for c in search.calls} == {MATERIAL, other_material}
        assert {x.snippet_id for x in result.cited} == {mine.snippet_id, theirs.snippet_id}


# ---------------------------------------------------------------------------
# 邻接上下文扩展
# ---------------------------------------------------------------------------


class TestNeighborExpansion:
    def test_neighbor_text_in_evidence_but_citations_stay_anchor_only(self) -> None:
        anchor = cand("锚点切片正文。", index=5, page=2)
        before = cand("前文邻居内容。", index=4, page=2)
        after = cand("后文邻居内容。", index=6, page=2)
        search = NeighborSearch([anchor], neighbors=[after, before])
        assert isinstance(search, NeighborSearchProtocol)
        llm = ScriptedLLM(draft=cite(anchor))

        result = run(search, llm, reranker=ScriptedRerank([0.9]))

        prompt = user_prompt(llm)
        assert "前文邻居内容" in prompt and "后文邻居内容" in prompt and "锚点切片正文" in prompt
        assert (
            prompt.index("前文邻居内容")
            < prompt.index("锚点切片正文")
            < prompt.index("后文邻居内容")
        )
        assert str(before.snippet_id) not in prompt and str(after.snippet_id) not in prompt
        assert [x.snippet_id for x in result.cited] == [anchor.snippet_id]
        assert search.neighbor_calls[0]["window"] == 1
        assert search.neighbor_calls[0]["user_id"] == USER

    def test_neighbors_of_other_anchor_not_mixed_in(self) -> None:
        anchor = cand("锚点正文。", index=5)
        far = cand("远处邻居。", index=50)
        search = NeighborSearch([anchor], neighbors=[far])
        llm = ScriptedLLM(draft=cite(anchor))
        run(search, llm)
        assert "远处邻居" not in user_prompt(llm)

    def test_neighbor_error_degrades_to_anchor_text(self) -> None:
        anchor = cand("锚点正文。", index=5)
        search = NeighborSearch([anchor], error=RuntimeError("db down"))
        llm = ScriptedLLM(draft=cite(anchor))
        result = run(search, llm)
        assert result.mode == "grounded"
        assert "锚点正文" in user_prompt(llm)

    def test_search_without_neighbor_capability_uses_plain_content(self) -> None:
        anchor = cand("锚点正文。", index=5)
        search = ScriptedSearch([anchor])
        assert not isinstance(search, NeighborSearchProtocol)
        llm = ScriptedLLM(draft=cite(anchor))
        assert run(search, llm).mode == "grounded"

    def test_anchor_without_index_skips_expansion(self) -> None:
        anchor = cand("无序号锚点。", index=None)
        neighbor = cand("不该出现的邻居。", index=1)
        search = NeighborSearch([anchor], neighbors=[neighbor])
        llm = ScriptedLLM(draft=cite(anchor))
        run(search, llm)
        assert "不该出现的邻居" not in user_prompt(llm)

    def test_evidence_is_trimmed_to_max_chars(self) -> None:
        anchor = cand("很长的句子。" * 400, index=1)
        llm = ScriptedLLM(draft=cite(anchor))
        run(ScriptedSearch([anchor]), llm, config=CoachGraphConfig(max_evidence_chars=100))
        prompt = user_prompt(llm)
        assert len(prompt) < 600

    def test_fake_search_adapter_neighbors_integrate(self) -> None:
        adapter = FakeSearchAdapter()
        contents = ["第零段。", "第一段，命中。", "第二段。"]
        cands = [cand(c, page=1, final=0.05 - i * 0.01) for i, c in enumerate(contents)]
        adapter.set_canned_candidates(cands)  # 自动补全 snippet_index 0..2
        llm = ScriptedLLM(draft=cite(cands[1]))
        reranker = ScriptedRerank([0.2, 0.9, 0.1])
        result = run(adapter, llm, reranker=reranker, config=CoachGraphConfig(min_score=0.5))
        assert result.mode == "grounded"
        prompt = user_prompt(llm)
        assert "第零段" in prompt and "第二段" in prompt


# ---------------------------------------------------------------------------
# LangGraph 检查点 / 兼容入口
# ---------------------------------------------------------------------------


class TestCheckpointerAndCompat:
    def test_memory_saver_serializes_state_per_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        saver = MemorySaver()
        original = cg.build_coach_graph
        monkeypatch.setattr(
            cg, "build_coach_graph", lambda *a, **k: original(*a, checkpointer=saver, **k)
        )
        item = cand("证据", index=0)
        search = NeighborSearch([item])
        llm = ScriptedLLM(draft=cite(item))

        result = run(search, llm, thread_id="u:folder:abc:t1", reranker=ScriptedRerank([0.9]))

        assert result.mode == "grounded"
        checkpoint = saver.get_tuple({"configurable": {"thread_id": "u:folder:abc:t1"}})
        assert checkpoint is not None
        assert saver.get_tuple({"configurable": {"thread_id": "other"}}) is None

    def test_default_thread_id_is_random_per_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list[str] = []
        original = cg.build_coach_graph

        def spy(*args: Any, **kwargs: Any) -> Any:
            graph = original(*args, **kwargs)
            real_invoke = graph.invoke

            def invoke(state: Any, config: Any = None, **kw: Any) -> Any:
                seen.append(config["configurable"]["thread_id"])
                return real_invoke(state, config=config, **kw)

            return MagicMock(invoke=invoke)

        monkeypatch.setattr(cg, "build_coach_graph", spy)
        run(MagicMock(), MagicMock(), "你好")
        run(MagicMock(), MagicMock(), "你好")
        assert len(seen) == 2 and seen[0] != seen[1]

    def test_graph_missing_result_degrades_to_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        graph = MagicMock()
        graph.invoke.return_value = {}
        monkeypatch.setattr(cg, "build_coach_graph", lambda *a, **k: graph)
        result = run(MagicMock(), MagicMock(), "什么是PCA", suggested_topics=["PCA"])
        assert result.mode == "fallback"
        assert result.suggestions == ["讲讲「PCA」"]

    def test_wrapper_grounded_returns_draft_and_cited(self) -> None:
        item = cand()
        llm = ScriptedLLM(draft=cite(item))
        draft, cited = answer_with_course_evidence(
            search=ScriptedSearch([item]),
            llm=llm,
            query="什么是PCA",
            user_id=USER,
            material_ids=(MATERIAL,),
        )
        assert draft is not None
        assert draft.citation_ids == [item.snippet_id]
        assert cited == [item]

    def test_wrapper_returns_none_for_fallback_and_chitchat(self) -> None:
        llm = ScriptedLLM(rewrite=RewrittenQuery(query="改写"))
        assert answer_with_course_evidence(
            search=ScriptedSearch([]),
            llm=llm,
            query="什么是PCA",
            user_id=USER,
            material_ids=(MATERIAL,),
        ) == (None, [])
        assert llm.names() == ["RewrittenQuery"]

        search = MagicMock()
        assert answer_with_course_evidence(
            search=search,
            llm=MagicMock(),
            query="你好",
            user_id=USER,
            material_ids=(MATERIAL,),
        ) == (None, [])
        search.search.assert_not_called()


def test_coach_graph_nested_openai_structured_workflow_does_not_inherit_checkpointer() -> None:
    """父图启用 MemorySaver 时，嵌套 agent_graph 必须禁用 checkpointer 以防序列化崩溃。"""
    import json

    import httpx

    from app.integrations.llm.openai import OpenAICompatibleLLMAdapter

    item = cand("奇异值分解可用于矩阵低秩近似压缩。")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        tool = body["tools"][0]["function"]
        tool_name = tool["name"]
        props = tool.get("parameters", {}).get("properties", {})
        args: dict[str, Any] = {"reply": "压缩回复", "suggestions": ["追问1"]}
        if "citation_ids" in props:
            args["citation_ids"] = [str(item.snippet_id)]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": json.dumps(args),
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    adapter = OpenAICompatibleLLMAdapter(
        api_key="test-key",
        model="test-model",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    overview_res = run_coach_graph(
        search=ScriptedSearch([item]),
        llm=adapter,
        query="帮我梳理本章重点",
        user_id=USER,
        material_ids=(MATERIAL,),
        overview_context="- 奇异值分解",
        thread_id="nested-overview",
    )
    assert overview_res.mode == "overview"
    assert overview_res.reply == "压缩回复"

    detail_res = run_coach_graph(
        search=ScriptedSearch([item]),
        llm=adapter,
        query="奇异值分解怎么用于数据压缩？",
        user_id=USER,
        material_ids=(MATERIAL,),
        thread_id="nested-detail",
    )
    assert detail_res.mode == "grounded"
    assert detail_res.cited == [item]
