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


class UpdateUserProfileRequest(BaseModel):
    """更新当前登录用户画像资料的请求契约 (BUG-AUTH-004)。

    全字段可选：未提供 (None) 的字段表示不修改，保持既有画像不变。
    """

    model_config = ConfigDict(extra="forbid")

    nickname: str | None = Field(default=None, max_length=50, description="用户昵称")
    avatar_url: str | None = Field(default=None, max_length=500, description="用户头像 URL")


__all__ = [
    "UpdateUserProfileRequest",
    "UserActionResponse",
    "UserProfileResponse",
]
