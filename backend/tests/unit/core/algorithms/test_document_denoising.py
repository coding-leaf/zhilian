"""Unit tests for app.core.algorithms.document_denoising pure functions."""

from dataclasses import dataclass

from app.core.algorithms.document_denoising import (
    PageRole,
    PageTextBlock,
    PageTextInput,
    classify_pages_with_fallback,
    classify_slide_or_page,
    filter_and_rank_evidence_snippets,
    is_non_substantive_chapter,
    strip_display_watermark_lines,
    strip_repeated_headers_footers,
)


@dataclass(frozen=True)
class _SnippetStub:
    snippet_index: int
    content: str
    chapter_title: str = ""


def test_strip_repeated_headers_footers_removes_bilingual_university_watermark_and_pages() -> None:
    """Cross-page repeated header/footer, bilingual watermark, and page counters are stripped."""
    pages = []
    for pn in range(1, 7):
        blocks = (
            PageTextBlock("第五章 支持向量机", 40, 20, 400, 50, 800, 600),
            PageTextBlock(
                f"正文第 {pn} 页：支持向量机通过最大化几何间隔构建分类超平面。",
                40,
                150,
                740,
                350,
                800,
                600,
            ),
            PageTextBlock(
                "福建師範大學\nFUJIAN NORMAL UNIVERSITY",
                50,
                520,
                380,
                580,
                800,
                600,
            ),
            PageTextBlock(f"{pn} / 6", 700, 550, 760, 580, 800, 600),
        )
        text = "\n\n".join(b.text for b in blocks)
        pages.append(PageTextInput(page_number=pn, text=text, blocks=blocks))

    cleaned = strip_repeated_headers_footers(pages)
    assert len(cleaned) == 6
    for pn, page_text in enumerate(cleaned, start=1):
        assert "福建師範大學" not in page_text
        assert "FUJIAN NORMAL UNIVERSITY" not in page_text
        assert "第五章 支持向量机" not in page_text
        assert f"{pn} / 6" not in page_text
        assert "支持向量机通过最大化几何间隔构建分类超平面" in page_text


def test_strip_display_watermark_lines_handles_legacy_snippets() -> None:
    """Display watermark cleaner strips institutional watermarks and pure page counters only."""
    raw = (
        "支持向量机引入松弛变量 $\\xi_i \\ge 0$ 处理线性不可分样本。\n"
        "福建師範大學\n"
        "FUJIAN NORMAL UNIVERSITY\n"
        "第 41 页 / 共 42 页"
    )
    cleaned = strip_display_watermark_lines(raw)
    assert "福建師範大學" not in cleaned
    assert "FUJIAN NORMAL UNIVERSITY" not in cleaned
    assert "第 41 页" not in cleaned
    assert "$\\xi_i \\ge 0$" in cleaned


def test_classify_slide_or_page_roles_and_punctuation_safety() -> None:
    """Verify thank-you with exclamation, TOC, empty vs rich summary, cover, and section divider."""
    assert classify_slide_or_page("谢谢！", 42, 42) == PageRole.THANK_YOU
    assert classify_slide_or_page("感谢聆听！Q&A?", 42, 42) == PageRole.THANK_YOU
    assert (
        classify_slide_or_page(
            "1.基本概念 2.线性可分支持向量机 3.线性支持向量机 4.核函数与核技巧",
            41,
            42,
        )
        == PageRole.TOC
    )
    assert classify_slide_or_page("目录\n1. 背景\n2. 推导\n3. 总结", 2, 42) == PageRole.TOC
    assert (
        classify_slide_or_page("小结\n1. 硬间隔\n2. 软间隔\n3. 核技巧", 40, 42)
        == PageRole.CHAPTER_SUMMARY
    )

    rich_summary = (
        "小结\n"
        "| 模型 | 目标函数 | 适用条件 |\n"
        "| --- | --- | --- |\n"
        "| 硬间隔 SVM | $\\min \\frac{1}{2}\\|w\\|^2$ | 严格线性可分 |"
    )
    assert classify_slide_or_page(rich_summary, 40, 42) == PageRole.CONTENT

    assert (
        classify_slide_or_page(
            "参考文献\n[1] Vapnik V. Statistical Learning Theory.\n[2] Cortes C.",
            41,
            42,
        )
        == PageRole.REFERENCES
    )
    assert classify_slide_or_page("第五章 支持向量机\n主讲教师：张三", 1, 10) == PageRole.COVER
    assert classify_slide_or_page("二、线性可分支持向量机", 5, 42) == PageRole.SECTION_DIVIDER
    assert classify_slide_or_page("小结", 40, 42) == PageRole.CHAPTER_SUMMARY


def test_classify_pages_with_fallback_protects_all_template_short_docs() -> None:
    """When every page would be filtered as template, non-empty pages fall back to CONTENT."""
    roles = classify_pages_with_fallback([(1, "目录\n1. 引言\n2. 结论"), (2, "谢谢！")])
    assert roles == [PageRole.CONTENT, PageRole.CONTENT]


def test_is_non_substantive_chapter_patterns() -> None:
    """Non-substantive chapters are detected cleanly while real chapters are preserved."""
    for title in ("小结", "本章小结", "1. 目录", "五、课后习题", "致谢", "Summary"):
        assert is_non_substantive_chapter(title) is True
    for real in ("第一章 支持向量机", "核函数与核技巧", "默认章节", None):
        assert is_non_substantive_chapter(real) is False


def test_filter_and_rank_evidence_snippets_filters_noise_and_caps_at_five() -> None:
    """Noise snippets are dropped, returning [] if none remain, else <= 5 ranked by relevance."""
    noise_only = [
        _SnippetStub(0, "谢谢！", "小结"),
        _SnippetStub(1, "1.基本概念 2.线性可分 3.核技巧 4.对偶问题", "目录"),
        _SnippetStub(2, "福建師範大學\nFUJIAN NORMAL UNIVERSITY", "支持向量机"),
        _SnippetStub(3, "支持向量机", "支持向量机"),
    ]
    assert filter_and_rank_evidence_snippets(noise_only, "支持向量机") == []

    mixed = [
        *noise_only,
        _SnippetStub(4, "这是一段泛泛而谈的背景描述，没有给出数学推导细节。", "支持向量机"),
        _SnippetStub(
            5,
            "核技巧定义：通过核函数 $K(x_i, x_j) = \\phi(x_i)^T\\phi(x_j)$ 避免显式高维映射。",
            "核方法",
        ),
        _SnippetStub(6, "常见核函数包括线性核、多项式核与高斯 RBF 核函数。", "核方法"),
        _SnippetStub(7, "支持向量机在核函数空间中求解最大几何间隔超平面。", "核方法"),
        _SnippetStub(8, "核方法可用于非线性分类与回归问题推导。", "核方法"),
        _SnippetStub(9, "核矩阵需满足 Mercer 半正定条件。", "核方法"),
        _SnippetStub(10, "高斯核带宽参数控制决策边界复杂度。", "核方法"),
    ]
    ranked = filter_and_rank_evidence_snippets(
        mixed,
        kp_name="核技巧",
        kp_summary="核函数将低维非线性样本映射至高维特征空间。",
        max_items=5,
    )
    assert len(ranked) == 5
    assert ranked[0].snippet_index == 5
    assert all(s.snippet_index not in {0, 1, 2, 3} for s in ranked)
