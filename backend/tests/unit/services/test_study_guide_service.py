"""Unit tests for Stage 2 study guide lazy generation, singleflight lock, prewarm & APIs."""

import threading
import time
import uuid
from collections.abc import Generator, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import worker
from app.api.deps.auth import get_current_user
from app.api.deps.knowledge import get_knowledge_service
from app.api.v1 import api_v1_router
from app.core.errors import AppError, KnowledgeNotFoundError, LLMResponseFormatError
from app.integrations.embedding import FakeEmbeddingAdapter
from app.integrations.llm.protocol import (
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
)
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.queue.protocol import REGISTERED_TASK_NAMES
from app.integrations.queue.rq_adapter import RQQueueAdapter
from app.models.base import Base
from app.models.knowledge import KnowledgePoint, KnowledgePointSnippet
from app.models.material import Material, MaterialSnippet, MaterialVersion, ParseStatus
from app.models.user import User
from app.schemas.knowledge import StudyGuideContent
from app.services._study_guide import _acquire_study_guide_lock, _release_study_guide_lock
from app.services.knowledge import KnowledgeService

T = TypeVar("T", bound=BaseModel)


def _sample_guide(title: str = "支持向量机间隔最大化") -> StudyGuideContent:
    return StudyGuideContent.model_validate(
        {
            "schema_version": 1,
            "exam_positioning": f"围绕{title}考察推导与计算题。",
            "core_definition": "最大几何间隔旨在最大化样本到超平面的最小距离。",
            "symbol_table": [
                {"symbol": "$w$", "meaning": "超平面法向量", "note": "$w \\in \\mathbb{R}^d$"}
            ],
            "key_formulas": ["$$\\min_{w,b} \\frac{1}{2}\\|w\\|^2$$"],
            "derivation_steps": [
                {
                    "step_title": "第 1 步：归一化函数间隔",
                    "formula": "$$y_i(w^T x_i + b) \\ge 1$$",
                    "explanation": "利用缩放不变性令最小函数间隔为 1。",
                }
            ],
            "worked_examples": [
                {
                    "title": "典型例题 1：二维线性可分超平面求解",
                    "question_type": "计算题",
                    "problem": "已知正例 $(3,3),(4,3)$ 与负例 $(1,1)$，求最大间隔超平面。",
                    "solution_idea": "利用几何对称性与 KKT 条件求解。",
                    "solution_steps": ["1. 写出约束条件", "2. 联立求解 $w, b$"],
                    "final_answer": "$\\frac{1}{2}x_1 + \\frac{1}{2}x_2 - 2 = 0$",
                }
            ],
            "comparisons": [
                {
                    "target_concept": "软间隔 SVM",
                    "similarities": "均最大化分类间隔。",
                    "differences": "硬间隔不允许误分类样本。",
                    "exam_distinction": "看是否存在松弛变量 $\\xi_i$。",
                }
            ],
            "pitfalls": [
                {
                    "mistake": "把函数间隔直接当几何间隔优化。",
                    "why_wrong": "未除以 $\\|w\\|$ 会导致缩放作弊。",
                    "correction": "固定函数间隔为 1 后最小化 $\\|w\\|^2$。",
                }
            ],
            "memory_anchors": ["先定函数间隔为 1，再最小化法向量模平方。"],
        }
    )


