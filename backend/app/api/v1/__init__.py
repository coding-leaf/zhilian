"""FastAPI v1 API 路由汇总模块。"""

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.diagnosis import router as diagnosis_router
from app.api.v1.grading import router as grading_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.materials import router as materials_router
from app.api.v1.practices import router as practices_router
from app.api.v1.questions import router as questions_router
from app.api.v1.users import router as users_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router)
api_v1_router.include_router(users_router)
api_v1_router.include_router(materials_router)
api_v1_router.include_router(knowledge_router)
api_v1_router.include_router(questions_router)
api_v1_router.include_router(practices_router)
api_v1_router.include_router(grading_router)
api_v1_router.include_router(diagnosis_router)

__all__ = [
    "api_v1_router",
    "auth_router",
    "diagnosis_router",
    "grading_router",
    "knowledge_router",
    "materials_router",
    "practices_router",
    "questions_router",
    "users_router",
]
