"""Grounded course-coach workflow tests."""

import uuid
from unittest.mock import MagicMock

from app.integrations.llm.coach_graph import CoachDraft, answer_with_course_evidence
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.search.protocol import SearchResult, SearchSnippetCandidate


def candidate(material_id: uuid.UUID, score: float = 0.8) -> SearchSnippetCandidate:
    return SearchSnippetCandidate(
        snippet_id=uuid.uuid4(),
        material_id=material_id,
        version_id=uuid.uuid4(),
        content="An actual excerpt from the material.",
        chapter_title="Chapter 1",
        source_info={"page": 1},
        vector_score=score,
        final_score=0.016,
    )


def test_coach_returns_only_verified_citations() -> None:
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    item = candidate(material_id)
    foreign = candidate(uuid.uuid4())
    search = FakeSearchAdapter()
    search.set_canned_candidates([item, foreign])
    llm = MagicMock()
    llm.generate_structured.return_value = (
        CoachDraft(reply="Grounded answer", citation_ids=[item.snippet_id]),
        MagicMock(),
    )

    answer, cited = answer_with_course_evidence(
        search=search,
        llm=llm,
        query="What does the material say?",
        user_id=user_id,
        material_ids=(material_id,),
    )

    assert answer is not None
    assert answer.reply == "Grounded answer"
    assert [source.snippet_id for source in cited] == [item.snippet_id]
    assert str(foreign.snippet_id) not in str(llm.generate_structured.call_args)


def test_coach_abstains_without_relevant_evidence() -> None:
    material_id = uuid.uuid4()
    search = FakeSearchAdapter()
    search.set_canned_candidates([candidate(material_id, score=0.1)])
    llm = MagicMock()

    answer, cited = answer_with_course_evidence(
        search=search,
        llm=llm,
        query="Unknown topic",
        user_id=uuid.uuid4(),
        material_ids=(material_id,),
    )

    assert answer is None
    assert cited == []
    llm.generate_structured.assert_not_called()


def test_coach_repairs_bad_citation_once() -> None:
    material_id = uuid.uuid4()
    item = candidate(material_id)
    search = FakeSearchAdapter()
    search.set_canned_candidates([item])
    llm = MagicMock()
    llm.generate_structured.side_effect = [
        (CoachDraft(reply="First answer", citation_ids=[uuid.uuid4()]), MagicMock()),
        (CoachDraft(reply="Repaired answer", citation_ids=[item.snippet_id]), MagicMock()),
    ]

    answer, cited = answer_with_course_evidence(
        search=search,
        llm=llm,
        query="Topic",
        user_id=uuid.uuid4(),
        material_ids=(material_id,),
    )

    assert answer is not None
    assert answer.reply == "Repaired answer"
    assert len(cited) == 1
    assert llm.generate_structured.call_count == 2


def test_coach_abstains_after_second_bad_citation() -> None:
    material_id = uuid.uuid4()
    item = candidate(material_id)
    search = FakeSearchAdapter()
    search.set_canned_candidates([item])
    llm = MagicMock()
    llm.generate_structured.return_value = (
        CoachDraft(reply="Unsupported", citation_ids=[uuid.uuid4()]),
        MagicMock(),
    )

    answer, cited = answer_with_course_evidence(
        search=search,
        llm=llm,
        query="Topic",
        user_id=uuid.uuid4(),
        material_ids=(material_id,),
    )

    assert answer is None
    assert cited == []
    assert llm.generate_structured.call_count == 2


def test_coach_excludes_stale_versions_from_evidence() -> None:
    material_id = uuid.uuid4()
    current = candidate(material_id)
    stale = candidate(material_id)
    search = MagicMock()
    search.search.return_value = SearchResult(query="Topic", items=[stale, current])
    llm = MagicMock()
    llm.generate_structured.return_value = (
        CoachDraft(reply="Current answer", citation_ids=[current.snippet_id]),
        MagicMock(),
    )

    answer, cited = answer_with_course_evidence(
        search=search,
        llm=llm,
        query="Topic",
        user_id=uuid.uuid4(),
        material_ids=(material_id,),
        material_versions={material_id: current.version_id},
    )

    assert answer is not None
    assert cited == [current]
    assert search.search.call_args.kwargs["version_id"] == current.version_id
    assert str(stale.snippet_id) not in str(llm.generate_structured.call_args)
