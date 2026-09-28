"""P0 端到端全链路闭环集成与 16 维多租户越权阻断测试套件。

严格遵循 AGENTS.md 规范与 spec.md / plan.md 技术契约：
1. 纯内存架构：基于 SQLite 纯内存库与内存适配器
   (Storage, OCR, LLM, Embedding, Queue, Idempotency)；
2. 零外部联网：被 conftest.py 网络阻断拦截器严格守护，全用例毫秒级执行；
3. 纯函数计算核真实物理调用：真实调用 split_material_into_snippets, verify_knowledge_points,
   filter_qualified_questions, match_and_grade_answer, aggregate_mastery_scores，零 Mock 替身；
4. 8 步正向端到端全生命周期闭环流转测试
   (鉴权 -> 资料 -> 知识点 -> 题目 -> 练习 -> 判题 -> 诊断 -> 错题/继续练习)；
5. 16 维多租户越权攻击阻断矩阵 (AT-01 ~ AT-16)，
   验证 User B 携带合法 Token 探测 User A 资源 100% 拦截并绝密脱敏。
"""

import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Annotated, Any

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps.auth import (
    get_auth_service,
    get_current_token_payload,
    get_current_user,
    validate_user_status,
)
from app.api.deps.diagnosis import get_diagnosis_service
from app.api.deps.grading import get_grading_service
from app.api.deps.knowledge import get_knowledge_service
from app.api.deps.material import get_material_service
from app.api.deps.practice import get_practice_service
from app.api.deps.question import get_question_service
from app.api.deps.user import get_user_service
from app.api.v1 import api_v1_router
from app.core.errors import AppError, AuthenticationError
from app.core.security import decode_token
from app.integrations.embedding.fake import FakeEmbeddingAdapter
from app.integrations.idempotency.memory import MemoryIdempotencyAdapter
from app.integrations.llm.fake import FakeLLMAdapter
from app.integrations.ocr.fake import FakeOCRAdapter
from app.integrations.ocr.protocol import OCRPoint, OCRPolygon, OCRResult, OCRTextBlock
from app.integrations.queue.memory import MemoryQueueAdapter
from app.integrations.search.fake import FakeSearchAdapter
from app.integrations.storage.memory import MemoryStorageAdapter
from app.models.base import Base
from app.models.question import QuestionType
from app.models.user import User
from app.repositories.user import UserRepository
from app.services.auth import AuthService
from app.services.diagnosis import DiagnosisService
from app.services.grading import GradingService, LLMGradingOutput
from app.services.knowledge import (
    ExtractedKnowledgeItem,
    KnowledgeExtractionOutput,
    KnowledgeService,
)
from app.services.material import MaterialService
from app.services.practice import PracticeService
from app.services.question import (
    LLMGeneratedQuestionItem,
    LLMGradingPointItem,
    LLMGradingRubric,
    LLMQuestionBatchOutput,
    LLMQuestionOptionItem,
    QuestionService,
)

# ------------------------------------------------------------------------------
# 确定性高质量测试数据预置
# ------------------------------------------------------------------------------

TEST_TEXTBOOK_PARAGRAPHS: list[str] = [
    (
        "第一章 极限与连续性原理\n"
        "在数学分析中，微积分的严密理论基础建立在极限的ε-δ定义之上。"
        "数列与函数极限不仅决定了函数在某点邻域内的局部变化趋势，"
        "而且是刻画连续性、导数与定积分核心性质的基本分析工具。\n"
        "重要性质包括：极限的局部保号性、有界性定理以及夹逼准则。"
    ),
    (
        "第二节 极限的四则运算法则\n"
        "若两个函数的极限均存在，则其和、差、积的极限等于各自极限的和、差、积。"
        "商的运算法则要求分母的极限值严格不为零。"
        "复合函数的极限求法要求外层函数在内层函数极限点处保持连续性。"
    ),
    (
        "第三节 无穷小量的阶与等价代换\n"
        "在求未定式极限时，等价无穷小量代换是极其高效的简化手段。"
        "定理明确指出：等价无穷小代换原则严格适用于分子或分母整体的乘除因式，"
        "绝对严禁直接对加减混合表达式中的局部项随意进行等价代换，以防消去高阶项导致错误。"
    ),
]


def build_canned_ocr_result() -> OCRResult:
    """构建能通过 OCR 门禁与知识切分的高质量教材识别结果。"""
    full_text = "\n\n".join(TEST_TEXTBOOK_PARAGRAPHS)
    blocks: list[OCRTextBlock] = []
    line_number = 1
    for paragraph in TEST_TEXTBOOK_PARAGRAPHS:
        for line in paragraph.split("\n"):
            if not line.strip():
                continue
            blocks.append(
                OCRTextBlock(
                    text=line.strip(),
                    confidence=0.99,
                    polygon=OCRPolygon(
                        points=(
                            OCRPoint(x=10, y=line_number * 30),
                            OCRPoint(x=600, y=line_number * 30),
                            OCRPoint(x=600, y=line_number * 30 + 25),
                            OCRPoint(x=10, y=line_number * 30 + 25),
                        )
                    ),
                    line_number=line_number,
                )
            )
            line_number += 1

    return OCRResult(
        full_text=full_text,
        blocks=tuple(blocks),
        duration_ms=2.0,
        image_width=1200,
        image_height=1800,
        provider="fake",
    )


