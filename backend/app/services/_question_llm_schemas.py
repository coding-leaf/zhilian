"""Internal Pydantic LLM output normalization schemas for QuestionService."""

import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

_OPTION_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^(?:\([A-Za-z]\)|（[A-Za-z]）|[A-Za-z][.、:：)）])\s*"
)
_OPTION_KEY_TOKEN_RE: re.Pattern[str] = re.compile(r"^[(\[（]?\s*([A-Za-z])\s*[)\]）.、:：]?$")


def _strip_option_label_prefix(text: str) -> str:
    """剥离选项正文前端重复出现的字母序号前缀（如 A. / A、 / (A) / A:）。"""
    cleaned = text.strip()
    for _ in range(2):
        updated = _OPTION_PREFIX_RE.sub("", cleaned, count=1).strip()
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


def _parse_int_score(raw_value: Any, *, fallback: int, minimum: int = 1) -> int:
    """安全将 LLM 返回的任意数值/字符串分值解析为整型下界分值。"""
    if raw_value is None:
        return fallback
    try:
        return max(minimum, int(float(raw_value)))
    except (ValueError, TypeError):
        return fallback


def _sum_rubric_points(points: list[Any]) -> int:
    """汇总评分要点列表中各条目的有效分值。"""
    total = 0
    for point in points:
        if isinstance(point, dict):
            total += _parse_int_score(point.get("score", 1), fallback=1)
        elif isinstance(point, LLMGradingPointItem):
            total += point.score
        elif isinstance(point, str):
            total += 1
    return total


def _normalize_rubric_dict(raw_dict: dict[str, Any]) -> dict[str, Any]:
    """规整字典格式的评分细则并推导缺省总分与要点集合。"""
    normalized = dict(raw_dict)
    if "points" not in normalized:
        for alt_key in ("rubric", "items", "criteria", "points_list"):
            if alt_key in normalized and isinstance(normalized[alt_key], list):
                normalized["points"] = normalized[alt_key]
                break
    points = normalized.get("points") or []
    if not isinstance(points, list):
        points = [points] if points else []
        normalized["points"] = points

    total_score_val = _parse_int_score(normalized.get("total_score"), fallback=0, minimum=0)
    if total_score_val < 1:
        computed = _sum_rubric_points(points)
        total_score_val = max(1, computed) if computed > 0 else 5

    normalized["total_score"] = total_score_val
    return normalized


def _normalize_llm_options(raw_options: Any) -> Any:
    """兼容 LLM 返回的字符串选项列表或别名字段字典选项。"""
    if not isinstance(raw_options, list):
        return raw_options
    normalized: list[Any] = []
    for idx, opt in enumerate(raw_options):
        if isinstance(opt, str):
            key = chr(ord("A") + idx)
            if len(opt) > 2 and opt[0].isalpha() and opt[1] in (".", "、", ":", " "):
                key = opt[0].upper()
                opt_content = opt[2:].strip()
            else:
                opt_content = opt
            normalized.append({"key": key, "content": opt_content})
        elif isinstance(opt, dict):
            opt_dict = dict(opt)
            if "content" not in opt_dict and "text" in opt_dict:
                opt_dict["content"] = opt_dict["text"]
            opt_dict.setdefault("key", chr(ord("A") + idx))
            if isinstance(opt_dict.get("key"), str):
                raw_key = opt_dict["key"].strip()
                key_match = _OPTION_KEY_TOKEN_RE.match(raw_key)
                if key_match:
                    opt_dict["key"] = key_match.group(1).upper()
                else:
                    opt_dict["key"] = raw_key.upper() or chr(ord("A") + idx)
            if isinstance(opt_dict.get("content"), str):
                opt_dict["content"] = _strip_option_label_prefix(opt_dict["content"])
            normalized.append(opt_dict)
        else:
            normalized.append(opt)
    return normalized


_CHOICE_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^[(\[（]?\s*([A-Za-z])\s*(?:[)\]）.、:：]|\s+(?![,;&]))\s*\S+"
)
_TRUE_BOOL_STRS: frozenset[str] = frozenset(
    {"TRUE", "T", "1", "YES", "Y", "对", "正确", "是", "V", "√"}
)
_FALSE_BOOL_STRS: frozenset[str] = frozenset(
    {"FALSE", "F", "0", "NO", "N", "错", "错误", "否", "X", "×"}
)


