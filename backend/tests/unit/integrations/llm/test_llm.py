"""大语言模型适配器模块单元测试套件。

严格遵循 AGENTS.md 规范：
- 零真实外部网络连接，使用 Mock/Fake 隔离测试；
- 覆盖数据传输契约、Fake 适配器、OpenAI 适配器、工厂函数；
- 行覆盖率与分支覆盖率门禁 >= 90%。
"""

import concurrent.futures
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import BaseModel

from app.core.errors import (
    LLMAuthError,
    LLMError,
    LLMTimeoutError,
)
from app.integrations.llm import (
    FakeLLMAdapter,
    LLMMessage,
    LLMOptions,
    LLMProtocol,
    LLMResponse,
    LLMUsage,
    OpenAICompatibleLLMAdapter,
    create_llm_adapter,
    create_structured_agent_graph,
)


class DummyOutput(BaseModel):
    """测试用 Pydantic 输出数据契约。"""

    name: str
    score: int


class TestLLMContracts:
    """数据模型与参数契约测试。"""

    def test_message_validation(self) -> None:
        """测试对话消息参数校验。"""
        msg = LLMMessage(role="user", content="Hello")
        assert msg.role == "user"
        assert msg.content == "Hello"

        with pytest.raises(ValueError, match="role 必须为"):
            LLMMessage(role="invalid_role", content="Hello")

        with pytest.raises(ValueError, match="content 不能为空字符串"):
            LLMMessage(role="user", content="   ")

    def test_options_validation(self) -> None:
        """测试调用控制选项参数校验。"""
        opts = LLMOptions(
            model="qwen-turbo",
            temperature=1.2,
            max_tokens=500,
            timeout=15.0,
            response_format="json_object",
        )
        assert opts.model == "qwen-turbo"
        assert opts.temperature == 1.2
        assert opts.max_tokens == 500
        assert opts.timeout == 15.0
        assert opts.response_format == "json_object"

        with pytest.raises(ValueError, match="temperature 必须在"):
            LLMOptions(temperature=-0.1)

        with pytest.raises(ValueError, match="temperature 必须在"):
            LLMOptions(temperature=2.1)

        with pytest.raises(ValueError, match="timeout 必须大于 0"):
            LLMOptions(timeout=0.0)

        with pytest.raises(ValueError, match="max_tokens 必须大于 0"):
            LLMOptions(max_tokens=0)

    def test_usage_validation(self) -> None:
        """测试 Token 消耗统计模型校验。"""
        usage = LLMUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        assert usage.prompt_tokens == 10
        assert usage.completion_tokens == 20
        assert usage.total_tokens == 30

        with pytest.raises(ValueError, match="token 数量不能小于 0"):
            LLMUsage(prompt_tokens=-1)

        with pytest.raises(ValueError, match="token 数量不能小于 0"):
            LLMUsage(completion_tokens=-1)

        with pytest.raises(ValueError, match="token 数量不能小于 0"):
            LLMUsage(total_tokens=-1)

    def test_response_dataclass(self) -> None:
        """测试模型响应数据传输对象只读属性。"""
        resp = LLMResponse(
            content="Answer",
            usage=LLMUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            model="qwen-max",
            duration_ms=25.0,
        )
        assert resp.content == "Answer"
        assert resp.model == "qwen-max"
        assert resp.duration_ms == 25.0


