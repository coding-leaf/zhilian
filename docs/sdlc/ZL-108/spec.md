# Spec: OCR 识别质量门禁算法 - 技术契约

- **关联 Intent**: ZL-108
- **主导设计人**: Dev
- **当前状态**: Draft / In-Review / Approved

---

## 1. 架构流向与设计方案

### 1.1 模块定位与分层防线
OCR 识别质量门禁算法位于智练系统后端五层单向架构的纯函数计算核：
- **物理路径**: `backend/app/core/algorithms/ocr_quality.py`
- **分层约束**: 严格属于纯函数计算核（Pure Functional Kernel），依赖仅限 Python 标准库（`re`, `dataclasses`, `typing`, `enum`）。绝对禁止导入 `fastapi`, `sqlalchemy`, `httpx`, `redis`, `boto3` 等网络、数据库与 Web 框架依赖，严禁导入上层业务模块 `app/services` 与 `app/repositories`。
- **与业务模型解耦**: 与 `backend/app/models/material.py` 中的 `MaterialOCRPage` 持久化实体解耦，上层 `material_service` 负责将 ORM 对象转换为纯函数 `OCRPageInput` 传递进算法核，再将只读输出 `BatchQualityReport` 映射回数据库模型或 API DTO。

### 1.2 核心数据流与状态机
质量门禁接收整批 OCR 页面的文本输入与重拍元数据，按页面清洗非法字符、提取统计量、动态计算批次长度基准、逐页执行三项门禁判定与优先级仲裁，最终输出不可变的批次质检报告：

```mermaid
flowchart TD
    A[输入: pages: Sequence[OCRPageInput], config: OCRQualityConfig] --> B[非法字符清洗: 剔除控制字符与零宽字符]
    B --> C[长度序列统计与批次规模识别]
    C --> D{批次页面数 N?}
    D -- N = 1 --> E[单页模式: 基准中位数设为 0.0, 跳过完整性检查]
    D -- N = 2 --> F[双页模式: 基准长度取两页算术平均值]
    D -- N >= 3 --> G[多页模式: 基准长度取文本长度中位数]
    E --> H[逐页质量评估 evaluate_page_quality]
    F --> H
    G --> H
    H --> I{页面文本为空或全空白?}
    I -- 是 --> J[极端边界: 乱码率 1.0, 有效字数 0, 判定 PAGE_INCOMPLETE]
    I -- 否 --> K[计算有效字数 count_valid_characters 与乱码率 calculate_gibberish_ratio]
    K --> L[检查完整性: 长度 < 基准 * 30% ?]
    L --> M[优先级仲裁: 完整性 > 乱码率 > 有效字数]
    J --> N[熔断判定: 不合格且重拍次数 >= 3 ?]
    M --> N
    N -- 是 --> O[标记 is_terminal_failure = True]
    N -- 否 --> P[标记 is_terminal_failure = False]
    O --> Q[装配不可变 PageQualityResult]
    P --> Q
    Q --> R[聚合生成不可变 BatchQualityReport]
```

### 1.3 白盒复杂度控制与函数拆分设计 ($V(G) \le 10$)
为严格遵守《代码管理工作介绍》第 4.2 节与 AGENTS.md 关于主切分函数与决策函数环路复杂度 $V(G) \le 10$ 的红线要求，将质检逻辑解耦为 6 个无状态独立纯函数：

1. `clean_ocr_text_and_count_removals(text: str) -> tuple[str, int]` ($V(G) \le 3$)
   - 过滤除换行 `\n` 与制表符 `\t` 外的非法 ASCII 控制字符（`\x00-\x08`, `\x0b-\x0c`, `\x0e-\x1f`, `\x7f`）及 Unicode 零宽/BOM 字符（`\u200b-\u200f`, `\ufeff`）。
   - 返回清洗后文本及剔除字符数。
2. `count_valid_characters(text: str) -> int` ($V(G) \le 4$)
   - 严格落实需求规格说明书 FR-08 规定：中文单个汉字（CJK 统一表意字符 `\u4e00-\u9fff`）计 1 字，英文连续单词（`[a-zA-Z]+`）计 1 词，阿拉伯连续数字串（`[0-9]+`）计 1 单元。
   - 统计有效文字与词汇单元总数。
