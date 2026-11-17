"""VLM 工厂与 LLMMessage.image_urls 多模态序列化单元测试（离线、确定性）。"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.core.errors import LLMError
from app.integrations.llm import (
    FakeLLMAdapter,
    LLMMessage,
    OpenAICompatibleLLMAdapter,
)
from app.integrations.llm.factory import create_vlm_adapter

SILICONFLOW_URL = "https://api.siliconflow.cn/v1"
IMG_A = "data:image/png;base64,AAAA"
IMG_B = "https://example.com/page-2.png"


def _ok_client() -> MagicMock:
    """构造返回固定成功响应的 mock HTTP 客户端。"""
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": "转录结果"}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }
    client = MagicMock()
    client.post.return_value = response
    return client


def _sent_payload(client: MagicMock) -> dict[str, Any]:
    """取出 mock 客户端收到的 JSON 请求体。"""
    client.post.assert_called_once()
    payload = client.post.call_args.kwargs["json"]
    assert isinstance(payload, dict)
    return payload


class TestCreateVlmAdapter:
    """create_vlm_adapter 降级与装配规则。"""

    def test_disabled_returns_none(self) -> None:
        """enabled=False 即便配了 key 也返回 None。"""
        assert create_vlm_adapter(enabled=False, adapter_type="siliconflow", api_key="k") is None

    def test_fake_returns_none(self) -> None:
        """provider=fake 返回 None。"""
        assert create_vlm_adapter(enabled=True, adapter_type="fake", api_key="k") is None

    @pytest.mark.parametrize("api_key", [None, ""])
    def test_missing_key_returns_none(self, api_key: str | None) -> None:
        """缺少 api_key 降级为 None，不阻断主链路。"""
        assert create_vlm_adapter(enabled=True, adapter_type="siliconflow", api_key=api_key) is None

    def test_siliconflow_default_base_url_and_model(self) -> None:
        """siliconflow 缺省 base_url 为官方地址，模型沿用 VLM 默认。"""
        adapter = create_vlm_adapter(enabled=True, adapter_type="siliconflow", api_key="sk-x")

        assert isinstance(adapter, OpenAICompatibleLLMAdapter)
        assert adapter.base_url == SILICONFLOW_URL
        assert adapter.model == "Qwen/Qwen2.5-VL-7B-Instruct"

    def test_siliconflow_explicit_base_url_wins(self) -> None:
        """显式 base_url 优先于默认值，且尾部斜杠被规整。"""
        adapter = create_vlm_adapter(
            enabled=True,
            adapter_type="siliconflow",
            api_key="sk-x",
            base_url="https://proxy.internal/v1/",
            model="m",
            timeout=9.0,
            max_retries=0,
        )

        assert isinstance(adapter, OpenAICompatibleLLMAdapter)
        assert adapter.base_url == "https://proxy.internal/v1"
        assert adapter.model == "m"
        assert adapter.timeout == 9.0
        assert adapter.max_retries == 0

    def test_openai_without_base_url_uses_adapter_default(self) -> None:
        """openai provider 不套用 siliconflow 默认地址。"""
        adapter = create_vlm_adapter(enabled=True, adapter_type="openai", api_key="sk-x")

        assert isinstance(adapter, OpenAICompatibleLLMAdapter)
        assert adapter.base_url != SILICONFLOW_URL

    def test_adapter_type_is_case_insensitive(self) -> None:
        """适配器类型大小写不敏感。"""
        adapter = create_vlm_adapter(enabled=True, adapter_type="SiliconFlow", api_key="sk-x")

        assert isinstance(adapter, OpenAICompatibleLLMAdapter)
        assert adapter.base_url == SILICONFLOW_URL

    def test_unknown_type_raises(self) -> None:
        """未知类型抛 LLMError（即便 disabled）。"""
        with pytest.raises(LLMError, match="未知的 VLM 适配器类型"):
            create_vlm_adapter(enabled=True, adapter_type="nope", api_key="k")
        with pytest.raises(LLMError, match="未知的 VLM 适配器类型"):
            create_vlm_adapter(enabled=False, adapter_type="nope")

    def test_injected_client_is_used(self) -> None:
        """注入的 client 被透传到适配器（离线打桩）。"""
        client = _ok_client()
        adapter = create_vlm_adapter(
            enabled=True, adapter_type="siliconflow", api_key="sk-x", client=client
        )
        assert adapter is not None

        adapter.generate([LLMMessage(role="user", content="识别", image_urls=(IMG_A,))])

        client.post.assert_called_once()
        assert client.post.call_args.args[0] == f"{SILICONFLOW_URL}/chat/completions"


class TestLLMMessageImages:
    """LLMMessage.image_urls 契约。"""

    def test_default_is_empty_tuple(self) -> None:
        """缺省无图片。"""
        assert LLMMessage(role="user", content="hi").image_urls == ()

    def test_accepts_urls_and_data_uri(self) -> None:
        """接受 https URL 与 data URI。"""
        msg = LLMMessage(role="user", content="hi", image_urls=(IMG_A, IMG_B))

        assert msg.image_urls == (IMG_A, IMG_B)

    @pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
    def test_rejects_empty_image_url(self, bad: str) -> None:
        """空白图片 URL 被拒绝。"""
        with pytest.raises(ValueError, match="image_urls 不能包含空字符串"):
            LLMMessage(role="user", content="hi", image_urls=(IMG_A, bad))

    def test_still_rejects_empty_content_with_images(self) -> None:
        """有图片也不能豁免空 content。"""
        with pytest.raises(ValueError, match="content 不能为空字符串"):
            LLMMessage(role="user", content=" ", image_urls=(IMG_A,))

    def test_is_frozen(self) -> None:
        """消息不可变。"""
        msg = LLMMessage(role="user", content="hi", image_urls=(IMG_A,))

        with pytest.raises(AttributeError):
            msg.image_urls = ()  # type: ignore[misc]


class TestOpenAIImagePayload:
    """OpenAI 兼容适配器的多模态消息序列化。"""

    def test_image_message_becomes_content_blocks(self) -> None:
        """含图片 → [text, image_url...] 内容块数组（保持顺序）。"""
        client = _ok_client()
        adapter = OpenAICompatibleLLMAdapter(api_key="sk-t", client=client)

        resp = adapter.generate(
            [LLMMessage(role="user", content="转录此页", image_urls=(IMG_A, IMG_B))]
        )

        assert resp.content == "转录结果"
        assert _sent_payload(client)["messages"] == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "转录此页"},
                    {"type": "image_url", "image_url": {"url": IMG_A}},
                    {"type": "image_url", "image_url": {"url": IMG_B}},
                ],
            }
        ]

    def test_plain_messages_stay_strings(self) -> None:
        """无图片消息保持纯字符串 content（行为不回归）。"""
        client = _ok_client()
        adapter = OpenAICompatibleLLMAdapter(api_key="sk-t", client=client)

        adapter.generate(
            [
                LLMMessage(role="system", content="你是助教"),
                LLMMessage(role="user", content="你好"),
            ]
        )

        assert _sent_payload(client)["messages"] == [
            {"role": "system", "content": "你是助教"},
            {"role": "user", "content": "你好"},
        ]

    def test_mixed_messages_only_image_one_is_blocks(self) -> None:
        """混合序列中仅带图消息被展开为内容块。"""
        client = _ok_client()
        adapter = OpenAICompatibleLLMAdapter(api_key="sk-t", client=client)

        adapter.generate(
            [
                LLMMessage(role="system", content="只输出 Markdown"),
                LLMMessage(role="user", content="识别", image_urls=(IMG_A,)),
            ]
        )

        messages = _sent_payload(client)["messages"]
        assert messages[0] == {"role": "system", "content": "只输出 Markdown"}
        assert messages[1]["content"] == [
            {"type": "text", "text": "识别"},
            {"type": "image_url", "image_url": {"url": IMG_A}},
        ]


class TestFakeIgnoresImages:
    """FakeLLMAdapter 忽略 image_urls。"""

    def test_same_output_with_and_without_images(self) -> None:
        """确定性输出仅取决于文本。"""
        adapter = FakeLLMAdapter()

        plain = adapter.generate([LLMMessage(role="user", content="识别此页")])
        with_images = adapter.generate(
            [LLMMessage(role="user", content="识别此页", image_urls=(IMG_A, IMG_B))]
        )

        assert plain.content == with_images.content

    def test_canned_response_matches_with_images(self) -> None:
        """预置响应对带图消息同样生效。"""
        adapter = FakeLLMAdapter()
        adapter.set_canned_response("识别此页", "预置转录")

        resp = adapter.generate([LLMMessage(role="user", content="识别此页", image_urls=(IMG_A,))])

        assert resp.content == "预置转录"
