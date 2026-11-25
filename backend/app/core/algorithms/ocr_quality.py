"""OCR recognition quality gate algorithm pure functional kernel.

Implements OCR quality gate validation based on gibberish ratio,
valid character count, and page completeness.
Strictly adheres to pure functional kernel constraints
(zero external I/O, zero network/ORM dependencies).
"""

import enum
import re
from collections.abc import Sequence
from dataclasses import dataclass

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-08，单页乱码率门禁上限为 15% (0.15)
# 超过 15% 表明拍摄模糊、严重反光或文档污损，强行出题会导致 LLM 严重幻觉
DEFAULT_MAX_GIBBERISH_RATIO: float = 0.15

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-08，单页有效识别字数门禁下限为 40 字
# 低于 40 字符不足以提取有效知识点，通常为封面、空白页或严重残页
DEFAULT_MIN_VALID_CHARS: int = 40

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-08，单页文本长度低于同批中位数 30% 判为残缺
# 用于识别拍摄折角、镜头遮挡截断等页面不完整缺陷
DEFAULT_MEDIAN_LENGTH_RATIO: float = 0.30

# 依据：概要设计说明书第 3.3/6.2 节与需求规格说明书 FR-09，单页就地重拍上限为 3 次
# 达到 3 次仍不合格时，触发最终失败熔断并引导用户切换其它导入方式，防止无限重试产生成本与死循环
MAX_RESHOOT_ATTEMPTS: int = 3

# 预编译正则：非法控制字符与零宽/BOM 字符
# 过滤除换行 \n 与制表符 \t 外的 ASCII 控制字符（\x00-\x08, \x0b-\x0c, \x0e-\x1f, \x7f）
# 以及 Unicode 零宽/BOM 字符（\u200b-\u200f, \ufeff）
ILLEGAL_CONTROL_CHARS_PATTERN: re.Pattern[str] = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\ufeff]"
)

# 预编译正则：有效中文单字（CJK 统一表意字符）
CJK_CHAR_PATTERN: re.Pattern[str] = re.compile(r"[\u4e00-\u9fff]")

# 预编译正则：有效英文连续单词与阿拉伯连续数字单元
WORD_OR_NUMBER_PATTERN: re.Pattern[str] = re.compile(r"[a-zA-Z]+|[0-9]+")

# 预编译正则：合法可打印字符（中英文字符、数字、中英文常用标点符号与空白符）
VALID_PRINTABLE_CHAR_PATTERN: re.Pattern[str] = re.compile(
    r"[\u4e00-\u9fff\w\s，。！？；：“”‘’（）【】《》、…—·\.,!?:;'\"()\[\]{}/\\-_+=*&%$#@~^<>|`]"
)

# 符号乱码探测集合：覆盖 SymbolMT 等缺失 ToUnicode 映射时常见的 ASCII 伪符号字符
_GARBLE_SYMBOL_CHARS: frozenset[str] = frozenset("!\"#$%&'*=?@^~")
_ALL_ASCII_SYMBOL_CHARS: frozenset[str] = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")
_NON_DOLLAR_CLUSTER_RE: re.Pattern[str] = re.compile(
    r"(?:[!\"#$%&'*=?@^~]{2,}|(?:[A-Za-z0-9]?[!\"#%&'*=?@^~]){2,}[A-Za-z0-9]?)"
)
_MARKDOWN_DECORATION_RE: re.Pattern[str] = re.compile(
    r"^(?:\|[-:|]+\||[-=*#~_]{2,}|\*\*[^*]+\*\*[.,:;!?]?|#{1,6}|\$\$?|```.*)$"
)
_MARKDOWN_BOLD_INLINE_RE: re.Pattern[str] = re.compile(r"\*\*([^*]+)\*\*")
_REPEATED_SAME_SYMBOL_RE: re.Pattern[str] = re.compile(r"^([!\"#$%&'*=?@^~`\-_])\1+$")

