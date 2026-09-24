"""FastAPI v1 API 路由汇总模块。"""

from fastapi import APIRouter

from app.api.v1.materials import router as materials_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(materials_router)

__all__ = ["api_v1_router", "materials_router"]
