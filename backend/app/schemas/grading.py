"""判题、自评与重判数据契约与 DTO 校验模型定义。

严格遵循 AGENTS.md 规范与 spec.md 技术契约：
- 字段类型全标注，支持 Pydantic v2 与 from_attributes 特性；
- 缩写白名单仅限 api, id, url, ocr, llm, db, config, env；
- Google 风格中文 Docstring。
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SelfEvaluateRequest(BaseModel):
    """主观题用户自主评分请求入参模型。"""

    attempt_item_id: uuid.UUID = Field(..., description="关联作答项主键 UUIDv4")
    score: float = Field(
        ...,
        ge=0.0,
        description="用户自主评定得分 (必须大于等于 0.0)",
    )
    is_correct: bool | None = Field(
        default=None,
        description="是否判定为正确 (若为空由系统依据 score > 0 自动判定)",
    )
    feedback: str | None = Field(
        default=None,
        max_length=1000,
        description="用户自评反馈说明与心得 (绝密数据，严禁直接写入日志)",
    )


class SelfEvaluateResponse(BaseModel):
    """主观题用户自主评分响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    grading_record_id: uuid.UUID = Field(..., description="生成生效的判题记录主键 UUIDv4")
    id: uuid.UUID | None = Field(default=None, description="判题记录标识别名")
    attempt_item_id: uuid.UUID = Field(..., description="关联作答项主键 UUIDv4")
    score: float = Field(..., ge=0.0, description="自评得分")
    is_final: bool = Field(default=True, description="是否生效为最终判定结果")
    evaluated_at: datetime | None = Field(default=None, description="自评完成时间戳")
    created_at: datetime | None = Field(default=None, description="记录生成时间戳")
    feedback: str | None = Field(default=None, description="自评反馈说明")
    channel: str = Field(default="user_self", description="判题渠道 (固定为 user_self)")

    @model_validator(mode="before")
    @classmethod
    def synchronize_self_evaluate_fields(cls, data: Any) -> Any:
        """同步 grading_record_id 与 id，以及 evaluated_at 与 created_at。"""
        if isinstance(data, dict):
            if "grading_record_id" not in data and "id" in data:
                data["grading_record_id"] = data["id"]
            elif "id" not in data and "grading_record_id" in data:
                data["id"] = data["grading_record_id"]

            if "evaluated_at" not in data and "created_at" in data:
                data["evaluated_at"] = data["created_at"]
            elif "created_at" not in data and "evaluated_at" in data:
                data["created_at"] = data["evaluated_at"]
        return data


class RegradeRequest(BaseModel):
    """申请重新判题请求入参模型。"""

    attempt_item_id: uuid.UUID = Field(..., description="关联作答项主键 UUIDv4")
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="申请重新判题的原因阐述",
    )


# 别名定义以保持兼容性
RegradeAttemptRequest = RegradeRequest


class RegradeResponse(BaseModel):
    """申请重新判题受理响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    attempt_item_id: uuid.UUID = Field(..., description="关联作答项主键 UUIDv4")
    status: str = Field(
        default="pending_regrade",
        description="重判处理状态 (如: pending_regrade)",
    )
    message: str = Field(default="", description="重判受理提示信息")
    grading_record_id: uuid.UUID | None = Field(
        default=None,
        description="重判关联的新判题记录主键标识 (可选)",
    )


class GradingRecordDTO(BaseModel):
    """判题审计记录数据传输对象模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID = Field(..., description="判题记录主键 UUIDv4")
    attempt_item_id: uuid.UUID = Field(..., description="关联作答项主键 UUIDv4")
    practice_id: uuid.UUID | None = Field(default=None, description="所属练习主键标识")
    question_id: uuid.UUID | None = Field(default=None, description="弱关联题目标识")
    channel: str = Field(
        ...,
        description="判题渠道 (offline: 离线规则, ai: 大模型判分, user_self: 用户自评)",
    )
    status: str = Field(
        default="success",
        description="判题处理状态 (pending, success, pending_regrade, failed)",
    )
    score: float | None = Field(default=None, description="判定得分")
    max_score: float = Field(default=1.0, description="题目满分基准分值")
    feedback: str | None = Field(
        default=None,
        description="判题评语与得分反馈说明 (绝密数据，严禁记录入日志)",
    )
    is_final: bool = Field(default=True, description="是否为最终生效判分结果")
    error_type: str | None = Field(
        default=None,
        description="错题归因类型 (conceptual, incomplete_expression 等)",
    )
    similarity_score: float | None = Field(
        default=None,
        description="主观题离线双阈值比对相似度 (0.0~1.0)",
    )
    confidence: float | None = Field(
        default=None,
        description="判题置信度评分 (0.0~1.0)",
    )
    hit_keywords: list[str] = Field(
        default_factory=list,
        description="命中要点关键词列表",
    )
    missing_keywords: list[str] = Field(
        default_factory=list,
        description="遗漏核心要点列表",
    )
    created_at: datetime | None = Field(default=None, description="记录创建时间戳")


# 别名定义以保持兼容性
GradingRecordResponse = GradingRecordDTO


class AttemptGradingDetailResponse(BaseModel):
    """作答判题记录与历史明细响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    attempt_item_id: uuid.UUID = Field(..., description="关联作答项主键 UUIDv4")
    practice_id: uuid.UUID | None = Field(default=None, description="所属练习主键标识")
    question_id: uuid.UUID | None = Field(default=None, description="弱关联题目标识")
    latest_grading: GradingRecordDTO | None = Field(
        default=None,
        description="最新生效判题记录",
    )
    current_record: GradingRecordDTO | None = Field(
        default=None,
        description="最新生效判题记录别名",
    )
    records: list[GradingRecordDTO] = Field(
        default_factory=list,
        description="全部判题记录列表",
    )
    history: list[GradingRecordDTO] = Field(
        default_factory=list,
        description="判题历史记录别名列表",
    )

    @model_validator(mode="before")
    @classmethod
    def synchronize_detail_records(cls, data: Any) -> Any:
        """同步 latest_grading 与 current_record，以及 records 与 history。"""
        if isinstance(data, dict):
            # 同步 latest_grading 与 current_record
            if "latest_grading" not in data and "current_record" in data:
                data["latest_grading"] = data["current_record"]
            elif "current_record" not in data and "latest_grading" in data:
                data["current_record"] = data["latest_grading"]

            # 同步 records 与 history
            if "records" not in data and "history" in data:
                data["records"] = data["history"]
            elif "history" not in data and "records" in data:
                data["history"] = data["records"]
        return data