# ---------------------------------------------------------------------------
# 数学排版损坏探测（希腊/西里尔字母映射错乱、公式被拆成超短碎行）
# 依据：research/rag-pdf-fragmentation-and-formulas.md —— 子集化数学字体缺失 /ToUnicode 时，
# 求和号/下标常被抽成 `σi=1`、`σpiupi`、`ђvpi` 等混合字符碎片，ASCII 符号簇探测对此无感。
# ---------------------------------------------------------------------------
_CYRILLIC_CHAR_RE: re.Pattern[str] = re.compile(r"[\u0400-\u04ff]")
# 连续 >= 3 个西里尔字母视为"真实西里尔词"（俄/塞尔维亚语正文），不触发错位判定
_CYRILLIC_WORD_RE: re.Pattern[str] = re.compile(r"[\u0400-\u04ff]{3,}")
# 拉丁/希腊字母（希腊字母块 U+0370-03FF）
_LATIN_GREEK_LETTER_RE: re.Pattern[str] = re.compile(r"[A-Za-z\u0370-\u03ff]")
_LATIN_GREEK_CJK_RE: re.Pattern[str] = re.compile(r"[A-Za-z\u0370-\u03ff\u4e00-\u9fff]")
# 希腊字母直接粘连 >= 3 个拉丁小写字母（如 `σpiupi`：σ π υ π 被抽成拉丁名）
_GREEK_LATIN_GLUE_RE: re.Pattern[str] = re.compile(
    r"(?<![A-Za-z\u0370-\u03ff])[\u0391-\u03a9\u03b1-\u03c9][a-z]{3,}"
)
# 合法的"希腊字母 + 拉丁缩写"后缀白名单（σmax / λmin / μmol 等），不应误报
_LEGIT_GREEK_SUFFIXES: tuple[str, ...] = (
    "max",
    "min",
    "sup",
    "inf",
    "exp",
    "log",
    "lim",
    "sin",
    "cos",
    "tan",
    "std",
    "var",
    "dim",
    "rank",
    "mean",
    "avg",
    "eff",
    "ref",
    "tot",
    "sat",
    "mol",
    "sec",
    "rad",
    "deg",
    "ohm",
)
_EDGE_STRIP_CHARS: str = ".,;:!?()[]{}<>\"'`"
_CJK_RE: re.Pattern[str] = re.compile(r"[\u4e00-\u9fff]")
_GREEK_CHAR_RE: re.Pattern[str] = re.compile(r"[\u0391-\u03a9\u03b1-\u03c9]")
_PUA_CHAR_RE: re.Pattern[str] = re.compile(r"[\ue000-\uf8ff]")
_UNCONDITIONAL_CORRUPT_GLYPH_RE: re.Pattern[str] = re.compile(r"[\ufffd\u2612\u25af]")
_MATH_BOX_CHARS: str = (
    r"\u2610\u2611\u25a0\u25a1\u25aa\u25ab\u25c6\u25c7\u25cb\u25cf\u274e\u2700-\u27bf"
)
_MATH_BOX_GARBLE_RE: re.Pattern[str] = re.compile(
    rf"(?:[A-Za-z0-9_=+\-<>≤≥(\\]\s*[{_MATH_BOX_CHARS}]|"
    rf"[{_MATH_BOX_CHARS}]\s*(?:[_^=+\-<>≤≥\\]|[\u0370-\u03ff]|(?:[ijkmnxyz]\b)))"
)
_MATH_BOX_CHAR_ONLY_RE: re.Pattern[str] = re.compile(rf"[{_MATH_BOX_CHARS}]")
_EXTENDED_LATIN_CHAR_RE: re.Pattern[str] = re.compile(r"[\u0100-\u024f]")
_STROKE_EXTENDED_LATIN_RE: re.Pattern[str] = re.compile(
    r"[\u0127\u0111\u00f8\u0142\u00fe\u0126\u0110\u00d8\u0141\u00de]"
)
_PINYIN_VOWEL_CHARS: frozenset[str] = frozenset("āēīōūǖĀĒĪŌŪǕáéíóúǘǎěǐǒǔǚǍĚǏǑǓǙàèìòùǜńňǹ")
_ASCII_ALNUM_OR_MATH_RE: re.Pattern[str] = re.compile(r"[A-Za-z0-9_=+\-^/*()\[\]{}]")
_DIGIT_OR_MATH_OP_RE: re.Pattern[str] = re.compile(r"[0-9_=+^/*]")
_DANGLING_INDEX_LINE_RE: re.Pattern[str] = re.compile(
    r"^\d+\s*,\s*(?:\.{2,3}\s*,\s*)?[A-Za-z\u0370-\u03ff][A-Za-z0-9]{0,3}$"
)
_MARKDOWN_BLOCK_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^(?:#{1,6}\s+|[-*•]\s+|\d+[.)]\s+|>\s?|```|\|)"
)
_MATH_SYMBOL_CHARS: frozenset[str] = frozenset(
    "=+-\u2212\u2013\u00d7\u00f7\u2211\u222b\u221a\u221e\u2248\u2264\u2265\u2260\u00b1^_/\u2202\u2207\u2208\u2200\u2203\u00b7\u220f"
)
_GREEK_OR_MATH_ALPHANUM_RE: re.Pattern[str] = re.compile(r"[\u0370-\u03ff\U0001d400-\U0001d7ff]")
_STRONG_MATH_CUES_CHARS: frozenset[str] = frozenset(
    "^_\u2016\u2211\u222b\u220f\u221a\u221e\u2264\u2265\u2260\u2248\u2208\u2209\u2282\u2283\u222a\u2229\u2202\u2207"
)
_PLAIN_MATH_OP_CHARS: frozenset[str] = frozenset("+-*/=<>")
_ISOLATED_MATH_SKIP_RE: re.Pattern[str] = re.compile(
    r"^(?:https?://|www\.|\d+(?:\.\d+)*\s+[A-Za-z]|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}$|\d+\s*/\s*\d+$)",
    re.IGNORECASE,
)
_ISOLATED_MATH_MD_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^(?:#{1,6}\s+|[-*•]\s+|\d+[.)]\s+|>\s?|```)"
)

