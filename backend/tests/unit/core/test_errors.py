"""Unit tests for the unified business exception hierarchy in app/core/errors.py."""

from app.core.errors import AppError, AuthenticationError, PermissionDeniedError


class TestAppErrors:
    """Test suite for AppError and derived domain exceptions."""

    def test_app_error_defaults(self) -> None:
        """Verify AppError default attributes."""
        error = AppError()
        assert error.error_code == 40000
        assert error.code == 40000
        assert error.status_code == 400
        assert error.message == "系统业务处理异常"
        assert error.details == {}
        assert error.detail == {}
        assert error.to_dict() == {
            "code": 40000,
            "message": "系统业务处理异常",
            "details": {},
        }

    def test_app_error_custom_fields(self) -> None:
        """Verify AppError custom initialization with alias parameters."""
        error = AppError(
            code=40005,
            message="自定义验证错误",
            status_code=422,
            detail={"field": "username"},
        )
        assert error.error_code == 40005
        assert error.code == 40005
        assert error.status_code == 422
        assert error.details == {"field": "username"}
        assert error.detail == {"field": "username"}
        assert error.to_dict() == {
            "code": 40005,
            "message": "自定义验证错误",
            "details": {"field": "username"},
        }

    def test_authentication_error(self) -> None:
        """Verify AuthenticationError code and default status."""
        error = AuthenticationError(message="Token expired", detail={"sub": "123"})
        assert error.error_code == 20001
        assert error.code == 20001
        assert error.status_code == 401
        assert error.message == "Token expired"
        assert error.details == {"sub": "123"}
        assert error.detail == {"sub": "123"}

    def test_permission_denied_error(self) -> None:
        """Verify PermissionDeniedError code and default status."""
        error = PermissionDeniedError(message="Access denied", detail={"resource": "notes"})
        assert error.error_code == 20002
        assert error.code == 20002
        assert error.status_code == 403
        assert error.message == "Access denied"
        assert error.details == {"resource": "notes"}
        assert error.detail == {"resource": "notes"}
