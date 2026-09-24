"""练习核心纯函数算法模块。

包含组卷题目同知识点不相邻打散贪心算法。
严格遵循 AGENTS.md 规范：
- 纯函数计算核，绝对禁止导入 fastapi, sqlalchemy, httpx, redis, boto3；
- 严禁导入 app/services 与 app/repositories；
- 环路复杂度 V(G) <= 8，分支覆盖率 100%。
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from typing import Any


def _extract_knowledge_id(
    item: Any,
    getter: Callable[[Any], Any] | None,
) -> Any:
    """提取题目对象的知识点标识纯函数。"""
    if getter is not None:
        return getter(item)
    if isinstance(item, dict):
        return item.get("knowledge_point_id")
    if hasattr(item, "knowledge_point_id"):
        return item.knowledge_point_id
    return item


def _build_knowledge_buckets[T](
    questions: Sequence[T],
    getter: Callable[[T], Any] | None,
) -> dict[Any, list[T]]:
    """将题目按知识点分组存入桶中，保留原有相对次序。"""
    buckets: dict[Any, list[T]] = defaultdict(list)
    for q in questions:
        kp_id = _extract_knowledge_id(q, getter)
        buckets[kp_id].append(q)
    return buckets


def _select_next_bucket_key[T](
    buckets: dict[Any, list[T]],
    last_kp_id: Any,
) -> Any:
    """基于剩余数量贪心选择下一个知识点桶的键。

    优先选取剩余题量最多且与上一题不同知识点的桶；
    若所有剩余桶均与上一题知识点相同，则回退选择该桶。
    """
    sorted_keys = sorted(buckets.keys(), key=lambda k: len(buckets[k]), reverse=True)
    for k in sorted_keys:
        if k != last_kp_id:
            return k
    return sorted_keys[0]


def scatter_adjacent_knowledge_questions[T](
    questions: Sequence[T],
    knowledge_id_getter: Callable[[T], Any] | None = None,
) -> list[T]:
    """根据知识点贪心打散题目序列，使得来自同一知识点的题目尽可能不相邻。

    算法契约：
    1. 若题目总数 <= 1 或全部属于同一知识点，直接返回原序列副本；
    2. 基于贪心频次交替排列，每次从非上一知识点的剩余桶中选取题量最多的题；
    3. 若某知识点占比超过 (N+1)//2 导致数学上必然相邻，尽可能最大化相邻间距；
    4. 纯函数实现，不包含任何 I/O、状态或时间依赖；环路复杂度 V(G) <= 8。

    Args:
        questions: 原始题目序列。
        knowledge_id_getter: 可选知识点标识提取函数。

    Returns:
        list[T]: 打散后的题目列表，包含所有原题目元素。
    """
    if len(questions) <= 1:
        return list(questions)

    buckets = _build_knowledge_buckets(questions, knowledge_id_getter)
    if len(buckets) <= 1:
        return list(questions)

    result: list[T] = []
    last_kp_id: Any = object()  # 初始非任何可能知识点 ID 的哨兵对象
    total_count = len(questions)

    while len(result) < total_count:
        next_key = _select_next_bucket_key(buckets, last_kp_id)
        chosen_item = buckets[next_key].pop(0)
        result.append(chosen_item)
        last_kp_id = next_key
        if not buckets[next_key]:
            del buckets[next_key]

    return result


__all__ = [
    "scatter_adjacent_knowledge_questions",
]