class _StudyGuideStubLLM(LLMProtocol):
    """可控延迟与思考模型降级测试用的 StubLLM。"""

    def __init__(
        self,
        *,
        guide: StudyGuideContent | None = None,
        delay_seconds: float = 0.0,
        raise_structured_format_error: bool = False,
        fallback_raw_text: str | None = None,
        fail_kp_keyword: str | None = None,
        on_call_check: Any = None,
    ) -> None:
        self.guide = guide or _sample_guide()
        self.delay_seconds = delay_seconds
        self.raise_structured_format_error = raise_structured_format_error
        self.fallback_raw_text = fallback_raw_text
        self.fail_kp_keyword = fail_kp_keyword
        self.on_call_check = on_call_check
        self.structured_calls: list[LLMOptions | None] = []
        self.generate_calls: int = 0
        self.received_messages: list[Sequence[LLMMessage]] = []

    def generate(
        self,
        messages: Sequence[LLMMessage],
        options: LLMOptions | None = None,
    ) -> LLMResponse:
        self.generate_calls += 1
        if self.fail_kp_keyword and any(
            f"【目标考点】{self.fail_kp_keyword}" in m.content for m in messages
        ):
            raise LLMResponseFormatError("simulated kp fallback failure")
        text = self.fallback_raw_text or self.guide.model_dump_json()
        return LLMResponse(content=text, usage=LLMUsage(), model="deepseek-flash")

    def generate_structured(
        self,
        messages: Sequence[LLMMessage],
        response_model: type[T],
        options: LLMOptions | None = None,
    ) -> tuple[T, LLMResponse]:
        if self.on_call_check is not None:
            self.on_call_check()
        self.structured_calls.append(options)
        self.received_messages.append(messages)
        if self.delay_seconds > 0:
            time.sleep(self.delay_seconds)
        if self.fail_kp_keyword and any(
            f"【目标考点】{self.fail_kp_keyword}" in m.content for m in messages
        ):
            raise LLMResponseFormatError("simulated kp failure")
        if self.raise_structured_format_error:
            raise LLMResponseFormatError("simulated thinking format fallback")
        return response_model.model_validate(self.guide.model_dump()), LLMResponse(
            content=self.guide.model_dump_json(),
            usage=LLMUsage(),
            model="deepseek-flash",
        )