3. `calculate_gibberish_ratio(text: str) -> float` ($V(G) \le 5$)
   - 落实概要设计说明书第 3.3/6.2 节“乱码比例按无法构成有效词的字符占比计算”。
   - 边界：全空白或空文本直接返回 `1.0` (100%)。
   - 正常文本：统计非空白字符总数及无法识别的异常乱码符号占比，精确返回 `0.0 ~ 1.0` 浮点数。
4. `calculate_median_length(lengths: Sequence[int]) -> float` ($V(G) \le 5$)
   - $N=0$ 或 $N=1$：返回 `0.0`（单页不适用中位数比较）；
   - $N=2$：返回算术平均值 `(lengths[0] + lengths[1]) / 2.0`；
   - $N \ge 3$：返回奇数/偶数标准中位数。
5. `evaluate_page_quality(page: OCRPageInput, baseline_median_length: float, config: OCRQualityConfig) -> PageQualityResult` ($V(G) \le 8$)
   - 单页评估决策函数：执行 5 大边界检查、3 级原因仲裁与重拍熔断标记。
6. `verify_ocr_quality(pages: Sequence[OCRPageInput], config: OCRQualityConfig | None = None) -> BatchQualityReport` ($V(G) \le 6$)
   - 批次顶层入口：协调清洗、提取长度序列、计算中位数基准并聚合全批次报告。

---

## 2. API 与数据契约设计

### 2.1 依赖与调用契约
本模块为底层纯算法计算核，不直接暴露 HTTP 接口，由上层服务（如资料解析流水线与 OCR 服务层）直接调用。输入输出均采用强类型不可变领域模型（基于 Python `dataclasses.dataclass(frozen=True)`）。

### 2.2 阈值常量与依据规范
```python
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
```

### 2.3 数据结构设计 (DTO)

```python
import enum
from dataclasses import dataclass
from collections.abc import Sequence


class UnqualifiedReasonCode(enum.StrEnum):
    """不合格原因代码枚举，严格遵循命名白名单与规范。"""

    PAGE_INCOMPLETE = "page_incomplete"
    GIBBERISH_EXCEEDED = "gibberish_exceeded"
    INSUFFICIENT_CHARS = "insufficient_chars"


@dataclass(frozen=True)
class OCRPageInput:
    """输入页面数据结构化描述。"""

    page_number: int  # 页码序号（从 1 开始）
    raw_text: str  # OCR 识别原始文本
    reshoot_count: int = 0  # 历史重拍次数（默认 0，上限 3）
    image_storage_key: str = ""  # MinIO 渲染切图存储键（用于前端标黄追溯）


@dataclass(frozen=True)
class OCRQualityConfig:
    """门禁算法配置参数。"""

    max_gibberish_ratio: float = DEFAULT_MAX_GIBBERISH_RATIO
    min_valid_chars: int = DEFAULT_MIN_VALID_CHARS
    median_length_ratio: float = DEFAULT_MEDIAN_LENGTH_RATIO
    max_reshoot_attempts: int = MAX_RESHOOT_ATTEMPTS


@dataclass(frozen=True)
class PageQualityResult:
    """单页质量门禁评估结果（不可变值对象）。"""

    page_number: int  # 页码序号
    raw_text_length: int  # 原始文本字符数
    cleaned_text_length: int  # 清洗后文本字符数
    valid_char_count: int  # 有效中文字符与英文词汇数
    gibberish_ratio: float  # 乱码比例 (0.00 ~ 1.00)
    is_page_complete: bool  # 页面完整性判定
    is_qualified: bool  # 页面是否达到门禁准出标准
    unqualified_code: UnqualifiedReasonCode | None  # 不合格错误枚举，合格为 None
    unqualified_reason: str | None  # 不合格提示文案，合格为 None
    reshoot_count: int  # 当前已重拍次数
    is_terminal_failure: bool  # 是否达到最大重拍次数且仍不合格的熔断状态
    cleaned_chars_count: int  # 剔除的控制字符与零宽字符数


@dataclass(frozen=True)
class BatchQualityReport:
    """批次页面识别质量门禁统一产出报告。"""

    page_results: tuple[PageQualityResult, ...]  # 逐页评估结果元组
    total_pages: int  # 总页数
    qualified_pages: int  # 合格页数
    unqualified_pages: int  # 不合格页数
    is_all_qualified: bool  # 全批次是否整体合格（可否直接进入分块与出题）
    median_length: float  # 同批页面文本长度计算基准（中位数或均值）
    terminal_failure_pages: tuple[int, ...]  # 达到熔断上限且仍不合格的页码集合
```

