"""智练自主学习平台 FastAPI 应用总入口与开发装配服务。

遵循 AGENTS.md 规范：
- 挂载全套全局异常处理器 (AppError / RequestValidationError)；
- 配置跨域中间件 (CORSMiddleware)；
- 提供开发/独立环境依赖注入装配 (SQLite、内存存储、假适配器与多领域服务)；
- 聚合加载 API v1 路由总线。
"""

import logging
import os
import uuid
from collections.abc import Generator
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

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

logger = logging.getLogger("zhilian.app")

# 1. 数据库引擎与元数据就绪
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./zhilian_dev.db")
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
Base.metadata.create_all(engine)
session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db_session() -> Generator[Session, None, None]:
    """生成单请求生命周期的独立数据库会话。"""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# 2. 外部适配器组装 (开发环境具备离线自闭环能力)
storage_adapter = MemoryStorageAdapter()
storage_adapter.ensure_bucket_exists("zhilian-materials")


def build_default_ocr_result() -> OCRResult:
    """构建开发环境默认 OCR 识别结果。"""
    sample_text = (
        "第一章 极限与连续性原理\n\n"
        "在数学分析中，微积分的理论基础建立在极限定义之上。\n\n"
        "第二节 极限的四则运算法则\n\n"
        "若函数极限存在，则其代数和与积的极限满足对应运算法则。"
    )
    blocks: list[OCRTextBlock] = []
    line_number = 1
    for line in sample_text.split("\n"):
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
        full_text=sample_text,
        blocks=tuple(blocks),
        duration_ms=5.0,
        image_width=1200,
        image_height=1800,
        provider="fake",
    )


ocr_adapter = FakeOCRAdapter(default_result=build_default_ocr_result())
embedding_adapter = FakeEmbeddingAdapter()
queue_adapter = MemoryQueueAdapter()
idempotency_adapter = MemoryIdempotencyAdapter()
search_adapter = FakeSearchAdapter()

# 预设大模型模拟响应
llm_adapter = FakeLLMAdapter()
canned_knowledge = KnowledgeExtractionOutput(
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
    ]
)
llm_adapter.set_canned_response(
    "你是一个专业的考纲分析与知识图谱构建专家",
    canned_knowledge.model_dump_json(),
)

canned_questions = LLMQuestionBatchOutput(
    questions=[
        LLMGeneratedQuestionItem(
            question_type=QuestionType.SINGLE_CHOICE.value,
            stem="在数学分析中，极限定义的核心思想体现了什么变化趋势？",
            options=[
                LLMQuestionOptionItem(key="A", content="局部逼近趋势"),
                LLMQuestionOptionItem(key="B", content="全局发散特性"),
                LLMQuestionOptionItem(key="C", content="完全不连续"),
                LLMQuestionOptionItem(key="D", content="跳跃间断"),
            ],
            answer="A",
            analysis="极限刻画了自变量趋近于某点时函数值的局部逼近趋势。",
            difficulty=3,
            source_snippet_index=0,
        ),
        LLMGeneratedQuestionItem(
            question_type=QuestionType.TRUE_FALSE.value,
            stem="若两个函数的极限均存在，则其乘积的极限等于各自极限的乘积。",
            options=[
                LLMQuestionOptionItem(key="T", content="正确"),
                LLMQuestionOptionItem(key="F", content="错误"),
            ],
            answer="T",
            analysis="根据极限乘法运算法则，乘积极限等于各自极限相乘。",
            difficulty=3,
            source_snippet_index=1,
        ),
        LLMGeneratedQuestionItem(
            question_type=QuestionType.SHORT_ANSWER.value,
            stem="简述极限的局部保号性及其核心结论。",
            options=[],
            answer="若函数在某点的极限大于零，则在该点的某一去心邻域内函数值均大于零。",
            analysis="局部保号性保证了极限的正负性在去心邻域内得到保持。",
            difficulty=3,
            source_snippet_index=0,
            grading_rubric=LLMGradingRubric(
                total_score=10,
                points=[
                    LLMGradingPointItem(point="指出去心邻域内函数值保持同号", score=5),
                    LLMGradingPointItem(point="阐明极限值符号与函数值局部保号关系", score=5),
                ],
            ),
        ),
    ]
)
llm_adapter.set_canned_response("你是一名资深教育命题专家", canned_questions.model_dump_json())
llm_adapter.set_canned_structured_response(
    LLMGradingOutput,
    LLMGradingOutput(
        score=9.0,
        confidence=0.95,
        feedback="要点论述清晰，论述完整无误。",
    ),
)