class _FakeRedis:
    """线程安全的轻量内存 Redis 替身，模拟 SET NX EX、Lua 释放与 Hash 读写。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kv: dict[str, str] = {}
        self._hashes: dict[str, dict[str, str]] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        _ = ex
        with self._lock:
            if nx and key in self._kv:
                return False
            self._kv[key] = value
            return True

    def get(self, key: str) -> bytes | None:
        with self._lock:
            val = self._kv.get(key)
            return val.encode("utf-8") if val is not None else None

    def exists(self, key: str) -> int:
        with self._lock:
            return 1 if key in self._kv else 0

    def delete(self, key: str) -> int:
        with self._lock:
            return 1 if self._kv.pop(key, None) is not None else 0

    def eval(self, _script: str, _numkeys: int, key: str, token: str) -> int:
        with self._lock:
            if self._kv.get(key) == token:
                self._kv.pop(key, None)
                return 1
            return 0

    def hset(self, key: str, mapping: dict[str, str]) -> int:
        with self._lock:
            bucket = self._hashes.setdefault(key, {})
            bucket.update({str(k): str(v) for k, v in mapping.items()})
            return len(mapping)

    def hgetall(self, key: str) -> dict[bytes, bytes]:
        with self._lock:
            bucket = self._hashes.get(key, {})
            return {k.encode("utf-8"): v.encode("utf-8") for k, v in bucket.items()}

    def expire(self, _key: str, _ttl: int) -> bool:
        return True


def _seed_study_guide_material(session: Session, kp_count: int = 2) -> dict[str, Any]:
    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    material = Material(
        id=material_id,
        user_id=user_id,
        title="机器学习导论.pdf",
        file_format="pdf",
        file_size=4096,
    )
    version = MaterialVersion(
        id=version_id,
        user_id=user_id,
        material_id=material_id,
        version_number=1,
        storage_key="test/ml_intro.pdf",
        content_hash="ml_intro_hash",
        parse_status=ParseStatus.READY.value,
    )
    parent = KnowledgePoint(
        id=uuid.uuid4(),
        user_id=user_id,
        material_id=material_id,
        version_id=version_id,
        name="支持向量机模块",
        description="模块总览",
        level=1,
        sort_order=0,
        batch_id="b1",
    )
    session.add_all([material, version, parent])
    session.flush()

    kps: list[KnowledgePoint] = []
    for i in range(kp_count):
        snip = MaterialSnippet(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            snippet_index=i,
            content=f"支持向量机考点{i}的详细教材原文定义与推导步骤内容。",
            char_length=40,
            start_offset=i * 40,
            end_offset=(i + 1) * 40,
            chapter_title="第五章 支持向量机",
            source_info={"page_number": i + 5},
        )
        kp = KnowledgePoint(
            id=uuid.uuid4(),
            user_id=user_id,
            material_id=material_id,
            version_id=version_id,
            parent_id=parent.id,
            name=f"考点_{i}",
            description=f"考点_{i} 摘要",
            level=2,
            sort_order=i + 1,
            batch_id="b1",
        )
        session.add_all([snip, kp])
        session.flush()
        session.add(
            KnowledgePointSnippet(
                user_id=user_id,
                knowledge_point_id=kp.id,
                snippet_id=snip.id,
            )
        )
        kps.append(kp)
    session.commit()
    return {
        "user_id": user_id,
        "material_id": material_id,
        "version_id": version_id,
        "parent_id": parent.id,
        "kps": kps,
    }


@pytest.fixture
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


def test_study_guide_schema_coerces_null_lists() -> None:
    """StudyGuideContent 容错将思考模型输出的 null 列表归一化为空列表。"""
    parsed = StudyGuideContent.model_validate(
        {
            "schema_version": None,
            "exam_positioning": "定位",
            "core_definition": "定义",
            "symbol_table": None,
            "key_formulas": None,
            "derivation_steps": None,
            "worked_examples": None,
            "comparisons": None,
            "pitfalls": None,
            "memory_anchors": None,
        }
    )
    assert parsed.schema_version == 1
    assert parsed.symbol_table == []
    assert parsed.worked_examples == []


def test_generate_study_guide_releases_transaction_caches_and_supports_thinking_fallback(
    session_factory: sessionmaker[Session],
) -> None:
    """验证短事务释放、max_tokens=6144/tool_choice='auto'、永久缓存与思考模型降级解析。"""
    with session_factory() as session:
        env = _seed_study_guide_material(session, kp_count=2)
        kp_id = env["kps"][0].id
        user_id = env["user_id"]

        tx_states_during_llm: list[bool] = []

        def _check_tx() -> None:
            tx_states_during_llm.append(session.in_transaction())

        llm = _StudyGuideStubLLM(on_call_check=_check_tx)
        redis = _FakeRedis()
        service = KnowledgeService(session, llm, FakeEmbeddingAdapter(), redis_client=redis)

        # 未生成前 GET -> empty
        empty_res = service.get_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert empty_res["status"] == "empty"
        assert empty_res["study_guide"] is None

        # 首次生成 -> 调用 LLM，事务已释放，写回缓存
        gen_res = service.generate_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert gen_res["status"] == "ready"
        assert gen_res["study_guide"] is not None
        assert tx_states_during_llm == [False]
        opts = llm.structured_calls[0]
        assert opts is not None
        assert opts.max_tokens == 16384
        assert opts.temperature == 0.25
        assert opts.timeout == 55.0
        assert opts.tool_choice == "auto"
        assert "考点_1" in llm.received_messages[0][-1].content
        assert redis.exists(f"zhilian:study_guide:lock:{kp_id}") == 0

        # 再次调用 force=False -> 直接命中永久缓存，不调用 LLM
        cached_res = service.generate_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert cached_res["status"] == "ready"
        assert len(llm.structured_calls) == 1

        # 思考模型降级解析容错：<think>...</think> + ```json ... ``` + force=True
        sample_json = _sample_guide("降级恢复").model_dump_json()
        fallback_llm = _StudyGuideStubLLM(
            raise_structured_format_error=True,
            fallback_raw_text=f"<think>推理过程...</think>\n```json\n{sample_json}\n```",
        )
        fallback_svc = KnowledgeService(
            session, fallback_llm, FakeEmbeddingAdapter(), redis_client=redis
        )
        forced_res = fallback_svc.generate_study_guide(
            knowledge_point_id=kp_id, user_id=user_id, force=True
        )
        assert forced_res["status"] == "ready"
        assert fallback_llm.generate_calls == 1
        assert "降级恢复" in forced_res["study_guide"].exam_positioning

        # 跨租户访问阻断
        with pytest.raises(KnowledgeNotFoundError):
            service.get_study_guide(knowledge_point_id=kp_id, user_id=uuid.uuid4())


def test_singleflight_lock_contention_shares_result_and_times_out_to_generating(
    tmp_path: Any,
) -> None:
    """验证单飞锁并发去重：等待方复用首飞落库结果（仅 1 次 LLM），超时返回 generating (202)。"""
    db_file = tmp_path / "singleflight.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 15.0},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    try:
        with factory() as seed_sess:
            env = _seed_study_guide_material(seed_sess, kp_count=1)
        kp_id = env["kps"][0].id
        user_id = env["user_id"]
        redis = _FakeRedis()

        # 1. 抢锁超时返回 generating
        held_lock_id = uuid.uuid4().hex
        assert _acquire_study_guide_lock(kp_id, held_lock_id, redis_client=redis) is True
        with factory() as s_timeout:
            svc_timeout = KnowledgeService(
                s_timeout, _StudyGuideStubLLM(), FakeEmbeddingAdapter(), redis_client=redis
            )
            status_during_lock = svc_timeout.get_study_guide(
                knowledge_point_id=kp_id, user_id=user_id
            )
            assert status_during_lock["status"] == "generating"

            timeout_res = svc_timeout.generate_study_guide(
                knowledge_point_id=kp_id,
                user_id=user_id,
                lock_wait_seconds=0.05,
                poll_interval_seconds=0.02,
            )
            assert timeout_res["status"] == "generating"
            assert timeout_res["study_guide"] is None
        _release_study_guide_lock(kp_id, held_lock_id, redis_client=redis)

        # 2. 两线程并发触发 -> 首飞执行 LLM，次飞等待落库后返回 ready，总共只调 1 次 LLM
        llm = _StudyGuideStubLLM(delay_seconds=0.12)
        results: list[dict[str, Any]] = []

        def _worker_call(wait_s: float) -> None:
            with factory() as sess:
                svc = KnowledgeService(sess, llm, FakeEmbeddingAdapter(), redis_client=redis)
                res = svc.generate_study_guide(
                    knowledge_point_id=kp_id,
                    user_id=user_id,
                    lock_wait_seconds=wait_s,
                    poll_interval_seconds=0.02,
                )
                results.append(res)

        t1 = threading.Thread(target=_worker_call, args=(1.0,))
        t2 = threading.Thread(target=_worker_call, args=(1.0,))
        t1.start()
        time.sleep(0.03)
        t2.start()
        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        assert len(results) == 2
        assert all(r["status"] == "ready" for r in results)
        assert len(llm.structured_calls) == 1
    finally:
        engine.dispose()


def test_prewarm_enqueue_worker_and_partial_failure(
    session_factory: sessionmaker[Session],
) -> None:
    """验证 prewarm 入队、REGISTERED_TASK_NAMES 注册、逐考点执行与单点失败容错。"""
    assert "prewarm_study_guides" in REGISTERED_TASK_NAMES
    assert "prewarm_study_guides" in worker.REGISTERED_TASKS

    with session_factory() as session:
        env = _seed_study_guide_material(session, kp_count=2)
        material_id = env["material_id"]
        version_id = env["version_id"]
        user_id = env["user_id"]

        queue = MemoryQueueAdapter()
        redis = _FakeRedis()
        llm = _StudyGuideStubLLM(fail_kp_keyword="考点_1")
        service = KnowledgeService(
            session, llm, FakeEmbeddingAdapter(), queue=queue, redis_client=redis
        )

        # 初始状态 idle
        init_status = service.get_study_guide_prewarm_status(
            material_id=material_id, user_id=user_id
        )
        assert init_status["status"] == "idle"
        assert init_status["total_kps"] == 2
        assert init_status["ready_kps"] == 0

        # 发起 prewarm -> 入普通队列
        prewarm_res = service.prewarm_study_guides(material_id=material_id, user_id=user_id)
        assert prewarm_res["status"] == "queued"
        assert len(queue._queue) == 1
        assert queue._queue[0].task_name == "prewarm_study_guides"
        assert queue._queue[0].priority == 0

        # 验证 RQQueueAdapter 白名单放行
        rq_client = MagicMock()
        rq_adapter = RQQueueAdapter(redis_client=rq_client)
        assert rq_adapter._client is rq_client

        # 执行 Worker 预热：考点_0 成功，考点_1 失败 -> partial_failed
        run_res = service.run_study_guide_prewarm(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )
        assert run_res["status"] == "partial_failed"
        assert run_res["total_kps"] == 2
        assert run_res["ready_kps"] == 1
        assert run_res["failed_kps"] == 1

        # 补跑成功 -> completed，再次 prewarm 不入队
        llm_ok = _StudyGuideStubLLM()
        svc_ok = KnowledgeService(
            session, llm_ok, FakeEmbeddingAdapter(), queue=queue, redis_client=redis
        )
        run_ok = svc_ok.run_study_guide_prewarm(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )
        assert run_ok["status"] == "completed"
        assert run_ok["ready_kps"] == 2
        assert len(llm_ok.structured_calls) == 1  # 仅补跑未就绪的考点_1

        already_done = svc_ok.prewarm_study_guides(material_id=material_id, user_id=user_id)
        assert already_done["status"] == "completed"
        assert len(queue._queue) == 1  # 未重复入队


def test_worker_dispatches_prewarm_study_guides(monkeypatch: pytest.MonkeyPatch) -> None:
    """验证 worker.py 分发 prewarm_study_guides 任务及终态失败回调。"""
    fake_session = MagicMock()
    fake_knowledge_svc = MagicMock()
    fake_container = MagicMock()
    fake_container.providers = MagicMock(queue=None, idempotency=None)
    fake_container.get_session.return_value.__enter__.return_value = fake_session
    fake_container.get_session.return_value.__exit__.return_value = False
    fake_container.create_knowledge_service.return_value = fake_knowledge_svc
    monkeypatch.setattr(worker.AppContainer, "create", classmethod(lambda cls: fake_container))

    user_id = uuid.uuid4()
    material_id = uuid.uuid4()
    version_id = uuid.uuid4()
    worker.execute_registered_task(
        "prewarm_study_guides",
        {
            "material_id": str(material_id),
            "version_id": str(version_id),
            "user_id": str(user_id),
            "force": "true",
        },
        str(user_id),
    )
    fake_knowledge_svc.run_study_guide_prewarm.assert_called_once_with(
        material_id=material_id,
        version_id=version_id,
        user_id=user_id,
        force=True,
        redis_client=None,
    )
    worker.shutdown_worker_container()


@pytest.mark.asyncio
async def test_study_guide_api_endpoints_contracts() -> None:
    """验证 4 个 Stage 2 HTTP 端点契约（200/202 状态码与响应结构）。"""
    app = FastAPI()

    @app.exception_handler(AppError)
    async def _err(_req: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.include_router(api_v1_router)

    user = User(id=uuid.uuid4(), nickname="u", is_active=True, token_version=1)
    mock_svc = MagicMock()
    kp_id = uuid.uuid4()
    mat_id = uuid.uuid4()
    ver_id = uuid.uuid4()
    now = datetime.now(UTC)
    guide = _sample_guide()

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_svc

    mock_svc.get_study_guide.return_value = {
        "knowledge_point_id": kp_id,
        "status": "empty",
        "study_guide": None,
        "generated_at": None,
    }
    mock_svc.generate_study_guide.side_effect = [
        {
            "knowledge_point_id": kp_id,
            "status": "generating",
            "study_guide": None,
            "generated_at": None,
        },
        {
            "knowledge_point_id": kp_id,
            "status": "ready",
            "study_guide": guide,
            "generated_at": now,
        },
    ]
    mock_svc.prewarm_study_guides.return_value = {
        "material_id": mat_id,
        "version_id": ver_id,
        "status": "queued",
        "total_kps": 8,
        "ready_kps": 2,
    }
    mock_svc.get_study_guide_prewarm_status.return_value = {
        "material_id": mat_id,
        "version_id": ver_id,
        "status": "running",
        "total_kps": 8,
        "ready_kps": 4,
        "failed_kps": 0,
        "current_kp_name": "核技巧",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_get = await client.get(f"/api/v1/knowledge/{kp_id}/study-guide")
        assert r_get.status_code == 200
        assert r_get.json()["status"] == "empty"

        r_gen_202 = await client.post(
            f"/api/v1/knowledge/{kp_id}/study-guide/generate", json={"force": False}
        )
        assert r_gen_202.status_code == 202
        assert r_gen_202.json()["status"] == "generating"

        r_gen_200 = await client.post(
            f"/api/v1/knowledge/{kp_id}/study-guide/generate", json={"force": True}
        )
        assert r_gen_200.status_code == 200
        assert r_gen_200.json()["status"] == "ready"
        assert r_gen_200.json()["study_guide"]["schema_version"] == 1

        r_prewarm = await client.post(
            f"/api/v1/materials/{mat_id}/study-guides/prewarm",
            json={"version_id": str(ver_id), "force": False},
        )
        assert r_prewarm.status_code == 202
        assert r_prewarm.json()["status"] == "queued"

        r_status = await client.get(
            f"/api/v1/materials/{mat_id}/study-guides/status?version_id={ver_id}"
        )
        assert r_status.status_code == 200
        assert r_status.json()["current_kp_name"] == "核技巧"
        assert r_status.json()["ready_kps"] == 4


class _AsyncRQStubQueue(MemoryQueueAdapter):
    """Stub queue mimicking RQQueueAdapter.supports_async_worker=True."""

    def __init__(self, *, fail_enqueue: bool = False) -> None:
        super().__init__()
        self.fail_enqueue = fail_enqueue

    @property
    def supports_async_worker(self) -> bool:
        return True

    def enqueue(
        self,
        task_name: str,
        payload: dict[str, Any],
        user_id: str,
        *,
        task_id: str | None = None,
        delay_seconds: int = 0,
        priority: int = 0,
    ) -> str:
        if self.fail_enqueue:
            raise RuntimeError("redis queue down")
        return super().enqueue(
            task_name,
            payload,
            user_id,
            task_id=task_id,
            delay_seconds=delay_seconds,
            priority=priority,
        )


def test_async_high_priority_study_guide_enqueue_worker_and_failure_state(
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证单考点精讲异步高优入队 (priority=1)、Worker 执行、失败态写回与单飞防重。"""
    from types import SimpleNamespace

    from app.schemas.knowledge import StudyGuideResponse
    from app.services._study_guide import (
        _build_study_guide_messages,
        clear_study_guide_error,
        get_study_guide_error,
        set_study_guide_error,
    )

    assert "generate_study_guide" in REGISTERED_TASK_NAMES
    assert "generate_study_guide" in worker.REGISTERED_TASKS

    # Schema 支持 failed + error_message
    failed_schema = StudyGuideResponse(
        knowledge_point_id=uuid.uuid4(),
        status="failed",
        error_message="生成超时，请重试",
    )
    assert failed_schema.status == "failed"
    assert failed_schema.error_message == "生成超时，请重试"

    # Prompt 提速预算校验
    prompt_msgs = _build_study_guide_messages(
        kp_name="支持向量机",
        kp_description="间隔最大化",
        kp_structured=None,
        snippet_items=[(0, "第 1 页", "原文内容")],
        sibling_names=["软间隔"],
    )
    assert "800~1,500" in prompt_msgs[0].content
    assert "1 道高含金量典型例题" in prompt_msgs[0].content
    assert "3~5 步" in prompt_msgs[0].content

    with session_factory() as session:
        env = _seed_study_guide_material(session, kp_count=1)
        kp_id = env["kps"][0].id
        user_id = env["user_id"]
        redis = _FakeRedis()

        # 1. 入队异常时立即释放锁并抛错
        broken_queue = _AsyncRQStubQueue(fail_enqueue=True)
        svc_broken = KnowledgeService(
            session,
            _StudyGuideStubLLM(),
            FakeEmbeddingAdapter(),
            queue=broken_queue,
            redis_client=redis,
        )
        with pytest.raises(RuntimeError, match="redis queue down"):
            svc_broken.generate_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert redis.exists(f"zhilian:study_guide:lock:{kp_id}") == 0

        # 2. 正常异步入队：返回 generating，投递 priority=1，重复触发单飞不重复入队
        async_queue = _AsyncRQStubQueue()
        llm = _StudyGuideStubLLM()
        set_study_guide_error(kp_id, "旧失败摘要", redis_client=redis)
        svc = KnowledgeService(
            session, llm, FakeEmbeddingAdapter(), queue=async_queue, redis_client=redis
        )
        res_enqueue = svc.generate_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert res_enqueue["status"] == "generating"
        assert res_enqueue["error_message"] is None
        assert len(async_queue._queue) == 1
        queued_msg = async_queue._queue[0]
        assert queued_msg.task_name == "generate_study_guide"
        assert queued_msg.priority == 1
        assert queued_msg.payload["knowledge_point_id"] == str(kp_id)
        assert queued_msg.payload["user_id"] == str(user_id)
        assert queued_msg.payload["force"] == "false"
        assert queued_msg.payload["lock_token"]
        assert get_study_guide_error(kp_id, redis_client=redis) is None
        assert len(llm.structured_calls) == 0

        # 并发双击 -> 单飞不重复入队
        res_dup = svc.generate_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert res_dup["status"] == "generating"
        assert len(async_queue._queue) == 1

        # GET 在持锁期间返回 generating
        status_locked = svc.get_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert status_locked["status"] == "generating"

        # 3. Worker 失败分支：记录安全错误摘要并释放锁，GET 返回 failed
        failing_llm = _StudyGuideStubLLM(fail_kp_keyword="考点_0")
        failing_svc = KnowledgeService(
            session, failing_llm, FakeEmbeddingAdapter(), queue=async_queue, redis_client=redis
        )
        with pytest.raises(LLMResponseFormatError):
            failing_svc.run_study_guide_generation(
                knowledge_point_id=kp_id,
                user_id=user_id,
                lock_token=queued_msg.payload["lock_token"],
            )
        assert redis.exists(f"zhilian:study_guide:lock:{kp_id}") == 0
        failed_get = svc.get_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert failed_get["status"] == "failed"
        assert failed_get["error_message"]

        # 4. Worker 成功分支：清除错误态，落库 study_guide，释放锁，GET 与 POST 均秒返 ready
        res_retry = svc.generate_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert res_retry["status"] == "generating"
        assert len(async_queue._queue) == 2
        retry_token = async_queue._queue[1].payload["lock_token"]
        run_res = svc.run_study_guide_generation(
            knowledge_point_id=kp_id,
            user_id=user_id,
            lock_token=retry_token,
        )
        assert run_res["status"] == "ready"
        assert redis.exists(f"zhilian:study_guide:lock:{kp_id}") == 0
        assert get_study_guide_error(kp_id, redis_client=redis) is None
        ready_res = svc.generate_study_guide(knowledge_point_id=kp_id, user_id=user_id)
        assert ready_res["status"] == "ready"
        assert len(async_queue._queue) == 2

    # 5. worker.execute_registered_task & handle_job_terminal_failure
    fake_session = MagicMock()
    fake_knowledge_svc = MagicMock()
    fake_redis = _FakeRedis()
    fake_container = MagicMock()
    fake_container.providers = MagicMock(
        queue=SimpleNamespace(_client=fake_redis),
        idempotency=None,
    )
    fake_container.get_session.return_value.__enter__.return_value = fake_session
    fake_container.get_session.return_value.__exit__.return_value = False
    fake_container.create_knowledge_service.return_value = fake_knowledge_svc
    monkeypatch.setattr(worker.AppContainer, "create", classmethod(lambda cls: fake_container))

    w_user = uuid.uuid4()
    w_kp = uuid.uuid4()
    worker_lock_val = uuid.uuid4().hex
    worker.execute_registered_task(
        "generate_study_guide",
        {
            "knowledge_point_id": str(w_kp),
            "user_id": str(w_user),
            "force": "true",
            "lock_token": worker_lock_val,
        },
        str(w_user),
    )
    fake_knowledge_svc.run_study_guide_generation.assert_called_once_with(
        knowledge_point_id=w_kp,
        user_id=w_user,
        force=True,
        lock_token=worker_lock_val,
        redis_client=fake_redis,
    )

    term_lock_val = uuid.uuid4().hex
    assert _acquire_study_guide_lock(w_kp, term_lock_val, redis_client=fake_redis) is True
    terminal_job = SimpleNamespace(
        id="sg-term-1",
        args=(
            "generate_study_guide",
            {
                "knowledge_point_id": str(w_kp),
                "user_id": str(w_user),
                "lock_token": term_lock_val,
            },
            str(w_user),
        ),
        meta={},
        should_retry=False,
    )
    worker.handle_job_terminal_failure(
        terminal_job,
        MagicMock(),
        TimeoutError,
        TimeoutError("llm timeout"),
        None,  # type: ignore[arg-type]
    )
    assert fake_redis.exists(f"zhilian:study_guide:lock:{w_kp}") == 0
    assert get_study_guide_error(w_kp, redis_client=fake_redis) is not None
    clear_study_guide_error(w_kp, redis_client=fake_redis)
    worker.shutdown_worker_container()


