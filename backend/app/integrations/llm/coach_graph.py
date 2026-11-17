"""Adaptive + Corrective RAG 课程助教工作流 (LangGraph)。

节点与流向::

    START -> route_intent
        chitchat  -> conversational_reply -> END          (零检索、零 LLM)
        overview  -> generate_overview    -> END          (读取结构化知识点概览)
        detail_qa -> retrieve_and_rerank -> [确定性 Rerank 分数门禁]
                         generate_grounded -> verify_citations -> END
                         rewrite_query (至多 1 次) -> retrieve_and_rerank
                         honest_fallback -> END

设计要点：

- 路由与门禁均为确定性规则，不额外消耗 LLM 打分调用；
- ``verify_citations`` 为纯 Python 校验（过滤越界/幻觉 ID，必要时回填 Top 候选），
  取代原先二次 LLM 返工；
- 多轮追问：调用方传入最近 6 轮历史（``CoachSessionMemory``），生成与改写节点据此消解指代；
- 图以 LangGraph ``MemorySaver`` 检查点器编译，``thread_id`` 作为检查点线程键。
  该检查点仅覆盖单次运行（每次调用新建，避免进程内无界增长）；跨请求的会话记忆由
  有界的 ``CoachSessionMemory``（Redis / 进程内 LRU）承担；
- 日志只记录计数与分数，绝不记录问题、切片正文或密钥。
"""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.core.algorithms.text_excerpt import merge_adjacent_snippet_texts, trim_excerpt_cleanly
from app.integrations.llm.coach_memory import CoachTurn
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.integrations.rerank.protocol import RerankProtocol
from app.integrations.search.protocol import (
    NeighborSearchProtocol,
    SearchOptions,
    SearchProtocol,
    SearchSnippetCandidate,
)

logger = logging.getLogger(__name__)

CoachIntent = Literal["chitchat", "overview", "detail_qa"]
CoachMode = Literal["chitchat", "overview", "grounded", "fallback"]


class CoachDraft(BaseModel):
    reply: str = Field(
        min_length=1,
        description="精炼、口语化的助教答疑回复（约150-260字，先结论后2-3条简短要点，不用大纲编号）",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="2-3条简短口语化的追问建议（每条不超过15字）",
    )
    citation_ids: list[uuid.UUID] = Field(min_length=1)


class CoachOverviewDraft(BaseModel):
    """章节/考点概览回复（依据结构化知识点梳理，不要求切片引用）。"""

    reply: str = Field(
        min_length=1,
        description="依据给定知识点梳理的条理化概览回复（先一句话总览，再分点列出核心考点）",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="2-3条简短口语化的追问建议（每条不超过15字）",
    )


class RewrittenQuery(BaseModel):
    """指代消解后的独立检索查询。"""

    query: str = Field(min_length=1, max_length=200, description="独立完整、适合检索的查询语句")


@dataclass(frozen=True)
class CoachGraphConfig:
    """图运行参数；与 RerankSettings 对齐。"""

    rerank_top_n: int = 6
    min_score: float = 0.25
    rewrite_threshold: float = 0.45
    retrieve_top_k: int = 16
    vector_top_k: int = 30
    vector_gate: float = 0.35
    neighbor_window: int = 1
    max_evidence_chars: int = 1500
    max_history_turns: int = 6


@dataclass(frozen=True)
class CoachGraphResult:
    """工作流最终结果。cited 仅在 grounded 模式下非空。"""

    reply: str
    suggestions: list[str]
    cited: list[SearchSnippetCandidate]
    mode: CoachMode
    top_score: float | None = None
    rewritten: bool = False


class CoachGraphState(TypedDict):
    query: str
    intent_text: str
    user_id: uuid.UUID
    material_ids: tuple[uuid.UUID, ...]
    version_id: uuid.UUID | None
    material_versions: dict[uuid.UUID, uuid.UUID]
    allowed_snippet_ids: frozenset[uuid.UUID] | None
    history: list[CoachTurn]
    scope_title: str
    suggested_topics: list[str]
    overview_context: str | None
    intent: CoachIntent
    search_query: str
    candidates: list[SearchSnippetCandidate]
    rerank_scores: dict[uuid.UUID, float]
    top_score: float | None
    evidence: dict[uuid.UUID, str]
    prev_candidates: list[SearchSnippetCandidate]
    prev_scores: dict[uuid.UUID, float]
    prev_top_score: float | None
    prev_evidence: dict[uuid.UUID, str]
    rewrite_count: int
    answer: CoachDraft | None
    result: CoachGraphResult | None
    status: Literal["pending", "no_evidence", "ready", "failed"]


