"""智练混合检索纯函数算法核模块。

严格遵循 AGENTS.md 规范：
- 仅包含纯函数，输入输出均为原生 Python 数据结构；
- 绝对禁止导入 fastapi, sqlalchemy, httpx, redis, boto3 等重型库；
- 严禁导入 app.services 与 app.repositories；
- 单函数环路复杂度 V(G) <= 8，分支覆盖率门禁 100%。
"""

import math
import re
from collections import Counter
from collections.abc import Sequence

# 中英文轻量分词正则：单个汉字或连续英文字母数字序列
_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fa5]|[a-z0-9]+")


def tokenize_text(text: str) -> list[str]:
    """对中英文字符串进行轻量分词与标准化。

    按单字切分中文汉字，按单词切分英文与数字，统一转换为小写，过滤空白与标点。

    Args:
        text: 待分词的原始字符串。

    Returns:
        list[str]: 分词后的词元序列。
    """
    if not text:
        return []
    lowered = text.lower()
    return _TOKEN_PATTERN.findall(lowered)


def compute_bm25_score(
    query_tokens: Sequence[str],
    doc_tokens: Sequence[str],
    doc_length: int,
    avg_doc_length: float,
    doc_frequencies: dict[str, int],
    total_docs: int,
    k1: float = 1.5,
    b: float = 0.75,
) -> float:
    """计算单个文档相对于查询项的 Okapi BM25 相关度得分。

    Args:
        query_tokens: 查询词元列表。
        doc_tokens: 候选文档词元列表。
        doc_length: 当前候选文档词元总数。
        avg_doc_length: 语料候选库平均文档长度。
        doc_frequencies: 词元在语料候选库中出现的文档频次映射字典。
        total_docs: 语料候选库总文档数。
        k1: 词频饱和度控制参数，默认 1.5（依据信息检索标准经验取值）。
        b: 文档长度归一化惩罚参数，默认 0.75（依据信息检索标准经验取值）。

    Returns:
        float: BM25 得分（非负数）。
    """
    if not query_tokens or not doc_tokens or total_docs <= 0:
        return 0.0

    actual_doc_length = doc_length if doc_length > 0 else len(doc_tokens)
    avg_len = avg_doc_length if avg_doc_length > 0 else 1.0
    doc_counter = Counter(doc_tokens)
    score = 0.0

    # 文档长度归一化分母项
    len_norm = 1.0 - b + b * (actual_doc_length / avg_len)

    for token in query_tokens:
        freq = doc_counter.get(token, 0)
        if freq == 0:
            continue
        doc_freq = doc_frequencies.get(token, 0)
        # 带平滑的 Okapi IDF 计算，避免负值
        idf = math.log((total_docs - doc_freq + 0.5) / (doc_freq + 0.5) + 1.0)
        tf = (freq * (k1 + 1.0)) / (freq + k1 * len_norm)
        score += idf * tf

    return max(0.0, score)


def reciprocal_rank_fusion(
    ranked_lists: Sequence[Sequence[str]],
    k: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[str, float]]:
    """基于倒数排名融合算法 (RRF) 合并多路有序文档检索结果。

    公式: RRF_Score(d) = sum_{m} w_m / (k + rank_m(d))

    Args:
        ranked_lists: 多路检索系统返回的文档唯一标识有序序列列表。
        k: 排名平滑常数，默认 60（根据 Cormack et al. 2009 经典基线取值）。
        weights: 对应每路检索通道的加权权重列表，缺省为全 1.0。

    Returns:
        list[tuple[str, float]]: 按 RRF 得分降序排序的 (doc_id, score) 元组列表。
    """
    if not ranked_lists:
        return []

    channel_weights = list(weights) if weights else [1.0] * len(ranked_lists)
    scores: dict[str, float] = {}

    for channel_index, ranked in enumerate(ranked_lists):
        weight = channel_weights[channel_index] if channel_index < len(channel_weights) else 1.0
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank)

    return sorted(scores.items(), key=lambda item: item[1], reverse=True)


def _normalize_score_map(scores: dict[str, float]) -> dict[str, float]:
    """对打分映射字典执行 Min-Max 归一化至 [0, 1] 区间。

    Args:
        scores: 文档 ID 到原始得分的映射字典。

    Returns:
        dict[str, float]: 归一化后的得分映射字典。
    """
    if not scores:
        return {}
    values = list(scores.values())
    min_val, max_val = min(values), max(values)
    if math.isclose(max_val, min_val):
        return {k: 1.0 for k in scores}
    return {k: (v - min_val) / (max_val - min_val) for k, v in scores.items()}


def weighted_score_fusion(
    vector_scores: dict[str, float],
    keyword_scores: dict[str, float],
    vector_weight: float = 0.7,
    keyword_weight: float = 0.3,
) -> list[tuple[str, float]]:
    """对向量相似度与关键词 BM25 得分执行 Min-Max 归一化后的加权线性融合。

    Args:
        vector_scores: 文档 ID 到向量相似度的映射字典。
        keyword_scores: 文档 ID 到 BM25 得分的映射字典。
        vector_weight: 向量通道权重，默认 0.7（根据混合检索经验配比）。
        keyword_weight: 关键词通道权重，默认 0.3（根据混合检索经验配比）。

    Returns:
        list[tuple[str, float]]: 降序排序的 (doc_id, score) 元组列表。
    """
    all_keys = set(vector_scores.keys()) | set(keyword_scores.keys())
    if not all_keys:
        return []

    norm_vector = _normalize_score_map(vector_scores)
    norm_keyword = _normalize_score_map(keyword_scores)

    combined: dict[str, float] = {}
    for doc_id in all_keys:
        v_score = norm_vector.get(doc_id, 0.0)
        k_score = norm_keyword.get(doc_id, 0.0)
        combined[doc_id] = vector_weight * v_score + keyword_weight * k_score

    return sorted(combined.items(), key=lambda item: item[1], reverse=True)


def cosine_similarity(vector_a: Sequence[float], vector_b: Sequence[float]) -> float:
    """计算两个同维度浮点向量的余弦相似度。

    Args:
        vector_a: 向量 A。
        vector_b: 向量 B。

    Returns:
        float: 余弦相似度，范围 [-1.0, 1.0]。
    """
    if len(vector_a) != len(vector_b) or not vector_a:
        return 0.0

    dot_product = sum(a * b for a, b in zip(vector_a, vector_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0

    raw_similarity = dot_product / (norm_a * norm_b)
    return max(-1.0, min(1.0, raw_similarity))


__all__ = [
    "compute_bm25_score",
    "cosine_similarity",
    "reciprocal_rank_fusion",
    "tokenize_text",
    "weighted_score_fusion",
]