def _build_option_content_map(options: Any) -> dict[str, str]:
    """构建选项正文小写文本到选项字母键的反向映射。"""
    if not isinstance(options, list):
        return {}
    mapping: dict[str, str] = {}
    for opt in options:
        if isinstance(opt, dict):
            key = str(opt.get("key", "")).strip().upper()
            content = str(opt.get("content", "")).strip().lower()
            if key and content:
                mapping[content] = key
    return mapping


def _extract_choice_key(segment: str, option_map: dict[str, str]) -> str | None:
    """从单个选项片段（如 'A. 最大间隔' / '(A)' / '选项 A' / 选项正文）中提取选项字母键。"""
    cleaned = re.sub(r"^(?:正确)?(?:选项|答案)\s*[:：]?\s*", "", segment.strip()).strip()
    if not cleaned:
        return None
    exact = _OPTION_KEY_TOKEN_RE.match(cleaned)
    if exact:
        return exact.group(1).upper()
    prefixed = _CHOICE_PREFIX_RE.match(cleaned)
    if prefixed:
        return prefixed.group(1).upper()
    return option_map.get(cleaned.lower())


def _normalize_choice_answer_text(
    text: str,
    *,
    question_type: str,
    option_map: dict[str, str],
) -> str:
    """规范化单选/多选题答案字符串，剥离多余前缀与选项正文。"""
    stripped = text.strip()
    if not stripped:
        return ""

    if question_type == "single_choice":
        # 保留明确的多答案格式（如 "A, B" / "A、B"），以便下游规则校验拦截多选单答冲突。
        multi_tokens = [tok for tok in re.split(r"[,;、\s|]+", stripped) if tok.strip()]
        matched_multi = [_OPTION_KEY_TOKEN_RE.match(tok) for tok in multi_tokens]
        if len(multi_tokens) > 1 and all(m is not None for m in matched_multi):
            return ",".join(m.group(1).upper() for m in matched_multi if m is not None)
        key = _extract_choice_key(stripped, option_map)
        return key if key is not None else stripped

    segments = [seg for seg in re.split(r"[,;；|\n]+", stripped) if seg.strip()]
    if len(segments) == 1:
        # 兼容 "A、B"（多键）vs "A、支持向量"（单键+正文）
        sub_tokens = [tok for tok in re.split(r"[、\s]+", stripped) if tok.strip()]
        matched_sub = [_OPTION_KEY_TOKEN_RE.match(tok) for tok in sub_tokens]
        if len(sub_tokens) > 1 and all(m is not None for m in matched_sub):
            return ",".join(m.group(1).upper() for m in matched_sub if m is not None)
        key = _extract_choice_key(stripped, option_map)
        return key if key is not None else stripped

    resolved: list[str] = []
    for seg in segments:
        key = _extract_choice_key(seg, option_map)
        if key is None:
            return stripped
        resolved.append(key)
    return ",".join(resolved)


def _normalize_llm_answer(
    raw_answer: Any,
    *,
    question_type: str = "",
    options: Any = None,
) -> str:
    """将布尔/列表/数字/字符串形式的参考答案规整为统一纯字符串。"""
    if raw_answer is None:
        return "A"
    if isinstance(raw_answer, bool):
        return "正确" if raw_answer else "错误"

    q_type = str(question_type).strip().lower()
    option_map = _build_option_content_map(options)

    if isinstance(raw_answer, (list, tuple)):
        items = [str(x).strip() for x in raw_answer if x is not None and str(x).strip()]
        if q_type in ("single_choice", "multiple_choice"):
            extracted = [_extract_choice_key(item, option_map) for item in items]
            if extracted and all(k is not None for k in extracted):
                return ",".join(k for k in extracted if k is not None)
        if all(len(x) == 1 and x.isalpha() for x in items):
            return ",".join(x.upper() for x in items)
        return "; ".join(items) if len(items) > 1 else (items[0] if items else "")

    text = str(raw_answer).strip()
    if q_type == "true_false":
        upper = text.upper()
        if upper in _TRUE_BOOL_STRS:
            return "正确"
        if upper in _FALSE_BOOL_STRS:
            return "错误"
        return text

    if q_type in ("single_choice", "multiple_choice"):
        return _normalize_choice_answer_text(text, question_type=q_type, option_map=option_map)

    return text