# ---------------------------------------------------------------------------
# 确定性意图路由
# ---------------------------------------------------------------------------

_FILLER_CHARS = re.compile(r"[呀啊哦哈吖啦呢吧嘛~～!！,，。.？?\s]+")
_GREETING_PHRASES = (
    "早上好",
    "下午好",
    "晚上好",
    "你好",
    "您好",
    "哈喽",
    "嗨",
    "hello",
    "hey",
    "hi",
    "在吗",
    "在不在",
)
_THANKS_PHRASES = (
    "非常感谢",
    "谢谢你",
    "谢谢您",
    "谢谢",
    "多谢",
    "感谢",
    "辛苦了",
    "太棒了",
    "明白了",
    "知道了",
    "好的",
    "ok",
)
_BYE_PHRASES = ("再见", "拜拜", "bye")
_IDENTITY_PHRASES = (
    "你是谁",
    "你是做什么的",
    "你能做什么",
    "你可以做什么",
    "你有什么功能",
    "你会什么",
    "怎么用",
    "如何使用",
    "介绍一下你自己",
    "自我介绍",
)
_OVERVIEW_PATTERN = re.compile(
    r"梳理|框架|概览|总览|概括|大纲|思维导图|知识结构|知识体系|主要内容|整体内容"
    r"|总结(?:一下)?(?:这|本|该|整)?一?(?:章|节|课|篇|份|资料|文档|讲)"
    r"|总结.{0,4}(?:重点|考点|要点|内容)"
    r"|(?:核心|主要|重要)?(?:考点|重点|知识点)(?:有哪些|是什么|都有什么|有什么)"
    r"|有哪些(?:考点|重点|知识点)|复习(?:重点|范围)"
)

ChitchatKind = Literal["greeting", "thanks", "bye", "identity"]


def classify_chitchat(query: str) -> ChitchatKind | None:
    """纯寒暄/元问题返回其类型，否则 None；含实质问题时绝不判为寒暄。"""
    text = query.strip().lower()
    if not text or len(text) > 24:
        return None
    for kind, phrases in (
        ("identity", _IDENTITY_PHRASES),
        ("greeting", _GREETING_PHRASES),
        ("thanks", _THANKS_PHRASES),
        ("bye", _BYE_PHRASES),
    ):
        remainder = text
        matched = False
        for phrase in sorted(phrases, key=len, reverse=True):
            if phrase in remainder:
                matched = True
                remainder = remainder.replace(phrase, "")
        if matched and not _FILLER_CHARS.sub("", remainder):
            return cast(ChitchatKind, kind)
    # 「你好，谢谢」等混合寒暄
    mixed = text
    kinds: set[str] = set()
    for kind, phrases in (
        ("greeting", _GREETING_PHRASES),
        ("thanks", _THANKS_PHRASES),
        ("bye", _BYE_PHRASES),
    ):
        for phrase in sorted(phrases, key=len, reverse=True):
            if phrase in mixed:
                kinds.add(kind)
                mixed = mixed.replace(phrase, "")
    if kinds and not _FILLER_CHARS.sub("", mixed):
        return "greeting" if "greeting" in kinds else cast(ChitchatKind, next(iter(kinds)))
    return None


def classify_intent(query: str, *, has_overview: bool) -> CoachIntent:
    """确定性意图分类：寒暄 / 概览（需有结构化知识点）/ 细节答疑。"""
    if classify_chitchat(query) is not None:
        return "chitchat"
    if has_overview and _OVERVIEW_PATTERN.search(query):
        return "overview"
    return "detail_qa"


_DEFAULT_TOPIC_SUGGESTIONS = ["帮我梳理本章重点", "解释一个核心概念", "举个例子帮我理解"]