def build_canned_knowledge_output() -> KnowledgeExtractionOutput:
    """构建能通过 verify_knowledge_points 4 条件决策表门禁的结构化知识点。"""
    return KnowledgeExtractionOutput(
        knowledge_points=[
            ExtractedKnowledgeItem(
                temp_id="kp_1",
                parent_temp_id=None,
                name="极限与连续性原理",
                description="在数学分析中，微积分的严密理论基础建立在极限的ε-δ定义之上。",
                level=1,
                chapter_title="第一章 极限与连续性原理",
                source_snippet_indices=[0],
            ),
            ExtractedKnowledgeItem(
                temp_id="kp_2",
                parent_temp_id="kp_1",
                name="极限四则运算法则",
                description="若两个函数的极限均存在，则其和、差、积的极限等于各自极限的和、差、积。",
                level=2,
                chapter_title="第二节 极限的四则运算法则",
                source_snippet_indices=[1],
            ),
            ExtractedKnowledgeItem(
                temp_id="kp_3",
                parent_temp_id="kp_2",
                name="无穷小量阶与代换",
                description="在求未定式极限时，等价无穷小量代换是极其高效的简化手段。",
                level=3,
                chapter_title="第三节 无穷小量的阶与等价代换",
                source_snippet_indices=[2],
            ),
        ]
    )


def build_canned_question_output() -> LLMQuestionBatchOutput:
    """构建能通过 filter_qualified_questions 质检门禁的高质量试题集合。"""
    return LLMQuestionBatchOutput(
        questions=[
            LLMGeneratedQuestionItem(
                question_type=QuestionType.SINGLE_CHOICE.value,
                stem="在数学分析中，极限的ε-δ定义与函数在某点局部变化趋势，主要表达了什么？",
                options=[
                    LLMQuestionOptionItem(
                        key="A", content="刻画函数在某点局部变化趋势的精确分析工具"
                    ),
                    LLMQuestionOptionItem(key="B", content="仅适用于计算函数的定积分"),
                    LLMQuestionOptionItem(key="C", content="仅适用于判定函数的非连续跳跃点"),
                    LLMQuestionOptionItem(key="D", content="无法用于微积分理论基础构建"),
                ],
                answer="A",
                analysis="极限的ε-δ定义是刻画函数局部变化趋势的严密数学基础。",
                difficulty=3,
                source_snippet_index=0,
            ),
            LLMGeneratedQuestionItem(
                question_type=QuestionType.MULTIPLE_CHOICE.value,
                stem="重要性质包括：极限的局部保号性、有界性定理以及夹逼准则，以下分析哪些正确？",
                options=[
                    LLMQuestionOptionItem(key="A", content="极限存在时函数在局部去心邻域内有界"),
                    LLMQuestionOptionItem(
                        key="B", content="极限值大于零时局部邻域函数值保持大于零"
                    ),
                    LLMQuestionOptionItem(key="C", content="该性质要求函数在全实数域连续"),
                ],
                answer="A,B",
                analysis="极限的保号性与局部有界性只要求局部极限存在，不要求全实数域连续。",
                difficulty=3,
                source_snippet_index=0,
            ),
            LLMGeneratedQuestionItem(
                question_type=QuestionType.SHORT_ANSWER.value,
                stem="在数学分析中，函数在某点邻域内的局部变化趋势、夹逼准则，具有怎样的分析作用？",
                options=[],
                answer="微积分理论中利用夹逼准则可以求解复杂未定式极限。",
                analysis="夹逼准则是通过上下界放缩确定极限的有效方法。",
                difficulty=3,
                source_snippet_index=0,
                grading_rubric=LLMGradingRubric(
                    total_score=10,
                    points=[
                        LLMGradingPointItem(point="指出夹逼准则用于复杂未定式极限求解", score=5),
                        LLMGradingPointItem(point="指出上下界放缩收敛原理", score=5),
                    ],
                ),
            ),
        ]
    )