# 公式碎片页判定：非空行 >= 6 且超短公式碎行占比 > 45%
_FORMULA_FRAGMENT_MAX_LINE_CHARS: int = 8
_FORMULA_FRAGMENT_MIN_LINES: int = 6
_FORMULA_FRAGMENT_LINE_RATIO: float = 0.45
_COMBINED_FRAGMENT_LINE_RATIO: float = 0.35


class UnqualifiedReasonCode(enum.StrEnum):
    """不合格原因代码枚举，严格遵循命名白名单与规范。"""

    PAGE_INCOMPLETE = "page_incomplete"
    GIBBERISH_EXCEEDED = "gibberish_exceeded"
    INSUFFICIENT_CHARS = "insufficient_chars"


@dataclass(frozen=True)
class OCRPageInput:
    """输入页面数据结构化描述。"""

    page_number: int
    raw_text: str
    reshoot_count: int = 0
    image_storage_key: str = ""


@dataclass(frozen=True)
class OCRQualityConfig:
    """门禁算法配置参数。"""

    max_gibberish_ratio: float = DEFAULT_MAX_GIBBERISH_RATIO
    min_valid_chars: int = DEFAULT_MIN_VALID_CHARS
    median_length_ratio: float = DEFAULT_MEDIAN_LENGTH_RATIO
    max_reshoot_attempts: int = MAX_RESHOOT_ATTEMPTS

    def __post_init__(self) -> None:
        """校验配置参数合法性。

        Raises:
            ValueError: 当配置参数超出合法边界时抛出。
        """
        if not (0.0 <= self.max_gibberish_ratio <= 1.0):
            raise ValueError("max_gibberish_ratio must be between 0.0 and 1.0")
        if self.min_valid_chars < 0:
            raise ValueError("min_valid_chars must be non-negative")
        if self.median_length_ratio < 0.0:
            raise ValueError("median_length_ratio must be non-negative")
        if self.max_reshoot_attempts < 0:
            raise ValueError("max_reshoot_attempts must be non-negative")


@dataclass(frozen=True)
class PageQualityResult:
    """单页质量门禁评估结果（不可变值对象）。"""

    page_number: int
    raw_text_length: int
    cleaned_text_length: int
    valid_char_count: int
    gibberish_ratio: float
    is_page_complete: bool
    is_qualified: bool
    unqualified_code: UnqualifiedReasonCode | None
    unqualified_reason: str | None
    reshoot_count: int
    is_terminal_failure: bool
    cleaned_chars_count: int


@dataclass(frozen=True)
class BatchQualityReport:
    """批次页面识别质量门禁统一产出报告。"""

    page_results: tuple[PageQualityResult, ...]
    total_pages: int
    qualified_pages: int
    unqualified_pages: int
    is_all_qualified: bool
    median_length: float
    terminal_failure_pages: tuple[int, ...]


def clean_ocr_text(text: str) -> tuple[str, int]:
    """过滤文本中非法控制字符与零宽字符并返回剔除计数。

    Args:
        text: 待清洗的原始文本字符串。

    Returns:
        tuple[str, int]: 清洗后文本及剔除字符数。
    """
    cleaned_text, removal_count = ILLEGAL_CONTROL_CHARS_PATTERN.subn("", text)
    return cleaned_text, removal_count


clean_ocr_text_and_count_removals = clean_ocr_text


def count_valid_characters(text: str) -> int:
    """统计文本中可用中文字符与英文单词及数字单元总数。

    中文单个汉字计 1 字，英文连续单词计 1 词，阿拉伯连续数字串计 1 单元。

    Args:
        text: 已清洗的输入文本字符串。

    Returns:
        int: 有效文字与词汇单元总数。
    """
    cjk_count = len(CJK_CHAR_PATTERN.findall(text))
    word_or_number_count = len(WORD_OR_NUMBER_PATTERN.findall(text))
    return cjk_count + word_or_number_count