def build_chitchat_reply(kind: ChitchatKind, topics: Sequence[str]) -> tuple[str, list[str]]:
    """生成零成本的亲切引导回复与 2-3 条学习建议。"""
    suggestions = [f"讲讲「{t}」" for t in topics[:3]] or list(_DEFAULT_TOPIC_SUGGESTIONS)
    replies = {
        "greeting": "你好呀～我是你的课程助教。可以直接问我资料里的概念、公式或题目，"
        "也可以让我帮你梳理本章重点，我会尽量依据你的资料来回答。",
        "thanks": "不客气～学习路上有疑问随时来问我，我会一直依据你的资料帮你理清思路。",
        "bye": "好的，下次见～记得及时复习巩固，有疑问随时回来找我。",
        "identity": "我是你的课程助教，只依据你上传的学习资料答疑：讲解概念与公式、"
        "梳理章节考点、解析题目思路。想从哪里开始？",
    }
    return replies[kind], suggestions[:3]


def build_fallback_reply(topics: Sequence[str]) -> tuple[str, list[str]]:
    """证据不足时的诚实兜底：说明缺口并给出可回答的方向。"""
    reply = (
        "这份资料里暂时没找到能可靠回答这个问题的依据，我就不随便猜测了。"
        "换个更具体的说法再试试，或者从资料里已有的内容问起。"
    )
    suggestions = [f"讲讲「{t}」" for t in topics[:3]] or list(_DEFAULT_TOPIC_SUGGESTIONS)
    return reply, suggestions[:3]


# ---------------------------------------------------------------------------
# 检索 / 精排 / 邻接扩展 / 引用校验
# ---------------------------------------------------------------------------


def _format_history(history: Sequence[CoachTurn], max_turns: int) -> str:
    turns = list(history)[-max_turns:]
    if not turns:
        return ""
    lines = [f"学生：{t.user[:300]}\n助教：{t.assistant[:400]}" for t in turns]
    return "【此前对话（用于理解指代，事实仍只依据资料）】\n" + "\n".join(lines) + "\n\n"


def _augment_followup_query(query: str, intent_text: str, history: Sequence[CoachTurn]) -> str:
    """短追问（如「那不满足这个条件会怎样」）拼上上一轮提问，提升检索召回。"""
    if history and len(intent_text.strip()) <= 16:
        return f"{history[-1].user[:120]} {query}"
    return query


def _search_pool(
    search: SearchProtocol,
    state: CoachGraphState,
    cfg: CoachGraphConfig,
    *,
    query: str,
    apply_vector_gate: bool,
) -> list[SearchSnippetCandidate]:
    allowed = state["allowed_snippet_ids"]
    if allowed is not None and not allowed:
        return []
    allowed_tuple = None if allowed is None else tuple(sorted(allowed, key=str))
    pool: dict[uuid.UUID, SearchSnippetCandidate] = {}
    for material_id in state["material_ids"]:
        expected_version = state["material_versions"].get(material_id, state["version_id"])
        result = search.search(
            query=query,
            user_id=state["user_id"],
            material_id=material_id,
            version_id=expected_version,
            options=SearchOptions(
                top_k=cfg.retrieve_top_k,
                vector_top_k=cfg.vector_top_k,
                allowed_snippet_ids=allowed_tuple,
            ),
        )
        for item in result.items:
            if item.material_id != material_id:
                continue
            if expected_version is not None and item.version_id != expected_version:
                continue
            if allowed is not None and item.snippet_id not in allowed:
                continue
            if apply_vector_gate and item.vector_score < cfg.vector_gate and item.bm25_score <= 0:
                continue
            previous = pool.get(item.snippet_id)
            if previous is None or (item.final_score, item.vector_score) > (
                previous.final_score,
                previous.vector_score,
            ):
                pool[item.snippet_id] = item
    ranked = sorted(pool.values(), key=lambda c: (c.final_score, c.vector_score), reverse=True)
    return ranked[: cfg.retrieve_top_k]


def _rerank_pool(
    reranker: RerankProtocol,
    query: str,
    pool: Sequence[SearchSnippetCandidate],
    cfg: CoachGraphConfig,
) -> tuple[list[SearchSnippetCandidate], dict[uuid.UUID, float], float | None]:
    """精排并按 min_score 过滤；精排异常时优雅降级为融合排序（top_score=None）。"""
    if not pool:
        return [], {}, None
    try:
        items = reranker.rerank(query, [c.content for c in pool], top_n=cfg.rerank_top_n)
    except Exception as exc:
        logger.warning("coach rerank degraded: %s", type(exc).__name__)
        return list(pool[: cfg.rerank_top_n]), {}, None
    scores: dict[uuid.UUID, float] = {}
    ordered: list[SearchSnippetCandidate] = []
    for item in items:
        if 0 <= item.index < len(pool):
            candidate = pool[item.index]
            scores[candidate.snippet_id] = item.relevance_score
            ordered.append(candidate)
    if not ordered:
        return list(pool[: cfg.rerank_top_n]), {}, None
    top_score = max(scores.values())
    kept = [c for c in ordered if scores[c.snippet_id] >= cfg.min_score]
    return kept, scores, top_score


