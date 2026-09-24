"""用户管理与画像响应 Pydantic v2 数据契约。

严格遵循 AGENTS.md 规范：
- 字段类型完全标注，支持 Pydantic v2 与 from_attributes；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserProfileResponse(BaseModel):
    """用户个人画像与资料详情响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="用户唯一标识 UUIDv4")
    nickname: str = Field(..., description="用户昵称")
    avatar_url: str = Field(..., description="用户头像 URL")
    created_at: datetime | None = Field(default=None, description="账号创建时间")


class UserActionResponse(BaseModel):
    """用户通用操作结果响应契约 (如注销、吊销令牌等)。"""

    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(..., description="操作是否执行成功")
    message: str = Field(..., description="面向用户的操作结果提示文案")


__all__ = [
    "UserActionResponse",
    "UserProfileResponse",
]