# 3. 依赖注入装配实现
def provide_auth_service(session: Annotated[Session, Depends(get_db_session)]) -> AuthService:
    """提供 AuthService 实例。"""
    return AuthService(session=session)


def provide_material_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> MaterialService:
    """提供 MaterialService 实例。"""
    return MaterialService(
        session=session,
        storage_adapter=storage_adapter,
        ocr_adapter=ocr_adapter,
        embedding_adapter=embedding_adapter,
        queue_adapter=queue_adapter,
        idempotency_adapter=idempotency_adapter,
    )


def provide_knowledge_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> KnowledgeService:
    """提供 KnowledgeService 实例。"""
    return KnowledgeService(
        session=session,
        llm=llm_adapter,
        embedding=embedding_adapter,
    )


def provide_question_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> QuestionService:
    """提供 QuestionService 实例。"""
    return QuestionService(
        session=session,
        llm=llm_adapter,
        embedding=embedding_adapter,
        search_adapter=search_adapter,
    )


def provide_practice_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> PracticeService:
    """提供 PracticeService 实例。"""
    return PracticeService(
        session=session,
        idempotency=idempotency_adapter,
        queue=queue_adapter,
    )


def provide_grading_service(session: Annotated[Session, Depends(get_db_session)]) -> GradingService:
    """提供 GradingService 实例。"""
    return GradingService(
        session=session,
        llm_adapter=llm_adapter,
    )


def provide_diagnosis_service(
    session: Annotated[Session, Depends(get_db_session)],
) -> DiagnosisService:
    """提供 DiagnosisService 实例。"""
    return DiagnosisService(
        session=session,
    )


async def provide_current_user(
    payload: Annotated[dict[str, Any], Depends(get_current_token_payload)],
    session: Annotated[Session, Depends(get_db_session)],
) -> User:
    """解析当前请求携带的有效租户用户。"""
    raw_sub = payload.get("sub")
    if not raw_sub:
        raise AuthenticationError("令牌载荷缺少用户标识 (sub)")

    try:
        user_uuid = uuid.UUID(str(raw_sub))
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("用户标识格式无效") from exc

    user_repo = UserRepository(session)
    user = user_repo.get_user_by_id(user_uuid)
    token_version = payload.get("token_version", 1)
    return validate_user_status(user, token_version)


# 4. 创建应用实例与挂载总线
app = FastAPI(
    title="智练自主学习平台 API",
    description="智练平台后端核心领域服务与 RESTful API 总线",
    version="1.0.0",
)

# 允许跨域（本地开发、小程序与真机调试）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    """全局统一业务异常处理器。"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.error_code,
            "message": exc.message,
            "details": exc.details,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """统一 Pydantic 校验错误转换。"""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": 10001,
            "message": "请求参数校验失败",
            "details": exc.errors(),
        },
    )


# 覆盖全量服务依赖项
app.dependency_overrides[get_auth_service] = provide_auth_service
app.dependency_overrides[get_user_service] = provide_auth_service
app.dependency_overrides[get_material_service] = provide_material_service
app.dependency_overrides[get_knowledge_service] = provide_knowledge_service
app.dependency_overrides[get_question_service] = provide_question_service
app.dependency_overrides[get_practice_service] = provide_practice_service
app.dependency_overrides[get_grading_service] = provide_grading_service
app.dependency_overrides[get_diagnosis_service] = provide_diagnosis_service
app.dependency_overrides[get_current_user] = provide_current_user

# 挂载 API v1 路由
app.include_router(api_v1_router)


@app.get("/health", tags=["system"], summary="服务健康检查")
async def health_check() -> dict[str, str]:
    """健康探测端点。"""
    return {"status": "ok", "app": "ZhiLian"}


@app.get("/", tags=["system"], summary="服务根入口")
async def root() -> dict[str, str]:
    """系统入口提示。"""
    return {
        "message": "智练自主学习平台 API 运行中",
        "docs_url": "/docs",
        "health_url": "/health",
    }
