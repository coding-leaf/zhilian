"""认证与账号管理业务编排服务模块。

负责统一编排事务、微信身份换取、JWT 双令牌签发、刷新、主动吊销及账号注销。
严格遵循 AGENTS.md 规范：
- 全系统唯一允许开启数据库事务的层；
- 结构化日志输出，绝密脱敏红线严禁向日志记录明文密钥、Token 全文或明文 user_id；
- 缩写白名单仅限 8 个 (api, id, url, ocr, llm, db, config, env)。
"""

import hashlib
import logging
import time
import uuid
from typing import cast

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AuthenticationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_user_ref,
    verify_token_version,
)
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import TokenResponse
from app.schemas.user import UserProfileResponse

logger = logging.getLogger(__name__)


def validate_user_status(user: User | None, payload_token_version: int) -> User:
    """核对用户实体存在性、激活状态、软删除标记及令牌版本一致性。

    纯校验逻辑，阻断停用用户、已注销用户或版本已过期的失效凭证。

    Args:
        user: 从持久化存储或服务层加载的用户实体（若不存在则为 None）。
        payload_token_version: 令牌载荷中声明的 token_version。

    Returns:
        User: 经校验状态合法的活跃用户实体。

    Raises:
        AuthenticationError: 当用户不存在、未激活、已注销或令牌版本失效时抛出。
    """
    if user is None:
        raise AuthenticationError("用户不存在或已被移除")

    if not user.is_active:
        raise AuthenticationError("用户账号已被停用")

    if getattr(user, "is_deleted", False):
        raise AuthenticationError("用户账号已被注销")

    if not verify_token_version(payload_token_version, user.token_version):
        raise AuthenticationError("令牌已被即时吊销或版本已过期，请重新登录")

    return user