### 2.4 主函数与辅助函数签名

```python
def clean_ocr_text_and_count_removals(text: str) -> tuple[str, int]:
    """过滤文本中非法控制字符与零宽字符并返回剔除计数。"""


def count_valid_characters(text: str) -> int:
    """统计文本中可用中文字符与英文单词及数字单元总数。"""


def calculate_gibberish_ratio(text: str) -> float:
    """计算文本中乱码与杂乱不可解析字符的比例 (0.0 ~ 1.0)。"""


def calculate_median_length(lengths: Sequence[int]) -> float:
    """计算同批页面文本长度中位数（含单页与双页降级逻辑）。"""


def evaluate_page_quality(
    page: OCRPageInput,
    baseline_median_length: float,
    config: OCRQualityConfig,
) -> PageQualityResult:
    """执行单页质量门禁评估与不合格原因仲裁。"""


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
        ValueError: 当配置参数非法（如 max_gibberish_ratio < 0 或 min_valid_chars < 0）时抛出。
    """
```

### 2.5 判定优先级与仲裁决策表
当单页同时触发多项不合格条件时，按需求规范严格执行确定性仲裁（优先级：页面不完整 > 乱码比例超限 > 有效字数不足）：

| 页面完整性 (`is_page_complete`) | 乱码率 (`gibberish_ratio`) | 有效字数 (`valid_char_count`) | 是否合格 (`is_qualified`) | 最终判定错误码 (`unqualified_code`) | 不合格提示文案格式 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **False** | 任意 | 任意 | **False** | `PAGE_INCOMPLETE` | `"页面内容不完整，显著低于同批页面文本长度"` |
| **True** | **> 15%** | 任意 | **False** | `GIBBERISH_EXCEEDED` | `"乱码率过高[{ratio:.1%}]，超出门禁上限"` |
| **True** | $\le 15\%$ | **< 40** | **False** | `INSUFFICIENT_CHARS` | `"有效识别字数不足[{count}字]，低于门禁下限"` |
| **True** | $\le 15\%$ | $\ge 40$ | **True** | `None` | `None` |

### 2.6 异常与降级约定
- **配置参数校验防御**:
  - 若 `max_gibberish_ratio < 0` 或 `max_gibberish_ratio > 1.0`，抛出 `ValueError("max_gibberish_ratio must be between 0.0 and 1.0")`；
  - 若 `min_valid_chars < 0` 或 `median_length_ratio < 0` 或 `max_reshoot_attempts < 0`，抛出 `ValueError`；
- **业务错误码映射（供服务层映射）**:
  - `10001`: 参数校验失败（当算法核抛出 ValueError 时上层捕获转换）；
  - `40001`: 资料质量不达标（当 `is_all_qualified=False` 时，服务层挂起任务，向用户抛出 40001 并返回未通过页面详情与重拍引导）。

---

## 3. 可测性设计 (Design for Testability)

### 3.1 独立纯函数计算核
- 算法完全封装在 `backend/app/core/algorithms/ocr_quality.py`；
- 无任何外部 I/O、无全局可变状态、无系统时间依赖；
- 相同输入在任意 OS、任意运行环境下计算必定产生完全一致的报告（100% 确定性）。

### 3.2 外部依赖与 Mock 策略
- **0 Mock 策略**: 根据项目架构规范，纯函数计算核测试**严格禁止使用 Mock/Patch 替身打桩**；
- 单元测试单用例在毫秒级完成，全套单测在 3 秒内执行完毕；
- 覆盖率硬性门禁：判定覆盖率 100%，行覆盖率 $\ge 95\%$，分支覆盖率 $\ge 90\%$。

### 3.3 等价类与边界值测试用例矩阵

