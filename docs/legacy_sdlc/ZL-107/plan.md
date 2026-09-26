# Plan: 资料分块算法实现 - 实施计划

- **关联 Spec**: ZL-107
- **实施执行人 / Agent**: Dev
- **当前状态**: Completed

---

## 1. 变更文件清单 (Files that change)
* `backend/app/__init__.py` (New - 顶层包声明)
* `backend/app/core/__init__.py` (New - 核心包声明)
* `backend/app/core/algorithms/__init__.py` (New - 纯函数算法核包声明)
* `backend/app/core/algorithms/material_chunking.py` (New - 资料分块纯算法核实现)
* `backend/tests/__init__.py` (New - 测试包声明)
* `backend/tests/unit/__init__.py` (New - 单元测试包声明)
* `backend/tests/unit/core/__init__.py` (New - 核心单测包声明)
* `backend/tests/unit/core/algorithms/__init__.py` (New - 算法单测包声明)
* `backend/tests/unit/core/algorithms/test_material_chunking.py` (New - TC-CHUNK-01 ~ 19 全覆盖单元测试)
* `tooling/check_layers.py` (New - 架构分层单向导入自动化检查脚本)

## 2. 伴随式分步实施与验证 (Step-by-Step Implementation Loops)

### Step 1: 测试先行与红灯复现 (Fail-repro First)
* **操作目标**: 编写针对资料分块规范的单元测试套件骨架与 19 项测试用例桩（TC-CHUNK-01 ~ TC-CHUNK-19），在算法尚未实现前验证用例有效捕获需求并产生导入失败（Fail）。
* **涉及文件**: `backend/tests/unit/core/algorithms/test_material_chunking.py`
* **局部验证命令**: `pytest backend/tests/unit/core/algorithms/test_material_chunking.py`
* **预期判据**: 确认 `ModuleNotFoundError: No module named 'app.core.algorithms.material_chunking'`，亲眼见证测试变红（Fail）。

### Step 2: 核心数据结构与纯函数算法实现
* **操作目标**: 遵循 $V(G) \le 12$ 约束与纯函数无 I/O 红线，在 `backend/app/core/algorithms/material_chunking.py` 中实现不可变领域模型（`ParagraphInput`, `Snippet`, `ChunkingResult`）与 5 个拆分子函数：
  1. `clean_text_and_count_removals`: Unicode 控制字符与零宽字符过滤
  2. `split_long_paragraph_into_sentences`: 句末标点 -> 次级标点 -> 硬切多级降级
  3. `align_overlap_sentence_boundary`: 120 字符重叠向前语义分句对齐
  4. `merge_isolated_short_snippets`: 孤立短段（< 80 字符）双向合并机制
  5. `split_material_into_snippets`: 驱动主流程、章节标题追踪与 3000 片段安全截断
* **涉及文件**: `backend/app/core/algorithms/material_chunking.py`, `backend/app/core/algorithms/__init__.py`
* **局部验证命令**: `pytest backend/tests/unit/core/algorithms/test_material_chunking.py --cov=app.core.algorithms.material_chunking --cov-branch --cov-report=term-missing`
* **预期判据**: 19 项单元测试全部通过，分支覆盖率达到 100%，行覆盖率 >= 95%，20 万字样本耗时 <= 2.0s，测试变绿（Pass）。

### Step 3: 分层校验工具与架构防线校验
* **操作目标**: 实现并执行 `tooling/check_layers.py`，根据 AGENTS.md 校验五层单向导入规则（纯函数算法核严禁导入 fastapi, sqlalchemy, httpx, redis, boto3 等），确保架构防线生效。
* **涉及文件**: `tooling/check_layers.py`
* **局部验证命令**: `python3 tooling/check_layers.py --root backend/app`
* **预期判据**: 脚本检查退出码为 0，确认算法核 0 跨层违规导入。

## 3. 全局质量门禁核验 (Global Quality Gate)
* **代码风格与静态检查**: `ruff check backend/app backend/tests && ruff format --check backend/app backend/tests`
* **类型与契约安全校验**: `mypy backend/app/core/algorithms`
* **全量相关测试回归与覆盖率**: `pytest backend/tests/unit/core/algorithms/test_material_chunking.py --cov=app.core.algorithms.material_chunking --cov-branch --cov-fail-under=95`
* **工件生命周期合规性**: `python3 tooling/check_sdlc_integrity.py`
* **核验结果**: 所有静态检查通过，零报警；全量相关测试用例 100% 绿灯，分支覆盖率 100%，行覆盖率 100%，工件门禁校验通过。

## 4. 实施偏差记录 (Deviations Log)
* 补充了 `tooling/check_layers.py` 自动化检查工具，依据 AGENTS.md 第 2 节要求对后端各层单向导入规则进行 AST 静态扫描，保障分层防护自动化落地。

---

## 5. 阶段准出签批 (Gate 3 Sign-off)
- [x] 所有分步实施项与验证断言均已就地执行并通过
- [x] 全局质量门禁（Lint / Type / Regression）全部绿灯
- [x] 变更文件与 plan.md 清单完全吻合，无越权修改
- **验收结论**: Passed
- **验证人 / 日期**: Dev / 2026-09-23