@pytest.mark.asyncio
async def test_study_guide_api_returns_failed_status_and_forwards_queue() -> None:
    """验证 GET /study-guide 返回 failed+error_message 且 POST /generate 透传 queue。"""
    app = FastAPI()
    app.include_router(api_v1_router)

    user = User(id=uuid.uuid4(), nickname="u", is_active=True, token_version=1)
    kp_id = uuid.uuid4()
    mock_svc = MagicMock()
    mock_queue = _AsyncRQStubQueue()
    mock_container = MagicMock()
    mock_container.providers = MagicMock(queue=mock_queue, idempotency=None)
    app.state.container = mock_container

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_knowledge_service] = lambda: mock_svc

    mock_svc.get_study_guide.return_value = {
        "knowledge_point_id": kp_id,
        "status": "failed",
        "study_guide": None,
        "generated_at": None,
        "error_message": "考前精讲生成超时，请点击重新生成重试",
    }
    mock_svc.generate_study_guide.return_value = {
        "knowledge_point_id": kp_id,
        "status": "generating",
        "study_guide": None,
        "generated_at": None,
        "error_message": None,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r_failed = await client.get(f"/api/v1/knowledge/{kp_id}/study-guide")
        assert r_failed.status_code == 200
        assert r_failed.json()["status"] == "failed"
        assert r_failed.json()["error_message"] == "考前精讲生成超时，请点击重新生成重试"

        r_gen = await client.post(
            f"/api/v1/knowledge/{kp_id}/study-guide/generate",
            json={"force": False},
        )
        assert r_gen.status_code == 202
        assert mock_svc.generate_study_guide.call_args.kwargs["queue"] is mock_queue
