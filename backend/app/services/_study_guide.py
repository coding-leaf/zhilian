"""考前精讲笔记单飞锁、思考模型容错解析与整章后台预热编排模块。"""

import json
import logging
import re
import threading
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.core.errors import (
    KnowledgeNotFoundError,
    LLMResponseFormatError,
    MaterialInvalidError,
    MaterialNotFoundError,
)
from app.core.security import generate_user_ref
from app.integrations.llm.protocol import LLMMessage, LLMOptions, LLMProtocol
from app.models.material import MaterialSnippet
from app.repositories.knowledge import KnowledgeRepository
from app.repositories.material import MaterialRepository
from app.schemas.knowledge import StudyGuideContent

logger = logging.getLogger(__name__)

_STUDY_GUIDE_LOCK_PREFIX: str = "zhilian:study_guide:lock:"
_STUDY_GUIDE_PREWARM_PREFIX: str = "zhilian:study_guide:prewarm:"
_STUDY_GUIDE_LOCK_TTL_SECONDS: int = 90
_STUDY_GUIDE_PREWARM_TTL_SECONDS: int = 86400
_STUDY_GUIDE_LOCK_WAIT_SECONDS: float = 25.0
_STUDY_GUIDE_POLL_INTERVAL_SECONDS: float = 0.5
_STUDY_GUIDE_LLM_MAX_TOKENS: int = 16384
_STUDY_GUIDE_LLM_TEMPERATURE: float = 0.25
_STUDY_GUIDE_LLM_TIMEOUT: float = 55.0

_RELEASE_LOCK_LUA = (
    'if redis.call("get", KEYS[1]) == ARGV[1] then '
    'return redis.call("del", KEYS[1]) '
    "else return 0 end"
)

_THINK_BLOCK_RE: re.Pattern[str] = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_JSON_FENCE_RE: re.Pattern[str] = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)

_LOCAL_LOCK_GUARD = threading.Lock()
_LOCAL_STUDY_GUIDE_LOCKS: dict[uuid.UUID, tuple[str, float]] = {}

_LOCAL_PREWARM_GUARD = threading.Lock()
_LOCAL_PREWARM_STATES: dict[uuid.UUID, dict[str, Any]] = {}


def resolve_study_guide_redis_client(source: Any, idempotency: Any = None) -> Any | None:
    """从 AppContainer 或 Queue/Idempotency 适配器提取可用 Redis 客户端（Duck-typed）。"""
    if source is None and idempotency is None:
        return None
    providers = getattr(source, "providers", None)
    if providers is not None:
        candidates = (getattr(providers, "queue", None), getattr(providers, "idempotency", None))
    else:
        candidates = (source, idempotency)
    for adapter in candidates:
        client = getattr(adapter, "_client", None)
        if (
            client is not None
            and callable(getattr(client, "get", None))
            and callable(getattr(client, "set", None))
        ):
            return client
    return None


def resolve_study_guide_queue(container: Any) -> Any | None:
    """安全从 AppContainer 提取任务队列适配器（避免路由层直接依赖 integrations）。"""
    providers = getattr(container, "providers", None)
    return getattr(providers, "queue", None) if providers is not None else None


def _lock_key(kp_id: uuid.UUID) -> str:
    return f"{_STUDY_GUIDE_LOCK_PREFIX}{kp_id}"


def _prewarm_key(version_id: uuid.UUID) -> str:
    return f"{_STUDY_GUIDE_PREWARM_PREFIX}{version_id}"


def _decode_redis_scalar(raw: Any) -> str:
    if raw is None:
        return ""
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _acquire_study_guide_lock(
    kp_id: uuid.UUID,
    token: str,
    *,
    redis_client: Any | None = None,
    ttl_seconds: int = _STUDY_GUIDE_LOCK_TTL_SECONDS,
) -> bool:
    """获取单考点精讲单飞锁（优先 Redis SET NX EX，降级进程内 TTL 锁）。"""
    if redis_client is not None:
        try:
            return bool(redis_client.set(_lock_key(kp_id), token, nx=True, ex=ttl_seconds))
        except Exception as exc:
            logger.warning("acquire study guide redis lock failed: %s", str(exc)[:160])

    now = time.monotonic()
    with _LOCAL_LOCK_GUARD:
        existing = _LOCAL_STUDY_GUIDE_LOCKS.get(kp_id)
        if existing is not None and existing[1] > now:
            return False
        _LOCAL_STUDY_GUIDE_LOCKS[kp_id] = (token, now + ttl_seconds)
        return True


