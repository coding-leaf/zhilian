# 技术设计：环境与 CI 准备

> 任务：`10-03-midterm-ci-baseline`
> 依据：`prd.md`（需求与验收）、`research/ci-and-baseline-facts.md`（现状事实）

## 1 设计原则

1. **不另立第二套门禁**。CI 命令继续**精确镜像** `Taskfile.yml`——本地跑绿即 CI 跑绿，避免两边标准漂移（这是仓库既有约定，见 `verify.yml` 文件头注释）。
2. **增量接入，不制造红灯**。新增能力（SonarCloud、前端覆盖率）在**未配置/未达阈值**时必须让 CI 保持绿色，否则「未启用」会被误读成「代码有问题」。
3. **数字不手抄**。文档中的范围/规模数字一律附取得命令。
4. **如实标注未验证项**。本任务不推送，因此**无法在真实 CI 上验证**新 job；这一点必须写进文档，不能写成"已验证通过"。

## 2 CI 流水线拓扑

改造后 `.github/workflows/verify.yml` 为 **3 个 job**：

```
verify
├── backend   ── ruff format/check → mypy(strict) → lint-imports → pytest(+cov)
│                  │
│                  └─ artifact: backend-coverage (coverage.xml)
├── frontend  ── eslint → vue-tsc → vitest(+coverage)
│                  │
│                  └─ artifact: frontend-coverage (lcov.info)
└── sonar     ── needs: [backend, frontend]（可选，无 token 时短路）
                   └─ download artifacts → SonarCloud 扫描
```

`sonar` 采用 `needs` 串行依赖，保证扫描时覆盖率报告已可用。

## 3 覆盖率留档设计

### 3.1 后端

`pytest-cov` 已具备（`pytest-cov>=5.0.0`），只需**增加报告格式**，不新增门禁：

| 位置 | 命令变化 |
| --- | --- |
| `Taskfile.yml` · `verify-backend` | 追加 `--cov-report=term-missing --cov-report=xml` |
| `verify.yml` · backend job | 与上完全一致（镜像） |
| CI 追加步骤 | `upload-artifact` 上传 `backend/coverage.xml` |

`--cov-fail-under=80` **原样保留**，门禁语义零变化；新增的只是「把已经算出来的覆盖率落成文件」。

### 3.2 前端

| 位置 | 设计 |
| --- | --- |
| `package.json` · scripts | 新增 `test:cov": "vitest run --coverage"`；`test:unit` **保持不变** |
| `Taskfile.yml` · `verify-frontend` | 第三步由 `test:unit` 改为 `test:cov` |
| `verify.yml` · frontend job | 与上完全一致（镜像） |
| CI 追加步骤 | `upload-artifact` 上传 `miniprogram/coverage/lcov.info` |

**为何 `verify-frontend` 要换成 `test:cov`**：保持镜像原则，且一次运行同时完成「测试 + 覆盖率」，不重复跑两遍。代价是本地 `task verify-frontend` 会多产出 `miniprogram/coverage/`——该目录需加入 `.gitignore`。

> 注意：此改动要求先执行 `pnpm install`（新增了 `@vitest/coverage-v8` 依赖）。未重装依赖时本地 `test:cov` 会报模块缺失——这是**新增依赖的正常代价**，不是设计缺陷，文档需明写。

### 3.3 artifact 命名与保留

| artifact | 路径 | 保留 |
| --- | --- | --- |
| `backend-coverage` | `backend/coverage.xml` | 14 天 |
| `frontend-coverage` | `miniprogram/coverage/` | 14 天 |

## 4 SonarCloud 接入设计

### 4.1 配置文件 `sonar-project.properties`（仓库根）