def _expand_with_neighbors(
    search: SearchProtocol,
    selected: Sequence[SearchSnippetCandidate],
    user_id: uuid.UUID,
    cfg: CoachGraphConfig,
) -> dict[uuid.UUID, str]:
    """为每个入选切片拼接同版本同页 ±window 的相邻切片；不支持/失败时只用原文。"""
    evidence = {c.snippet_id: c.content for c in selected}
    if not selected or not isinstance(search, NeighborSearchProtocol):
        return _trim_evidence(evidence, cfg)
    try:
        neighbors = search.fetch_neighbor_snippets(
            list(selected), user_id=user_id, window=cfg.neighbor_window
        )
    except Exception as exc:
        logger.warning("coach neighbor expansion degraded: %s", type(exc).__name__)
        return _trim_evidence(evidence, cfg)
    for anchor in selected:
        if anchor.snippet_index is None:
            continue
        near = [
            n
            for n in neighbors
            if n.version_id == anchor.version_id
            and n.snippet_index is not None
            and abs(n.snippet_index - anchor.snippet_index) <= cfg.neighbor_window
        ]
        if not near:
            continue
        group = sorted([anchor, *near], key=lambda c: c.snippet_index or 0)
        evidence[anchor.snippet_id] = merge_adjacent_snippet_texts([c.content for c in group])
    return _trim_evidence(evidence, cfg)


def _trim_evidence(evidence: dict[uuid.UUID, str], cfg: CoachGraphConfig) -> dict[uuid.UUID, str]:
    return {
        key: trim_excerpt_cleanly(text, max_chars=cfg.max_evidence_chars)
        for key, text in evidence.items()
    }


def verify_citations(
    draft: CoachDraft, candidates: Sequence[SearchSnippetCandidate], *, backfill: int = 2
) -> CoachDraft:
    """确定性引用校验：只保留合法 ID（去重保序）；全部非法/为空时回填 Top 候选。"""
    allowed = [c.snippet_id for c in candidates]
    allowed_set = set(allowed)
    valid = [i for i in dict.fromkeys(draft.citation_ids) if i in allowed_set]
    if not valid:
        valid = allowed[:backfill]
    return draft.model_copy(update={"citation_ids": valid})


_GROUNDED_SYSTEM_PROMPT = (
    "你是亲切耐心的课程助教，像真人学长/老师一对一聊天那样为学生点拨答疑。\n"
    "【事实底线】只根据给定资料回答，资料不足以回答时坦诚说明；"
    "citation_ids 只能从给定切片 ID 中选择，严禁编造或改写来源。\n"
    "【表达规范】\n"
    "1. 先用 1~2 句话直接给出核心结论；\n"
    "2. 再补充 2~3 条简短要点（条件、原因或小例子），"
    "口语自然、有温度；\n"
    "3. 总长控制在 150~260 字左右，方便手机小屏阅读；\n"
    "4. 严禁使用「一、二、三、」教科书式大纲，严禁机械照搬大段讲义原文；\n"
    "5. 数学公式保持资料中的 $...$ / $$...$$ 写法，不要改写成乱码或纯文本；\n"
    "6. 若有此前对话，请据此理解「那」「这个条件」等指代，但事实仍只依据资料；\n"
    "7. suggestions 给出 2~3 条简短自然的追问建议（每条不超过 15 字）。"
)

_OVERVIEW_SYSTEM_PROMPT = (
    "你是亲切耐心的课程助教。学生想了解章节框架或核心考点，"
    "请严格依据下方【知识点梳理】作答，不得引入梳理之外的概念或数值。\n"
    "【表达规范】先用一句话总览，再分点列出 4~8 个核心考点（每点一句话讲清要义），"
    "语气自然；公式保持 $...$ 写法；总长控制在 300 字以内；"
    "suggestions 给出 2~3 条简短追问建议（每条不超过 15 字）。"
)