def calculate_gibberish_ratio(text: str) -> float:
    """计算文本中乱码与杂乱不可解析字符的比例 (0.0 ~ 1.0)。

    空文本或全空白文本直接返回 1.0 (100%)。

    Args:
        text: 已清洗的输入文本字符串。

    Returns:
        float: 乱码字符占非空白字符总数的比例。
    """
    non_space_chars = [char for char in text if not char.isspace()]
    if not non_space_chars:
        return 1.0
    gibberish_count = sum(
        1 for char in non_space_chars if not VALID_PRINTABLE_CHAR_PATTERN.match(char)
    )
    return gibberish_count / len(non_space_chars)


def _is_garble_cluster_token(token: str) -> bool:
    """判断单个空白分隔 token 是否包含高密度符号乱码簇。"""
    if not token or token.startswith(("http://", "https://")):
        return False
    stripped_md = _MARKDOWN_BOLD_INLINE_RE.sub(r"\1", token)
    if _MARKDOWN_DECORATION_RE.match(stripped_md) or _REPEATED_SAME_SYMBOL_RE.match(stripped_md):
        return False
    non_dollar_count = sum(1 for ch in stripped_md if ch in _GARBLE_SYMBOL_CHARS and ch != "$")
    if non_dollar_count < 2:
        return False
    return bool(_NON_DOLLAR_CLUSTER_RE.search(stripped_md))


def _is_short_symbol_burst_token(token: str) -> bool:
    """判断是否为跨空白符乱码碎片中的短符号 token。"""
    if len(token) > 4 or token in {"|", "-", "*", "$$", "$"}:
        return False
    return all(ch in _ALL_ASCII_SYMBOL_CHARS for ch in token) and any(
        ch in _GARBLE_SYMBOL_CHARS for ch in token
    )


def _is_glued_greek_latin_token(token: str) -> bool:
    """判断 token 是否含有希腊字母粘连拉丁名的损坏簇（如 `σpiupi`），白名单缩写除外。"""
    for match in _GREEK_LATIN_GLUE_RE.finditer(token):
        suffix = match.group()[1:]
        if not suffix.startswith(_LEGIT_GREEK_SUFFIXES):
            return True
    return False


def _is_extended_latin_math_garble(core: str, *, line_has_cjk_or_math: bool) -> bool:
    """判断 token 是否包含数学字体错映射的扩展拉丁字符（如 `ħx1`）或私用区 PUA 字符。"""
    if _PUA_CHAR_RE.search(core):
        return True
    if _STROKE_EXTENDED_LATIN_RE.search(core) and _ASCII_ALNUM_OR_MATH_RE.search(core):
        return True
    if not _EXTENDED_LATIN_CHAR_RE.search(core):
        return False
    if _DIGIT_OR_MATH_OP_RE.search(core):
        return True
    if not line_has_cjk_or_math:
        return False
    has_non_pinyin_ext = any(
        "\u0100" <= ch <= "\u024f" and ch not in _PINYIN_VOWEL_CHARS for ch in core
    )
    return has_non_pinyin_ext and any(ch.isascii() and ch.isalnum() for ch in core)


def _math_garble_tokens(tokens: Sequence[str]) -> list[str]:
    """返回单行 token 中属于数学字体映射错乱的碎片（希腊字母粘连、西里尔、扩展拉丁/PUA）。

    西里尔判定仅在整行没有"真实西里尔词"（连续 >= 3 个西里尔字母）且行内存在
    拉丁/希腊/汉字时生效，以免误伤俄语、塞尔维亚语等真实西里尔正文。
    """
    if not tokens:
        return []
    line = " ".join(tokens)
    stray_cyrillic_applies = (
        _CYRILLIC_CHAR_RE.search(line) is not None
        and _CYRILLIC_WORD_RE.search(line) is None
        and _LATIN_GREEK_CJK_RE.search(line) is not None
    )
    line_has_cjk_or_math = bool(
        _CJK_RE.search(line) or any(ch in _MATH_SYMBOL_CHARS for ch in line)
    )
    garbled: list[str] = []
    for tok in tokens:
        core = tok.strip(_EDGE_STRIP_CHARS)
        if not core:
            continue
        if (
            _is_glued_greek_latin_token(core)
            or (stray_cyrillic_applies and _CYRILLIC_CHAR_RE.search(core) is not None)
            or _is_extended_latin_math_garble(core, line_has_cjk_or_math=line_has_cjk_or_math)
        ):
            garbled.append(tok)
    return garbled