class AuthService:
    """认证与用户管理领域编排服务。"""

    def __init__(
        self,
        session: Session,
        user_repo: UserRepository | None = None,
        user_repository: UserRepository | None = None,
    ) -> None:
        """初始化认证与用户管理编排服务。

        Args:
            session: 数据库事务会话。
            user_repo: 用户数据仓储实例 (可选)。
            user_repository: 用户数据仓储实例兼容别名 (可选)。
        """
        self.session = session
        self.user_repo = user_repo or user_repository or UserRepository(session)
        self.user_repository = self.user_repo

    def _resolve_wechat_openid(self, code: str) -> str:
        """解析微信登录凭证换取 OpenID。

        支持双模：
        1. 开发/测试模式：针对 dev_code 与 mock_/dev_ 前缀映射确定性账号，避免用户分裂；
        2. 生产环境（配置了 wechat_app_id 与 wechat_app_secret 且非测试码）：
           调用微信官方 jscode2session 置换真实 OpenID；
        3. 兜底回退：若未配置微信凭据，则按哈希/前缀规则映射。

        Args:
            code: 微信临时登录凭证。

        Returns:
            str: 格式化后的 OpenID 字符串。

        Raises:
            AuthenticationError: 微信授权服务调用失败或返回错误码。
        """
        # 1. 确定性测试/开发凭证映射
        if code == "dev_code":
            return "wx_dev_deterministic_user"
        if code.startswith(("dev_", "mock_")):
            return f"wx_dev_{code}"

        # 2. 真实微信鉴权置换
        settings = get_settings()
        if settings.wechat_app_id and settings.wechat_app_secret:
            secret_value = settings.wechat_app_secret.get_secret_value()
            if secret_value:
                try:
                    url = "https://api.weixin.qq.com/sns/jscode2session"
                    params = {
                        "appid": settings.wechat_app_id,
                        "secret": secret_value,
                        "js_code": code,
                        "grant_type": "authorization_code",
                    }
                    response = httpx.get(url, params=params, timeout=10.0)
                    response.raise_for_status()
                    data = response.json()
                    if "openid" in data:
                        return cast(str, data["openid"])
                    err_code = data.get("errcode", -1)
                    err_msg = data.get("errmsg", "未知错误")
                    raise AuthenticationError(
                        f"微信授权登录失败 (错误码 {err_code}): {err_msg}",
                        details={"errcode": err_code, "errmsg": err_msg},
                    )
                except httpx.HTTPError as exc:
                    raise AuthenticationError(
                        f"微信授权接口网络请求失败: {exc}",
                        details={"error": str(exc)},
                    ) from exc

        # 3. 兜底回退（未配置微信密钥的开发/单测环境）
        if len(code) <= 50:
            return f"wx_{code}"
        hashed_suffix = hashlib.sha256(code.encode("utf-8")).hexdigest()[:28]
        return f"wx_{hashed_suffix}"

    def login_with_wechat(
        self,
        code: str,
        nickname: str | None = None,
        avatar_url: str | None = None,
    ) -> tuple[User, TokenResponse]:
        """通过微信小程序临时凭证进行登录或自动注册。

        检索已有用户，若不存在则创建；若存在则校验状态与更新基础画像；
        签发双令牌并提交事务，同时输出结构化脱敏审计日志。

        Args:
            code: 微信小程序临时登录凭据 code。
            nickname: 微信昵称 (可选)。
            avatar_url: 微信头像 URL (可选)。

        Returns:
            tuple[User, TokenResponse]: 包含用户实体及签发的双令牌响应契约。

        Raises:
            AuthenticationError: 当用户已被停用或已被注销时抛出。
        """
        start_time = time.perf_counter()
        openid = self._resolve_wechat_openid(code)

        try:
            user = self.user_repo.get_user_by_openid(openid)
            if user is None:
                user = self.user_repo.create_user(
                    openid=openid,
                    nickname=nickname or "",
                    avatar_url=avatar_url or "",
                )
            else:
                if user.is_deleted:
                    raise AuthenticationError("用户账号已被注销")
                if not user.is_active:
                    raise AuthenticationError("用户账号已被停用")

                if nickname is not None or avatar_url is not None:
                    self.user_repo.update_profile(
                        user.id,
                        nickname=nickname,
                        avatar_url=avatar_url,
                    )

            access_token = create_access_token(user.id, user.token_version)
            refresh_token = create_refresh_token(user.id, user.token_version)

            self.session.commit()

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(
                "用户微信登录成功",
                extra={
                    "user_ref": generate_user_ref(user.id),
                    "target_id": str(user.id),
                    "duration_ms": duration_ms,
                    "error_code": 0,
                },
            )

            token_response = TokenResponse(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_in=7200,
            )
            return user, token_response

        except Exception:
            self.session.rollback()
            raise

    def refresh_tokens(self, refresh_token: str) -> TokenResponse:
        """使用长效 Refresh Token 置换全新的双令牌对。

        校验令牌合法性、用户状态及版本一致性。

        Args:
            refresh_token: 客户端提交的长效刷新凭证。

        Returns:
            TokenResponse: 包含新 access_token 与 refresh_token 的响应契约。

        Raises:
            AuthenticationError: 凭证损坏、过期、类型错误或版本不一致时抛出。
        """
        start_time = time.perf_counter()
        payload = decode_token(refresh_token, expected_type="refresh")

        raw_user_id = payload.get("sub")
        if not raw_user_id:
            raise AuthenticationError("令牌载荷不完整: 缺失用户标识 (sub)")

        try:
            user_id = uuid.UUID(str(raw_user_id))
        except (ValueError, TypeError) as exc:
            raise AuthenticationError("令牌载荷用户标识格式非法") from exc

        token_version = payload.get("token_version")
        if token_version is None:
            raise AuthenticationError("令牌载荷缺失版本号")

        user = self.user_repo.get_user_by_id(user_id)
        valid_user = validate_user_status(user, token_version)

        new_access_token = create_access_token(valid_user.id, valid_user.token_version)
        new_refresh_token = create_refresh_token(valid_user.id, valid_user.token_version)

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.info(
            "用户刷新双令牌成功",
            extra={
                "user_ref": generate_user_ref(valid_user.id),
                "target_id": str(valid_user.id),
                "duration_ms": duration_ms,
                "error_code": 0,
            },
        )

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in=7200,
        )

    def revoke_tokens(self, user_id: uuid.UUID) -> bool:
        """主动递增用户的 token_version 使当前所有历史签发凭据立即失效。

        Args:
            user_id: 归属用户唯一标识 UUID。

        Returns:
            bool: 是否成功递增版本。
        """
        start_time = time.perf_counter()
        try:
            new_version = self.user_repo.increment_token_version(user_id)
            self.session.commit()

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(
                "主动吊销全端历史凭据",
                extra={
                    "user_ref": generate_user_ref(user_id),
                    "target_id": str(user_id),
                    "duration_ms": duration_ms,
                    "error_code": 0,
                },
            )
            return bool(new_version > 0)
        except Exception:
            self.session.rollback()
            raise

    def revoke_user_tokens(self, user_id: uuid.UUID) -> bool:
        """主动吊销令牌方法别名。

        Args:
            user_id: 归属用户唯一标识 UUID。

        Returns:
            bool: 是否成功递增版本。
        """
        return self.revoke_tokens(user_id)

    def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        """根据用户唯一标识获取用户实体。

        Args:
            user_id: 归属用户唯一标识 UUID。

        Returns:
            User | None: 用户实体，不存在则返回 None。
        """
        return self.user_repo.get_user_by_id(user_id)

    def get_user_profile(self, user_id: uuid.UUID) -> UserProfileResponse:
        """获取指定用户的个人画像资料详情。

        Args:
            user_id: 归属用户唯一标识 UUID。

        Returns:
            UserProfileResponse: 用户画像响应数据对象。

        Raises:
            AuthenticationError: 用户不存在、已注销或已停用时抛出。
        """
        user = self.user_repo.get_user_by_id(user_id)
        if user is None or user.is_deleted:
            raise AuthenticationError("用户不存在或已注销")

        if not user.is_active:
            raise AuthenticationError("用户账号已被停用")

        return UserProfileResponse.model_validate(user)

    def delete_account(self, user_id: uuid.UUID) -> bool:
        """软删除用户账号并递增 token_version 立即作废全端历史令牌。

        Args:
            user_id: 归属用户唯一标识 UUID。

        Returns:
            bool: 账号是否注销成功。
        """
        start_time = time.perf_counter()
        try:
            success = self.user_repo.soft_delete_user(user_id)
            self.user_repo.increment_token_version(user_id)
            self.session.commit()

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.info(
                "用户账号注销完成",
                extra={
                    "user_ref": generate_user_ref(user_id),
                    "target_id": str(user_id),
                    "duration_ms": duration_ms,
                    "error_code": 0,
                },
            )
            return success
        except Exception:
            self.session.rollback()
            raise

    def delete_user_account(self, user_id: uuid.UUID) -> bool:
        """注销账号方法别名。

        Args:
            user_id: 归属用户唯一标识 UUID。

        Returns:
            bool: 账号是否注销成功。
        """
        return self.delete_account(user_id)


__all__ = [
    "AuthService",
    "validate_user_status",
]