def _clean_optional_rubric(raw_rubric: Any) -> Any:
    """将空串、占位词或空容器评分细则统一清洗为 None。"""
    if raw_rubric is None:
        return None
    if isinstance(raw_rubric, str):
        cleaned = raw_rubric.strip()
        if not cleaned or cleaned.lower() in ("none", "null", "无", "{}"):
            return None
        return cleaned
    if isinstance(raw_rubric, (list, tuple)):
        return list(raw_rubric) if raw_rubric else None
    if isinstance(raw_rubric, dict):
        return raw_rubric if raw_rubric else None
    return raw_rubric


class LLMQuestionOptionItem(BaseModel):
    """客观题选项条目。"""

    key: str = Field(description="选项标识，如 A, B, C, D")
    content: str = Field(description="选项文本内容")


class LLMGradingPointItem(BaseModel):
    """主观题采分要点条目。"""

    point: str = Field(description="采分要点阐述")
    score: int = Field(ge=1, description="本要点分值")

    @model_validator(mode="before")
    @classmethod
    def _normalize_point(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"point": data.strip() or "采分要点", "score": 1}
        if isinstance(data, dict):
            d = dict(data)
            if not d.get("point"):
                d["point"] = (
                    d.get("content")
                    or d.get("text")
                    or d.get("description")
                    or d.get("criterion")
                    or d.get("name")
                    or "采分要点"
                )
            d["score"] = _parse_int_score(d.get("score"), fallback=1)
            return d
        return data


class LLMGradingRubric(BaseModel):
    """主观题评分细则。"""

    total_score: int = Field(ge=1, description="主观题总分")
    points: list[LLMGradingPointItem] = Field(
        default_factory=list,
        description="采分要点列表",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_rubric(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"total_score": max(1, _sum_rubric_points(data)), "points": data}
        if isinstance(data, str):
            s = data.strip()
            if not s or s.lower() in ("none", "null", "无", "{}"):
                return {"total_score": 5, "points": []}
            return {"total_score": 5, "points": [{"point": s, "score": 5}]}
        if isinstance(data, dict):
            return _normalize_rubric_dict(data)
        return data


class LLMGeneratedQuestionItem(BaseModel):
    """大模型抽取的单道题目数据结构。"""

    question_type: str = Field(description="题型枚举")
    stem: str = Field(description="题干内容，至少 6 字符")
    options: list[LLMQuestionOptionItem] = Field(
        default_factory=list,
        description="客观题选项列表",
    )
    answer: str = Field(description="参考答案或标准答案")
    analysis: str = Field(default="", description="题目解析")
    difficulty: int = Field(default=3, ge=1, le=5, description="题目难度系数")
    grading_rubric: LLMGradingRubric | None = Field(
        default=None,
        description="主观题评分细则",
    )
    source_snippet_index: int = Field(
        default=0,
        description="主要依据的切片序号 (0~3)",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_item(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        if not d.get("stem") and ("question" in d or "title" in d):
            d["stem"] = d.get("question") or d.get("title")

        if "options" in d:
            d["options"] = _normalize_llm_options(d.get("options"))

        if "difficulty" not in d:
            if "target_difficulty" in d:
                d["difficulty"] = d["target_difficulty"]
            elif "difficulty_level" in d:
                d["difficulty"] = d["difficulty_level"]

        raw_answer = d.get("answer")
        if raw_answer is None:
            raw_answer = (
                d.get("correct_answer") if "correct_answer" in d else d.get("standard_answer")
            )
        d["answer"] = _normalize_llm_answer(
            raw_answer,
            question_type=str(d.get("question_type") or ""),
            options=d.get("options"),
        )

        if "grading_rubric" in d:
            d["grading_rubric"] = _clean_optional_rubric(d.get("grading_rubric"))

        return d


class LLMQuestionBatchOutput(BaseModel):
    """大模型批次出题输出容器 DTO。"""

    questions: list[LLMGeneratedQuestionItem] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_batch(cls, data: Any) -> Any:
        if isinstance(data, list):
            return {"questions": data}
        if isinstance(data, dict) and "questions" not in data and "items" in data:
            data["questions"] = data["items"]
        return data


__all__ = [
    "LLMGeneratedQuestionItem",
    "LLMGradingPointItem",
    "LLMGradingRubric",
    "LLMQuestionBatchOutput",
    "LLMQuestionOptionItem",
]