```
sonar.host.url=https://sonarcloud.io
sonar.organization=<待填：你的 SonarCloud 组织 key>
sonar.projectKey=<待填：<organization>_zhilian>
sonar.projectName=zhilian
sonar.sources=backend/app,miniprogram/src
sonar.tests=backend/tests,miniprogram/tests
sonar.python.coverage.reportPaths=backend/coverage.xml
sonar.javascript.lcov.reportPaths=miniprogram/coverage/lcov.info
sonar.sourceEncoding=UTF-8
sonar.exclusions=backend/migrations/**,**/*.d.ts,miniprogram/src/static/**
sonar.python.version=3.13
```

`organization` / `projectKey` 需用户在 SonarCloud 建项目后回填——设计上留占位符并在文档给出逐步指引，避免我编造一个不存在的 key。

### 4.2 `sonar` job 的降级逻辑

关键点：**job 级 `env` 中的 `SONAR_TOKEN` 可在 step 级 `if` 中求值**，据此短路：

```yaml
  sonar:
    name: 静态扫描（SonarCloud）
    runs-on: ubuntu-latest
    needs: [backend, frontend]
    env:
      SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
    steps:
      - name: 未配置 SONAR_TOKEN，跳过静态扫描
        if: env.SONAR_TOKEN == ''
        run: echo "::notice title=SonarCloud 未启用::未配置 SONAR_TOKEN secret，已跳过静态扫描。"
      - uses: actions/checkout@v4
        if: env.SONAR_TOKEN != ''
        with:
          fetch-depth: 0
      - uses: actions/download-artifact@v4
        if: env.SONAR_TOKEN != ''
        with:
          path: artifacts
      - name: SonarCloud 扫描
        if: env.SONAR_TOKEN != ''
        uses: SonarSource/sonarqube-scan-action@v5
        env:
          SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

设计要点：

- `permissions` 不需要额外授权（本设计用 token 而非 `GITHUB_TOKEN`）。
- `fetch-depth: 0` 是**必需的**——SonarCloud 需要完整历史来算新代码（new code）覆盖率，浅克隆会让「新增代码覆盖率」失真。
- 用 `echo "::notice::"` 而非 `exit 1`，保证未启用时 job 绿色。
- 使用统一扫描 Action `sonarqube-scan-action`（旧版 `sonarcloud-github-action` 已不再推荐）。

### 4.3 无法代做的部分（必须由用户执行）

1. 在 SonarCloud 用 GitHub 账号登录并**导入 `coding-leaf/zhilian` 仓库**；
2. 记下 Organization Key 与 Project Key，回填 `sonar-project.properties` 两个占位符；
3. 在 SonarCloud 生成 token；
4. 在 GitHub 仓库 `Settings → Secrets and variables → Actions` 新增 secret `SONAR_TOKEN`。

## 5 前端覆盖率接入设计

### 5.1 依赖（已完成）

- `@vitest/coverage-v8@1.6.1`，**与 `vitest@1.6.1` 严格同版本**（vitest 的覆盖率 provider 与主包强绑定版本）。
- 用 `pnpm add -D --lockfile-only` 更新 `package.json` + `pnpm-lock.yaml`，**不动 `node_modules`**（规避本机杀软对 pnpm 的干扰）。
- 已实测：`lockfileVersion` 保持 `9.0`，diff 为纯新增 108 行 —— 兼容 CI 的 pnpm 10 与 `--frozen-lockfile`。

### 5.2 `vitest.config.ts` 追加

```ts
  test: {
    // ...既有 environment / globals / setupFiles 不动
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,vue}'],
      exclude: [
        'src/main.ts',
        'src/env.d.ts',
        'src/pages.json',
        'src/manifest.json',
        'src/types/**',
        'src/static/**',
      ],
    },
  },
