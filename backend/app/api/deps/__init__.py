"""FastAPI 依赖注入导出模块。"""

from app.api.deps.auth import (
    get_current_token_payload,
    get_current_user,
    get_current_user_id,
    http_bearer,
    validate_user_status,
)
from app.api.deps.diagnosis import get_diagnosis_service
from app.api.deps.grading import get_grading_service
from app.api.deps.knowledge import get_db_session, get_knowledge_service
from app.api.deps.material import get_material_service
from app.api.deps.practice import get_practice_service
from app.api.deps.question import get_question_service

__all__ = [
    "get_current_token_payload",
    "get_current_user",
    "get_current_user_id",
    "get_db_session",
    "get_diagnosis_service",
    "get_grading_service",
    "get_knowledge_service",
    "get_material_service",
    "get_practice_service",
    "get_question_service",
    "http_bearer",
    "validate_user_status",
]
