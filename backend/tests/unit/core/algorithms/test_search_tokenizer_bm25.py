"""Unit tests for the math-aware tokenizer and smoothed BM25 length normalization."""

import math

from app.core.algorithms.search import (
    MIN_EFFECTIVE_DOC_LENGTH,
    compute_bm25_score,
    tokenize_text,
)


class TestTokenizerGreekAndLatex:
    def test_greek_letters_preserved_as_single_tokens(self) -> None:
        assert tokenize_text("σi=1") == ["σ", "i", "1"]
        assert tokenize_text("αβγ") == ["α", "β", "γ"]

    def test_uppercase_greek_lowercased_and_final_sigma_normalized(self) -> None:
        assert tokenize_text("Σ") == ["σ"]
        assert tokenize_text("Δθ") == ["δ", "θ"]
        assert tokenize_text("ς") == ["σ"]
        assert tokenize_text("ΑΣ") == ["α", "σ"]  # str.lower() 会把词尾 Σ 变成 ς

    def test_latex_command_strips_backslash_and_adds_greek_letter(self) -> None:
        assert tokenize_text(r"\sigma") == ["sigma", "σ"]
        assert tokenize_text(r"\Sigma_i") == ["sigma", "σ", "i"]
        assert tokenize_text(r"\alpha + \beta") == ["alpha", "α", "beta", "β"]

    def test_non_greek_latex_command_kept_without_letter(self) -> None:
        assert tokenize_text(r"\frac{a}{b}") == ["frac", "a", "b"]
        assert tokenize_text(r"\sum_{i=1}^{k}") == ["sum", "i", "1", "k"]
        assert tokenize_text(r"\mathbb{R}") == ["mathbb", "r"]

    def test_latex_and_pdf_forms_share_a_token(self) -> None:
        assert "σ" in tokenize_text(r"$\sigma_i$")
        assert "σ" in tokenize_text("σi")

    def test_underscore_identifiers_stay_whole(self) -> None:
        assert tokenize_text("snake_case x_1 __init__") == ["snake_case", "x_1", "init"]
        assert tokenize_text("_ __ ___") == []

    def test_alnum_and_decimal_behaviour_unchanged(self) -> None:
        assert tokenize_text("v1.0 GPT4o 3.14") == ["v1", "0", "gpt4o", "3", "14"]

    def test_punctuation_only_still_empty(self) -> None:
        assert tokenize_text("!@#$%^&*()+-=[]{}|;':\",./<>?\\") == []
        assert tokenize_text("") == []

    def test_mixed_formula_sentence(self) -> None:
        tokens = tokenize_text("奇异值 σ_i 满足 rank=k")
        assert "σ" in tokens
        assert "i" in tokens
        assert "rank" in tokens
        assert "奇异" in tokens
        assert "异值" in tokens


class TestTokenizerChinese:
    def test_unigrams_then_bigrams(self) -> None:
        assert tokenize_text("智练平台") == ["智", "练", "平", "台", "智练", "练平", "平台"]

    def test_single_char_run_has_no_bigram(self) -> None:
        assert tokenize_text("我") == ["我"]

    def test_bigrams_do_not_cross_non_chinese_boundaries(self) -> None:
        tokens = tokenize_text("深度ai学习")
        assert "深度" in tokens
        assert "学习" in tokens
        assert "度a" not in tokens
        assert "ai" in tokens
        assert "度学" not in tokens

    def test_bigrams_do_not_cross_punctuation_or_space(self) -> None:
        tokens = tokenize_text("机器，学习 模型")
        assert "器学" not in tokens
        assert "习模" not in tokens
        assert "机器" in tokens
        assert "模型" in tokens

    def test_unigram_precision_preserved(self) -> None:
        tokens = tokenize_text("机器学习")
        for char in "机器学习":
            assert char in tokens

    def test_bigram_count(self) -> None:
        run = "一二三四五"
        tokens = tokenize_text(run)
        assert len(tokens) == 5 + 4


def _bm25(doc: list[str], query: list[str], avg: float, total: int = 100) -> float:
    return compute_bm25_score(
        query_tokens=query,
        doc_tokens=doc,
        doc_length=len(doc),
        avg_doc_length=avg,
        doc_frequencies={t: 10 for t in query},
        total_docs=total,
    )


class TestBM25Smoothing:
    def test_min_doc_length_constant(self) -> None:
        assert MIN_EFFECTIVE_DOC_LENGTH == 25.0

    def test_short_fragment_does_not_outscore_rich_paragraph(self) -> None:
        query = ["奇异", "值", "分解", "秩"]
        fragment = ["奇异", "x"]
        rich = ["奇异", "值", "分解", "秩"] + [f"w{i}" for i in range(110)]
        avg = 100.0
        assert _bm25(rich, query, avg) > _bm25(fragment, query, avg)

    def test_length_below_floor_scores_like_floor_length(self) -> None:
        query = ["a"]
        avg = 100.0
        short2 = ["a", "x"]
        short20 = ["a"] + [f"x{i}" for i in range(19)]
        assert math.isclose(_bm25(short2, query, avg), _bm25(short20, query, avg))

    def test_floor_never_exceeds_average_length(self) -> None:
        # 小语料（平均长度 9 < 25）不应被额外惩罚
        query = ["a"]
        with_floor = _bm25(["a", "b"], query, 9.0)
        explicit = compute_bm25_score(
            query_tokens=query,
            doc_tokens=["a", "b"],
            doc_length=2,
            avg_doc_length=9.0,
            doc_frequencies={"a": 10},
            total_docs=100,
            min_doc_length=9.0,
        )
        assert math.isclose(with_floor, explicit)

    def test_longer_docs_still_penalized_beyond_floor(self) -> None:
        query = ["a"]
        base = ["a"] + ["x"] * 29
        longer = ["a"] + ["x"] * 299
        assert _bm25(base, query, 50.0) > _bm25(longer, query, 50.0)

    def test_explicit_b_and_min_doc_length_override(self) -> None:
        query = ["a"]
        doc = ["a", "x"]
        no_floor = compute_bm25_score(
            query_tokens=query,
            doc_tokens=doc,
            doc_length=2,
            avg_doc_length=100.0,
            doc_frequencies={"a": 10},
            total_docs=100,
            b=0.75,
            min_doc_length=0.0,
        )
        floored = _bm25(doc, query, 100.0)
        assert no_floor > floored

    def test_zero_score_and_empty_guards_unchanged(self) -> None:
        assert _bm25(["x"], ["a"], 10.0) == 0.0
        assert compute_bm25_score([], ["a"], 1, 1.0, {}, 1) == 0.0