class TestFakeLLMAdapter:
    """Fake 大模型适配器测试。"""

    def test_fake_generate_default(self) -> None:
        """测试默认确定性哈希文本生成。"""
        adapter = FakeLLMAdapter()
        assert isinstance(adapter, LLMProtocol)

        messages1 = [LLMMessage(role="user", content="题目内容A")]
        messages2 = [LLMMessage(role="user", content="题目内容A")]
        messages3 = [LLMMessage(role="user", content="题目内容B")]

        resp1 = adapter.generate(messages1)
        resp2 = adapter.generate(messages2)
        resp3 = adapter.generate(messages3)

        assert resp1.content.startswith("Fake deterministic response")
        assert resp1.content == resp2.content
        assert resp1.content != resp3.content
        assert resp1.model == "qwen-max"
        assert resp1.duration_ms == 1.0

    def test_fake_generate_with_options(self) -> None:
        """测试自定义 options 传参。"""
        adapter = FakeLLMAdapter()
        resp = adapter.generate(
            [LLMMessage(role="user", content="测试自定义模型")],
            options=LLMOptions(model="custom-model"),
        )
        assert resp.model == "custom-model"

    def test_fake_canned_text(self) -> None:
        """测试预置文本与预置 LLMResponse 命中。"""
        adapter = FakeLLMAdapter()
        adapter.set_canned_response("关键词A", "预置回答内容A")

        custom_resp = LLMResponse(
            content="预置对象回答B",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=50, total_tokens=150),
            model="custom-resp-model",
            duration_ms=10.0,
        )
        adapter.set_canned_response("关键词B", custom_resp)

        hit_a = adapter.generate([LLMMessage(role="user", content="包含关键词A的内容")])
        assert hit_a.content == "预置回答内容A"

        hit_b = adapter.generate([LLMMessage(role="user", content="包含关键词B的内容")])
        assert hit_b == custom_resp

    def test_fake_canned_structured(self) -> None:
        """测试预设结构化 Pydantic 模型绑定返回。"""
        adapter = FakeLLMAdapter()
        expected = DummyOutput(name="zhilian", score=99)
        adapter.set_canned_structured_response(DummyOutput, expected)

        obj, resp = adapter.generate_structured(
            [LLMMessage(role="user", content="获取结构化输出")],
            DummyOutput,
        )
        assert obj == expected
        assert obj.name == "zhilian"
        assert obj.score == 99
        assert "zhilian" in resp.content

    def test_fake_generate_structured_fallback_to_graph(self) -> None:
        """测试未配置预设模型时自动走 Agent 状态图自愈流程。"""
        adapter = FakeLLMAdapter()
        adapter.set_canned_response("结构化测试", '{"name": "test_auto", "score": 100}')
        obj, _resp = adapter.generate_structured(
            [LLMMessage(role="user", content="结构化测试")],
            DummyOutput,
        )
        assert obj.name == "test_auto"
        assert obj.score == 100

    def test_fake_latency_and_fault(self) -> None:
        """测试模拟网络时延与故障注入。"""
        adapter = FakeLLMAdapter()
        adapter.set_latency(0.001)

        # 针对 generate 注入全局异常
        adapter.set_fault_injection("generate", LLMTimeoutError("模拟超时"))
        with pytest.raises(LLMTimeoutError, match="模拟超时"):
            adapter.generate([LLMMessage(role="user", content="任何消息")])

        adapter.reset()
        ok_resp = adapter.generate([LLMMessage(role="user", content="恢复正常")])
        assert ok_resp.content.startswith("Fake deterministic response")

        # 针对 Prompt 关键词注入
        adapter.set_fault_injection("敏感词", LLMError("敏感词拦截"))
        with pytest.raises(LLMError, match="敏感词拦截"):
            adapter.generate([LLMMessage(role="user", content="带有敏感词的消息")])

        # 针对不匹配的 key，不应抛出异常
        adapter.set_fault_injection("不存在的关键词", LLMError("不应触发"))
        normal_resp = adapter.generate([LLMMessage(role="user", content="常规请求")])
        assert normal_resp.content.startswith("Fake deterministic response")

        # 针对 "all" 注入
        adapter.set_fault_injection("all", LLMError("全局故障"))
        with pytest.raises(LLMError, match="全局故障"):
            adapter.generate([LLMMessage(role="user", content="测试")])

    def test_fake_thread_safety(self) -> None:
        """测试多线程并发安全。"""
        adapter = FakeLLMAdapter()

        def _worker(idx: int) -> str:
            msg = [LLMMessage(role="user", content=f"并发测试提示词-{idx}")]
            if idx % 2 == 0:
                adapter.set_canned_response(f"并发测试提示词-{idx}", f"预置并发回答-{idx}")
            return adapter.generate(msg).content

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_worker, i) for i in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 20

    def test_fake_repr(self) -> None:
        """测试 repr 绝密脱敏统计展示。"""
        adapter = FakeLLMAdapter()
        adapter.set_canned_response("key", "val")
        adapter.set_latency(0.05)
        repr_str = repr(adapter)
        str_str = str(adapter)
        assert "canned_count=1" in repr_str
        assert "latency_seconds=0.05" in repr_str
        assert "val" not in repr_str
        assert repr_str == str_str