| 用例编号 | 测试场景 / 等价类划分 | 输入特征与边界参数 | 预期断言与行为判定 | 对应规范要求 |
| :--- | :--- | :--- | :--- | :--- |
| **TC-OCR-01** | 空批次输入 | `pages = []` | 返回 `total_pages = 0`, `is_all_qualified = True`, `page_results = ()` | 边界：空输入 |
| **TC-OCR-02** | 空字符串与全空白页面 | `raw_text = ""` 或 `"   \n\t  "` | `gibberish_ratio = 1.0`, `valid_char_count = 0`, `is_page_complete = False`, 原因优先为 `PAGE_INCOMPLETE` | 5 大边界 a：空白页 |
| **TC-OCR-03** | 单页场景 ($N=1$) 合格 | 单页正常文本 (80 汉字, 乱码率 0%) | 不使用中位数比较，`is_page_complete = True`, `is_qualified = True` | 5 大边界 b：单页场景 |
| **TC-OCR-04** | 单页场景 ($N=1$) 字数不足 | 单页文本仅 20 汉字 (乱码率 0%) | `is_page_complete = True`, 判定 `INSUFFICIENT_CHARS` 不合格 | 5 大边界 b：单页字数下限 |
| **TC-OCR-05** | 双页场景 ($N=2$) 算术平均值 | 页 1: 100 字，页 2: 10 字 (均值 55 字) | 页 2 (10 < 55 * 30% = 16.5) 判定 `PAGE_INCOMPLETE` 不合格 | 5 大边界 c：N=2 均值降级 |
| **TC-OCR-06** | 多页正常中位数基准 | 5 页长度分别为 [100, 200, 300, 400, 500]，中位数 300 | 某页长度 80 (< 300*0.3=90) 判定 `PAGE_INCOMPLETE` | 完整性：中位数基准 |
| **TC-OCR-07** | 乱码率恰好等于上限 15% | 85 个有效汉字 + 15 个乱码字符 | 乱码率恰等于 0.15，判定为合格 (`is_qualified = True`) | 边界值：恰等于上限 |
| **TC-OCR-08** | 乱码率超过上限 15% | 80 个有效汉字 + 20 个乱码字符 (20%) | 判定 `GIBBERISH_EXCEEDED` 不合格，文案含百分比 | 边界值：乱码率超限 |
| **TC-OCR-09** | 有效字数恰好等于下限 40 字 | 40 个标准汉字，乱码率 0% | 判定为合格 (`is_qualified = True`) | 边界值：恰等于下限 |
| **TC-OCR-10** | 有效字数低于下限 39 字 | 39 个标准汉字，乱码率 0% | 判定 `INSUFFICIENT_CHARS` 不合格，文案含有效字数 | 边界值：字数下限减一 |
| **TC-OCR-11** | 优先级仲裁 1: 完整性 vs 乱码 | 长度显著低于中位数 30% 且乱码率 50% | 最终原因仲裁为 `PAGE_INCOMPLETE` | 判定优先级：完整性优先 |
| **TC-OCR-12** | 优先级仲裁 2: 乱码 vs 字数不足 | 页面完整，乱码率 30% 且有效字数 20 字 | 最终原因仲裁为 `GIBBERISH_EXCEEDED` | 判定优先级：乱码率次优先 |
| **TC-OCR-13** | 重拍次数熔断达标 | `reshoot_count = 3` 且页面仍不合格 | `is_terminal_failure = True`，批次包含该熔断页码 | 5 大边界 d：重拍熔断 |
| **TC-OCR-14** | 重拍次数未达上限 | `reshoot_count = 2` 且页面不合格 | `is_terminal_failure = False`，引导继续重拍 | 业务规则：重拍未熔断 |
| **TC-OCR-15** | 重拍 3 次后页面质检合格 | `reshoot_count = 3` 且文本合格 (100字) | `is_qualified = True`, `is_terminal_failure = False` | 业务规则：重拍成功放行 |
| **TC-OCR-16** | 非法控制字符与零宽字符清洗 | 文本注入 `\x00\x1f\u200b\ufeff` | 字符被剔除，`cleaned_chars_count > 0`，不影响有效字数统计 | 5 大边界 e：安全清洗 |
| **TC-OCR-17** | 致命参数非法校验防御 | `max_gibberish_ratio = -0.1` 或 `1.5` | 抛出 `ValueError` | 参数防御 |
| **TC-OCR-18** | 大规模批次吞吐性能测试 | 100 页教材 OCR 文本（每页 800 字） | 纯函数核全批次处理耗时 $\le 50\text{ms}$ | 性能红线：KISS 极简 |

---

## 4. 替代方案与权衡考量 (Alternatives Considered & Trade-offs)

