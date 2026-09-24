"""FastAPI 依赖注入导出模块。"""

from app.api.deps.auth import (
    get_current_token_payload,
    get_current_user,
    get_current_user_id,
    http_bearer,
    validate_user_status,
)
from app.api.deps.material import get_material_service

__all__ = [
    "get_current_token_payload",
    "get_current_user",
    "get_current_user_id",
    "get_material_service",
    "http_bearer",
    "validate_user_status",
]