class TestOpenAICompatibleLLMAdapter:
    """生产级 OpenAI 兼容适配器测试。"""

    def test_openai_init_validation(self) -> None:
        """测试初始化参数校验。"""
        with pytest.raises(LLMAuthError, match="api_key 不能为空"):
            OpenAICompatibleLLMAdapter(api_key="")

        with pytest.raises(LLMAuthError, match="api_key 不能为空"):
            OpenAICompatibleLLMAdapter(api_key="   ")

        with pytest.raises(LLMError, match="timeout 必须大于 0"):
            OpenAICompatibleLLMAdapter(api_key="sk-test", timeout=-1.0)

        with pytest.raises(LLMError, match="max_retries 不能小于 0"):
            OpenAICompatibleLLMAdapter(api_key="sk-test", max_retries=-1)

    def test_openai_repr_masks_api_key(self) -> None:
        """测试 api_key 绝对脱敏红线。"""
        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-live-secret-998877665544332211",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        repr_str = repr(adapter)
        str_str = str(adapter)
        assert "sk-live-secret-998877665544332211" not in repr_str
        assert "api_key='******'" in repr_str
        assert "api_key='******'" in str_str

    def test_openai_generate_success(self) -> None:
        """测试正常自由补全调用成功流转。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "模型生成的解答内容",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 25,
                "total_tokens": 40,
            },
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=mock_client,
            retry_delay_base=0.001,
        )

        resp = adapter.generate(
            [
                LLMMessage(role="system", content="你是智能助教"),
                LLMMessage(role="user", content="请解析知识点"),
            ],
            options=LLMOptions(model="qwen-plus", temperature=0.5, max_tokens=200),
        )

        assert resp.content == "模型生成的解答内容"
        assert resp.model == "qwen-plus"
        assert resp.usage.prompt_tokens == 15
        assert resp.usage.completion_tokens == 25
        assert resp.usage.total_tokens == 40
        assert resp.duration_ms >= 0.0
        mock_client.post.assert_called_once()

    def test_openai_dynamic_timeout(self) -> None:
        """测试 options.timeout 动态覆盖默认超时。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            timeout=30.0,
            client=mock_client,
        )

        # 传入 options.timeout = 60.0
        adapter.generate(
            [LLMMessage(role="user", content="长耗时出题")],
            options=LLMOptions(timeout=60.0),
        )
        _, kwargs = mock_client.post.call_args
        assert kwargs.get("timeout") == 60.0

    def test_openai_tool_calls_payload_and_parsing(self) -> None:
        """测试 options.tools 与 options.tool_choice 注入 payload 并正确解析 tool_calls 响应。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_abc123",
                                "type": "function",
                                "function": {
                                    "name": "submit_structured_output",
                                    "arguments": '{"score": 95}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=mock_client,
        )

        test_tools = [
            {
                "type": "function",
                "function": {
                    "name": "submit_structured_output",
                    "parameters": {"type": "object"},
                },
            }
        ]
        resp = adapter.generate(
            [LLMMessage(role="user", content="请打分")],
            options=LLMOptions(
                tools=test_tools,
                tool_choice={"type": "function", "function": {"name": "submit_structured_output"}},
            ),
        )

        _, kwargs = mock_client.post.call_args
        sent_payload = kwargs.get("json", {})
        assert sent_payload.get("tools") == test_tools
        assert sent_payload.get("tool_choice") == {
            "type": "function",
            "function": {"name": "submit_structured_output"},
        }

        assert resp.tool_calls is not None
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].id == "call_abc123"
        assert resp.tool_calls[0].name == "submit_structured_output"
        assert resp.tool_calls[0].arguments == '{"score": 95}'

    def test_openai_auth_error_no_retry(self) -> None:
        """测试 401/403 鉴权失败立即阻断抛出 LLMAuthError，无多余重试。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Invalid API Key"
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-invalid",
            client=mock_client,
            max_retries=3,
            retry_delay_base=0.001,
        )

        with pytest.raises(LLMAuthError, match="认证失败"):
            adapter.generate([LLMMessage(role="user", content="测试")])

        assert mock_client.post.call_count == 1

    def test_openai_retry_on_429_then_success(self) -> None:
        """测试 429 频率限制指数退避重试并最终成功。"""
        mock_client = MagicMock()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.text = "Rate limit exceeded"

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "choices": [{"message": {"content": "重试后成功"}}],
            "usage": {},
        }
        mock_client.post.side_effect = [resp_429, resp_200]

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=2,
            retry_delay_base=0.001,
        )

        resp = adapter.generate([LLMMessage(role="user", content="测试重试")])
        assert resp.content == "重试后成功"
        assert mock_client.post.call_count == 2

    def test_openai_retry_on_5xx_exhausted(self) -> None:
        """测试 503 持续服务端错误直至重试耗尽抛出 LLMError。"""
        mock_client = MagicMock()
        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.text = "Service Unavailable"
        mock_client.post.return_value = resp_503

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=2,
            retry_delay_base=0.001,
        )

        with pytest.raises(LLMError, match="暂时不可用"):
            adapter.generate([LLMMessage(role="user", content="测试重试耗尽")])

        assert mock_client.post.call_count == 3

    def test_openai_timeout_mapped_to_app_error(self) -> None:
        """测试 httpx.TimeoutException 转译为 LLMTimeoutError。"""
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("Read timed out")

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=1,
            retry_delay_base=0.001,
        )

        with pytest.raises(LLMTimeoutError, match="大模型服务响应超时"):
            adapter.generate([LLMMessage(role="user", content="测试")])

    def test_openai_request_error_mapped_to_llm_error(self) -> None:
        """测试网络连接错误转译为 LLMError。"""
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.RequestError("Connection reset")

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=1,
            retry_delay_base=0.001,
        )

        with pytest.raises(LLMError, match="网络请求异常"):
            adapter.generate([LLMMessage(role="user", content="测试")])

    def test_openai_bad_response_cases(self) -> None:
        """测试非 200 状态码、JSON 解码失败与 choices 缺失场景。"""
        mock_client = MagicMock()
        resp = MagicMock()

        # 400 Bad Request
        resp.status_code = 400
        resp.text = "Bad Request"
        mock_client.post.return_value = resp

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=mock_client,
            max_retries=0,
        )
        with pytest.raises(LLMError, match="返回异常状态码: 400"):
            adapter.generate([LLMMessage(role="user", content="测试")])

        # 200 但 JSON 解码失败
        resp.status_code = 200
        resp.json.side_effect = ValueError("Invalid JSON string")
        with pytest.raises(LLMError, match="反序列化失败"):
            adapter.generate([LLMMessage(role="user", content="测试")])

        # 200 但缺少 choices
        resp.json.side_effect = None
        resp.json.return_value = {"choices": []}
        with pytest.raises(LLMError, match="未包含有效 choices 内容"):
            adapter.generate([LLMMessage(role="user", content="测试")])

    def test_openai_default_client_init(self) -> None:
        """测试未注入客户端时的客户端实例化。"""
        adapter = OpenAICompatibleLLMAdapter(api_key="sk-test", timeout=45.0)
        client = adapter._get_client(effective_timeout=45.0)
        assert isinstance(client, httpx.Client)
        assert client.timeout.read == 45.0

    def test_openai_generate_options_response_format(self) -> None:
        """测试传入 response_format 选项。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"name": "json_mode", "score": 90}'}}],
            "usage": {},
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(api_key="sk-test", client=mock_client)
        resp = adapter.generate(
            [LLMMessage(role="user", content="请输出JSON")],
            options=LLMOptions(response_format="json_object"),
        )
        assert "json_mode" in resp.content
        _call_args, kwargs = mock_client.post.call_args
        payload = kwargs.get("json", {})
        assert payload.get("response_format") == {"type": "json_object"}

    def test_openai_generate_structured_direct(self) -> None:
        """测试直接通过 OpenAICompatibleLLMAdapter 调用 generate_structured。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"name": "direct", "score": 80}'}}],
            "usage": {},
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(api_key="sk-test", client=mock_client)
        obj, _resp = adapter.generate_structured(
            [LLMMessage(role="user", content="生成数据")],
            DummyOutput,
        )
        assert obj.name == "direct"
        assert obj.score == 80

    def test_openai_client_type_error_fallback(self) -> None:
        """测试注入的不支持 timeout 关键字参数的 client 回退分支。"""

        class DummyClientWithoutTimeout:
            def post(self, url: str, json: dict[str, Any], headers: dict[str, Any]) -> Any:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {"choices": [{"message": {"content": "ok_fallback"}}]}
                return resp

        adapter = OpenAICompatibleLLMAdapter(
            api_key="sk-test",
            client=DummyClientWithoutTimeout(),
        )
        resp = adapter.generate([LLMMessage(role="user", content="hi")])
        assert resp.content == "ok_fallback"