def _collect_line_garble_fragments(line: str) -> tuple[list[str], bool]:
    """提取单行内的 ASCII 符号乱码簇并判断是否整行为孤立符号噪声行。"""
    stripped = line.strip()
    if not stripped or _MARKDOWN_DECORATION_RE.match(stripped):
        return [], False

    tokens = stripped.split()
    if tokens and tokens[0].startswith("#") and len(set(tokens[0])) == 1:
        tokens = tokens[1:]

    fragments: list[str] = [tok for tok in tokens if _is_garble_cluster_token(tok)]
    fragments.extend(tok for tok in _math_garble_tokens(tokens) if tok not in fragments)

    burst: list[str] = []
    for tok in tokens:
        if _is_short_symbol_burst_token(tok):
            burst.append(tok)
            continue
        if len(burst) >= 2 and sum(len(b) for b in burst) >= 3:
            fragments.append(" ".join(burst))
        burst.clear()
    if len(burst) >= 2 and sum(len(b) for b in burst) >= 3:
        fragments.append(" ".join(burst))

    non_ws = [ch for ch in stripped if not ch.isspace()]
    sym_only_line = False
    if len(non_ws) >= 2:
        sym_count = sum(1 for ch in non_ws if ch in _ALL_ASCII_SYMBOL_CHARS)
        garble_count = sum(1 for ch in non_ws if ch in _GARBLE_SYMBOL_CHARS and ch != "$")
        if sym_count / len(non_ws) >= 0.8 and garble_count >= 2:
            sym_only_line = True
            if not fragments:
                fragments.append(stripped)

    return fragments, sym_only_line


def _collect_corrupt_glyph_fragments(text: str) -> list[str]:
    """收集 `\ufffd`/`☒`/`▯` 及数学语境方框占位符命中的局部上下文片段。"""
    hits: list[str] = []
    for pattern in (_UNCONDITIONAL_CORRUPT_GLYPH_RE, _MATH_BOX_GARBLE_RE):
        for match in pattern.finditer(text):
            start = max(0, match.start() - 4)
            end = min(len(text), match.end() + 4)
            frag = text[start:end].strip()
            if frag and frag not in hits:
                hits.append(frag)
            if len(hits) >= 10:
                return hits
    return hits


def _strip_corrupt_glyphs_from_line(line: str) -> str:
    """移除无法修复的替换符/方框占位符与数学邻接损坏方框。"""
    cleaned = _UNCONDITIONAL_CORRUPT_GLYPH_RE.sub("", line)
    return _MATH_BOX_GARBLE_RE.sub(
        lambda m: _MATH_BOX_CHAR_ONLY_RE.sub("", m.group(0)),
        cleaned,
    )


def detect_symbol_garble(text: str) -> tuple[bool, float, tuple[str, ...]]:
    """探测文档/页面文本中是否存在缺失字体编码导致的符号乱码簇或损坏字形。

    专门识别 SymbolMT/Wingdings 等符号字体缺失 `/ToUnicode` 映射时产生的
    ``AB&A&``、``"#$``、``!" ! #``、``☒``、``\ufffd``、``▯`` 等噪声簇，
    同时避免对正常 LaTeX 或 Markdown 装饰符误报。

    Args:
        text: 待检测文本。

    Returns:
        tuple[bool, float, tuple[str, ...]]:
            (是否检测到符号乱码, 乱码符号占比估算, 命中的典型乱码片段元组)。
    """
    if not text or not text.strip():
        return False, 0.0, ()

    non_ws_total = sum(1 for ch in text if not ch.isspace())
    if non_ws_total == 0:
        return False, 0.0, ()

    corrupt_frags = _collect_corrupt_glyph_fragments(text)
    all_fragments: list[str] = list(corrupt_frags)
    sym_only_lines = 0
    for line in text.splitlines():
        line_frags, is_sym_line = _collect_line_garble_fragments(line)
        all_fragments.extend(line_frags)
        if is_sym_line:
            sym_only_lines += 1

    # ASCII 符号簇按符号字符计；数学字体错乱碎片（σpiupi/ђvpi/ħx1，不含 ASCII 符号）按整段长度计
    garble_char_total = sum(
        sum(1 for ch in frag if ch in _ALL_ASCII_SYMBOL_CHARS) or len(frag)
        for frag in all_fragments
    )
    has_pua = _PUA_CHAR_RE.search(text) is not None
    has_corrupt_glyph = bool(corrupt_frags)
    garble_ratio = min(1.0, garble_char_total / non_ws_total)
    is_garbled = (
        has_pua
        or has_corrupt_glyph
        or sym_only_lines >= 1
        or len(all_fragments) >= 2
        or (len(all_fragments) == 1 and garble_ratio >= 0.15)
    )
    dedup_frags = tuple(dict.fromkeys(all_fragments[:10]))
    return is_garbled, round(garble_ratio, 4), dedup_frags


