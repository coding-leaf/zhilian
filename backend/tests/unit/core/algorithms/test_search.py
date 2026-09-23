"""智练混合检索纯函数算法核单元测试套件。

严格遵循 AGENTS.md 规范：
- 零外部网络、零数据库依赖；
- 边界值、等价类与极端输入覆盖；
- 分支覆盖率目标 100%。
"""

import math

from app.core.algorithms.search import (
    _normalize_score_map,
    compute_bm25_score,
    cosine_similarity,
    reciprocal_rank_fusion,
    tokenize_text,
    weighted_score_fusion,
)


class TestTokenizeText:
    """分词与文本标准化单元测试。"""

    def test_tokenize_text_chinese_and_english(self) -> None:
        """测试中英文混合、标点符号过滤与小写转换。"""
        text = "智练 AI 平台 v1.0 架构！"
        tokens = tokenize_text(text)
        expected = ["智", "练", "ai", "平", "台", "v1", "0", "架", "构"]
        assert tokens == expected

    def test_tokenize_text_empty_and_spaces(self) -> None:
        """测试空字符串、全空格与纯标点符号。"""
        assert tokenize_text("") == []
        assert tokenize_text("   \t\n  ") == []
        assert tokenize_text("!@#$%^&*()_+-=[]{}|;':\",./<>?") == []

    def test_tokenize_text_digits_and_alphanumeric(self) -> None:
        """测试纯英文、数字及驼峰大小写归一化。"""
        assert tokenize_text("OpenAI GPT4o") == ["openai", "gpt4o"]


class TestComputeBM25Score:
    """Okapi BM25 评分纯函数单元测试。"""

    def test_bm25_exact_match_higher_score(self) -> None:
        """测试高频匹配词文档得分高于低频或未匹配文档。"""
        query = ["智", "练", "架", "构"]
        doc1 = ["智", "练", "自", "主", "学", "习", "平", "台", "架", "构", "设", "计"]
        doc2 = ["今", "天", "天", "气", "真", "好"]

        doc_frequencies = {"智": 1, "练": 1, "架": 1, "构": 1}
        total_docs = 2
        avg_doc_len = 9.0

        score1 = compute_bm25_score(
            query_tokens=query,
            doc_tokens=doc1,
            doc_length=len(doc1),
            avg_doc_length=avg_doc_len,
            doc_frequencies=doc_frequencies,
            total_docs=total_docs,
        )
        score2 = compute_bm25_score(
            query_tokens=query,
            doc_tokens=doc2,
            doc_length=len(doc2),
            avg_doc_length=avg_doc_len,
            doc_frequencies=doc_frequencies,
            total_docs=total_docs,
        )

        assert score1 > 0.0
        assert score2 == 0.0

    def test_bm25_zero_length_and_empty_inputs(self) -> None:
        """测试边界防御：空查询、空候选词、总文档数为0。"""
        assert (
            compute_bm25_score(
                query_tokens=[],
                doc_tokens=["智", "练"],
                doc_length=2,
                avg_doc_length=2.0,
                doc_frequencies={"智": 1},
                total_docs=1,
            )
            == 0.0
        )

        assert (
            compute_bm25_score(
                query_tokens=["智"],
                doc_tokens=[],
                doc_length=0,
                avg_doc_length=2.0,
                doc_frequencies={"智": 1},
                total_docs=1,
            )
            == 0.0
        )

        assert (
            compute_bm25_score(
                query_tokens=["智"],
                doc_tokens=["智"],
                doc_length=1,
                avg_doc_length=1.0,
                doc_frequencies={"智": 1},
                total_docs=0,
            )
            == 0.0
        )

    def test_bm25_doc_length_fallback_and_avg_len_fallback(self) -> None:
        """测试 doc_length <= 0 时回退与 avg_doc_length <= 0 时回退。"""
        query = ["智"]
        doc = ["智", "练"]
        score = compute_bm25_score(
            query_tokens=query,
            doc_tokens=doc,
            doc_length=-1,  # 触发回退 len(doc)
            avg_doc_length=-1.0,  # 触发回退 1.0
            doc_frequencies={"智": 1},
            total_docs=5,
        )
        assert score > 0.0


