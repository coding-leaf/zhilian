"""基于 LangGraph StateGraph 的 Agent 状态机引擎单元测试套件。

严格遵循 AGENTS.md 规范：
- 零真实外部网络连接，使用 Mock/Fake 隔离测试；
- 全生命周期覆盖：直接成功、Markdown 解析、单次自愈重试、自愈耗尽阻断；
- 多线程并发隔离验证；
- 行覆盖率与分支覆盖率门禁 >= 90%。
"""

import concurrent.futures
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field

from app.core.errors import LLMResponseFormatError
from app.integrations.llm import (
    AgentWorkflowState,
    FakeLLMAdapter,
    LLMMessage,
    LLMOptions,
    LLMResponse,
    LLMUsage,
    OpenAICompatibleLLMAdapter,
    build_structured_agent_graph,
    call_model_node,
    decide_after_validation,
    fallback_node,
    repair_prompt_node,
    run_structured_agent_workflow,
    validate_output_node,
)


class StudentReport(BaseModel):
    """用于测试的结构化数据契约模型。"""

    student_id: str
    mastery_rate: float = Field(ge=0.0, le=1.0)
    suggestions: list[str]


class TestAgentGraphWorkflow:
    """LangGraph 状态机图执行流程测试。"""

    def test_graph_direct_success(self) -> None:
        """测试一次性生成合规 JSON 并直接校验成功流转至 END。"""
        fake_adapter = FakeLLMAdapter()
        valid_json = (
            '{"student_id": "STU001", "mastery_rate": 0.85, '
            '"suggestions": ["复习代数", "加强刷题"]}'
        )
        fake_adapter.set_canned_response("评估报告", valid_json)

        obj, resp = run_structured_agent_workflow(
            adapter=fake_adapter,
            messages=[LLMMessage(role="user", content="生成学生评估报告")],
            response_model=StudentReport,
        )

        assert isinstance(obj, StudentReport)
        assert obj.student_id == "STU001"
        assert obj.mastery_rate == 0.85
        assert len(obj.suggestions) == 2
        assert resp.content == valid_json

    def test_graph_markdown_json_success(self) -> None:
        """测试大模型返回 Markdown 代码块时的剥离与反序列化。"""
        fake_adapter = FakeLLMAdapter()
        markdown_content = """```json
{
  "student_id": "STU002",
  "mastery_rate": 0.92,
  "suggestions": ["拓展竞赛题"]
}
```"""
        fake_adapter.set_canned_response("代码块报告", markdown_content)

        obj, resp = run_structured_agent_workflow(
            adapter=fake_adapter,
            messages=[LLMMessage(role="user", content="代码块报告")],
            response_model=StudentReport,
        )

        assert obj.student_id == "STU002"
        assert obj.mastery_rate == 0.92
        assert obj.suggestions == ["拓展竞赛题"]
        assert resp.content == markdown_content

    def test_graph_single_repair_flow(self) -> None:
        """测试单次残缺输出触发 repair_prompt_node 自愈重试并成功。"""
        fake_adapter = FakeLLMAdapter()

        # 首次调用匹配关键词，返回损坏 JSON
        broken_json = '{"student_id": "STU003", "mastery_rate": 1.5, "suggestions": "不是列表"}'
        fake_adapter.set_canned_response("待自愈报告", broken_json)

        # repair 节点追加诊断后，包含 "Your previous response failed validation" 关键词
        repaired_json = (
            '{"student_id": "STU003", "mastery_rate": 0.75, "suggestions": ["修正后的建议"]}'
        )
        fake_adapter.set_canned_response("Your previous response failed validation", repaired_json)

        obj, resp = run_structured_agent_workflow(
            adapter=fake_adapter,
            messages=[LLMMessage(role="user", content="生成待自愈报告")],
            response_model=StudentReport,
        )

        assert obj.student_id == "STU003"
        assert obj.mastery_rate == 0.75
        assert obj.suggestions == ["修正后的建议"]
        assert resp.content == repaired_json

    def test_graph_repair_exhausted_fail(self) -> None:
        """测试自愈 1 次后仍然校验失败，流向 fallback_node 并抛出 30014 异常。"""
        fake_adapter = FakeLLMAdapter()
        # 持续返回损坏的非法 JSON
        persistent_bad = '{"student_id": "STU004", bad_syntax'
        fake_adapter.set_canned_response("持续损坏", persistent_bad)

        with pytest.raises(
            LLMResponseFormatError, match="结构化 Agent 状态图校验自愈失败"
        ) as exc_info:
            run_structured_agent_workflow(
                adapter=fake_adapter,
                messages=[LLMMessage(role="user", content="持续损坏报告")],
                response_model=StudentReport,
            )

        err = exc_info.value
        assert err.error_code == 30014
        assert err.status_code == 502
        assert err.details.get("retry_count") == 1

    def test_graph_concurrency_safety(self) -> None:
        """测试多线程并发执行状态图互不干扰。"""
        fake_adapter = FakeLLMAdapter()
        for i in range(10):
            payload = f'{{"student_id": "STU-{i}", "mastery_rate": 0.5, "suggestions": ["s-{i}"]}}'
            fake_adapter.set_canned_response(f"并发报告-{i}", payload)

        def _worker(idx: int) -> StudentReport:
            obj, _ = run_structured_agent_workflow(
                adapter=fake_adapter,
                messages=[LLMMessage(role="user", content=f"并发报告-{idx}")],
                response_model=StudentReport,
            )
            return obj

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(_worker, i) for i in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 10
        returned_ids = {r.student_id for r in results}
        assert len(returned_ids) == 10

    def test_openai_generate_structured_delegation(self) -> None:
        """测试 OpenAI 适配器的 generate_structured 委托状态图正常工作。"""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        report_content = (
            '{"student_id": "STU-OPENAI", "mastery_rate": 0.88, "suggestions": ["多练难题"]}'
        )
        mock_response.json.return_value = {
            "choices": [{"message": {"content": report_content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
        mock_client.post.return_value = mock_response

        adapter = OpenAICompatibleLLMAdapter(api_key="sk-test", client=mock_client)
        obj, _resp = adapter.generate_structured(
            messages=[LLMMessage(role="user", content="请输出学生报告")],
            response_model=StudentReport,
            options=LLMOptions(temperature=0.2),
        )

        assert isinstance(obj, StudentReport)
        assert obj.student_id == "STU-OPENAI"
        assert obj.mastery_rate == 0.88


class TestAgentGraphUnitNodes:
    """状态图各个节点的边界与防御性单元测试。"""

    def test_call_model_node_missing_adapter(self) -> None:
        """测试缺少 adapter 时防御报错。"""
        state: AgentWorkflowState = {
            "messages": [LLMMessage(role="user", content="hi")],
        }
        with pytest.raises(ValueError, match="未指定有效 adapter"):
            call_model_node(state)

    def test_call_model_node_success(self) -> None:
        """测试 call_model_node 正常执行。"""
        fake_adapter = FakeLLMAdapter()
        fake_adapter.set_canned_response("test", "hello world")
        state: AgentWorkflowState = {
            "adapter": fake_adapter,
            "messages": [LLMMessage(role="user", content="test")],
            "options": None,
        }
        res = call_model_node(state)
        assert "raw_response" in res
        assert res["raw_response"].content == "hello world"

    def test_validate_output_node_missing_raw_response(self) -> None:
        """测试缺少 raw_response 时的状态返回。"""
        state: AgentWorkflowState = {
            "response_model": StudentReport,
        }
        res = validate_output_node(state)
        assert res["status"] == "failed"
        assert res["parsed_data"] is None
        assert "未获取到模型原始响应" in res["error_message"]

    def test_validate_output_node_missing_response_model(self) -> None:
        """测试缺少 response_model 时的状态返回。"""
        state: AgentWorkflowState = {
            "raw_response": LLMResponse(
                content="{}",
                usage=LLMUsage(),
                model="qwen-max",
            ),
        }
        res = validate_output_node(state)
        assert res["status"] == "failed"
        assert res["parsed_data"] is None
        assert "未指定 response_model" in res["error_message"]

    def test_validate_output_node_invalid_json(self) -> None:
        """测试非法 JSON 字符串。"""
        state: AgentWorkflowState = {
            "response_model": StudentReport,
            "raw_response": LLMResponse(
                content="not a json",
                usage=LLMUsage(),
                model="qwen-max",
            ),
        }
        res = validate_output_node(state)
        assert res["parsed_data"] is None
        assert res["error_message"] is not None

    def test_decide_after_validation_branches(self) -> None:
        """测试条件边的三大分支决策。"""
        # 分支 1: 已有校验成功数据 -> 结束
        state1: AgentWorkflowState = {
            "parsed_data": StudentReport(student_id="S", mastery_rate=0.5, suggestions=[]),
            "retry_count": 0,
        }
        assert decide_after_validation(state1) == "__end__"

        # 分支 2: 未成功且 retry_count == 0 -> 自愈
        state2: AgentWorkflowState = {
            "parsed_data": None,
            "retry_count": 0,
        }
        assert decide_after_validation(state2) == "repair_prompt_node"

        # 分支 3: 未成功且 retry_count >= 1 -> 阻断降级
        state3: AgentWorkflowState = {
            "parsed_data": None,
            "retry_count": 1,
        }
        assert decide_after_validation(state3) == "fallback_node"

    def test_repair_prompt_node_context_injection(self) -> None:
        """测试 repair_prompt_node 追加上下文与递增计数。"""
        state: AgentWorkflowState = {
            "retry_count": 0,
            "messages": [LLMMessage(role="user", content="请输出报告")],
            "raw_response": LLMResponse(
                content="残缺输出",
                usage=LLMUsage(),
                model="qwen-max",
            ),
            "error_message": "缺少必需字段 student_id",
        }
        res = repair_prompt_node(state)
        assert res["retry_count"] == 1
        msgs = res["messages"]
        assert len(msgs) == 3
        assert msgs[1].role == "assistant"
        assert msgs[1].content == "残缺输出"
        assert msgs[2].role == "user"
        assert "缺少必需字段 student_id" in msgs[2].content

    def test_fallback_node(self) -> None:
        """测试 fallback_node 状态输出。"""
        state: AgentWorkflowState = {"status": "pending"}
        res = fallback_node(state)
        assert res["status"] == "failed"

    def test_build_structured_agent_graph_lazy_adapter(self) -> None:
        """测试 build_structured_agent_graph 绑定 adapter 的图构造。"""
        fake_adapter = FakeLLMAdapter()
        fake_adapter.set_canned_response(
            "测试",
            '{"student_id": "S1", "mastery_rate": 0.5, "suggestions": []}',
        )
        graph = build_structured_agent_graph(adapter=fake_adapter)

        # 初始状态不传入 adapter，依靠图预绑的 adapter
        initial_state: AgentWorkflowState = {
            "messages": [LLMMessage(role="user", content="测试")],
            "response_model": StudentReport,
        }
        res = graph.invoke(initial_state)
        assert res.get("status") == "success"
        assert res.get("parsed_data") is not None

    def test_build_structured_agent_graph_no_adapter_raises(self) -> None:
        """测试未指定 adapter 且图未预绑 adapter 时 invoke 抛出 ValueError。"""
        graph = build_structured_agent_graph()
        initial_state: AgentWorkflowState = {
            "messages": [LLMMessage(role="user", content="测试")],
            "response_model": StudentReport,
        }
        with pytest.raises(ValueError, match="未指定 adapter"):
            graph.invoke(initial_state)

    def test_run_structured_agent_workflow_no_raw_response_on_fail(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """测试失败且无 raw_response 时的异常构造分支。"""
        fake_adapter = FakeLLMAdapter()
        mock_graph = MagicMock()
        mock_graph.invoke.return_value = {
            "status": "failed",
            "error_message": "模拟图执行失败",
            "raw_response": None,
        }
        monkeypatch.setattr(
            "app.integrations.llm.agent_graph.build_structured_agent_graph",
            lambda adapter=None: mock_graph,
        )

        with pytest.raises(LLMResponseFormatError, match="模拟图执行失败") as exc_info:
            run_structured_agent_workflow(
                adapter=fake_adapter,
                messages=[LLMMessage(role="user", content="测试")],
                response_model=StudentReport,
            )
        assert exc_info.value.details.get("last_content_preview") == ""