def sanitize_symbol_garble(text: str) -> str:
    """在缺少视觉/大模型修复时确定性清除不可读符号乱码噪声。

    除 ASCII 符号簇外，同样移除数学字体映射错乱碎片（如 `σpiupi`、`ħx1`、PUA、`☒`、`\ufffd`）。
    """
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        _frags, is_sym_line = _collect_line_garble_fragments(line)
        if is_sym_line:
            continue
        stripped_corrupt = _strip_corrupt_glyphs_from_line(line)
        tokens = stripped_corrupt.split()
        math_garbled = set(_math_garble_tokens(tokens))
        kept_tokens = [
            _PUA_CHAR_RE.sub("", tok)
            for tok in tokens
            if tok not in math_garbled and not _is_garble_cluster_token(tok)
        ]
        rebuilt = " ".join(tok for tok in kept_tokens if tok).strip()
        if rebuilt:
            cleaned_lines.append(rebuilt)
    return "\n".join(cleaned_lines)


def _is_formula_fragment_line(line: str) -> bool:
    """判断单行是否为超短公式碎片（<= 8 字符、不含汉字、含希腊字母/数学符号/数字）。"""
    if (
        len(line) > _FORMULA_FRAGMENT_MAX_LINE_CHARS
        or _CJK_RE.search(line)
        or _MARKDOWN_BLOCK_PREFIX_RE.match(line)
    ):
        return False
    return any(
        ch.isdigit() or ch in _MATH_SYMBOL_CHARS or _GREEK_CHAR_RE.match(ch) is not None
        for ch in line
    )


def _is_single_ascii_letter_line(line: str) -> bool:
    """判断单行是否为孤立单字母变量行（如独立成行的 `m`、`n`、`d`、`X`）。"""
    return len(line) == 1 and line.isascii() and line.isalpha()


def _is_dangling_math_fragment(line: str) -> bool:
    """判断单行是否为残缺上下标/悬空符号断行（如 `1, xi`、`2, ..., xi`、`X =`、`f(`）。"""
    if len(line) > 24 or _CJK_RE.search(line) or _MARKDOWN_BLOCK_PREFIX_RE.match(line):
        return False
    if _DANGLING_INDEX_LINE_RE.match(line):
        return True
    if line.endswith(("=", "(", "[", ",")):
        has_symbol_or_var = any(
            ch.isalpha() or ch in _MATH_SYMBOL_CHARS or _GREEK_CHAR_RE.match(ch) is not None
            for ch in line
        )
        return has_symbol_or_var
    return False


def _extract_non_code_lines(text: str) -> list[str]:
    """抽取非空且不在围栏代码块内的行（用于排版损坏统计，避免误伤示例代码）。"""
    lines: list[str] = []
    in_fence = False
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(stripped)
    return lines


def detect_broken_math_layout(text: str) -> bool:
    """探测 PDF 文本层中数学公式排版/字体映射损坏的页面。

    命中任一条件即返回 True（调用方据此触发视觉/大模型修复）：

    1. 希腊字母粘连、孤立西里尔字母、扩展拉丁映射错乱（如 `ħx1`）或 PUA 字符；
    2. 稠密超短公式碎片页：非空行 >= 6 且 > 45% 的行 <= 8 字符、不含汉字、
       含希腊字母/数学符号/数字（上下标、求和上下限被拆成独立短行）；
    3. 孤立单字母变量行堆积（如连续 `m`/`n`/`d`/`X`）或与残缺公式碎行共现。

    正常中英文段落、Markdown 列表/代码块与 ``E=mc^2``、``σ = 0.5`` 这类独立短公式不会命中。

    Args:
        text: 待检测的页面文本。

    Returns:
        bool: 是否检测到数学排版损坏。
    """
    if not text or not text.strip():
        return False

    if _collect_corrupt_glyph_fragments(text):
        return True

    non_code_lines = _extract_non_code_lines(text)
    if any(_math_garble_tokens(ln.split()) for ln in non_code_lines):
        return True

    fragment_lines = 0
    single_letter_lines = 0
    dangling_lines = 0
    consecutive_single = 0
    max_consecutive_single = 0

    for ln in non_code_lines:
        is_single = _is_single_ascii_letter_line(ln)
        if is_single:
            single_letter_lines += 1
            consecutive_single += 1
            max_consecutive_single = max(max_consecutive_single, consecutive_single)
        else:
            consecutive_single = 0
        if _is_formula_fragment_line(ln):
            fragment_lines += 1
        if _is_dangling_math_fragment(ln):
            dangling_lines += 1

    if dangling_lines >= 1 and max_consecutive_single >= 3:
        return True

    if len(non_code_lines) < _FORMULA_FRAGMENT_MIN_LINES:
        return False

    if fragment_lines / len(non_code_lines) > _FORMULA_FRAGMENT_LINE_RATIO:
        return True

    if single_letter_lines >= 3:
        combined = fragment_lines + single_letter_lines + dangling_lines
        if combined / len(non_code_lines) >= _COMBINED_FRAGMENT_LINE_RATIO:
            return True

    return False