```

**不设 `thresholds`**：首次接入没有历史基线，直接设阈值会让 CI 立刻红灯（违反原则 2）。阈值在 M0 基线化取到实测值后再定，属第 1 步《单测计划》M0-2。

## 6 PR/MR 模板落地设计

`.github/PULL_REQUEST_TEMPLATE.md` ← 由 `中期质量检查/templates/PR-MR模板.md` 派生。

两项处理：

1. **去真名**：模板正文保持零真名，角色只用四代号。
2. **加自证行**：模板底部附「本模板同时存放于 `中期质量检查/templates/PR-MR模板.md`」的互指说明，避免两处正文各自漂移。

> GitHub 识别规则：仓库根或 `.github/` 下的 `PULL_REQUEST_TEMPLATE.md`（大小写不敏感）。同时保留 `docs/` 版本作为课程交付物。

## 7 基线版本与评审范围设计

### 7.1 范围表达

`ZL-143` 是**任务编号**，`git log --grep` 查不到（实测为空）。因此评审范围改用**可复现的 commit 边界**：

| 项 | 值 |
| --- | --- |
| base（不含） | `61b9ee1` · 2026-09-28 19:21:42 |
| 首个纳入 | `609e7f1` · 2026-09-29 00:45:20 |
| 终点 | `e1cef6d` · 2026-09-29 12:05:34（master HEAD） |
| 提交数 | 66 |
| 涉及文件 | 301 |

### 7.2 tag 设计

- 名称：`midterm-baseline-2026-10-03`
  - 选语义化前缀而非 `v*`：本项目尚未发布正式版本，`v0.x` 会与"版本发布"里程碑（第 7 步）混淆。
- 类型：**附注 tag**（`git tag -a`），带说明信息，便于 `git show` 追溯基线含义。
- 目标：用户提交本次改动后的 `master` HEAD。
- **本任务只输出命令，不执行**（约束 C-2）。

命令（写入文档，由用户执行）：

```bash
git tag -a midterm-baseline-2026-10-03 -m "中期质量检查基线：自 2026-09-29 收敛起点起"
git push origin midterm-baseline-2026-10-03
```

## 8 文档产物设计

| 文件 | 内容 |
| --- | --- |
| `中期质量检查/环境与CI准备.md` | 分支策略 · 保护分支现状与手工步骤 · CI 流水线（3 job）· 测试环境与 Mock · 可重复运行 · SonarCloud 接入手册 |
| `中期质量检查/基线版本.md` | 基线 tag · 评审 commit 范围 · 取得命令 · 范围内容概览 |
| `中期质量检查/README.md` | 更新索引（新增两份，阅读顺序插入第 5、6 位） |

## 9 一致性检查

| 既有约定 | 本设计是否冲突 |
| --- | --- |
| `verify.yml` 文件头「精确镜像 Taskfile.yml」 | **不冲突**：Taskfile 与 CI 同步改，镜像保持 |
| `AGENTS.md` 「禁止经由 WSL」 | **不冲突**：不涉及 |
| `AGENTS.md` 「wall-clock 抖动不放宽阈值」 | **不冲突**：不动算法核测试 |
| `.github/CODEOWNERS` | **不冲突**：不改所有权 |
| `docs/开发过程文档.md` §6.1 「必需评审不可执行」 | **不冲突**：本设计不尝试启用必需评审 |
| 第 1 步《单测计划》§3「增量口径待接入」 | **不冲突**：本任务只做「覆盖率留档」，不接增量门禁 |

## 10 已知限制（如实登记）

| 编号 | 限制 |
| --- | --- |
| L-1 | **新增 CI job 未在真实 Actions 上跑过**——本任务不推送，`sonar` job 在无 token 时短路，故其正确性只有静态检视证据 |
| L-2 | `sonar-project.properties` 的 `organization` / `projectKey` 为**占位符**，需用户回填后才能生效 |
| L-3 | 前端覆盖率**只有报告、无阈值**，因此暂不能作为准出判据 |
| L-4 | 本机 `node_modules` **未安装** `@vitest/coverage-v8`（刻意用 `--lockfile-only`），故本地 `test:cov` 需先 `pnpm install` |
| L-5 | 增量覆盖率门禁（`diff-cover`）仍属后续任务，不在本次 |