_REWRITE_SYSTEM_PROMPT = (
    "你是检索查询改写器。把学生的口语化/带指代的提问，结合此前对话与当前学习范围，"
    "改写成一条独立、完整、适合在教材中检索的查询（保留专有名词、公式符号与关键词）。"
    "只输出改写后的查询，严禁回答问题或添加新概念。"
)


# ---------------------------------------------------------------------------
# 图构建
# ---------------------------------------------------------------------------


class _CoachNodes:
    """图节点集合：持有协作者引用，避免 build_coach_graph 过度嵌套。"""

    def __init__(
        self,
        search: SearchProtocol,
        llm: LLMProtocol,
        reranker: RerankProtocol | None,
        cfg: CoachGraphConfig,
    ) -> None:
        self.search = search
        self.llm = llm
        self.reranker = reranker
        self.cfg = cfg

    def route_intent(self, state: CoachGraphState) -> dict[str, Any]:
        return {
            "intent": classify_intent(
                state["intent_text"], has_overview=bool(state["overview_context"])
            )
        }

    @staticmethod
    def route_after_intent(state: CoachGraphState) -> str:
        return state["intent"]

    @staticmethod
    def conversational_reply(state: CoachGraphState) -> dict[str, Any]:
        kind = classify_chitchat(state["intent_text"]) or "greeting"
        reply, suggestions = build_chitchat_reply(kind, state["suggested_topics"])
        result = CoachGraphResult(reply=reply, suggestions=suggestions, cited=[], mode="chitchat")
        return {"result": result, "status": "ready"}

    def generate_overview(self, state: CoachGraphState) -> dict[str, Any]:
        history = _format_history(state["history"], self.cfg.max_history_turns)
        draft, _ = self.llm.generate_structured(
            messages=[
                LLMMessage(role="system", content=_OVERVIEW_SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=(
                        f"{history}问题：{state['query']}\n\n"
                        f"【知识点梳理】\n{state['overview_context']}"
                    ),
                ),
            ],
            response_model=CoachOverviewDraft,
            options=LLMOptions(temperature=0.45, max_tokens=900),
        )
        result = CoachGraphResult(
            reply=draft.reply,
            suggestions=list(draft.suggestions)[:3],
            cited=[],
            mode="overview",
        )
        return {"result": result, "status": "ready"}

    def retrieve_and_rerank(self, state: CoachGraphState) -> dict[str, Any]:
        cfg = self.cfg
        query = state["search_query"] or state["query"]
        pool = _search_pool(
            self.search, state, cfg, query=query, apply_vector_gate=self.reranker is None
        )
        top_score: float | None = None
        scores: dict[uuid.UUID, float] = {}
        if self.reranker is not None:
            selected, scores, top_score = _rerank_pool(self.reranker, query, pool, cfg)
        else:
            selected = pool[: cfg.rerank_top_n + 2]
        if state["rewrite_count"] > 0 and _is_worse(top_score, state["prev_top_score"]):
            # 改写后的结果不如首轮：回退到首轮的最佳证据
            return {
                "candidates": state["prev_candidates"],
                "rerank_scores": state["prev_scores"],
                "top_score": state["prev_top_score"],
                "evidence": state["prev_evidence"],
                "status": "pending" if state["prev_candidates"] else "no_evidence",
            }
        return {
            "candidates": selected,
            "rerank_scores": scores,
            "top_score": top_score,
            "evidence": _expand_with_neighbors(self.search, selected, state["user_id"], cfg),
            "status": "pending" if selected else "no_evidence",
        }

    def check_evidence(self, state: CoachGraphState) -> str:
        can_rewrite = state["rewrite_count"] == 0
        if not state["candidates"]:
            return "rewrite" if can_rewrite else "fallback"
        top = state["top_score"]
        if top is not None and top < self.cfg.rewrite_threshold:
            if can_rewrite:
                return "rewrite"
            if top < self.cfg.min_score:
                return "fallback"
        return "generate"

    def rewrite_query(self, state: CoachGraphState) -> dict[str, Any]:
        fallback_query = f"{state['scope_title']} {state['query']}".strip()
        history = _format_history(state["history"], self.cfg.max_history_turns)
        try:
            rewritten, _ = self.llm.generate_structured(
                messages=[
                    LLMMessage(role="system", content=_REWRITE_SYSTEM_PROMPT),
                    LLMMessage(
                        role="user",
                        content=(
                            f"{history}学习范围：{state['scope_title'] or '（未指定）'}\n"
                            f"学生提问：{state['query']}"
                        ),
                    ),
                ],
                response_model=RewrittenQuery,
                options=LLMOptions(temperature=0.1, max_tokens=120),
            )
            new_query = rewritten.query.strip() or fallback_query
        except Exception as exc:
            logger.warning("coach query rewrite degraded: %s", type(exc).__name__)
            new_query = fallback_query
        return {
            "search_query": new_query,
            "rewrite_count": state["rewrite_count"] + 1,
            "prev_candidates": state["candidates"],
            "prev_scores": state["rerank_scores"],
            "prev_top_score": state["top_score"],
            "prev_evidence": state["evidence"],
        }

    @staticmethod
    def honest_fallback(state: CoachGraphState) -> dict[str, Any]:
        reply, suggestions = build_fallback_reply(state["suggested_topics"])
        result = CoachGraphResult(
            reply=reply,
            suggestions=suggestions,
            cited=[],
            mode="fallback",
            top_score=state["top_score"],
            rewritten=state["rewrite_count"] > 0,
        )
        return {"result": result, "status": "no_evidence"}

    def generate_grounded(self, state: CoachGraphState) -> dict[str, Any]:
        evidence = "\n\n".join(
            f"[{item.snippet_id}] {item.chapter_title}\n"
            f"{state['evidence'].get(item.snippet_id, item.content)}"
            for item in state["candidates"]
        )
        history = _format_history(state["history"], self.cfg.max_history_turns)
        answer, _ = self.llm.generate_structured(
            messages=[
                LLMMessage(role="system", content=_GROUNDED_SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=f"{history}问题：{state['query']}\n\n资料：\n{evidence}",
                ),
            ],
            response_model=CoachDraft,
            options=LLMOptions(temperature=0.45, max_tokens=900),
        )
        return {"answer": answer}

    @staticmethod
    def verify_citations(state: CoachGraphState) -> dict[str, Any]:
        answer = state["answer"]
        if answer is None:
            return {"status": "failed"}
        checked = verify_citations(answer, state["candidates"])
        cited_ids = set(checked.citation_ids)
        result = CoachGraphResult(
            reply=checked.reply,
            suggestions=list(checked.suggestions)[:3],
            cited=[c for c in state["candidates"] if c.snippet_id in cited_ids],
            mode="grounded",
            top_score=state["top_score"],
            rewritten=state["rewrite_count"] > 0,
        )
        return {"answer": checked, "result": result, "status": "ready"}


