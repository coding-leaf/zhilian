# Technical Design — M2: 废代码废依赖清退与跨层P0快修

## 1. Parallel Track Architecture & Zero-Collision Isolation

本里程碑基于 `M1` 落盘后的临时基准引用 `refs/swarm-opt/m1-base` 派生 **前后端完全物理隔离的双轨 `share` Swarm**：

- **`be-hygiene`（`workspace: "share"`，`model: "gemini-4-hydrogen-high"`）**：严格只允许修改 `backend/**`（`pyproject.toml`、`uv.lock`、`backend/app/**`、`backend/tests/**`）。
- **`fe-hygiene`（`workspace: "share"`，`model: "gemini-4-hydrogen-high"`）**：严格只允许修改 `miniprogram/**`（`package.json`、`pnpm-lock.yaml`、`miniprogram/src/**`、`miniprogram/tests/**`）。
- **`verifier-m2`（`workspace: "inherit"`，`model: "gemini-4-hydrogen-high"`）**：交叉核验 `be-hygiene` 与 `fe-hygiene` 的提交差异、零误删 25 个扩展路由、跨层契约对齐及双端门禁结果。

两个作者轨道的文件集合交集为 **空集（`∅`）**，合并零冲突。

## 2. Key Technical Contracts

### 2.1 Backend DI Session Factory (`backend/app/api/deps/_factory.py`)
```python
from collections.abc import Callable, Generator
from typing import TypeVar
from fastapi import Depends
from sqlalchemy.orm import Session
from app.api.deps.container import get_app_container
from app.api.deps.db import get_db_session
from app.container import AppContainer

T = TypeVar("T")

def make_service_dep(builder: Callable[[AppContainer, Session], T]) -> Callable[..., Generator[T, None, None]]:
    def _dep(
        container: AppContainer = Depends(get_app_container),
        session: Session = Depends(get_db_session),
    ) -> Generator[T, None, None]:
        if isinstance(session, Session):
            yield builder(container, session)
        else:
            with container.get_session() as managed_session:
                yield builder(container, managed_session)
    return _dep
```
> **注意兼容性**：检查现有测试是否直接无参或位置参数调用 `get_<domain>_service(container=..., session=...)`（如 `test_deps_supplemental.py`）——若测试预期直接调用返回实例而非 generator，或 FastAPI `Depends` 支持 generator，`be-hygiene` 必须先阅读 `backend/tests/unit/api/test_deps_supplemental.py` 与 `test_user_deps.py`，确保与 `user.py` 的 generator 契约及单测 100% 兼容！

### 2.2 `POST /practices` Single Round-Trip Alignment
- 检查 `backend/app/services/practice.py::create_practice` 与 `get_practice`：确保 `create_practice` 返回的 `PracticeDetailResponse` 同样挂载 `source_snippet`（与 `get_practice` 一致），使前端 `apiCreatePractice` 可直接 `return adaptPractice(await post<WirePractice>('/practices', payload))`，省去多余的 `GET /practices/{id}` 二次请求。

### 2.3 Knowledge Snippet Cross-Layer Alignment
- 后端 `SnippetSourceResponse`（保持不变）：`{ id, material_id, version_id, page_index, snippet_index, chapter_title, content, char_length }`（注：核查 `page_index` 是 0-based 还是 1-based——先读 `backend/app/core/algorithms/material_chunking.py` 与 `services/material.py` 确认 `page_index` 起始基数，再在前端适配器/视图层准确展示页码！）。
- 前端 `KnowledgeSnippet` 更新为 `{ id, material_id, version_id, page_index, snippet_index, chapter_title: string | null, content, char_length }`，`course/index.vue` 渲染真实页码与章节标题。