def is_isolated_math_expression_block(text: str) -> bool:
    """判断独立短块是否为未封装 LaTeX 的散落数学表达式（如 `ω^T x_i + b`、`||ω||`）。"""
    stripped = text.strip()
    if not (2 <= len(stripped) <= 45) or stripped.count("\n") > 1:
        return False
    if _CJK_RE.search(stripped) or _ISOLATED_MATH_MD_PREFIX_RE.match(stripped):
        return False
    if stripped.startswith("| ") and stripped.endswith(" |"):
        return False
    if stripped.startswith("$") and stripped.endswith("$"):
        return False
    if _ISOLATED_MATH_SKIP_RE.match(stripped):
        return False
    has_greek = _GREEK_OR_MATH_ALPHANUM_RE.search(stripped) is not None
    has_strong_cue = "||" in stripped or any(ch in _STRONG_MATH_CUES_CHARS for ch in stripped)
    op_count = sum(1 for ch in stripped if ch in _PLAIN_MATH_OP_CHARS)
    if has_greek and (has_strong_cue or op_count >= 1):
        return True
    if has_strong_cue:
        return True
    return op_count >= 2 and any(ch.isalpha() for ch in stripped)


def has_scattered_math_blocks(text: str) -> bool:
    """探测整页文本中是否存在未封装 LaTeX 的散架二维公式块（用于 VLM 触发与小模型公式修复提示）。"""
    if not text or not text.strip():
        return False
    blocks = re.split(r"\n\s*\n", text.strip())
    candidates: list[str] = []
    for block in blocks:
        stripped = block.strip()
        if not stripped:
            continue
        if is_isolated_math_expression_block(stripped):
            candidates.append(stripped)
            continue
        for line in stripped.splitlines():
            ln = line.strip()
            if ln and is_isolated_math_expression_block(ln):
                candidates.append(ln)
    if len(candidates) >= 2:
        return True
    if len(candidates) == 1:
        item = candidates[0]
        has_greek = _GREEK_OR_MATH_ALPHANUM_RE.search(item) is not None
        has_sub_sup = "^" in item or "_" in item or "||" in item or "\u2016" in item
        return has_greek and has_sub_sup
    return False


def calculate_median_length(lengths: Sequence[int]) -> float:
    """计算同批页面文本长度中位数（含单页与双页降级逻辑）。

    Args:
        lengths: 同批页面清洗后文本长度序列。

    Returns:
        float: 计算所得的基准中位数或均值。
    """
    total_items = len(lengths)
    if total_items <= 1:
        return 0.0
    if total_items == 2:
        return (lengths[0] + lengths[1]) / 2.0

    sorted_lengths = sorted(lengths)
    middle_index = total_items // 2
    if total_items % 2 == 1:
        return float(sorted_lengths[middle_index])
    return (sorted_lengths[middle_index - 1] + sorted_lengths[middle_index]) / 2.0


