"""Unit tests for shared FastAPI pagination dependency app.api.deps.pagination."""

from app.api.deps import PaginationParams, get_pagination_params


def test_get_pagination_params_defaults_and_page_mode() -> None:
    """Verify default values and standard page/page_size offset calculation."""
    default_params = get_pagination_params()
    assert isinstance(default_params, PaginationParams)
    assert default_params == PaginationParams(page=1, page_size=20, limit=20, offset=0, raw_page=1)

    paged = get_pagination_params(page=3, page_size=15)
    assert paged == PaginationParams(page=3, page_size=15, limit=15, offset=30, raw_page=3)


def test_get_pagination_params_cursor_limit_offset_override() -> None:
    """Verify limit/offset override derives compatible page number while keeping raw_page."""
    params = get_pagination_params(page=2, page_size=20, limit=5, offset=10)
    assert params.limit == 5
    assert params.offset == 10
    assert params.page == 3
    assert params.raw_page == 2
    assert params.page_size == 20