### 4.1 评估过的替代方案
- **方案 A (当前采纳方案)**: 基于标准字符集、正则与统计分布的纯函数计算核。
- **方案 B**: 引入 Jieba 或重型外部词典进行分词有效性匹配。
- **方案 C**: 调用大模型 (LLM) 进行整页语义可读性审查。

### 4.2 未采纳原因与权衡分析

| 维度 | 方案 A: 标准纯函数计算核 (当前采纳) | 方案 B: Jieba/外部词典分词匹配 | 方案 C: 大模型 LLM 审查 |
| :--- | :--- | :--- | :--- |
| **架构分层合规性** | **完全合规**：纯 Python 标准库，0 依赖，完全符合纯函数核铁律 | **不推荐**：引入数十 MB 词典 I/O 与 C 扩展，拖慢冷启动 | **严重违规**：违背纯函数核禁止 I/O 与网络调用的红线 |
| **确定性与可重复性** | **100% 确定**：相同输入输出绝对一致，测试可复现 | **中等**：受词典版本与未登录词分词策略干扰 | **极差**：受模型温度、幻觉与版本漂移影响，无法绝对断言 |
| **执行时延与开销** | **极高**：单页处理 $< 0.5\text{ms}$，100 页批次 $< 50\text{ms}$ | **中等**：单页约 5~10ms，首次词典加载耗时 1~2s | **极慢且昂贵**：单页 1~3s，产生额外 Token 费用与配额消耗 |
| **单测门禁友好性** | **极佳**：单测 3 秒跑完，支持边界构造与 100% 判定覆盖 | **一般**：字典依赖增加单测开销与打包体积 | **不可行**：单测无法真实联网，无法做确定性断言 |

---

## 5. 动态风险核验与回滚预案 (Risk & Rollback Verification)

### 5.1 七维风险动态核验矩阵
- [x] **Files (文件破坏面)**:
  - 仅新增纯算法文件 `backend/app/core/algorithms/ocr_quality.py` 与单元测试 `backend/tests/unit/core/algorithms/test_ocr_quality.py`；
  - 不修改任何已有业务代码，无 Git 冲突与文件覆盖破坏风险。
- [x] **API (对外接口契约)**:
  - 属于内部纯算法层 DTO 契约，不直接修改任何对外暴露的 HTTP 接口路由与返回结构。
- [x] **Schema (数据库模型与存储)**:
  - 数据模型 `MaterialOCRPage` 已在 `ZL-104` 中就绪，字段名（`gibberish_ratio`, `valid_char_count`, `is_qualified`, `unqualified_reason`, `reshoot_count`）与本算法 DTO 严格 1:1 映射，无需任何数据库变更与迁移。
- [x] **Auth (鉴权与安全隔离)**:
  - 纯函数不涉及用户会话与权限逻辑；用户数据由上层服务通过 `user_id` 保障多租户物理隔离。
- [x] **Deps (第三方依赖变动)**:
  - 仅使用 Python 标准库（`re`, `dataclasses`, `typing`, `enum`），0 外部三方库引入。
- [x] **Rollback (回滚难度与迁移)**:
  - 纯无状态代码变动，若出现逻辑缺陷，可直接通过 `git revert` 秒级回滚并重新部署，无需数据库逆向修复。
- [x] **Blast Radius (爆炸半径评估)**:
  - 爆炸半径严格限定在“图片资料 OCR 识别完成后的质量门禁判定”环节；不影响原生 PDF/DOCX 导入，不影响已生成的题目、练习作答与诊断报告。

### 5.2 回滚与故障应急策略
- **Git 秒级回滚**: 若新算法在线上产生意外拦截，直接撤销提交并构建，无任何持久化副作用。
- **服务层熔断保护**: 上层 `material_service` 调用本算法时具备结构化异常捕获；若算法抛出未处理异常，服务层自动捕获并标记资料解析异常（错误码 `40001`），记录脱敏指标，系统不崩溃。

---

## 6. 阶段准出签批 (Gate 2 Sign-off)
- [x] 架构流向与 API 契约已冻结
- [x] 替代方案已完成推演与权衡
- [x] 7 维风险已核验且具备明确回滚预案
- **审查结论**: Accepted
- **签批人 / 日期**: SecLead / 2026-09-23
