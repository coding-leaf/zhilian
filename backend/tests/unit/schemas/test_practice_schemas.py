"""Unit tests for practice Pydantic schemas in app/schemas/practice.py.

Covers:
- PracticeCreateRequest validation (title length, question count bounds 1~50, mode whitelist);
- QuestionSnapshotDTO 6-element structure and analysis/explanation field compatibility;
- PracticeItemDetailResponse field mappings and time/duration aliases;
- PracticeDetailResponse field synchronization and items aggregation;
- PracticeSummaryResponse & PracticeListResponse list views;
- SaveAnswerRequest payload flexibility (str, list, dict, None) and non-negative time;
- SaveAnswerResponse and PracticeStatusResponse status updates;
- SubmitPracticeResponse idempotency replay and unanswered count.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.material import SourceSnippetDTO
from app.schemas.practice import (
    AttemptItemDetailResponse,
    PracticeCreateRequest,
    PracticeCreateResponse,
    PracticeDetailResponse,
    PracticeItemDetailResponse,
    PracticeListItemResponse,
    PracticeListResponse,
    PracticeSaveAnswerRequest,
    PracticeSaveAnswerResponse,
    PracticeStatusActionResponse,
    PracticeStatusResponse,
    PracticeSubmitRequest,
    PracticeSubmitResponse,
    PracticeSummaryResponse,
    QuestionSnapshotDTO,
    SaveAnswerRequest,
    SaveAnswerResponse,
    SubmitPracticeResponse,
)


def test_practice_create_request_valid() -> None:
    """测试合法参数下的练习创建请求。"""
    material_id = uuid.uuid4()
    knowledge_point_id = uuid.uuid4()

    request = PracticeCreateRequest(
        title="计算机网络-传输层专项",
        material_id=material_id,
        knowledge_point_ids=[knowledge_point_id],
        question_count=15,
        mode="sequential",
    )
    assert request.title == "计算机网络-传输层专项"
    assert request.material_id == material_id
    assert request.knowledge_point_ids == [knowledge_point_id]
    assert request.question_count == 15
    assert request.mode == "sequential"
    assert request.source_type == "normal"
    assert request.difficulty is None


def test_practice_create_request_question_count_bounds() -> None:
    """测试题目数量边界校验 (1~50)。"""
    material_id = uuid.uuid4()
    kp_id = uuid.uuid4()

    req_min = PracticeCreateRequest(
        title="边界测试-最小题量",
        material_id=material_id,
        knowledge_point_ids=[kp_id],
        question_count=1,
    )
    assert req_min.question_count == 1

    req_max = PracticeCreateRequest(
        title="边界测试-最大题量",
        material_id=material_id,
        knowledge_point_ids=[kp_id],
        question_count=50,
    )
    assert req_max.question_count == 50

    with pytest.raises(ValidationError):
        PracticeCreateRequest(
            title="非法题量-0",
            material_id=material_id,
            knowledge_point_ids=[kp_id],
            question_count=0,
        )

    with pytest.raises(ValidationError):
        PracticeCreateRequest(
            title="非法题量-51",
            material_id=material_id,
            knowledge_point_ids=[kp_id],
            question_count=51,
        )


def test_practice_create_request_mode_validation() -> None:
    """测试抽题模式枚举校验。"""
    material_id = uuid.uuid4()
    kp_id = uuid.uuid4()

    for valid_mode in ["sequential", "random", "weak_points"]:
        req = PracticeCreateRequest(
            title=f"模式测试-{valid_mode}",
            material_id=material_id,
            knowledge_point_ids=[kp_id],
            mode=valid_mode,
        )
        assert req.mode == valid_mode

    with pytest.raises(ValidationError):
        PracticeCreateRequest(
            title="非法模式",
            material_id=material_id,
            knowledge_point_ids=[kp_id],
            mode="invalid_mode",
        )

    req_weakness = PracticeCreateRequest(
        title="薄弱点练习",
        material_id=material_id,
        knowledge_point_ids=[kp_id],
        source_type="weakness",
    )
    assert req_weakness.source_type == "weakness"

    with pytest.raises(ValidationError):
        PracticeCreateRequest(
            title="非法来源",
            material_id=material_id,
            knowledge_point_ids=[kp_id],
            source_type="unknown_source",
        )


def test_practice_create_request_empty_knowledge_points() -> None:
    """测试知识点列表为空时抛出校验错误。"""
    material_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        PracticeCreateRequest(
            title="空知识点",
            material_id=material_id,
            knowledge_point_ids=[],
        )


def test_practice_create_request_folder_scope_without_points() -> None:
    """课程文件夹范围允许 knowledge_point_ids 缺省（默认取文件夹全部考点）。"""
    folder_id = uuid.uuid4()
    request = PracticeCreateRequest(
        title="课程范围练习",
        folder_id=folder_id,
        question_count=5,
    )

    assert request.folder_id == folder_id
    assert request.knowledge_point_ids == []
    assert request.material_id is None


def test_practice_create_request_wrong_record_and_optional_material() -> None:
    """测试 wrong_record 来源合法且 material_id 缺省时可创建 (由后端解析)。"""
    kp_id = uuid.uuid4()

    req = PracticeCreateRequest(
        title="错题巩固练习",
        knowledge_point_ids=[kp_id],
        source_type="wrong_record",
    )
    assert req.source_type == "wrong_record"
    assert req.material_id is None

    # 显式提供 material_id 仍兼容
    mat_id = uuid.uuid4()
    req_with_material = PracticeCreateRequest(
        title="错题巩固练习",
        material_id=mat_id,
        knowledge_point_ids=[kp_id],
        source_type="wrong_record",
    )
    assert req_with_material.material_id == mat_id


def test_question_snapshot_dto_valid() -> None:
    """测试题目 6 要素快照模型及其字段解析。"""
    snippet_id = uuid.uuid4()
    snapshot = QuestionSnapshotDTO(
        stem="TCP 建立连接需要几次握手？",
        question_type="single_choice",
        options=[
            {"key": "A", "content": "1次"},
            {"key": "B", "content": "2次"},
            {"key": "C", "content": "3次"},
            {"key": "D", "content": "4次"},
        ],
        answer="C",
        explanation="TCP通过三次握手建立可靠连接",
        source_snippet_id=snippet_id,
        difficulty=2,
    )
    assert snapshot.stem == "TCP 建立连接需要几次握手？"
    assert snapshot.question_type == "single_choice"
    assert len(snapshot.options) == 4
    assert snapshot.answer == "C"
    assert snapshot.explanation == "TCP通过三次握手建立可靠连接"
    assert snapshot.analysis == "TCP通过三次握手建立可靠连接"
    assert snapshot.source_snippet_id == snippet_id
    assert snapshot.difficulty == 2


def test_question_snapshot_dto_analysis_alias() -> None:
    """测试使用 analysis 入参时能自动兼容并同步到 explanation。"""
    snapshot = QuestionSnapshotDTO(
        stem="简述 DNS 的工作原理",
        question_type="short_answer",
        answer="域名解析为 IP 地址",
        analysis="应用层协议，默认基于 UDP 53 端口",
    )
    assert snapshot.explanation == "应用层协议，默认基于 UDP 53 端口"
    assert snapshot.analysis == "应用层协议，默认基于 UDP 53 端口"


def test_practice_item_detail_response_and_aliases() -> None:
    """测试题目作答项详情及别名同步机制。"""
    item_id = uuid.uuid4()
    question_id = uuid.uuid4()

    response = PracticeItemDetailResponse(
        attempt_item_id=item_id,
        question_id=question_id,
        order_index=1,
        status="answered",
        user_answer="C",
        time_spent_seconds=25,
        question_snapshot={
            "stem": "选择题题干",
            "question_type": "single_choice",
            "options": [{"key": "A", "content": "1"}],
            "answer": "A",
        },
    )
    assert response.attempt_item_id == item_id
    assert response.id == item_id
    assert response.question_id == question_id
    assert response.order_index == 1
    assert response.status == "answered"
    assert response.user_answer == "C"
    assert response.time_spent_seconds == 25
    assert response.duration_seconds == 25
    assert response.is_answered is True

    resp_reverse = PracticeItemDetailResponse.model_validate(
        {
            "id": item_id,
            "order_index": 2,
            "duration_seconds": 40,
            "user_answer": "B",
            "status": "unanswered",
            "question_snapshot": {
                "stem": "题干",
                "question_type": "single_choice",
                "answer": "B",
            },
        }
    )
    assert resp_reverse.attempt_item_id == item_id
    assert resp_reverse.time_spent_seconds == 40
    assert resp_reverse.status == "answered"

    assert AttemptItemDetailResponse is PracticeItemDetailResponse


def test_practice_item_grading_status_three_states() -> None:
    """测试作答项判题状态三态(未作答/待重判/已判分)计算与真实 0 分区分。"""
    item_id = uuid.uuid4()
    snapshot = {"stem": "题干", "question_type": "short_answer", "answer": "参考答案"}

    unanswered = PracticeItemDetailResponse.model_validate(
        {
            "id": item_id,
            "order_index": 1,
            "is_answered": False,
            "score": None,
            "question_snapshot": snapshot,
        }
    )
    assert unanswered.grading_status == "unanswered"

    pending = PracticeItemDetailResponse.model_validate(
        {
            "id": item_id,
            "order_index": 2,
            "is_answered": True,
            "score": None,
            "question_snapshot": snapshot,
        }
    )
    assert pending.grading_status == "pending_regrade"

    # 真实 0 分必须判定为 graded，不能被误判为 pending_regrade
    graded_zero = PracticeItemDetailResponse.model_validate(
        {
            "id": item_id,
            "order_index": 3,
            "is_answered": True,
            "score": 0.0,
            "question_snapshot": snapshot,
        }
    )
    assert graded_zero.grading_status == "graded"

    # 显式提供的 grading_status 必须被尊重，不被自动计算覆盖
    explicit = PracticeItemDetailResponse.model_validate(
        {
            "id": item_id,
            "order_index": 4,
            "is_answered": True,
            "score": 0.0,
            "grading_status": "pending_regrade",
            "question_snapshot": snapshot,
        }
    )
    assert explicit.grading_status == "pending_regrade"


def test_practice_detail_response_and_summary() -> None:
    """测试练习详情响应与摘要列表模型。"""
    practice_id = uuid.uuid4()
    material_id = uuid.uuid4()
    item_id = uuid.uuid4()
    now = datetime.now(UTC)

    detail = PracticeDetailResponse(
        practice_id=practice_id,
        title="网络协议专项测试",
        material_id=material_id,
        mode="random",
        status="in_progress",
        total_count=10,
        completed_count=3,
        created_at=now,
        items=[
            PracticeItemDetailResponse(
                attempt_item_id=item_id,
                question_id=uuid.uuid4(),
                order_index=1,
                status="answered",
                user_answer="A",
                time_spent_seconds=12,
                question_snapshot={
                    "stem": "题干",
                    "question_type": "single_choice",
                    "answer": "A",
                },
            )
        ],
    )
    assert detail.practice_id == practice_id
    assert detail.id == practice_id
    assert detail.total_count == 10
    assert detail.question_count == 10
    assert detail.completed_count == 3
    assert len(detail.items) == 1

    detail_reverse = PracticeDetailResponse.model_validate(
        {
            "id": practice_id,
            "title": "反向字段测试",
            "material_id": material_id,
            "status": "not_started",
            "question_count": 5,
        }
    )
    assert detail_reverse.practice_id == practice_id
    assert detail_reverse.total_count == 5

    summary = PracticeSummaryResponse(
        id=practice_id,
        material_id=material_id,
        title="网络协议专项测试",
        status="in_progress",
        question_count=10,
    )
    assert summary.id == practice_id
    assert summary.practice_id == practice_id
    assert summary.question_count == 10
    assert summary.total_count == 10

    summary_reverse = PracticeSummaryResponse.model_validate(
        {
            "practice_id": practice_id,
            "material_id": material_id,
            "title": "反向摘要",
            "status": "completed",
            "total_count": 8,
        }
    )
    assert summary_reverse.id == practice_id
    assert summary_reverse.question_count == 8

    list_response = PracticeListResponse(
        items=[summary],
        total=1,
        limit=20,
        offset=0,
    )
    assert list_response.total == 1
    assert len(list_response.items) == 1
    assert PracticeListItemResponse is PracticeSummaryResponse


def test_practice_detail_response_derives_completed_count() -> None:
    """测试详情响应根据 items 的 is_answered 自动统计已答题目数 (BUG-PRAC-011)."""
    practice_id = uuid.uuid4()
    material_id = uuid.uuid4()
    snapshot = {"stem": "题干", "question_type": "single_choice", "answer": "A"}

    detail = PracticeDetailResponse.model_validate(
        {
            "id": practice_id,
            "title": "已答统计测试",
            "material_id": material_id,
            "mode": "random",
            "status": "in_progress",
            "total_count": 3,
            "items": [
                {
                    "id": uuid.uuid4(),
                    "order_index": 1,
                    "is_answered": True,
                    "question_snapshot": snapshot,
                },
                {
                    "id": uuid.uuid4(),
                    "order_index": 2,
                    "is_answered": True,
                    "question_snapshot": snapshot,
                },
                {
                    "id": uuid.uuid4(),
                    "order_index": 3,
                    "is_answered": False,
                    "question_snapshot": snapshot,
                },
            ],
        }
    )

    assert detail.mode == "random"
    assert detail.completed_count == 2

    # An explicit non-zero completed_count is preserved (backward compatible)
    explicit = PracticeDetailResponse.model_validate(
        {
            "id": practice_id,
            "title": "显式统计",
            "material_id": material_id,
            "status": "in_progress",
            "total_count": 1,
            "completed_count": 3,
            "items": [
                {
                    "id": uuid.uuid4(),
                    "order_index": 1,
                    "is_answered": False,
                    "question_snapshot": snapshot,
                }
            ],
        }
    )
    assert explicit.completed_count == 3


def test_practice_detail_response_derives_time_elapsed_seconds() -> None:
    """测试详情响应由 items 聚合单题耗时得到 time_elapsed_seconds (BUG-PRAC-015)."""
    practice_id = uuid.uuid4()
    material_id = uuid.uuid4()
    snapshot = {"stem": "题干", "question_type": "short_answer", "answer": "参考答案"}

    detail = PracticeDetailResponse.model_validate(
        {
            "id": practice_id,
            "title": "累计耗时聚合测试",
            "material_id": material_id,
            "status": "in_progress",
            "total_count": 3,
            "items": [
                {
                    "id": uuid.uuid4(),
                    "order_index": 1,
                    "duration_seconds": 12,
                    "is_answered": True,
                    "question_snapshot": snapshot,
                },
                {
                    "id": uuid.uuid4(),
                    "order_index": 2,
                    "time_spent_seconds": 30,
                    "is_answered": True,
                    "question_snapshot": snapshot,
                },
                {
                    "id": uuid.uuid4(),
                    "order_index": 3,
                    "is_answered": False,
                    "question_snapshot": snapshot,
                },
            ],
        }
    )

    assert detail.time_elapsed_seconds == 42

    # An explicit value is preserved (backward compatible).
    explicit = PracticeDetailResponse.model_validate(
        {
            "id": practice_id,
            "title": "显式耗时",
            "material_id": material_id,
            "status": "in_progress",
            "total_count": 1,
            "time_elapsed_seconds": 99,
            "items": [
                {
                    "id": uuid.uuid4(),
                    "order_index": 1,
                    "duration_seconds": 5,
                    "question_snapshot": snapshot,
                }
            ],
        }
    )
    assert explicit.time_elapsed_seconds == 99


def test_practice_item_response_normalizes_legacy_repr_answer() -> None:
    """测试历史 Python repr 多选题作答被规范化为标准 JSON 字符串 (BUG-PRAC-016)."""
    item_id = uuid.uuid4()
    snapshot = {"stem": "题干", "question_type": "multiple_choice", "answer": "AB"}

    legacy = PracticeItemDetailResponse.model_validate(
        {
            "id": item_id,
            "order_index": 1,
            "user_answer": "['A', 'B']",
            "question_snapshot": snapshot,
        }
    )
    assert legacy.user_answer == '["A", "B"]'

    # A plain non-list string must be untouched.
    plain = PracticeItemDetailResponse.model_validate(
        {
            "id": item_id,
            "order_index": 2,
            "user_answer": "进程是资源分配单位",
            "question_snapshot": snapshot,
        }
    )
    assert plain.user_answer == "进程是资源分配单位"


def test_practice_create_response() -> None:
    """测试创建练习响应模型。"""
    practice_id = uuid.uuid4()
    material_id = uuid.uuid4()
    now = datetime.now(UTC)

    create_resp = PracticeCreateResponse(
        id=practice_id,
        material_id=material_id,
        title="随堂小测",
        status="not_started",
        question_count=5,
        created_at=now,
    )
    assert create_resp.id == practice_id
    assert create_resp.status == "not_started"
    assert create_resp.question_count == 5


def test_save_answer_request_payload_variants() -> None:
    """测试作答内容支持字符串、列表、字典及空值。"""
    q_id = uuid.uuid4()

    req_str = SaveAnswerRequest(
        question_id=q_id,
        user_answer="A",
        time_spent_seconds=10,
    )
    assert req_str.user_answer == "A"
    assert req_str.time_spent_seconds == 10
    assert req_str.duration_seconds == 10

    req_list = SaveAnswerRequest(
        question_id=q_id,
        user_answer=["A", "C"],
        time_spent_seconds=20,
    )
    assert req_list.user_answer == ["A", "C"]

    req_dict = SaveAnswerRequest(
        question_id=q_id,
        user_answer={"blank1": "TCP", "blank2": "UDP"},
        time_spent_seconds=30,
    )
    assert req_dict.user_answer == {"blank1": "TCP", "blank2": "UDP"}

    req_none = SaveAnswerRequest(
        question_id=q_id,
        user_answer=None,
        time_spent_seconds=0,
    )
    assert req_none.user_answer is None

    req_reverse_dur = SaveAnswerRequest.model_validate(
        {
            "question_id": q_id,
            "duration_seconds": 45,
        }
    )
    assert req_reverse_dur.time_spent_seconds == 45

    with pytest.raises(ValidationError):
        SaveAnswerRequest(
            question_id=q_id,
            user_answer="A",
            time_spent_seconds=-1,
        )

    assert PracticeSaveAnswerRequest is SaveAnswerRequest


def test_save_answer_response() -> None:
    """测试暂存作答响应模型。"""
    item_id = uuid.uuid4()
    now = datetime.now(UTC)

    resp = SaveAnswerResponse(
        attempt_item_id=item_id,
        status="answered",
        updated_at=now,
        duration_seconds=15,
    )
    assert resp.attempt_item_id == item_id
    assert resp.status == "answered"
    assert resp.updated_at == now
    assert resp.time_spent_seconds == 15

    resp_reverse = SaveAnswerResponse.model_validate(
        {
            "attempt_item_id": item_id,
            "time_spent_seconds": 30,
        }
    )
    assert resp_reverse.duration_seconds == 30
    assert PracticeSaveAnswerResponse is SaveAnswerResponse


def test_practice_status_response() -> None:
    """测试练习暂停/恢复状态响应模型。"""
    practice_id = uuid.uuid4()
    resp = PracticeStatusResponse(
        practice_id=practice_id,
        status="paused",
        message="练习已暂停计时",
    )
    assert resp.practice_id == practice_id
    assert resp.id == practice_id
    assert resp.status == "paused"
    assert resp.message == "练习已暂停计时"

    resp_reverse = PracticeStatusResponse.model_validate(
        {
            "id": practice_id,
            "status": "in_progress",
        }
    )
    assert resp_reverse.practice_id == practice_id
    assert PracticeStatusActionResponse is PracticeStatusResponse


def test_submit_practice_request_and_response() -> None:
    """测试交卷请求入参与交卷调度响应。"""
    practice_id = uuid.uuid4()

    submit_req = PracticeSubmitRequest(confirm_unanswered=True)
    assert submit_req.confirm_unanswered is True

    submit_resp = SubmitPracticeResponse(
        practice_id=practice_id,
        status="completed",
        message="答卷提交成功，判题队列已受理",
        uncompleted_count=0,
        is_idempotent_replay=False,
    )
    assert submit_resp.practice_id == practice_id
    assert submit_resp.status == "completed"
    assert submit_resp.uncompleted_count == 0
    assert submit_resp.unanswered_count == 0
    assert submit_resp.is_idempotent_replay is False

    submit_reverse = SubmitPracticeResponse.model_validate(
        {
            "practice_id": practice_id,
            "status": "partially_graded",
            "unanswered_count": 2,
        }
    )
    assert submit_reverse.uncompleted_count == 2
    assert PracticeSubmitResponse is SubmitPracticeResponse


def test_source_snippet_dto_roundtrip() -> None:
    """测试来源切片摘要 DTO 字段解析 (BUG-GRADE-004)。"""
    snippet_id = uuid.uuid4()
    snippet = SourceSnippetDTO(
        id=snippet_id,
        chapter_title="第 3 章 树与二叉树",
        page_index=42,
        snippet_content="二叉树的中序遍历先左后根再右。",
    )
    assert snippet.id == snippet_id
    assert snippet.chapter_title == "第 3 章 树与二叉树"
    assert snippet.page_index == 42
    assert snippet.snippet_content == "二叉树的中序遍历先左后根再右。"

    defaulted = SourceSnippetDTO()
    assert defaulted.chapter_title == ""
    assert defaulted.page_index == 1
    assert defaulted.snippet_content == ""


def test_practice_item_response_merges_final_grading_keywords() -> None:
    """测试作答项 DTO 合并生效判题记录的命中/遗漏要点 (BUG-GRADE-003)。"""

    def snapshot_field(snapshot: object, key: str) -> object:
        if isinstance(snapshot, dict):
            return snapshot.get(key)
        return getattr(snapshot, key, None)

    item_id = uuid.uuid4()
    final_record = SimpleNamespace(
        is_final=True,
        hit_keywords=["递归回溯"],
        missing_keywords=["基准元素", "子数组长度"],
    )
    stale_record = SimpleNamespace(
        is_final=False,
        hit_keywords=[],
        missing_keywords=[],
    )
    orm_item = SimpleNamespace(
        id=item_id,
        order_index=1,
        is_answered=True,
        score=0.5,
        max_score=5.0,
        user_answer="采用递归回溯求解",
        grading_records=[stale_record, final_record],
        question_snapshot={
            "stem": "请阐述快速排序的递归基设计思想。",
            "question_type": "short_answer",
            "answer": "当子数组长度小于等于 1 时直接返回。",
        },
    )

    response = PracticeItemDetailResponse.model_validate(orm_item)

    assert response.hit_keywords == ["递归回溯"]
    assert response.missing_keywords == ["基准元素", "子数组长度"]
    # 顶层与嵌套快照必须双向同步，保证前端二级兜底可读
    snapshot = response.question_snapshot
    assert snapshot_field(snapshot, "hit_keywords") == ["递归回溯"]
    assert snapshot_field(snapshot, "missing_keywords") == ["基准元素", "子数组长度"]

    # 显式提供的要点不得被判题记录覆盖 (向后兼容)
    explicit = PracticeItemDetailResponse.model_validate(
        {
            "attempt_item_id": item_id,
            "order_index": 2,
            "hit_keywords": ["显式命中"],
            "missing_keywords": ["显式遗漏"],
            "grading_records": [final_record],
            "question_snapshot": {
                "stem": "题干",
                "question_type": "short_answer",
                "answer": "参考答案",
            },
        }
    )
    assert explicit.hit_keywords == ["显式命中"]
    assert explicit.missing_keywords == ["显式遗漏"]


def test_practice_item_response_propagates_source_snippet() -> None:
    """测试作答项 DTO 透传来源切片对象至顶层与嵌套快照 (BUG-GRADE-004)."""
    item_id = uuid.uuid4()
    snippet_id = uuid.uuid4()
    snippet_payload = {
        "id": str(snippet_id),
        "chapter_title": "第 5 章 树形数据结构",
        "page_index": 108,
        "snippet_content": "AVL 树是一棵自平衡二叉搜索树。",
    }

    response = PracticeItemDetailResponse.model_validate(
        {
            "attempt_item_id": item_id,
            "order_index": 1,
            "source_snippet": snippet_payload,
            "question_snapshot": {
                "stem": "AVL 树高度差？",
                "question_type": "single_choice",
                "answer": "1",
                "source_snippet_id": str(snippet_id),
            },
        }
    )

    assert response.source_snippet is not None
    resolved = (
        response.source_snippet
        if isinstance(response.source_snippet, SourceSnippetDTO)
        else SourceSnippetDTO.model_validate(response.source_snippet)
    )
    assert resolved.chapter_title == "第 5 章 树形数据结构"
    assert resolved.page_index == 108
    assert resolved.snippet_content == "AVL 树是一棵自平衡二叉搜索树。"
    nested_snapshot = response.question_snapshot
    if isinstance(nested_snapshot, dict):
        assert nested_snapshot.get("source_snippet") is not None
    else:
        assert nested_snapshot.source_snippet is not None

    # 默认缺省时必须为 None，不破坏历史响应
    fallback = PracticeItemDetailResponse.model_validate(
        {
            "attempt_item_id": item_id,
            "order_index": 2,
            "question_snapshot": {
                "stem": "题干",
                "question_type": "single_choice",
                "answer": "A",
            },
        }
    )
    assert fallback.source_snippet is None
    assert fallback.hit_keywords == []
    assert fallback.missing_keywords == []
