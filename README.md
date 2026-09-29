# 智练 ZhiLian · 自主学习平台

[![verify](https://github.com/coding-leaf/zhilian/actions/workflows/verify.yml/badge.svg)](https://github.com/coding-leaf/zhilian/actions/workflows/verify.yml)

把一份自己的学习资料，变成一套**能出题、能判题、能诊断**的个人练习闭环。

微信小程序端 + Python 后端。上传 PDF / DOCX / TXT / 图片，系统切分、抽取知识点建成知识树，
再基于资料原文出题；做完交卷后判题、沉淀错题，并按时间衰减计算掌握度、给出诊断报告。

---

## 1 主链路：8 个流转节点

```
[1.资料上传解析] → [2.切分与OCR门禁] → [3.知识点抽取建树] → [4.检索增强出题]
      → [5.作答与幂等交卷] → [6.混合判题与超时降级] → [7.掌握度衰减与报告] → [8.错题与继续练习]
```

| 节点 | 关键约束 |
| --- | --- |
| 1 上传解析 | 魔数白名单校验；支持 PDF / DOCX / TXT / 图片；异步解析可轮询 |
| 2 切分与 OCR 门禁 | 800 字上限 / 120 字重叠 / 标点降级 / 短段合并；OCR 乱码率与有效字数双门禁 |
| 3 抽取建树 | 四项一票否决质检；失败自动重抽（上限 2 次），超限降级并打低可信标记 |
| 4 检索出题 | 无资料来源直接拒绝出题；生成后过题目质检（无来源 / 重复 / 冲突 / 歧义） |
| 5 作答交卷 | 题目打散；交卷强幂等，重复提交返回原结果 |
| 6 混合判题 | 客观题确定性匹配；主观题双阈值，落在不确定区间才转大模型；超时严格标记「待重新判题」而**非判错** |
| 7 掌握度与报告 | 指数时间衰减（半衰期 30 天），最近 200 条加权聚合，四档划分 |
| 8 错题与继续练习 | 答错自动入错题本；可手动标记；继续练习排除已做合格题 |

## 2 技术栈

| 层 | 选型 |
| --- | --- |
| 后端 | Python 3.13 · FastAPI · SQLAlchemy 2.x（async）· Alembic · Pydantic v2 |
| 数据 | PostgreSQL 16 + pgvector（向量）· Redis 7（队列 / 幂等）· MinIO（对象存储） |
| 异步 | RQ 后台 worker |
| 前端 | uni-app · Vue 3 · TypeScript · Pinia · Wot Design Uni（微信小程序） |
| 质量 | ruff · mypy(strict) · import-linter · pytest · eslint · vue-tsc · vitest |

架构上有一条硬约束：**五层单向依赖**（`api → services → repositories`），
外加「算法核禁止 IO」「仓储层禁止外部框架」等契约，由 import-linter 强制，越层调用直接失败。

外部能力（大模型 / OCR / 向量化 / 对象存储 / 队列）全部走协议抽象，**每个都有一套纯内存假实现**。
因此全量测试不依赖数据库与网络——这是 548 个测试函数能在秒级跑完的原因。

## 3 目录结构

```
backend/            FastAPI 服务
  app/core/algorithms/   9 个纯函数算法核（分块 / 质检 / 判题 / 掌握度 / 诊断 / 检索）
  app/services/          业务编排（事务边界在这一层）
  app/repositories/      数据访问
  app/integrations/      外部能力适配（协议抽象 + 假实现 + 生产实现）
  app/api/v1/            路由层，只做校验与转发
  migrations/            10 个 Alembic 迁移
  tests/                 91 个测试文件、548 个测试函数
miniprogram/        uni-app 小程序端（18 个页面）
deploy/             docker-compose：postgres+pgvector / redis / minio / worker
docs/               设计规范、开发过程文档、待解决问题、截图、团队分工
.trellis/           开发过程记录（任务树 PRD / 设计与执行计划、规范、开发日志）
```

## 4 快速开始

前置：Docker、[uv](https://docs.astral.sh/uv/)、Node 22+、pnpm、微信开发者工具。

```bash
# 1) 起中间件（postgres+pgvector / redis / minio / worker）
docker compose -f deploy/docker-compose.yml up -d

# 2) 后端
cd backend
cp .env.example .env          # 默认全是 memory / fake，不接外部服务也能起来
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload      # http://localhost:8000/docs

# 3) 小程序端
cd ../miniprogram
pnpm install
pnpm run dev:mp-weixin        # 产物在 dist/dev/mp-weixin
```

然后用微信开发者工具**导入 `miniprogram/dist/dev/mp-weixin` 目录**（`appid` 为 `touristappid`，免登录）。

要让出题 / 抽取 / 判题真正调用大模型，把 `backend/.env` 里的 `ZHILIAN_LLM__PROVIDER`
改成 `deepseek` / `openai` / `dashscope` / `siliconflow` 并填上 `BASE_URL` 与 `API_KEY`。
队列需真实消费时，把 `ZHILIAN_QUEUE__PROVIDER` 设为 `redis`，另开一个终端跑 `task worker`。

## 5 质量门禁

```bash
task verify           # 全量：后端 + 前端
task verify-backend   # ruff format/check · mypy(strict) · import-linter · pytest（覆盖率 ≥ 80%）
task verify-frontend  # eslint · vue-tsc · vitest
task format           # 自动格式化
```

等价的原生命令（`task` 不可用时）：

```bash
cd backend    && uv run ruff format --check . && uv run ruff check . && uv run mypy app \
              && uv run lint-imports \
              && uv run pytest tests --cov=app --cov-branch --cov-fail-under=80
cd miniprogram && pnpm run lint && pnpm run type-check && pnpm run test:unit
```

同一套门禁已接进 GitHub Actions（`.github/workflows/verify.yml`），push 与 PR 都会跑。

> **已知的测试抖动**：`backend/tests/unit/core/algorithms/` 下有 4 处墙钟微基准断言
> （200 / 50 / 20 / 100 ms）。全量套件在 CPU 争用下可能失败，**单独跑全过**。
> 这是既有的测试设计问题，不是回归——详见 `AGENTS.md` 的说明。

## 6 当前完成度

主链路「上传 → 解析 → 出题 → 作答 → 判题 → 学情沉淀」已打通，并在真机与开发者工具上实测过。

| 指标 | 数值 |
| --- | --- |
| 提交 | 250 次（2026-09-23 起） |
| 后端算法核 | 9 个纯函数模块，分支覆盖率 100% |
| 后端测试 | 91 个文件 / 548 个测试函数 |
| 前端单元测试 | 13 个文件 / 125 个用例 |
| 数据库迁移 | 10 个 Alembic 版本 |

## 7 已知问题

尚在收口的功能缺陷按优先级列在 **[docs/后续待解决问题.md](docs/后续待解决问题.md)**，其中阻塞项包括：
解析流水线可能卡死且不可恢复、出题链路缺少反馈、思考模式模型上结构化输出不可用、
个人页学习足迹统计口径漏算。

## 8 文档索引

| 文档 | 内容 |
| --- | --- |
| [docs/开发过程文档.md](docs/开发过程文档.md) | 开发过程、迭代节奏、缺陷修复史、质量证据、版本控制说明 |
| [docs/后续待解决问题.md](docs/后续待解决问题.md) | 未收口问题清单、延期与永久排除范围 |
| [docs/团队分工.md](docs/团队分工.md) | 角色分工、职责边界、代码所有权（**角色代号版**） |
| [docs/DESIGN.md](docs/DESIGN.md) | 前端设计规范（色值、间距、动效的量化事实源） |
| [docs/screenshots/](docs/screenshots/) | 界面截图与说明 |
| [docs/specs_extracted/](docs/specs_extracted/) | 软件需求规格说明书 V2.0 · 概要设计说明书 V1.0 · 代码管理工作介绍 V1.0 |
| [docs/legacy_sdlc/](docs/legacy_sdlc/) | P0 任务拓扑矩阵（ROADMAP）、交付台账（ARCHIVE）、范围对齐函 |
| [AGENTS.md](AGENTS.md) | 工程约定与本机工具链注意事项 |

## 9 约定

- **提交信息**：`type(scope): 中文描述`，类型与 scope 取值见《代码管理工作介绍 V1.0》第 3.2 节。
- **门禁必须全绿**才允许合并。
- 本仓库为公开仓库，**不记载成员姓名**，一律使用角色代号（TechLead / SecLead / Reviewer / DevOpsLead）。