# ------------------------------------------------------------------------------
# 测试环境与依赖注入装配
# ------------------------------------------------------------------------------


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """创建基于 StaticPool 的纯内存 SQLite 数据库会话。"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def storage_adapter() -> MemoryStorageAdapter:
    """实例化纯内存对象存储适配器并预置存储桶。"""
    adapter = MemoryStorageAdapter()
    adapter.ensure_bucket_exists("zhilian-materials")
    return adapter


@pytest.fixture
def ocr_adapter() -> FakeOCRAdapter:
    """实例化纯内存假 OCR 适配器并注入高清教材文本。"""
    canned = build_canned_ocr_result()
    return FakeOCRAdapter(default_result=canned)


@pytest.fixture
def embedding_adapter() -> FakeEmbeddingAdapter:
    """实例化确定性向量计算适配器。"""
    return FakeEmbeddingAdapter()


@pytest.fixture
def queue_adapter() -> MemoryQueueAdapter:
    """实例化纯内存异步队列适配器。"""
    return MemoryQueueAdapter()


@pytest.fixture
def idempotency_adapter() -> MemoryIdempotencyAdapter:
    """实例化纯内存防重幂等锁适配器。"""
    return MemoryIdempotencyAdapter()


@pytest.fixture
def search_adapter() -> FakeSearchAdapter:
    """实例化纯内存假检索适配器。"""
    return FakeSearchAdapter()


@pytest.fixture
def llm_adapter() -> FakeLLMAdapter:
    """实例化纯内存假大模型网关适配器并预置确定性响应。"""
    llm = FakeLLMAdapter()
    # 预置知识点抽取响应
    k_out = build_canned_knowledge_output()
    llm.set_canned_response("你是一个专业的考纲分析与知识图谱构建专家", k_out.model_dump_json())
    # 预置试题生成响应
    q_out = build_canned_question_output()
    llm.set_canned_response("你是一名资深教育命题专家", q_out.model_dump_json())
    # 预置主观题判题响应
    g_out = LLMGradingOutput(
        score=8.0,
        confidence=0.92,
        feedback="回答准确全面，要点论述清晰",
    )
    llm.set_canned_structured_response(LLMGradingOutput, g_out)
    return llm


@pytest.fixture
def e2e_services(
    db_session: Session,
    storage_adapter: MemoryStorageAdapter,
    ocr_adapter: FakeOCRAdapter,
    embedding_adapter: FakeEmbeddingAdapter,
    queue_adapter: MemoryQueueAdapter,
    idempotency_adapter: MemoryIdempotencyAdapter,
    search_adapter: FakeSearchAdapter,
    llm_adapter: FakeLLMAdapter,
) -> dict[str, Any]:
    """装配直连 5 块纯函数算法核的真实领域服务全景字典。"""
    auth_service = AuthService(session=db_session)
    material_service = MaterialService(
        session=db_session,
        storage_adapter=storage_adapter,
        ocr_adapter=ocr_adapter,
        embedding_adapter=embedding_adapter,
        queue_adapter=queue_adapter,
        idempotency_adapter=idempotency_adapter,
    )
    knowledge_service = KnowledgeService(
        session=db_session,
        llm=llm_adapter,
        embedding=embedding_adapter,
    )
    question_service = QuestionService(
        session=db_session,
        llm=llm_adapter,
        embedding=embedding_adapter,
        search_adapter=search_adapter,
    )
    practice_service = PracticeService(
        session=db_session,
        idempotency=idempotency_adapter,
        queue=queue_adapter,
    )
    grading_service = GradingService(
        session=db_session,
        llm_adapter=llm_adapter,
    )
    diagnosis_service = DiagnosisService(
        session=db_session,
    )

    return {
        "session": db_session,
        "auth": auth_service,
        "material": material_service,
        "knowledge": knowledge_service,
        "question": question_service,
        "practice": practice_service,
        "grading": grading_service,
        "diagnosis": diagnosis_service,
        "llm": llm_adapter,
        "storage": storage_adapter,
        "ocr": ocr_adapter,
        "embedding": embedding_adapter,
        "queue": queue_adapter,
        "idempotency": idempotency_adapter,
    }


@pytest.fixture
def test_app(e2e_services: dict[str, Any]) -> FastAPI:
    """创建挂载全局 api_v1_router 与统一 AppError 异常处理器的测试 FastAPI 应用。"""
    app = FastAPI(title="P0 Full Chain E2E Test App")

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "data": None,
            },
        )

    user_repo = UserRepository(e2e_services["session"])

    async def override_get_current_user(
        payload: Annotated[dict[str, Any], Depends(get_current_token_payload)],
    ) -> User:
        user_id = uuid.UUID(str(payload["sub"]))
        user = user_repo.get_user_by_id(user_id)
        if user is None:
            raise AuthenticationError("用户不存在或已被移除")
        return validate_user_status(user, payload.get("token_version", 1))

    app.dependency_overrides[get_auth_service] = lambda: e2e_services["auth"]
    app.dependency_overrides[get_user_service] = lambda: e2e_services["auth"]
    app.dependency_overrides[get_material_service] = lambda: e2e_services["material"]
    app.dependency_overrides[get_knowledge_service] = lambda: e2e_services["knowledge"]
    app.dependency_overrides[get_question_service] = lambda: e2e_services["question"]
    app.dependency_overrides[get_practice_service] = lambda: e2e_services["practice"]
    app.dependency_overrides[get_grading_service] = lambda: e2e_services["grading"]
    app.dependency_overrides[get_diagnosis_service] = lambda: e2e_services["diagnosis"]
    app.dependency_overrides[get_current_user] = override_get_current_user

    app.include_router(api_v1_router)
    return app


@pytest_asyncio.fixture
async def http_client(test_app: FastAPI) -> AsyncGenerator[AsyncClient, None]:
    """提供基于 ASGITransport 的异步 HTTP 客户端。"""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ==============================================================================
# Milestone 1: 基础设施与双租户就绪验证
# ==============================================================================


@pytest.mark.asyncio
async def test_e2e_infrastructure_setup(
    http_client: AsyncClient,
    e2e_services: dict[str, Any],
) -> None:
    """验证纯内存数据库、适配器全集、领域服务与双租户登录初始化就绪。"""
    # 1. 验证用户 A 微信换端登录
    resp_a = await http_client.post(
        "/api/v1/auth/login",
        json={"code": "user_a_code", "nickname": "Learner_A"},
    )
    assert resp_a.status_code == 200
    token_data_a = resp_a.json()
    assert "access_token" in token_data_a
    assert "refresh_token" in token_data_a

    # 2. 验证用户 B 微信换端登录
    resp_b = await http_client.post(
        "/api/v1/auth/login",
        json={"code": "user_b_code", "nickname": "Attacker_B"},
    )
    assert resp_b.status_code == 200
    token_data_b = resp_b.json()
    assert "access_token" in token_data_b
    assert "refresh_token" in token_data_b
    assert token_data_a["access_token"] != token_data_b["access_token"]

    # 3. 验证内存适配器开箱即用状态
    assert e2e_services["storage"] is not None
    assert e2e_services["ocr"] is not None
    assert e2e_services["llm"] is not None
    assert e2e_services["embedding"] is not None
    assert e2e_services["queue"] is not None
    assert e2e_services["idempotency"] is not None


# ==============================================================================
# Milestone 2: 完整 8 步正向端到端全业务链路流转测试
# ==============================================================================


@pytest.mark.asyncio
async def test_p0_positive_full_chain(
    http_client: AsyncClient,
    e2e_services: dict[str, Any],
) -> None:
    """完整验证 8 步正向端到端全业务链路流转与纯函数算法核真实调用。"""
    # --------------------------------------------------------------------------
    # 步骤 1: 鉴权 - 登录签发双令牌
    # --------------------------------------------------------------------------
    login_resp = await http_client.post(
        "/api/v1/auth/login",
        json={"code": "learner_a_p0_full", "nickname": "租户学员A"},
    )
    assert login_resp.status_code == 200
    tokens = login_resp.json()
    token_a = tokens["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # --------------------------------------------------------------------------
    # 步骤 2: 资料与切片 - 上传、解析触发 split_material_into_snippets、就地重拍
    # --------------------------------------------------------------------------
    file_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
    upload_resp = await http_client.post(
        "/api/v1/materials/upload",
        files={"file": ("higher_math_guide.png", file_bytes, "image/png")},
        data={"title": "高等数学微积分精析", "source_type": "local"},
        headers=headers_a,
    )
    assert upload_resp.status_code == 201
    mat_data = upload_resp.json()
    material_id = uuid.UUID(mat_data["id"])
    version_id = uuid.UUID(mat_data["version_id"])

    # 同步触发解析流水线 (调用 split_material_into_snippets 物理分块)
    parse_resp = await http_client.post(
        f"/api/v1/materials/{material_id}/parse",
        json={"version_id": str(version_id), "sync": True},
        headers=headers_a,
    )
    assert parse_resp.status_code == 200
    assert parse_resp.json()["parse_status"] == "ready"

    # 就地重拍单页测试
    sharp_bytes = b"\xff\xd8\xff" + b"\x00" * 128
    reshoot_resp = await http_client.post(
        f"/api/v1/materials/{material_id}/reshoot",
        data={"page_index": 1, "version_id": str(version_id)},
        files={"file": ("sharp_p1.jpg", sharp_bytes, "image/jpeg")},
        headers=headers_a,
    )
    assert reshoot_resp.status_code == 200
    assert reshoot_resp.json()["is_qualified"] is True
    assert reshoot_resp.json()["reshoot_count"] == 1

    # --------------------------------------------------------------------------
    # 步骤 3: 知识点与建树 - 抽取触发 verify_knowledge_points、获取树形拓扑
    # --------------------------------------------------------------------------
    extract_resp = await http_client.post(
        f"/api/v1/materials/{material_id}/knowledge/extract",
        json={"version_id": str(version_id)},
        headers=headers_a,
    )
    assert extract_resp.status_code == 200
    assert extract_resp.json()["extracted_count"] == 3

    tree_resp = await http_client.get(
        f"/api/v1/materials/{material_id}/knowledge-tree",
        headers=headers_a,
    )
    assert tree_resp.status_code == 200
    tree_data = tree_resp.json()
    assert len(tree_data["nodes"]) >= 1
    root_node = tree_data["nodes"][0]
    knowledge_point_id = uuid.UUID(root_node["id"])

    # --------------------------------------------------------------------------
    # 步骤 4: 题目与编辑 - 出题触发 filter_qualified_questions、人工微调
    # --------------------------------------------------------------------------
    gen_resp = await http_client.post(
        "/api/v1/questions/generate",
        json={
            "material_id": str(material_id),
            "version_id": str(version_id),
            "knowledge_point_id": str(knowledge_point_id),
            "question_types": ["single_choice", "multiple_choice", "short_answer"],
            "count": 3,
            "difficulty": 3,
        },
        headers=headers_a,
    )
    assert gen_resp.status_code == 200
    gen_data = gen_resp.json()
    assert gen_data["qualified_count"] == 3
    assert len(gen_data["qualified_questions"]) == 3

    question_1 = gen_data["qualified_questions"][0]
    question_1_id = uuid.UUID(question_1["id"])

    # 来源切片正文随出题响应真实下发（核对页来源框），不再是 id 级元数据
    assert question_1["source_snippet_id"] is not None
    generated_source = question_1["source_snippet"]
    assert generated_source is not None
    assert generated_source["id"] == question_1["source_snippet_id"]
    assert generated_source["snippet_content"].strip() != ""
    # 章节标题允许为空（切片未标注章节时），但字段必须存在且为字符串
    assert isinstance(generated_source["chapter_title"], str)
    assert generated_source["page_index"] >= 1

    # 详情路径与出题路径装配同一投影
    detail_resp = await http_client.get(
        f"/api/v1/questions/{question_1_id}",
        headers=headers_a,
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["source_snippet"] == generated_source

    # 列表路径同样装配；无来源的题目保持 null（不伪造正文）
    list_resp = await http_client.get(
        f"/api/v1/questions?material_id={material_id}",
        headers=headers_a,
    )
    assert list_resp.status_code == 200
    listed_items = list_resp.json()["items"]
    assert listed_items
    for listed in listed_items:
        if listed["source_snippet_id"] is None:
            assert listed["source_snippet"] is None
        else:
            assert listed["source_snippet"]["snippet_content"].strip() != ""

    # 微调题干并留存审计日志
    edit_resp = await http_client.put(
        f"/api/v1/questions/{question_1_id}",
        json={
            "stem": question_1["stem"] + " [已审定教学用题]",
            "reason": "完善题干修辞与专业审定标注",
        },
        headers=headers_a,
    )
    assert edit_resp.status_code == 200
    assert "[已审定教学用题]" in edit_resp.json()["stem"]
    # 更新响应仍带来源，前端复用同一卡片渲染不丢来源框
    assert edit_resp.json()["source_snippet"] == generated_source

    # --------------------------------------------------------------------------
    # 步骤 5: 练习与草稿 - 智能组卷、暂存作答草稿、暂停与恢复
    # --------------------------------------------------------------------------
    create_prac_resp = await http_client.post(
        "/api/v1/practices",
        json={
            "title": "极限理论精选测评卷",
            "material_id": str(material_id),
            "knowledge_point_ids": [str(knowledge_point_id)],
            "mode": "sequential",
            "question_count": 3,
        },
        headers=headers_a,
    )
    assert create_prac_resp.status_code == 201
    prac_data = create_prac_resp.json()
    practice_id = uuid.UUID(prac_data["id"])
    attempt_items = prac_data["items"]
    assert len(attempt_items) == 3

    item_1 = attempt_items[0]
    item_2 = attempt_items[1]
    item_3 = attempt_items[2]

    # 保存题 1 作答草稿 (故意选错 B，参考答案为 A，以沉淀错题)
    save_1 = await http_client.put(
        f"/api/v1/practices/{practice_id}/answers",
        json={"question_id": item_1["question_id"], "user_answer": "B", "time_spent_seconds": 15},
        headers=headers_a,
    )
    assert save_1.status_code == 200

    # 保存题 2 作答草稿 (多选题答对 A,B)
    save_2 = await http_client.put(
        f"/api/v1/practices/{practice_id}/answers",
        json={
            "question_id": item_2["question_id"],
            "user_answer": "A,B",
            "time_spent_seconds": 25,
        },
        headers=headers_a,
    )
    assert save_2.status_code == 200

    # 保存题 3 作答草稿 (主观题论述)
    save_3 = await http_client.put(
        f"/api/v1/practices/{practice_id}/answers",
        json={
            "question_id": item_3["question_id"],
            "user_answer": "微积分理论中利用夹逼准则可以求解复杂未定式极限。",
            "time_spent_seconds": 40,
        },
        headers=headers_a,
    )
    assert save_3.status_code == 200

    # 暂停与恢复练习
    pause_resp = await http_client.post(
        f"/api/v1/practices/{practice_id}/pause",
        headers=headers_a,
    )
    assert pause_resp.status_code == 200
    assert pause_resp.json()["status"] == "paused"

    resume_resp = await http_client.post(
        f"/api/v1/practices/{practice_id}/resume",
        headers=headers_a,
    )
    assert resume_resp.status_code == 200
    assert resume_resp.json()["status"] == "in_progress"

    # --------------------------------------------------------------------------
    # 步骤 6: 幂等交卷与判题 - 强幂等回放、触发 match_and_grade_answer 与大模型
    # --------------------------------------------------------------------------
    submit_key = str(uuid.uuid4())
    sub_resp_1 = await http_client.post(
        f"/api/v1/practices/{practice_id}/submit",
        headers={**headers_a, "Idempotency-Key": submit_key},
        json={"confirm_unanswered": False},
    )
    assert sub_resp_1.status_code == 200
    assert sub_resp_1.json()["status"] == "submitted"

    # 重复交卷验证强幂等回放
    sub_resp_2 = await http_client.post(
        f"/api/v1/practices/{practice_id}/submit",
        headers={**headers_a, "Idempotency-Key": submit_key},
        json={"confirm_unanswered": False},
    )
    assert sub_resp_2.status_code == 200
    assert sub_resp_2.json()["status"] == "submitted"

    # 执行判题编排流水线 (客观题秒判 + 主观题 AI 判分)
    grading_svc: GradingService = e2e_services["grading"]
    user_a_id = uuid.UUID(str(decode_token(token_a)["sub"]))
    grading_summary = grading_svc.grade_practice(
        user_id=user_a_id,
        practice_id=practice_id,
    )
    assert grading_summary.total_items == 3

    # 查询作答项判题明细
    item_3_id = uuid.UUID(item_3["id"])
    detail_grade_resp = await http_client.get(
        f"/api/v1/attempts/{item_3_id}/grading",
        headers=headers_a,
    )
    assert detail_grade_resp.status_code == 200
    assert detail_grade_resp.json()["attempt_item_id"] == str(item_3_id)

    # --------------------------------------------------------------------------
    # 步骤 7: 诊断与自评重判 - 报告生成触发 aggregate_mastery_scores、自评与重判
    # --------------------------------------------------------------------------
    diag_resp = await http_client.post(
        f"/api/v1/practices/{practice_id}/diagnosis",
        headers=headers_a,
    )
    assert diag_resp.status_code == 200
    diag_data = diag_resp.json()
    report_id = uuid.UUID(diag_data["id"])
    assert diag_data["practice_id"] == str(practice_id)

    # 用户自主评分覆盖 (自评打 1.0 分)
    self_eval_resp = await http_client.post(
        "/api/v1/grading/self-evaluate",
        json={"attempt_item_id": str(item_3_id), "score": 1.0, "feedback": "要点清晰，自评满分"},
        headers=headers_a,
    )
    assert self_eval_resp.status_code == 200
    assert self_eval_resp.json()["channel"] == "user_self"

    # 申请大模型复核重判
    regrade_resp = await http_client.post(
        "/api/v1/grading/regrade",
        json={"attempt_item_id": str(item_3_id), "reason": "申请专业阅卷专家二次核对"},
        headers=headers_a,
    )
    assert regrade_resp.status_code == 200
    assert regrade_resp.json()["attempt_item_id"] == str(item_3_id)

    # --------------------------------------------------------------------------
    # 步骤 8: 错题与继续练习 - 错题本检索、手动攻克标记、一键继续练习
    # --------------------------------------------------------------------------
    wrong_list_resp = await http_client.get(
        f"/api/v1/wrong-records?material_id={material_id}",
        headers=headers_a,
    )
    assert wrong_list_resp.status_code == 200
    wrong_data = wrong_list_resp.json()
    assert wrong_data["total"] >= 1
    wrong_record = wrong_data["items"][0]
    wrong_record_id = uuid.UUID(wrong_record["id"])

    # 手动标记攻克
    master_resp = await http_client.post(
        f"/api/v1/wrong-records/{wrong_record_id}/master",
        headers=headers_a,
    )
    assert master_resp.status_code == 200
    assert master_resp.json()["is_mastered"] is True

    # 针对薄弱点继续练习闭环
    cont_prac_resp = await http_client.post(
        "/api/v1/practices",
        json={
            "title": "薄弱环节专项重练",
            "material_id": str(material_id),
            "knowledge_point_ids": [str(knowledge_point_id)],
            "mode": "weak_points",
            "source_type": "weakness",
            "source_report_id": str(report_id),
            "question_count": 2,
        },
        headers=headers_a,
    )
    assert cont_prac_resp.status_code == 201
    assert cont_prac_resp.json()["id"] != str(practice_id)


# ==============================================================================
# Milestone 3: 16 维多租户越权阻断测试矩阵 (AT-01 ~ AT-16)
# ==============================================================================


@pytest.mark.asyncio
async def test_tenant_isolation_attack_matrix(
    http_client: AsyncClient,
    e2e_services: dict[str, Any],
) -> None:
    """16 维多租户越权攻击阻断矩阵。

    断言 User B 携带合法 Token 探测 User A 资源 100% 拦截并绝密脱敏。
    """
    # 1. 登录正常租户 User A 并生成完整一套私有业务资产
    login_a = await http_client.post(
        "/api/v1/auth/login",
        json={"code": "user_a_target", "nickname": "TargetUserA"},
    )
    token_a = login_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 上传资料 A
    file_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
    mat_resp = await http_client.post(
        "/api/v1/materials/upload",
        files={"file": ("tenant_a_doc.png", file_bytes, "image/png")},
        data={"title": "绝密核心算法与知识体系", "source_type": "local"},
        headers=headers_a,
    )
    a_mat_id = uuid.UUID(mat_resp.json()["id"])
    a_ver_id = uuid.UUID(mat_resp.json()["version_id"])

    # 解析资料 A
    await http_client.post(
        f"/api/v1/materials/{a_mat_id}/parse",
        json={"version_id": str(a_ver_id), "sync": True},
        headers=headers_a,
    )

    # 资料 A 真实重拍确保完整切片与清晰度达标
    sharp_bytes = b"\xff\xd8\xff" + b"\x00" * 128
    reshoot_setup = await http_client.post(
        f"/api/v1/materials/{a_mat_id}/reshoot",
        data={"page_index": 1, "version_id": str(a_ver_id)},
        files={"file": ("sharp_p1.jpg", sharp_bytes, "image/jpeg")},
        headers=headers_a,
    )
    assert reshoot_setup.status_code == 200

    # 抽取知识点 A
    await http_client.post(
        f"/api/v1/materials/{a_mat_id}/knowledge/extract",
        json={"version_id": str(a_ver_id)},
        headers=headers_a,
    )
    tree_resp = await http_client.get(
        f"/api/v1/materials/{a_mat_id}/knowledge-tree",
        headers=headers_a,
    )
    a_point_id = uuid.UUID(tree_resp.json()["nodes"][0]["id"])

    # 生成题目 A
    q_resp = await http_client.post(
        "/api/v1/questions/generate",
        json={
            "material_id": str(a_mat_id),
            "version_id": str(a_ver_id),
            "knowledge_point_id": str(a_point_id),
            "question_types": ["single_choice", "multiple_choice", "short_answer"],
            "count": 3,
            "difficulty": 3,
        },
        headers=headers_a,
    )
    a_quest_id = uuid.UUID(q_resp.json()["qualified_questions"][0]["id"])

    # 创建练习 A
    prac_resp = await http_client.post(
        "/api/v1/practices",
        json={
            "title": "User A 私密测评卷",
            "material_id": str(a_mat_id),
            "knowledge_point_ids": [str(a_point_id)],
            "mode": "sequential",
            "question_count": 3,
        },
        headers=headers_a,
    )
    assert prac_resp.status_code == 201, f"Create practice failed: {prac_resp.text}"
    a_prac_id = uuid.UUID(prac_resp.json()["id"])
    a_items = prac_resp.json()["items"]
    a_item_id = uuid.UUID(a_items[0]["id"])
    a_sub_item_id = uuid.UUID(a_items[2]["id"])

    # 保存答题、提交交卷、判题并生成诊断报告
    for it in a_items:
        await http_client.put(
            f"/api/v1/practices/{a_prac_id}/answers",
            json={
                "question_id": it["question_id"],
                "user_answer": "B",
                "time_spent_seconds": 10,
            },
            headers=headers_a,
        )
    await http_client.post(
        f"/api/v1/practices/{a_prac_id}/submit",
        headers={**headers_a, "Idempotency-Key": str(uuid.uuid4())},
    )

    grading_svc: GradingService = e2e_services["grading"]
    user_a_id = uuid.UUID(str(decode_token(token_a)["sub"]))
    grading_summary = grading_svc.grade_practice(
        user_id=user_a_id,
        practice_id=a_prac_id,
    )
    assert grading_summary.total_items == 3

    await http_client.post(
        f"/api/v1/practices/{a_prac_id}/diagnosis",
        headers=headers_a,
    )
    wrong_list_resp = await http_client.get(
        f"/api/v1/wrong-records?material_id={a_mat_id}",
        headers=headers_a,
    )
    a_wrong_id = uuid.UUID(wrong_list_resp.json()["items"][0]["id"])

    # 2. 登录攻击者租户 User B，获得合法身份凭据 Token B
    login_b = await http_client.post(
        "/api/v1/auth/login",
        json={"code": "user_b_attacker", "nickname": "AttackerUserB"},
    )
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. 逐项执行 AT-01 ~ AT-16 越权攻击校验
    # --------------------------------------------------------------------------
    # AT-01: 尝试偷窥 User A 资料详情
    # --------------------------------------------------------------------------
    at01 = await http_client.get(f"/api/v1/materials/{a_mat_id}", headers=headers_b)
    assert at01.status_code == 404
    assert at01.json()["code"] == 40004
    assert "绝密核心算法与知识体系" not in at01.text

    # --------------------------------------------------------------------------
    # AT-02: 尝试重拍 User A 的资料页面
    # --------------------------------------------------------------------------
    at02 = await http_client.post(
        f"/api/v1/materials/{a_mat_id}/reshoot",
        data={"page_index": 1},
        files={"file": ("malicious.jpg", b"\xff\xd8\xff" + b"\x00" * 32, "image/jpeg")},
        headers=headers_b,
    )
    assert at02.status_code == 404
    assert at02.json()["code"] == 40004

    # --------------------------------------------------------------------------
    # AT-03: 尝试拉取 User A 专属知识树
    # --------------------------------------------------------------------------
    at03 = await http_client.get(
        f"/api/v1/materials/{a_mat_id}/knowledge-tree",
        headers=headers_b,
    )
    assert at03.status_code == 404
    assert at03.json()["code"] == 40004

    # --------------------------------------------------------------------------
    # AT-04: 尝试读取 User A 提取的知识点详情
    # --------------------------------------------------------------------------
    at04 = await http_client.get(f"/api/v1/knowledge/{a_point_id}", headers=headers_b)
    assert at04.status_code == 404
    assert at04.json()["code"] == 40007

    # --------------------------------------------------------------------------
    # AT-05: 尝试窃取 User A 题干与参考答案
    # --------------------------------------------------------------------------
    at05 = await http_client.get(f"/api/v1/questions/{a_quest_id}", headers=headers_b)
    assert at05.status_code == 404
    assert at05.json()["code"] in (40008, 40009)
    assert "极限的ε-δ定义" not in at05.text

    # --------------------------------------------------------------------------
    # AT-06: 尝试篡改 User A 题目内容
    # --------------------------------------------------------------------------
    at06 = await http_client.put(
        f"/api/v1/questions/{a_quest_id}",
        json={"stem": "恶意篡改的题干内容", "reason": "越权篡改"},
        headers=headers_b,
    )
    assert at06.status_code == 404
    assert at06.json()["code"] in (40008, 40009)

    # --------------------------------------------------------------------------
    # AT-07: 尝试查看 User A 练习卷面快照
    # --------------------------------------------------------------------------
    at07 = await http_client.get(f"/api/v1/practices/{a_prac_id}", headers=headers_b)
    assert at07.status_code == 404
    assert at07.json()["code"] == 40010

    # --------------------------------------------------------------------------
    # AT-08: 尝试覆盖 User A 的作答草稿
    # --------------------------------------------------------------------------
    at08 = await http_client.put(
        f"/api/v1/practices/{a_prac_id}/answers",
        json={"question_id": str(a_quest_id), "user_answer": "恶意作答", "time_spent_seconds": 1},
        headers=headers_b,
    )
    assert at08.status_code == 404
    assert at08.json()["code"] == 40010

    # --------------------------------------------------------------------------
    # AT-09: 尝试提前交卷 User A 练习
    # --------------------------------------------------------------------------
    at09 = await http_client.post(
        f"/api/v1/practices/{a_prac_id}/submit",
        headers={**headers_b, "Idempotency-Key": str(uuid.uuid4())},
        json={"confirm_unanswered": True},
    )
    assert at09.status_code == 404
    assert at09.json()["code"] == 40010

    # --------------------------------------------------------------------------
    # AT-10: 尝试读取 User A 作答判题记录
    # --------------------------------------------------------------------------
    at10 = await http_client.get(f"/api/v1/attempts/{a_item_id}/grading", headers=headers_b)
    assert at10.status_code == 404
    assert at10.json()["code"] == 40013

    # --------------------------------------------------------------------------
    # AT-11: 尝试替 User A 主观题打分自评
    # --------------------------------------------------------------------------
    at11 = await http_client.post(
        "/api/v1/grading/self-evaluate",
        json={"attempt_item_id": str(a_sub_item_id), "score": 10.0, "feedback": "恶意自评满分"},
        headers=headers_b,
    )
    assert at11.status_code == 404
    assert at11.json()["code"] == 40013

    # --------------------------------------------------------------------------
    # AT-12: 尝试对 User A 题目恶意发起重新判题
    # --------------------------------------------------------------------------
    at12 = await http_client.post(
        "/api/v1/grading/regrade",
        json={"attempt_item_id": str(a_sub_item_id), "reason": "恶意消耗配额重判"},
        headers=headers_b,
    )
    assert at12.status_code == 404
    assert at12.json()["code"] == 40013

    # --------------------------------------------------------------------------
    # AT-13: 尝试获取 User A 的学情诊断报告
    # --------------------------------------------------------------------------
    at13 = await http_client.get(
        f"/api/v1/practices/{a_prac_id}/diagnosis",
        headers=headers_b,
    )
    assert at13.status_code == 404
    assert at13.json()["code"] == 40017

    # --------------------------------------------------------------------------
    # AT-14: 尝试查询 User A 的艾宾浩斯掌握看板 (返回 User B 自身空看板)
    # --------------------------------------------------------------------------
    at14 = await http_client.get(f"/api/v1/mastery?material_id={a_mat_id}", headers=headers_b)
    assert at14.status_code == 200
    at14_data = at14.json()
    assert at14_data["total_points"] == 0
    assert len(at14_data.get("weak_points", [])) == 0

    # --------------------------------------------------------------------------
    # AT-15: 尝试拉取 User A 专属错题列表 (返回 User B 自身空列表)
    # --------------------------------------------------------------------------
    at15 = await http_client.get(
        f"/api/v1/wrong-records?material_id={a_mat_id}",
        headers=headers_b,
    )
    assert at15.status_code == 200
    at15_data = at15.json()
    assert at15_data["total"] == 0
    assert len(at15_data["items"]) == 0

    # --------------------------------------------------------------------------
    # AT-16: 尝试标记 User A 的错题为已攻克
    # --------------------------------------------------------------------------
    at16 = await http_client.post(
        f"/api/v1/wrong-records/{a_wrong_id}/master",
        headers=headers_b,
    )
    assert at16.status_code == 404
    assert at16.json()["code"] == 40019