def build_coach_graph(
    search: SearchProtocol,
    llm: LLMProtocol,
    *,
    reranker: RerankProtocol | None = None,
    config: CoachGraphConfig | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """构建 Adaptive + Corrective 助教图；授权范围须由调用方预先解析。"""
    nodes = _CoachNodes(search, llm, reranker, config or CoachGraphConfig())
    graph = StateGraph(CoachGraphState)
    graph.add_node("route_intent", nodes.route_intent)
    graph.add_node("conversational_reply", nodes.conversational_reply)
    graph.add_node("generate_overview", nodes.generate_overview)
    graph.add_node("retrieve_and_rerank", nodes.retrieve_and_rerank)
    graph.add_node("rewrite_query", nodes.rewrite_query)
    graph.add_node("honest_fallback", nodes.honest_fallback)
    graph.add_node("generate_grounded", nodes.generate_grounded)
    graph.add_node("verify_citations", nodes.verify_citations)
    graph.add_edge(START, "route_intent")
    graph.add_conditional_edges(
        "route_intent",
        nodes.route_after_intent,
        {
            "chitchat": "conversational_reply",
            "overview": "generate_overview",
            "detail_qa": "retrieve_and_rerank",
        },
    )
    graph.add_conditional_edges(
        "retrieve_and_rerank",
        nodes.check_evidence,
        {
            "generate": "generate_grounded",
            "rewrite": "rewrite_query",
            "fallback": "honest_fallback",
        },
    )
    graph.add_edge("rewrite_query", "retrieve_and_rerank")
    graph.add_edge("generate_grounded", "verify_citations")
    graph.add_edge("conversational_reply", END)
    graph.add_edge("generate_overview", END)
    graph.add_edge("honest_fallback", END)
    graph.add_edge("verify_citations", END)
    return graph.compile(checkpointer=checkpointer if checkpointer is not None else MemorySaver())


def _is_worse(new_top: float | None, prev_top: float | None) -> bool:
    """改写后的精排最高分低于首轮最高分时视为更差（无精排分数时不比较）。"""
    return new_top is not None and prev_top is not None and new_top < prev_top


def run_coach_graph(
    *,
    search: SearchProtocol,
    llm: LLMProtocol,
    query: str,
    user_id: uuid.UUID,
    material_ids: tuple[uuid.UUID, ...],
    version_id: uuid.UUID | None = None,
    material_versions: dict[uuid.UUID, uuid.UUID] | None = None,
    allowed_snippet_ids: frozenset[uuid.UUID] | None = None,
    reranker: RerankProtocol | None = None,
    config: CoachGraphConfig | None = None,
    history: Sequence[CoachTurn] = (),
    scope_title: str = "",
    suggested_topics: Sequence[str] = (),
    overview_context: str | None = None,
    thread_id: str | None = None,
    intent_text: str | None = None,
) -> CoachGraphResult:
    """运行 Adaptive + Corrective 工作流并返回已校验的结果。"""
    cfg = config or CoachGraphConfig()
    recent = list(history)[-cfg.max_history_turns :]
    state: CoachGraphState = {
        "query": query,
        "intent_text": intent_text if intent_text is not None else query,
        "user_id": user_id,
        "material_ids": material_ids,
        "version_id": version_id,
        "material_versions": material_versions or {},
        "allowed_snippet_ids": allowed_snippet_ids,
        "history": recent,
        "scope_title": scope_title,
        "suggested_topics": list(suggested_topics),
        "overview_context": overview_context,
        "intent": "detail_qa",
        "search_query": _augment_followup_query(
            query, intent_text if intent_text is not None else query, recent
        ),
        "candidates": [],
        "rerank_scores": {},
        "top_score": None,
        "evidence": {},
        "prev_candidates": [],
        "prev_scores": {},
        "prev_top_score": None,
        "prev_evidence": {},
        "rewrite_count": 0,
        "answer": None,
        "result": None,
        "status": "pending",
    }
    graph = build_coach_graph(search, llm, reranker=reranker, config=cfg)
    run_config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
    final = graph.invoke(state, config=run_config)
    result = final.get("result")
    if result is None:
        reply, suggestions = build_fallback_reply(state["suggested_topics"])
        return CoachGraphResult(reply=reply, suggestions=suggestions, cited=[], mode="fallback")
    return cast(CoachGraphResult, result)


def answer_with_course_evidence(
    *,
    search: SearchProtocol,
    llm: LLMProtocol,
    query: str,
    user_id: uuid.UUID,
    material_ids: tuple[uuid.UUID, ...],
    version_id: uuid.UUID | None = None,
    material_versions: dict[uuid.UUID, uuid.UUID] | None = None,
    allowed_snippet_ids: frozenset[uuid.UUID] | None = None,
    reranker: RerankProtocol | None = None,
    config: CoachGraphConfig | None = None,
) -> tuple[CoachDraft | None, list[SearchSnippetCandidate]]:
    """兼容入口：返回已校验的有据回答及其引用切片；无依据时返回 (None, [])。"""
    result = run_coach_graph(
        search=search,
        llm=llm,
        query=query,
        user_id=user_id,
        material_ids=material_ids,
        version_id=version_id,
        material_versions=material_versions,
        allowed_snippet_ids=allowed_snippet_ids,
        reranker=reranker,
        config=config,
    )
    if result.mode != "grounded" or not result.cited:
        return None, []
    draft = CoachDraft(
        reply=result.reply,
        suggestions=result.suggestions,
        citation_ids=[c.snippet_id for c in result.cited],
    )
    return draft, result.cited


__all__ = [
    "CoachDraft",
    "CoachGraphConfig",
    "CoachGraphResult",
    "CoachOverviewDraft",
    "RewrittenQuery",
    "answer_with_course_evidence",
    "build_chitchat_reply",
    "build_coach_graph",
    "build_fallback_reply",
    "classify_chitchat",
    "classify_intent",
    "run_coach_graph",
    "verify_citations",
]
