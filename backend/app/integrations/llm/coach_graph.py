"""Grounded course-coach workflow with bounded citation repair."""

import uuid
from typing import Any, Literal, TypedDict, cast

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.integrations.search.protocol import (
    SearchOptions,
    SearchProtocol,
    SearchSnippetCandidate,
)


class CoachDraft(BaseModel):
    reply: str = Field(min_length=1)
    suggestions: list[str] = Field(default_factory=list)
    citation_ids: list[uuid.UUID] = Field(min_length=1)


class CoachGraphState(TypedDict):
    query: str
    user_id: uuid.UUID
    material_ids: tuple[uuid.UUID, ...]
    version_id: uuid.UUID | None
    material_versions: dict[uuid.UUID, uuid.UUID]
    allowed_snippet_ids: frozenset[uuid.UUID] | None
    candidates: list[SearchSnippetCandidate]
    answer: CoachDraft | None
    retry_count: int
    status: Literal["pending", "no_evidence", "retry", "ready", "failed"]


def build_coach_graph(search: SearchProtocol, llm: LLMProtocol) -> Any:
    """Build a single-request graph; authorization must be resolved by the caller."""

    def retrieve(state: CoachGraphState) -> dict[str, Any]:
        allowed_snippets = state["allowed_snippet_ids"]
        candidates: dict[uuid.UUID, SearchSnippetCandidate] = {}
        for material_id in state["material_ids"]:
            expected_version = state["material_versions"].get(material_id, state["version_id"])
            result = search.search(
                query=state["query"],
                user_id=state["user_id"],
                material_id=material_id,
                version_id=expected_version,
                options=SearchOptions(top_k=8, vector_top_k=20),
            )
            for item in result.items:
                if item.material_id != material_id:
                    continue
                if expected_version is not None and item.version_id != expected_version:
                    continue
                if allowed_snippets is not None and item.snippet_id not in allowed_snippets:
                    continue
                if item.vector_score < 0.35:
                    continue
                previous = candidates.get(item.snippet_id)
                if previous is None or item.vector_score > previous.vector_score:
                    candidates[item.snippet_id] = item
        selected = sorted(
            candidates.values(),
            key=lambda item: (item.vector_score, item.final_score),
            reverse=True,
        )[:8]
        return {"candidates": selected, "status": "pending" if selected else "no_evidence"}

    def route_evidence(state: CoachGraphState) -> str:
        return "generate" if state["candidates"] else "end"

    def generate(state: CoachGraphState) -> dict[str, Any]:
        evidence = "\n\n".join(
            f"[{item.snippet_id}] {item.chapter_title}\n{item.content[:800]}"
            for item in state["candidates"]
        )
        repair = (
            "上次引用的切片 ID 不在给定证据中。请只使用下方真实 ID，并至少引用一条。"
            if state["retry_count"]
            else ""
        )
        answer, _ = llm.generate_structured(
            messages=[
                LLMMessage(
                    role="system",
                    content=(
                        "你是课程助教。只根据给定资料回答，不足以回答就明确说明。"
                        "citation_ids 只能选给定切片 ID，不得编造来源。"
                    ),
                ),
                LLMMessage(
                    role="user",
                    content=f"问题：{state['query']}\n{repair}\n资料：\n{evidence}",
                ),
            ],
            response_model=CoachDraft,
            options=LLMOptions(temperature=0.2),
        )
        return {"answer": answer}

    def validate(state: CoachGraphState) -> dict[str, Any]:
        answer = state["answer"]
        allowed = {item.snippet_id for item in state["candidates"]}
        if answer is not None and answer.citation_ids and set(answer.citation_ids) <= allowed:
            return {"status": "ready"}
        if state["retry_count"] == 0:
            return {"status": "retry", "retry_count": 1}
        return {"status": "failed"}

    def route_validation(state: CoachGraphState) -> str:
        return "generate" if state["status"] == "retry" else "end"

    graph = StateGraph(CoachGraphState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_node("validate", validate)
    graph.add_edge(START, "retrieve")
    graph.add_conditional_edges("retrieve", route_evidence, {"generate": "generate", "end": END})
    graph.add_edge("generate", "validate")
    graph.add_conditional_edges("validate", route_validation, {"generate": "generate", "end": END})
    return graph.compile()


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
) -> tuple[CoachDraft | None, list[SearchSnippetCandidate]]:
    """Return a checked answer and only the snippets it cites."""
    state: CoachGraphState = {
        "query": query,
        "user_id": user_id,
        "material_ids": material_ids,
        "version_id": version_id,
        "material_versions": material_versions or {},
        "allowed_snippet_ids": allowed_snippet_ids,
        "candidates": [],
        "answer": None,
        "retry_count": 0,
        "status": "pending",
    }
    result = build_coach_graph(search, llm).invoke(state)
    if result["status"] != "ready":
        return None, []
    answer = cast(CoachDraft, result["answer"])
    cited = set(answer.citation_ids)
    return answer, [item for item in result["candidates"] if item.snippet_id in cited]


__all__ = ["CoachDraft", "answer_with_course_evidence", "build_coach_graph"]
