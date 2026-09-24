"""认证与授权相关 Pydantic v2 数据契约与 DTO 定义。

严格遵循 AGENTS.md 规范：
- 字段类型完全标注，支持 Pydantic v2 与 from_attributes；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

from pydantic import BaseModel, ConfigDict, Field


class WechatLoginRequest(BaseModel):
    """微信登录置换令牌请求契约。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=1, max_length=128, description="微信小程序临时登录凭据 code")
    nickname: str | None = Field(default=None, max_length=64, description="用户微信昵称 (可选)")
    avatar_url: str | None = Field(default=None, max_length=512, description="用户头像 URL (可选)")


class RefreshTokenRequest(BaseModel):
    """刷新令牌请求契约。"""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(..., min_length=16, description="长效 Refresh Token 凭据")


class TokenResponse(BaseModel):
    """JWT 双令牌发放成功响应契约。"""

    model_config = ConfigDict(from_attributes=True)

    access_token: str = Field(..., description="短期访问凭证 Access Token (2小时有效)")
    refresh_token: str = Field(..., description="长期刷新凭证 Refresh Token (30天有效)")
    token_type: str = Field(default="Bearer", description="令牌类型，固定为 Bearer")
    expires_in: int = Field(default=7200, description="Access Token 过期剩余秒数 (默认 7200 秒)")


class RevokeTokenResponse(BaseModel):
    """主动吊销令牌响应契约。"""

    model_config = ConfigDict(from_attributes=True)

    success: bool = Field(default=True, description="操作是否执行成功")
    message: str = Field(default="已成功注销所有登录凭据", description="面向用户的操作结果提示文案")


__all__ = [
    "RefreshTokenRequest",
    "RevokeTokenResponse",
    "TokenResponse",
    "WechatLoginRequest",
]
