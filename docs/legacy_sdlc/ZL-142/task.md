# Task ZL-142: 鉴权会话保持、资料解析重试与 LangGraph Tool Calling 框架化升级

- **任务编号**: ZL-142
- **评级**: Tier 2 (Bugfix & Architectural Alignment)
- **提出人**: User
- **创建时间**: 2026-09-26 02:00
- **终态**: Failed / Fall (已回滚至 02bf56b)

---

## 1. 任务背景与原始诉求

用户在测试出题功能后，提出三点优化与排查诉求：
1. 异常掉登录，登录时间过长；
2. 导入同一份文件显示解析异常且无重试标识；
3. 优化 LangGraph 流程并活用 tool_call，避免硬编码，活用 AI 框架。

---

## 2. 执行与失败记录 (Failure Retrospective)

### 实施变更内容 (Commit 76a7b07):
- 改造了 `backend/app/services/auth.py` 与 `miniprogram/src/pages/auth/login.vue`，重构了鉴权与 OpenID 解析逻辑；
- 修改了 `miniprogram/src/subpackages/material/components/MaterialCard.vue`、`detail/index.vue`、`list/index.vue`，添加了 FAILED 态重试按钮与失败横幅；
- 改造了 `backend/app/integrations/llm/agent_graph.py`，升级为 Tool Calling 模式。

### 失败原因分析 (Fall / Failure Analysis):
1. **变更耦合度过高**：在单次任务中同时触碰了前端登录授权生命周期、资料多状态流转界面、以及核心 AI 框架适配层，破坏了“小步迭代、范围最小化”原则；
2. **前端运行时异常**：前端在实机环境直接出现异常，影响正常使用；
3. **决策裁定**：经用户指令，立即终止该任务推进，对引发前端异常的 Commit `76a7b07` 执行完全版本回退（`git reset --hard 02bf56b`），系统安全恢复至纯净稳定态。

---

## 3. 任务结论与状态标记

- **最终结论**: **Fall (Failed / Reverted)**
- **回退目标版本**: `02bf56b` (`fix(questions): tolerate llm structured output format variations`)
- **后续规划**: 后续针对鉴权、重试及 LangGraph 的重构必须严格按独立原子任务拆分推进，单任务绝不允许跨越登录流与业务组件同时改动。