def _release_study_guide_lock(
    kp_id: uuid.UUID,
    token: str,
    *,
    redis_client: Any | None = None,
) -> None:
    """按持有者 token 安全释放单飞锁，防止误删已过期重入的新锁。"""
    if redis_client is not None:
        key = _lock_key(kp_id)
        try:
            if callable(getattr(redis_client, "eval", None)):
                redis_client.eval(_RELEASE_LOCK_LUA, 1, key, token)
            elif _decode_redis_scalar(redis_client.get(key)) == token:
                redis_client.delete(key)
            return
        except Exception as exc:
            logger.warning("release study guide redis lock failed: %s", str(exc)[:160])

    with _LOCAL_LOCK_GUARD:
        existing = _LOCAL_STUDY_GUIDE_LOCKS.get(kp_id)
        if existing is not None and existing[0] == token:
            _LOCAL_STUDY_GUIDE_LOCKS.pop(kp_id, None)


def is_study_guide_locked(
    kp_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> bool:
    """查询指定考点单飞锁是否正在持有中。"""
    if redis_client is not None:
        try:
            if callable(getattr(redis_client, "exists", None)):
                return bool(redis_client.exists(_lock_key(kp_id)))
            return redis_client.get(_lock_key(kp_id)) is not None
        except Exception as exc:
            logger.warning("check study guide redis lock failed: %s", str(exc)[:160])

    now = time.monotonic()
    with _LOCAL_LOCK_GUARD:
        existing = _LOCAL_STUDY_GUIDE_LOCKS.get(kp_id)
        if existing is None:
            return False
        if existing[1] <= now:
            _LOCAL_STUDY_GUIDE_LOCKS.pop(kp_id, None)
            return False
        return True


def _set_prewarm_state(
    version_id: uuid.UUID,
    *,
    status: str,
    failed_kps: int,
    current_kp_name: str | None,
    redis_client: Any | None = None,
) -> None:
    """写入整章精讲预热瞬态进度（优先 Redis Hash，降级进程内缓存）。"""
    payload = {
        "status": status,
        "failed_kps": str(max(0, int(failed_kps))),
        "current_kp_name": (current_kp_name or "").strip(),
    }
    if redis_client is not None:
        key = _prewarm_key(version_id)
        try:
            if callable(getattr(redis_client, "hset", None)) and callable(
                getattr(redis_client, "expire", None)
            ):
                redis_client.hset(key, mapping=payload)
                redis_client.expire(key, _STUDY_GUIDE_PREWARM_TTL_SECONDS)
                return
            redis_client.set(
                key,
                json.dumps(payload, ensure_ascii=False),
                ex=_STUDY_GUIDE_PREWARM_TTL_SECONDS,
            )
            return
        except Exception as exc:
            logger.warning("set study guide prewarm state failed: %s", str(exc)[:160])

    with _LOCAL_PREWARM_GUARD:
        _LOCAL_PREWARM_STATES[version_id] = {
            "status": status,
            "failed_kps": max(0, int(failed_kps)),
            "current_kp_name": (current_kp_name or "").strip() or None,
        }


def _get_prewarm_state(
    version_id: uuid.UUID,
    *,
    redis_client: Any | None = None,
) -> dict[str, Any] | None:
    """读取整章精讲预热瞬态进度。"""
    if redis_client is not None:
        key = _prewarm_key(version_id)
        try:
            if callable(getattr(redis_client, "hgetall", None)):
                raw_map = redis_client.hgetall(key)
                if raw_map:
                    decoded = {
                        _decode_redis_scalar(k): _decode_redis_scalar(v) for k, v in raw_map.items()
                    }
                    return _normalize_prewarm_dict(decoded)
            else:
                raw_json = redis_client.get(key)
                if raw_json:
                    parsed = json.loads(_decode_redis_scalar(raw_json))
                    if isinstance(parsed, dict):
                        return _normalize_prewarm_dict(parsed)
        except Exception as exc:
            logger.warning("get study guide prewarm state failed: %s", str(exc)[:160])

    with _LOCAL_PREWARM_GUARD:
        cached = _LOCAL_PREWARM_STATES.get(version_id)
        return dict(cached) if cached is not None else None


def _normalize_prewarm_dict(raw: dict[str, Any]) -> dict[str, Any]:
    raw_failed = raw.get("failed_kps", 0)
    try:
        failed_kps = max(0, int(raw_failed))
    except (TypeError, ValueError):
        failed_kps = 0
    kp_name = str(raw.get("current_kp_name") or "").strip() or None
    return {
        "status": str(raw.get("status") or "idle"),
        "failed_kps": failed_kps,
        "current_kp_name": kp_name,
    }


def _extract_balanced_json_object(text: str) -> str | None:
    """从包含前导思考或解释文本的响应中提取最外层 JSON 对象。"""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if escaped:
            escaped = False
            continue
        if ch == "\\":
            if in_string:
                escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def _parse_study_guide_fallback_text(raw_content: str) -> StudyGuideContent:
    """容错解析思考模型文本输出（剥离 <think>、代码块并提取完整 JSON）。"""
    cleaned = _THINK_BLOCK_RE.sub("", raw_content or "").strip()
    fence_match = _JSON_FENCE_RE.search(cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    json_blob = _extract_balanced_json_object(cleaned) or cleaned
    data = json.loads(json_blob)
    guide = StudyGuideContent.model_validate(data)
    guide.schema_version = 1
    return guide


def _build_study_guide_messages(
    *,
    kp_name: str,
    kp_description: str,
    kp_structured: dict[str, Any] | None,
    snippet_items: Sequence[tuple[int, str, str]],
    sibling_names: Sequence[str],
) -> list[LLMMessage]:
    """构建单考点考前精讲笔记生成 Prompt（9 要素 + 防幻觉 + 字数预算）。"""
    system_prompt = (
        "你是一位经验丰富的大学理工科主讲教授与命题组考前复习导师。\n"
        "请基于所提供的教材原文切片，为当前核心考点撰写一份"
        "可直接用于考前冲刺复习的【深度考前精讲笔记】。\n"
        "【输出必须严格涵盖以下 9 个部分】\n"
        "1. exam_positioning：直观定位与考法（讲清解决什么问题、在本章知识体系中的作用、"
        "常见题型与考察方式；**严禁杜撰任何原文没有的考试频次百分比或星级标签**）；\n"
        "2. core_definition：完整严谨定义 + 通俗直觉类比"
        "（使用规范 Markdown 与 `$...$`/`$$...$$` LaTeX）；\n"
        "3. symbol_table：核心符号速查表（`symbol`, `meaning`, `note`，纯概念类可为 []）；\n"
        "4. key_formulas：核心结论公式组（使用独立 `$$...$$` 展示公式，纯概念类可为 []）；\n"
        "5. derivation_steps：逐步推导或算法流程链"
        "（`step_title`, `formula`, `explanation`，讲清每一步成立依据）；\n"
        "6. worked_examples：1~2 道典型例题（紧扣讲义原型或标准同构教学例题，"
        "含题干 `problem`、切入点 `solution_idea`、"
        "分步解答 `solution_steps` 与明确结论 `final_answer`）；\n"
        "7. comparisons：相邻易混概念对比（优先对照同章兄弟考点，"
        "写明共同点、本质区别与考场快速判别依据）；\n"
        "8. pitfalls：考场高频避坑（`mistake`, `why_wrong`, `correction`）；\n"
        "9. memory_anchors：2~4 条考前 30 秒速记锚点或口诀。\n"
        "【硬性要求】\n"
        "- 所有定义、符号体系与定理必须严格忠实于传入的原文切片，"
        "禁止编造原文不存在的定理编号或考频；\n"
        "- 精讲正文总字数控制在 1,400~2,400 汉字，推导严谨、步骤不跳步、结论可直接背诵；\n"
        "- 思考过程保持精炼，并严格按 Schema 输出结构化 JSON。"
    )

    lines: list[str] = [f"【目标考点】{kp_name}"]
    if kp_description:
        lines.append(f"【Stage 1 概述】{kp_description}")
    if isinstance(kp_structured, dict):
        summary = str(kp_structured.get("core_summary") or "").strip()
        if summary and summary != kp_description:
            lines.append(f"【核心摘要】{summary}")
        formulas = kp_structured.get("key_formulas")
        if isinstance(formulas, list) and formulas:
            lines.append("【核心公式线索】" + "；".join(str(item) for item in formulas[:4]))

    if sibling_names:
        lines.append("【同章相邻概念（供对比表优先参照）】" + "、".join(sibling_names[:10]))

    if snippet_items:
        lines.append("【教材原文切片】")
        for idx, page_ref, content in snippet_items:
            header = f"切片 #{idx}" + (f" ({page_ref})" if page_ref else "")
            lines.append(f"{header}:\n{content}")
    else:
        lines.append(
            "【教材原文切片】当前考点暂未关联原文切片，请严格围绕目标考点与概述展开标准学科精讲。"
        )

    return [
        LLMMessage(role="system", content=system_prompt),
        LLMMessage(role="user", content="\n\n".join(lines)),
    ]


def _invoke_study_guide_llm(
    llm: LLMProtocol,
    messages: Sequence[LLMMessage],
) -> StudyGuideContent:
    """调用大模型生成考前精讲，支持 thinking 模型纯文本 JSON 降级容错。"""
    options = LLMOptions(
        temperature=_STUDY_GUIDE_LLM_TEMPERATURE,
        max_tokens=_STUDY_GUIDE_LLM_MAX_TOKENS,
        timeout=_STUDY_GUIDE_LLM_TIMEOUT,
        tool_choice="auto",
    )
    try:
        guide, _ = llm.generate_structured(
            messages=messages,
            response_model=StudyGuideContent,
            options=options,
        )
        guide.schema_version = 1
        return guide
    except LLMResponseFormatError:
        schema_json = json.dumps(StudyGuideContent.model_json_schema(), ensure_ascii=False)
        fallback_messages = [
            *messages,
            LLMMessage(
                role="user",
                content=(
                    "请直接输出一个严格符合上述 StudyGuideContent JSON Schema 的纯 JSON 对象，"
                    "不要附带任何解释文字或额外标记。\n"
                    f"Schema: {schema_json[:2400]}"
                ),
            ),
        ]
        raw_resp = llm.generate(
            fallback_messages,
            LLMOptions(
                temperature=0.2,
                max_tokens=_STUDY_GUIDE_LLM_MAX_TOKENS,
                timeout=_STUDY_GUIDE_LLM_TIMEOUT,
            ),
        )
        try:
            return _parse_study_guide_fallback_text(raw_resp.content)
        except Exception as fallback_exc:
            raise LLMResponseFormatError(
                "考前精讲生成格式异常，请稍后重试",
                details={"reason": str(fallback_exc)[:200]},
            ) from fallback_exc


def _format_snippet_page_ref(snippet: MaterialSnippet) -> str:
    info = snippet.source_info if isinstance(snippet.source_info, dict) else {}
    source_ref = str(info.get("source_ref") or "").strip()
    if source_ref:
        return source_ref
    page_num = info.get("page_number", info.get("page_index"))
    page_end = info.get("page_end")
    if isinstance(page_num, int) and page_num >= 1:
        if isinstance(page_end, int) and page_end > page_num:
            return f"第 {page_num}-{page_end} 页"
        return f"第 {page_num} 页"
    return ""


def _validate_cached_guide(raw_guide: dict[str, Any]) -> StudyGuideContent:
    guide = StudyGuideContent.model_validate(raw_guide)
    if guide.schema_version <= 0:
        guide.schema_version = 1
    return guide


class StudyGuideCoordinator:
    """封装考前精讲单飞生成、永久缓存读取与整章后台预热逻辑。"""

    def __init__(
        self,
        *,
        knowledge_service: Any,
        knowledge_repo: KnowledgeRepository,
        material_repo: MaterialRepository,
        llm: LLMProtocol,
    ) -> None:
        self._service = knowledge_service
        self._knowledge_repo = knowledge_repo
        self._material_repo = material_repo
        self._llm = llm

    def _rollback_read_only(self) -> None:
        session = self._service.session
        if not session.new and not session.dirty and not session.deleted:
            session.rollback()

    def get_study_guide(
        self,
        *,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
        redis_client: Any | None = None,
    ) -> dict[str, Any]:
        """纯只读查询单考点精讲状态与永久缓存。"""
        point = self._knowledge_repo.get_by_id(knowledge_point_id, user_id)
        if point is None:
            raise KnowledgeNotFoundError(
                "请求的知识点不存在或已被删除",
                details={"knowledge_point_id": str(knowledge_point_id)},
            )
        if point.study_guide is not None:
            guide = _validate_cached_guide(point.study_guide)
            generated_at = point.study_guide_generated_at
            self._rollback_read_only()
            return {
                "knowledge_point_id": knowledge_point_id,
                "status": "ready",
                "study_guide": guide,
                "generated_at": generated_at,
            }
        self._rollback_read_only()
        locked = is_study_guide_locked(knowledge_point_id, redis_client=redis_client)
        return {
            "knowledge_point_id": knowledge_point_id,
            "status": "generating" if locked else "empty",
            "study_guide": None,
            "generated_at": None,
        }

    def generate_study_guide(
        self,
        *,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
        force: bool = False,
        redis_client: Any | None = None,
        lock_wait_seconds: float = _STUDY_GUIDE_LOCK_WAIT_SECONDS,
        poll_interval_seconds: float = _STUDY_GUIDE_POLL_INTERVAL_SECONDS,
    ) -> dict[str, Any]:
        """单飞防重生成考前精讲并永久写入 KnowledgePoint.study_guide。"""
        point = self._knowledge_repo.get_by_id(knowledge_point_id, user_id)
        if point is None:
            raise KnowledgeNotFoundError(
                "请求的知识点不存在或已被删除",
                details={"knowledge_point_id": str(knowledge_point_id)},
            )
        initial_generated_at = point.study_guide_generated_at
        if not force and point.study_guide is not None:
            guide = _validate_cached_guide(point.study_guide)
            self._rollback_read_only()
            return {
                "knowledge_point_id": knowledge_point_id,
                "status": "ready",
                "study_guide": guide,
                "generated_at": initial_generated_at,
            }
        self._rollback_read_only()

        lock_token = uuid.uuid4().hex
        acquired = _acquire_study_guide_lock(
            knowledge_point_id, lock_token, redis_client=redis_client
        )
        if acquired:
            try:
                return self._generate_with_lock_owned(
                    knowledge_point_id=knowledge_point_id,
                    user_id=user_id,
                    force=force,
                )
            finally:
                _release_study_guide_lock(knowledge_point_id, lock_token, redis_client=redis_client)

        return self._wait_for_inflight_generation(
            knowledge_point_id=knowledge_point_id,
            user_id=user_id,
            force=force,
            initial_generated_at=initial_generated_at,
            redis_client=redis_client,
            lock_wait_seconds=lock_wait_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    def _generate_with_lock_owned(
        self,
        *,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
        force: bool,
    ) -> dict[str, Any]:
        """持锁路径：短事务读快照并释放连接 → 事务外调 LLM → 短事务落库提交。"""
        start_time = time.perf_counter()
        point = self._knowledge_repo.get_by_id(knowledge_point_id, user_id)
        if point is None:
            raise KnowledgeNotFoundError(
                "请求的知识点不存在或已被删除",
                details={"knowledge_point_id": str(knowledge_point_id)},
            )
        if not force and point.study_guide is not None:
            guide = _validate_cached_guide(point.study_guide)
            generated_at = point.study_guide_generated_at
            self._rollback_read_only()
            return {
                "knowledge_point_id": knowledge_point_id,
                "status": "ready",
                "study_guide": guide,
                "generated_at": generated_at,
            }

        kp_name = point.name
        kp_description = point.description
        kp_structured = (
            dict(point.structured_content) if isinstance(point.structured_content, dict) else None
        )
        material_id = point.material_id
        version_id = point.version_id
        parent_id = point.parent_id

        clean_snippets = self._service.get_snippets_for_point(knowledge_point_id, user_id)
        snippet_items = [
            (snip.snippet_index, _format_snippet_page_ref(snip), snip.content)
            for snip in clean_snippets
        ]
        sibling_names = self._knowledge_repo.list_sibling_kp_names(
            material_id,
            version_id,
            user_id,
            exclude_kp_id=knowledge_point_id,
            parent_id=parent_id,
        )
        # 严格遵守短事务铁律：释放只读连接后再发起外部 LLM 请求
        self._rollback_read_only()

        messages = _build_study_guide_messages(
            kp_name=kp_name,
            kp_description=kp_description,
            kp_structured=kp_structured,
            snippet_items=snippet_items,
            sibling_names=sibling_names,
        )
        guide = _invoke_study_guide_llm(self._llm, messages)
        now = datetime.now(UTC)

        session = self._service.session
        try:
            target = self._knowledge_repo.get_by_id(knowledge_point_id, user_id)
            if target is None:
                raise KnowledgeNotFoundError(
                    "请求的知识点不存在或已被删除",
                    details={"knowledge_point_id": str(knowledge_point_id)},
                )
            target.study_guide = guide.model_dump()
            target.study_guide_generated_at = now
            target.study_guide_version = 1
            session.commit()
        except Exception:
            session.rollback()
            raise

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        logger.info(
            "knowledge point study guide generated",
            extra={
                "user_ref": generate_user_ref(user_id),
                "target_id": str(knowledge_point_id),
                "duration_ms": duration_ms,
                "error_code": 0,
                "action": "generate_study_guide",
            },
        )
        return {
            "knowledge_point_id": knowledge_point_id,
            "status": "ready",
            "study_guide": guide,
            "generated_at": now,
        }

    def _wait_for_inflight_generation(
        self,
        *,
        knowledge_point_id: uuid.UUID,
        user_id: uuid.UUID,
        force: bool,
        initial_generated_at: datetime | None,
        redis_client: Any | None,
        lock_wait_seconds: float,
        poll_interval_seconds: float,
    ) -> dict[str, Any]:
        """并发抢锁失败时短轮询等待首飞结果，超时返回 generating (202)。"""
        deadline = time.monotonic() + max(0.0, lock_wait_seconds)
        sleep_step = max(0.01, poll_interval_seconds)

        while time.monotonic() < deadline:
            time.sleep(min(sleep_step, max(0.01, deadline - time.monotonic())))
            point = self._knowledge_repo.get_by_id(knowledge_point_id, user_id)
            if point is None:
                raise KnowledgeNotFoundError(
                    "请求的知识点不存在或已被删除",
                    details={"knowledge_point_id": str(knowledge_point_id)},
                )
            locked_now = is_study_guide_locked(knowledge_point_id, redis_client=redis_client)
            has_fresh = point.study_guide is not None and (
                not force
                or point.study_guide_generated_at != initial_generated_at
                or not locked_now
            )
            if has_fresh and point.study_guide is not None:
                guide = _validate_cached_guide(point.study_guide)
                generated_at = point.study_guide_generated_at
                self._rollback_read_only()
                return {
                    "knowledge_point_id": knowledge_point_id,
                    "status": "ready",
                    "study_guide": guide,
                    "generated_at": generated_at,
                }
            self._rollback_read_only()
            if not locked_now:
                break

        return {
            "knowledge_point_id": knowledge_point_id,
            "status": "generating",
            "study_guide": None,
            "generated_at": None,
        }

    def _resolve_material_version(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID | None,
        user_id: uuid.UUID,
    ) -> uuid.UUID:
        material = self._material_repo.get_material_by_id(material_id, user_id)
        if material is None:
            raise MaterialNotFoundError(
                "请求的学习资料不存在或已被删除",
                details={"material_id": str(material_id)},
            )
        if version_id is None:
            return uuid.UUID(str(self._service.get_latest_version_id(material_id, user_id)))
        version = self._material_repo.get_version_by_id(version_id, user_id)
        if version is None or version.material_id != material_id:
            raise MaterialNotFoundError(
                "请求的资料版本不存在或已被删除",
                details={"material_id": str(material_id), "version_id": str(version_id)},
            )
        return version_id

    def prewarm_study_guides(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        force: bool = False,
        queue: Any | None = None,
        redis_client: Any | None = None,
    ) -> dict[str, Any]:
        """一键入队整章考前精讲后台预热（全部已就绪直接返回 completed 不入队）。"""
        resolved_version_id = self._resolve_material_version(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )
        leaves = self._knowledge_repo.list_leaf_study_guide_statuses(
            material_id, resolved_version_id, user_id
        )
        self._rollback_read_only()
        total_kps = len(leaves)
        ready_kps = sum(1 for _, _, has_guide in leaves if has_guide)

        if total_kps == 0:
            raise MaterialInvalidError(
                "当前资料暂无可用核心考点，请先完成资料解析",
                details={"material_id": str(material_id), "version_id": str(resolved_version_id)},
            )

        if not force and ready_kps >= total_kps:
            _set_prewarm_state(
                resolved_version_id,
                status="completed",
                failed_kps=0,
                current_kp_name=None,
                redis_client=redis_client,
            )
            return {
                "material_id": material_id,
                "version_id": resolved_version_id,
                "status": "completed",
                "total_kps": total_kps,
                "ready_kps": ready_kps,
            }

        existing = _get_prewarm_state(resolved_version_id, redis_client=redis_client)
        if not force and existing is not None and existing["status"] in ("queued", "running"):
            return {
                "material_id": material_id,
                "version_id": resolved_version_id,
                "status": existing["status"],
                "total_kps": total_kps,
                "ready_kps": ready_kps,
            }

        _set_prewarm_state(
            resolved_version_id,
            status="queued",
            failed_kps=0,
            current_kp_name=None,
            redis_client=redis_client,
        )
        if queue is not None:
            try:
                queue.enqueue(
                    "prewarm_study_guides",
                    {
                        "material_id": str(material_id),
                        "version_id": str(resolved_version_id),
                        "user_id": str(user_id),
                        "force": "true" if force else "false",
                    },
                    str(user_id),
                    priority=0,
                )
            except Exception:
                _set_prewarm_state(
                    resolved_version_id,
                    status="idle",
                    failed_kps=0,
                    current_kp_name=None,
                    redis_client=redis_client,
                )
                raise

        return {
            "material_id": material_id,
            "version_id": resolved_version_id,
            "status": "queued",
            "total_kps": total_kps,
            "ready_kps": ready_kps,
        }

    def get_study_guide_prewarm_status(
        self,
        *,
        material_id: uuid.UUID,
        user_id: uuid.UUID,
        version_id: uuid.UUID | None = None,
        redis_client: Any | None = None,
    ) -> dict[str, Any]:
        """查询整章考前精讲预热进度（DB 真相计数 + Redis Hash 瞬态进度）。"""
        resolved_version_id = self._resolve_material_version(
            material_id=material_id,
            version_id=version_id,
            user_id=user_id,
        )
        leaves = self._knowledge_repo.list_leaf_study_guide_statuses(
            material_id, resolved_version_id, user_id
        )
        self._rollback_read_only()
        total_kps = len(leaves)
        ready_kps = sum(1 for _, _, has_guide in leaves if has_guide)

        state = _get_prewarm_state(resolved_version_id, redis_client=redis_client)
        raw_status = state["status"] if state is not None else None
        failed_kps = state["failed_kps"] if state is not None else 0
        current_kp_name = state["current_kp_name"] if state is not None else None

        if total_kps > 0 and ready_kps >= total_kps and raw_status not in ("queued", "running"):
            effective_status = "completed"
            current_kp_name = None
            failed_kps = 0
        elif raw_status in ("queued", "running", "completed", "partial_failed"):
            if (
                raw_status in ("queued", "running")
                and total_kps > 0
                and ready_kps >= total_kps
                and failed_kps == 0
            ):
                effective_status = "completed"
                current_kp_name = None
            else:
                effective_status = raw_status
        else:
            effective_status = "idle"
            current_kp_name = None
            failed_kps = 0

        return {
            "material_id": material_id,
            "version_id": resolved_version_id,
            "status": effective_status,
            "total_kps": total_kps,
            "ready_kps": ready_kps,
            "failed_kps": failed_kps,
            "current_kp_name": current_kp_name,
        }

    def run_study_guide_prewarm(
        self,
        *,
        material_id: uuid.UUID,
        version_id: uuid.UUID,
        user_id: uuid.UUID,
        force: bool = False,
        redis_client: Any | None = None,
    ) -> dict[str, Any]:
        """Worker 入口：逐考点独立短事务调用 generate_study_guide 完成整章预热。"""
        leaves = self._knowledge_repo.list_leaf_study_guide_statuses(
            material_id, version_id, user_id
        )
        self._rollback_read_only()

        targets = [
            (kp_id, kp_name) for kp_id, kp_name, has_guide in leaves if force or not has_guide
        ]
        failed_kps = 0
        _set_prewarm_state(
            version_id,
            status="running",
            failed_kps=0,
            current_kp_name=targets[0][1] if targets else None,
            redis_client=redis_client,
        )

        for kp_id, kp_name in targets:
            _set_prewarm_state(
                version_id,
                status="running",
                failed_kps=failed_kps,
                current_kp_name=kp_name,
                redis_client=redis_client,
            )
            try:
                self.generate_study_guide(
                    knowledge_point_id=kp_id,
                    user_id=user_id,
                    force=force,
                    redis_client=redis_client,
                )
            except Exception as exc:
                self._service.session.rollback()
                failed_kps += 1
                logger.warning(
                    "prewarm study guide failed for kp",
                    extra={
                        "user_ref": generate_user_ref(user_id),
                        "target_id": str(kp_id),
                        "error_code": 30011,
                        "details": str(exc)[:180],
                    },
                )

        final_status = "partial_failed" if failed_kps > 0 else "completed"
        _set_prewarm_state(
            version_id,
            status=final_status,
            failed_kps=failed_kps,
            current_kp_name=None,
            redis_client=redis_client,
        )
        updated_leaves = self._knowledge_repo.list_leaf_study_guide_statuses(
            material_id, version_id, user_id
        )
        self._rollback_read_only()
        return {
            "material_id": material_id,
            "version_id": version_id,
            "status": final_status,
            "total_kps": len(updated_leaves),
            "ready_kps": sum(1 for _, _, has_guide in updated_leaves if has_guide),
            "failed_kps": failed_kps,
            "current_kp_name": None,
        }


def mark_study_guide_prewarm_failed(
    *,
    version_id: uuid.UUID,
    redis_client: Any | None = None,
) -> None:
    """RQ 终态失败回调辅助：将挂起的整章预热状态标为 partial_failed。"""
    existing = _get_prewarm_state(version_id, redis_client=redis_client)
    failed_count = max(1, existing["failed_kps"]) if existing is not None else 1
    _set_prewarm_state(
        version_id,
        status="partial_failed",
        failed_kps=failed_count,
        current_kp_name=None,
        redis_client=redis_client,
    )