class TestLLMFactory:
    """工厂函数测试。"""

    def test_create_llm_adapter(self) -> None:
        """测试适配器类型分发。"""
        fake = create_llm_adapter("fake")
        assert isinstance(fake, FakeLLMAdapter)

        openai = create_llm_adapter("openai", api_key="sk-test")
        assert isinstance(openai, OpenAICompatibleLLMAdapter)

        dashscope = create_llm_adapter("dashscope", api_key="sk-test")
        assert isinstance(dashscope, OpenAICompatibleLLMAdapter)
        assert "dashscope.aliyuncs.com" in dashscope.base_url

        deepseek = create_llm_adapter("deepseek", api_key="sk-test")
        assert isinstance(deepseek, OpenAICompatibleLLMAdapter)
        assert "api.deepseek.com" in deepseek.base_url

        siliconflow = create_llm_adapter("siliconflow", api_key="sk-test")
        assert isinstance(siliconflow, OpenAICompatibleLLMAdapter)
        assert "api.siliconflow.cn" in siliconflow.base_url

        custom = create_llm_adapter(
            "openai",
            api_key="sk-test",
            base_url="https://custom.endpoint.com/v1",
        )
        assert isinstance(custom, OpenAICompatibleLLMAdapter)
        assert custom.base_url == "https://custom.endpoint.com/v1"

        with pytest.raises(LLMError, match="需要提供有效的 api_key"):
            create_llm_adapter("openai")

        with pytest.raises(LLMError, match="未知的 LLM 适配器类型"):
            create_llm_adapter("unsupported_provider")

    def test_create_structured_agent_graph(self) -> None:
        """测试创建编译后的结构化 Agent 状态图。"""
        fake = FakeLLMAdapter()
        graph = create_structured_agent_graph(fake)
        assert hasattr(graph, "invoke")