def evaluate_page_quality(
    page: OCRPageInput,
    baseline_median_length: float,
    config: OCRQualityConfig,
    is_single_page: bool = False,
) -> PageQualityResult:
    """执行单页质量门禁评估与不合格原因仲裁。

    判定优先级：
    页面不完整 (PAGE_INCOMPLETE) > 乱码率超限 (GIBBERISH_EXCEEDED)
    > 有效字数不足 (INSUFFICIENT_CHARS)。

    Args:
        page: 输入单页 OCR 数据。
        baseline_median_length: 同批页面基准中位数长度。
        config: 质量门禁阈值配置。
        is_single_page: 是否为单页批次模式（单页模式跳过完整性检查）。

    Returns:
        PageQualityResult: 单页质量评估不可变结果。
    """
    cleaned_text, cleaned_chars_count = clean_ocr_text(page.raw_text)
    raw_text_length = len(page.raw_text)
    cleaned_text_length = len(cleaned_text)

    # 边界情况：空文本或全空白文本
    if not cleaned_text.strip():
        is_terminal = page.reshoot_count >= config.max_reshoot_attempts
        return PageQualityResult(
            page_number=page.page_number,
            raw_text_length=raw_text_length,
            cleaned_text_length=cleaned_text_length,
            valid_char_count=0,
            gibberish_ratio=1.0,
            is_page_complete=False,
            is_qualified=False,
            unqualified_code=UnqualifiedReasonCode.PAGE_INCOMPLETE,
            unqualified_reason="页面内容不完整，显著低于同批页面文本长度",
            reshoot_count=page.reshoot_count,
            is_terminal_failure=is_terminal,
            cleaned_chars_count=cleaned_chars_count,
        )

    valid_char_count = count_valid_characters(cleaned_text)
    gibberish_ratio = calculate_gibberish_ratio(cleaned_text)

    # 页面完整性判断
    if is_single_page or baseline_median_length <= 0.0:
        is_page_complete = True
    else:
        threshold_length = baseline_median_length * config.median_length_ratio
        is_page_complete = cleaned_text_length >= threshold_length

    # 优先级仲裁：完整性 > 乱码率 > 有效字数
    is_qualified = True
    unqualified_code: UnqualifiedReasonCode | None = None
    unqualified_reason: str | None = None

    if not is_page_complete:
        is_qualified = False
        unqualified_code = UnqualifiedReasonCode.PAGE_INCOMPLETE
        unqualified_reason = "页面内容不完整，显著低于同批页面文本长度"
    elif gibberish_ratio > config.max_gibberish_ratio:
        is_qualified = False
        unqualified_code = UnqualifiedReasonCode.GIBBERISH_EXCEEDED
        unqualified_reason = f"乱码率过高[{gibberish_ratio:.1%}]，超出门禁上限"
    elif valid_char_count < config.min_valid_chars:
        is_qualified = False
        unqualified_code = UnqualifiedReasonCode.INSUFFICIENT_CHARS
        unqualified_reason = f"有效识别字数不足[{valid_char_count}字]，低于门禁下限"

    is_terminal_failure = (not is_qualified) and (page.reshoot_count >= config.max_reshoot_attempts)

    return PageQualityResult(
        page_number=page.page_number,
        raw_text_length=raw_text_length,
        cleaned_text_length=cleaned_text_length,
        valid_char_count=valid_char_count,
        gibberish_ratio=gibberish_ratio,
        is_page_complete=is_page_complete,
        is_qualified=is_qualified,
        unqualified_code=unqualified_code,
        unqualified_reason=unqualified_reason,
        reshoot_count=page.reshoot_count,
        is_terminal_failure=is_terminal_failure,
        cleaned_chars_count=cleaned_chars_count,
    )


def verify_ocr_quality(
    pages: Sequence[OCRPageInput],
    config: OCRQualityConfig | None = None,
) -> BatchQualityReport:
    """执行批次 OCR 页面质量门禁核验。

    Args:
        pages: 待检测的 OCR 页面输入序列。
        config: 可选算法阈值配置，不传使用标准默认基线。

    Returns:
        BatchQualityReport: 包含逐页判定结果与整批准出结论的报告。

    Raises:
        ValueError: 当配置参数非法时抛出。
    """
    effective_config = config if config is not None else OCRQualityConfig()

    if not pages:
        return BatchQualityReport(
            page_results=(),
            total_pages=0,
            qualified_pages=0,
            unqualified_pages=0,
            is_all_qualified=True,
            median_length=0.0,
            terminal_failure_pages=(),
        )

    # 第一遍扫描：收集各页清洗后长度
    cleaned_lengths = [len(clean_ocr_text(page.raw_text)[0]) for page in pages]
    baseline_median_length = calculate_median_length(cleaned_lengths)
    is_single_page = len(pages) == 1

    # 第二遍扫描：逐页执行门禁评估
    page_results_list: list[PageQualityResult] = []
    terminal_failures: list[int] = []
    qualified_count = 0

    for page in pages:
        result = evaluate_page_quality(
            page=page,
            baseline_median_length=baseline_median_length,
            config=effective_config,
            is_single_page=is_single_page,
        )
        page_results_list.append(result)
        if result.is_qualified:
            qualified_count += 1
        if result.is_terminal_failure:
            terminal_failures.append(page.page_number)

    total_count = len(pages)
    unqualified_count = total_count - qualified_count

    return BatchQualityReport(
        page_results=tuple(page_results_list),
        total_pages=total_count,
        qualified_pages=qualified_count,
        unqualified_pages=unqualified_count,
        is_all_qualified=unqualified_count == 0,
        median_length=baseline_median_length,
        terminal_failure_pages=tuple(terminal_failures),
    )
