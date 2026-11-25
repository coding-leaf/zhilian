"""KaTeX 静态字体托管端点单元测试。"""

from starlette.testclient import TestClient

from app.main import app


def test_katex_woff2_font_served_with_immutable_cache_and_cors() -> None:
    """验证核心 .woff2 字体返回 200、正确 MIME、强缓存头与 CORS 头。"""
    with TestClient(app) as client:
        response = client.get("/static/fonts/katex/KaTeX_Main-Regular.woff2")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "public, max-age=31536000, immutable"
        assert response.headers.get("access-control-allow-origin") == "*"
        assert response.headers.get("content-type", "").startswith("font/woff2")
        assert len(response.content) > 1000


def test_katex_ttf_font_served_successfully() -> None:
    """验证兼容旧版 Android 的 .ttf 字体同样可正常获取。"""
    with TestClient(app) as client:
        response = client.get("/static/fonts/katex/KaTeX_Main-Regular.ttf")
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "public, max-age=31536000, immutable"
        assert response.headers.get("access-control-allow-origin") == "*"
        assert len(response.content) > 1000


def test_katex_font_rejects_path_traversal_and_non_font_files() -> None:
    """验证路径穿越 ../、编码穿越及非字体扩展名均返回 404。"""
    with TestClient(app) as client:
        for path in (
            "/static/fonts/katex/../main.py",
            "/static/fonts/katex/..%2F..%2Fmain.py",
            "/static/fonts/katex/sub/KaTeX_Main-Regular.woff2",
            "/static/fonts/katex/KaTeX_Main-Regular.css",
            "/static/fonts/katex/nonexistent.woff2",
        ):
            response = client.get(path)
            assert response.status_code == 404, (
                f"Expected 404 for {path}, got {response.status_code}"
            )