class TestReciprocalRankFusion:
    """倒数排名融合 (RRF) 单元测试。"""

    def test_rrf_rank_aggregation(self) -> None:
        """测试双通道高排位文档优先于单通道高排位文档。"""
        # doc_a 在通道1排第1，在通道2排第2
        # doc_b 在通道1排第2，在通道2排第1
        # doc_c 仅在通道1排第10
        ranked_channel_1 = ["doc_a", "doc_b", "doc_c"]
        ranked_channel_2 = ["doc_b", "doc_a"]

        results = reciprocal_rank_fusion([ranked_channel_1, ranked_channel_2], k=60)
        assert len(results) == 3
        top_docs = [r[0] for r in results]
        assert top_docs[0] in ("doc_a", "doc_b")
        assert top_docs[1] in ("doc_a", "doc_b")
        assert top_docs[2] == "doc_c"
        assert results[0][1] > results[2][1]

    def test_rrf_empty_inputs(self) -> None:
        """测试空输入边界。"""
        assert reciprocal_rank_fusion([]) == []

    def test_rrf_custom_weights(self) -> None:
        """测试通道加权及权重列表长度短于通道数时的默认回退。"""
        ranked_channel_1 = ["doc_1", "doc_2"]
        ranked_channel_2 = ["doc_2", "doc_1"]
        # 权重列表只给第1路赋 2.0，第2路缺省回退 1.0
        results = reciprocal_rank_fusion([ranked_channel_1, ranked_channel_2], k=60, weights=[2.0])
        # doc_1 在第1路第一 (rank=1) 权重 2.0；在第2路第二 (rank=2) 权重 1.0
        # doc_2 在第1路第二 (rank=2) 权重 2.0；在第2路第一 (rank=1) 权重 1.0
        # doc_1 得分: 2/(60+1) + 1/(60+2) = 2/61 + 1/62 = 0.032786 + 0.016129 = 0.048915
        # doc_2 得分: 2/(60+2) + 1/(60+1) = 2/62 + 1/61 = 0.032258 + 0.016393 = 0.048651
        assert results[0][0] == "doc_1"


class TestWeightedScoreFusion:
    """加权归一化融合单元测试。"""

    def test_weighted_fusion_normalization(self) -> None:
        """测试大尺度差异下的 Min-Max 归一化线性融合。"""
        vec_scores = {"doc_1": 0.9, "doc_2": 0.5, "doc_3": 0.1}
        bm25_scores = {"doc_1": 10.0, "doc_2": 50.0, "doc_3": 5.0}

        fused = weighted_score_fusion(
            vector_scores=vec_scores,
            keyword_scores=bm25_scores,
            vector_weight=0.7,
            keyword_weight=0.3,
        )
        assert len(fused) == 3
        # 所有文档均被融合计算
        doc_ids = [item[0] for item in fused]
        assert set(doc_ids) == {"doc_1", "doc_2", "doc_3"}

    def test_weighted_fusion_empty_and_single_value(self) -> None:
        """测试空输入与单值分数的特殊归一化场景。"""
        assert weighted_score_fusion({}, {}) == []

        # 单值或所有分数相等（max_val == min_val）
        vec_scores = {"doc_1": 0.8, "doc_2": 0.8}
        bm25_scores = {"doc_1": 5.0, "doc_2": 5.0}
        fused = weighted_score_fusion(vec_scores, bm25_scores)
        assert len(fused) == 2
        assert math.isclose(fused[0][1], 1.0)
        assert math.isclose(fused[1][1], 1.0)

    def test_normalize_score_map_empty(self) -> None:
        """测试归一化私有辅助函数处理空字典。"""
        assert _normalize_score_map({}) == {}


class TestCosineSimilarity:
    """余弦相似度计算单元测试。"""

    def test_cosine_similarity_orthogonal_and_same(self) -> None:
        """测试相同向量、正交向量与反向向量。"""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [1.0, 0.0, 0.0]
        vec_c = [0.0, 1.0, 0.0]
        vec_d = [-1.0, 0.0, 0.0]

        assert math.isclose(cosine_similarity(vec_a, vec_b), 1.0)
        assert math.isclose(cosine_similarity(vec_a, vec_c), 0.0)
        assert math.isclose(cosine_similarity(vec_a, vec_d), -1.0)

    def test_cosine_similarity_zeros_and_mismatched(self) -> None:
        """测试维度不一致、全零向量与空向量。"""
        assert cosine_similarity([], []) == 0.0
        assert cosine_similarity([1.0, 2.0], [1.0]) == 0.0
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0
        assert cosine_similarity([1.0, 1.0], [0.0, 0.0]) == 0.0
